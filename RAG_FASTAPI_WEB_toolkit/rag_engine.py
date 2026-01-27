import sys
import os
import json
import sqlite3
import requests
import urllib3
import time
import numpy as np
import re
import hashlib
import jieba
import jieba.posseg as pseg
from collections import defaultdict
import threading
import traceback
import gc 

# 获取当前脚本所在的绝对目录，用于构建鲁棒的相对路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ================= CRITICAL FIX: 防止 Windows 下 FAISS/Torch 与 PyQt 冲突导致的闪退 =================
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

# 尝试导入 psutil 用于系统监控
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# 尝试导入 FAISS
try:
    import faiss
except ImportError:
    faiss = None

# 尝试导入 sentence_transformers 用于本地模型
try:
    from sentence_transformers import SentenceTransformer
    HAS_LOCAL_LIB = True
except ImportError:
    HAS_LOCAL_LIB = False

# ================= 配置与环境 =================
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
os.environ['CURL_CA_BUNDLE'] = ''

# API 配置 (硬编码 Key)
API_KEY = "YOUR API KEY"
ROUTING_API_KEY = API_KEY 

# Endpoints
EMBEDDING_API_URL = "https://WWW.SICONFLOW:18080/v1/embeddings"
EMBEDDING_MODEL_NAME = "bge-m3"

RERANK_API_URL = "https://WWW.SICONFLOW.COM:18080/v1/rerank"
RERANK_MODEL_NAME = "bge-reranker-v2-m3"

DEEPSEEK_API_URL = "https://WWW.DEEPSEEK.COM.cn:18080/v1/chat/completions"
DEEPSEEK_V3_MODEL_NAME = "DeepSeek-V3"

ROUTING_EMBED_URL = EMBEDDING_API_URL
ROUTING_MODEL_NAME = "bge-m3"

# 文件路径配置 (使用 BASE_DIR 确保路径鲁棒性)
AIRLINE_DICT_FILE = os.path.join(BASE_DIR, "airline_dict.txt")
DEFAULT_AIRLINES = [
    "中国国际航空", "南方航空", "东方航空", "海南航空",
    "厦门航空", "四川航空", "深圳航空", "春秋航空",
    "吉祥航空", "首都航空", "山东航空", "天津航空",
    "上海航空", "祥鹏航空", "西部航空", "长龙航空",
    "Air China", "China Southern", "China Eastern"
]

# System Prompts
REWRITE_SYSTEM_PROMPT = """你是一个工业级 RAG 系统中的「Query Rewrite 模块」。
你的职责不是回答问题，而是：
将用户输入的「简短、模糊或口语化查询」
重写为一个「语义清晰、信息密度高、适合向量检索与 reranker 判断相关性的查询」。

你必须遵守以下原则：
1. 保持用户原始意图不变，不引入不存在的事实
2. 对概念进行合理展开与同义补全（semantic expansion）
3. 输出的查询必须更有利于技术文档、论文、说明性文本的检索
4. 不要输出任何解释、分析或多版本结果
5. 只输出一条重写后的查询文本

重写规则：
- 如果用户查询过短（≤3 个词），必须进行语义扩展
- 如果查询包含歧义词（如 model、train、data、method 等），需根据「技术文档检索」场景进行消歧
- 优先使用完整自然语言描述，而不是关键词堆叠
- 输出长度建议为 1 句话，最多不超过 2 句话"""

DEEPSEEK_R1_BASE_PROMPT = """🎯【角色定义】
你是一个 RAG Final Answer Composer（检索增强生成的最终答案生成器）。
你的任务 不是检索、不是排序、不是猜测，而是：
严格基于已提供的召回结果，对用户问题生成最终、可读、准确的回答。

📥【输入说明】
你将收到一个结构化输入，包含：
1. query: 用户的原始问题
2. retrieved_chunks: 包含来自 [VECTOR] (向量召回) 和 [JSON_Source] (原文硬匹配) 的混合内容。

🔒【强制约束】
1️⃣ 事实来源约束（防幻觉）
❌ 禁止 使用任何外部知识
❌ 禁止 补充未在 retrieved_chunks 中出现的事实
✅ 只允许 基于提供内容进行归纳、重写、总结
如果证据不足：必须明确说明「当前召回内容不足以完整回答该问题」

2️⃣ 内容使用规则（防遗漏）
优先使用 Rank 靠前的内容。
注意区分来源：[JSON_Source] 来源的内容直接来自原始文档，具有最高的事实参考价值。

3️⃣ 噪声处理规则
允许你：修复断行、合并被拆散的句子、去除明显乱码
❌ 不允许“合理猜测”缺失内容

✍️【输出要求】
输出必须满足：
✅ 语言清晰、技术准确
✅ **必须使用 Markdown 格式，包含清晰的段落、列表和加粗**
✅ 不直接大段复制原文（允许短引用）

⚠️【失败兜底策略】
如果所有 retrieved_chunks 与 query 相关性都很弱，必须输出：“根据当前召回的文档内容，无法对该问题给出可靠回答。”"""

# ================= 核心工具函数 =================
def cosine_similarity(vec1, vec2):
    try:
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(vec1, vec2) / (norm1 * norm2))
    except Exception:
        return 0.0

def get_text_hash(text):
    """生成文本的 SHA256 哈希，用于严格去重"""
    if not text: return ""
    clean_text = text.strip().lower()
    return hashlib.sha256(clean_text.encode('utf-8')).hexdigest()

def extract_keywords_with_jieba(query, stopwords=None, airline_dict=None, top_n=5):
    """
    【三步走策略应用】
    Step 1: 字典优先 (Airline Dict) -> 权重 3 (最高)
    Step 2: 正则优先 (Flight No/Code) -> 权重 3
    Step 3: Jieba NLP -> 权重 1-2
    """
    if not query: return []
    # 如果环境确实没有 jieba
    if 'jieba' not in sys.modules:
        return query.split() # Fallback
    
    keywords = []
    query_lower = query.lower()
    
    # 预处理 stopwords set
    stop_set = set()
    if stopwords:
        for sw in stopwords:
            stop_set.add(sw.strip().lower())

    # --- Step 1: 字典优先 (Exact Match in Query) ---
    if airline_dict:
        for airline in airline_dict:
            if airline.lower() in query_lower:
                keywords.append((airline, 3))

    # --- Step 2: 正则优先 (Regex for Codes) ---
    code_pattern = r'[A-Za-z]{2,3}\d{3,4}' 
    codes = re.findall(code_pattern, query)
    for code in codes:
        keywords.append((code, 3))

    # --- Step 3: NLP (Jieba) ---
    try:
        words = pseg.cut(query)
        for w in words:
            word = w.word.strip()
            flag = w.flag
            
            if len(word) < 2: continue 
            if word.lower() in stop_set: continue
            
            if any(k[0].lower() == word.lower() for k in keywords):
                continue

            if flag.startswith('n') or flag == 'eng': 
                keywords.append((word, 2)) 
            elif flag.startswith('v'): 
                keywords.append((word, 1)) 
    except Exception:
        # 兜底防止分词错误
        return query.split()[:top_n]

    keywords.sort(key=lambda x: x[1], reverse=True)
    seen = set()
    result = []
    for k, score in keywords:
        if k not in seen:
            result.append(k)
            seen.add(k)
            
    return result[:top_n]

def is_precise_intent(query):
    """动态路由逻辑：检测是否包含大写字母+数字的组合"""
    pattern = r'[A-Z]{2,3}\d{3,4}'
    return bool(re.search(pattern, query))

# ================= PageIndex Loader =================
class PageIndexLoader:
    def __init__(self):
        self.index = {}          
        self.ordered_ids = []    
        self.is_loaded = False

    def load_json(self, json_path):
        if not json_path or not os.path.exists(json_path):
            return False, f"文件不存在: {json_path}"
        
        try:
            with open(json_path, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
            
            self.index = {}
            self.ordered_ids = []
            
            root_structure = data.get("structure", []) if isinstance(data, dict) else data
            for item in root_structure:
                self._traverse(item, parent_path=[])
            
            self.is_loaded = True
            return True, f"成功加载 PageIndex，包含 {len(self.index)} 个节点"
        except Exception as e:
            return False, f"加载异常: {str(e)}"

    def _traverse(self, node, parent_path):
        current_title = node.get("title", "")
        node_id = str(node.get("node_id", "")) 
        current_path = parent_path + [current_title]
        
        if node_id:
            self.index[node_id] = {
                "title": current_title,
                "text": node.get("text", ""),
                "summary": node.get("summary", ""),
                "path": current_path,
                "raw_node": node 
            }
            self.ordered_ids.append(node_id)
        
        if "nodes" in node and isinstance(node["nodes"], list):
            for child in node["nodes"]:
                self._traverse(child, current_path)

    def get_node(self, node_id):
        return self.index.get(str(node_id))

# ================= Local Model Wrapper (Robust Version) =================
class LocalModelWrapper:
    """
    本地模型包装器 - 增强版 (Fixed for Manual Path & Version Compatibility)
    """
    def __init__(self, model_name_or_path):
        self.model = None
        self.model_name = model_name_or_path
        self.is_loaded = False
        self.error_msg = ""
        
        if not HAS_LOCAL_LIB:
            self.error_msg = "sentence_transformers 库未安装"
            return

        try:
            # 1. 优先检查本地路径是否存在
            if os.path.exists(model_name_or_path):
                self.error_msg = f"Loading local: {model_name_or_path}" 
                # [CRITICAL FIX] 移除 local_files_only 参数
                # 您的库版本不支持此参数，但只要路径存在，它默认就是本地加载
                self.model = SentenceTransformer(model_name_or_path)
                self.is_loaded = True
            else:
                # 2. 尝试 HuggingFace 下载 (Fallback)
                self.error_msg = f"Downloading: {model_name_or_path}"
                self.model = SentenceTransformer(model_name_or_path)
                self.is_loaded = True

        except Exception as e:
            self.is_loaded = False
            self.error_msg = f"Load Failed ({model_name_or_path}): {str(e)}"
            # Debug print removed to prevent thread issues

    def compute_similarity(self, query, texts):
        if not self.is_loaded or not self.model or not texts:
            return [0.0] * len(texts)
        
        try:
            query_emb = self.model.encode(query, convert_to_tensor=True)
            doc_embs = self.model.encode(texts, convert_to_tensor=True)
            
            from sentence_transformers import util
            scores_tensor = util.cos_sim(query_emb, doc_embs)[0]
            
            scores = scores_tensor.cpu().numpy().tolist()
            return scores
        except Exception:
            return [0.0] * len(texts)

    def unload(self):
        """显式释放资源"""
        self.model = None
        self.is_loaded = False
        gc.collect()

# ================= RAG Engine Core =================
class RAGQueryEngine:
    def __init__(self, db_path, json_path, local_filter_model=None):
        self.db_path = db_path
        self.json_path = json_path
        
        # 加载 PageIndex
        self.page_index = PageIndexLoader()
        self.index_load_msg = "PageIndex 未加载"
        if self.json_path:
            success, msg = self.page_index.load_json(self.json_path)
            self.index_load_msg = msg
        
        # 本地模型管理
        self.local_model_instance = None
        self.local_model_name = "None"
        
        # 默认配置
        self.use_faiss = True
        self.stop_words = []
        self.airline_names = []
        self._ensure_airline_dict()
        self.reload_airline_dict()
        
        # 中断控制
        self.stop_flag = False

    def _ensure_airline_dict(self):
        if not os.path.exists(AIRLINE_DICT_FILE):
            try:
                with open(AIRLINE_DICT_FILE, "w", encoding="utf-8") as f:
                    for airline in DEFAULT_AIRLINES:
                        f.write(airline + "\n")
            except: pass

    def reload_airline_dict(self):
        """从文件重新加载航司字典"""
        self.airline_names = []
        if os.path.exists(AIRLINE_DICT_FILE):
            try:
                with open(AIRLINE_DICT_FILE, 'r', encoding='utf-8') as f:
                    self.airline_names = [line.strip() for line in f if line.strip()]
            except: pass
        return self.airline_names

    # === API 暴露的管理接口 ===
    def manage_airline_dict(self, operation="list", value=None):
        if operation == "list":
            return self.reload_airline_dict()
        
        current_list = self.reload_airline_dict()
        
        if operation == "add" and value:
            if value not in current_list:
                current_list.append(value)
        elif operation == "delete" and value:
            if value in current_list:
                current_list.remove(value)
        
        # 保存回文件
        try:
            with open(AIRLINE_DICT_FILE, "w", encoding="utf-8") as f:
                for item in current_list:
                    f.write(item + "\n")
            self.reload_airline_dict()
            return {"status": "success", "data": current_list}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def switch_local_model(self, model_identifier):
        """
        切换本地模型 - 修复 Issue 3: 使用鲁棒的相对路径，不再硬编码用户目录
        """
        # 1. 卸载旧模型
        if self.local_model_instance:
            self.local_model_instance.unload()
            self.local_model_instance = None
            self.local_model_name = "None"
            gc.collect()
        
        if not model_identifier or model_identifier.lower() == 'none':
            return {"status": "success", "message": "Local model unloaded"}

        # 2. 准备路径 (FIXED HERE: 使用相对于 BASE_DIR 的 models 目录)
        target_path = ""
        display_name = ""
        # 定义模型根目录为当前脚本所在目录下的 models 文件夹
        models_dir = os.path.join(BASE_DIR, "models")
        
        if model_identifier.lower() == 'bge':
            # 优先检查项目内的 models 目录
            potential_local_path = os.path.join(models_dir, "bge-small-zh-v1.5")
            if os.path.exists(potential_local_path):
                target_path = potential_local_path
            else:
                # fallback 到 HuggingFace ID
                target_path = "BAAI/bge-small-zh-v1.5"
            display_name = "BGE-Small-Zh-v1.5"
            
        elif model_identifier.lower() == 'minilm':
            # === CRITICAL FIX: 使用项目内的相对路径，不再硬编码用户目录 ===
            # 请确保模型文件已放置在 C:\RagSource\models\sentence-transformers_all-MiniLM-L6-v2
            target_path = os.path.join(models_dir, "sentence-transformers_all-MiniLM-L6-v2")
            display_name = "MiniLM-L6 (Local Optimized)"
        else:
            return {"status": "error", "message": "Unknown model identifier"}

        # 3. 尝试加载
        try:
            wrapper = LocalModelWrapper(target_path)
            if wrapper.is_loaded:
                self.local_model_instance = wrapper
                self.local_model_name = display_name
                return {"status": "success", "message": f"Loaded {display_name}"}
            else:
                return {"status": "warning", "message": f"Load Failed: {wrapper.error_msg}. Please ensure model is in {target_path}"}
        except Exception as e:
            return {"status": "error", "message": f"Critical Error: {str(e)}"}

    def get_system_metrics(self):
        metrics = {"cpu": 0.0, "ram": 0.0}
        if HAS_PSUTIL:
            try:
                metrics["cpu"] = psutil.cpu_percent(interval=None)
                metrics["ram"] = psutil.virtual_memory().percent
            except: pass
        return metrics

    def stop(self):
        """中断当前搜索"""
        self.stop_flag = True

    # === 内部核心逻辑 (改造为生成器辅助) ===
    def _log_event(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        full_msg = f"[{timestamp}] {msg}"
        return {"type": "log", "data": full_msg}

    # --- Routing ---
    def check_routing_suggestion(self, query):
        # 修复 Issue 2: 使用基于脚本路径的绝对路径，而不是依赖 os.getcwd()
        summary_db_path = os.path.join(BASE_DIR, "rooter_Step1", "doc_summary_v4.db")
        
        if not os.path.exists(summary_db_path):
            # 可以选择打印日志帮助调试
            # print(f"Routing DB not found at: {summary_db_path}")
            return None
        
        conn = None
        try:
            conn = sqlite3.connect(summary_db_path)
            cursor = conn.cursor()
            
            # Phase 1: 硬匹配
            cursor.execute("SELECT file_name FROM document_summaries WHERE file_name LIKE ? LIMIT 1", (f"%{query}%",))
            res = cursor.fetchone()
            if res:
                return {"file": res[0], "type": "文件名硬匹配", "score": 1.0}
            
            # Phase 2: 向量匹配
            query_vec = self._get_remote_embedding(query, is_routing=True)
            if not query_vec:
                return None
                
            cursor.execute("SELECT file_name, summary_vector FROM document_summaries")
            rows = cursor.fetchall()
            
            best_score = -1.0
            best_file = None
            q_vec = np.array(query_vec, dtype=np.float32)
            q_norm = np.linalg.norm(q_vec)
            
            for fname, vec_str in rows:
                if not vec_str or len(vec_str) < 10: continue
                try:
                    d_vec = np.array(json.loads(vec_str), dtype=np.float32)
                    d_norm = np.linalg.norm(d_vec)
                    if d_norm == 0: continue
                    score = float(np.dot(q_vec, d_vec) / (q_norm * d_norm))
                    if score > best_score:
                        best_score = score
                        best_file = fname
                except: continue
            
            if best_file and best_score > 0.35:
                return {"file": best_file, "type": "向量语义路由", "score": float(best_score)}
            
        except Exception as e:
            # Routing 失败不应导致主流程崩溃
            # print(f"Routing error: {e}")
            pass
        finally:
            if conn: 
                try: conn.close()
                except: pass
        return None

    # --- API Calls ---
    def _get_remote_embedding(self, text, is_routing=False):
        url = ROUTING_EMBED_URL if is_routing else EMBEDDING_API_URL
        model = ROUTING_MODEL_NAME if is_routing else EMBEDDING_MODEL_NAME
        key = ROUTING_API_KEY if is_routing else API_KEY
        
        if not text: return None

        headers = { 'Content-Type': 'application/json', 'Authorization': f'Bearer {key}' }
        payload = { "model": model, "input": [text[:8000]] }
        
        try:
            # 增加超时保护防止挂起
            resp = requests.post(url, headers=headers, json=payload, verify=False, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if 'data' in data and len(data['data']) > 0:
                    return data['data'][0]['embedding']
        except Exception:
            pass
        return None

    def _rerank_candidates(self, query, candidates, doc_type_pref=None):
        if not candidates: return []
        
        rerank_query = query
        if doc_type_pref and doc_type_pref != "不指定类型":
            rerank_query = f"{query} (Prefer document type: {doc_type_pref})"
        
        input_texts = [f"Section Path: {c['path']}\nContent: {c['content']}" for c in candidates]
        
        headers = { 'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}' }
        payload = {
            "model": RERANK_MODEL_NAME,
            "query": rerank_query, 
            "documents": input_texts 
        }

        try:
            resp = requests.post(RERANK_API_URL, headers=headers, json=payload, verify=False, timeout=120)
            if resp.status_code == 200:
                data = resp.json()
                scores = [0.0] * len(candidates)
                if "results" in data:
                    for res in data["results"]:
                        idx = res.get("index")
                        score = res.get("relevance_score", 0.0)
                        if idx is not None and 0 <= idx < len(scores):
                            scores[idx] = score
                elif isinstance(data, list):
                     scores = data
                
                for i, c in enumerate(candidates):
                    c['rerank_score'] = scores[i]
                
                candidates.sort(key=lambda x: x.get('rerank_score', 0), reverse=True)
                return candidates
        except Exception:
            pass
        return candidates

    def _rewrite_query(self, query, doc_type="不指定类型"):
        headers = { 'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}' }
        doc_type_hint = ""
        if doc_type and doc_type != "不指定类型":
            doc_type_hint = f"\n\n[Important Context]: The user explicitly expects content from document type: '{doc_type}'."

        messages = [
            {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": f"用户查询：\n{query}{doc_type_hint}\n\n请输出重写后的查询："}
        ]
        payload = { "model": DEEPSEEK_V3_MODEL_NAME, "messages": messages, "temperature": 0.7, "stream": False }

        try:
            resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, verify=False, timeout=30)
            if resp.status_code == 200:
                content = resp.json()['choices'][0]['message']['content'].strip()
                return content.replace('"', '').replace("'", "")
        except Exception:
            pass
        return query

    # --- Search Components ---
    def _search_json_hard(self, query, keywords, limit_k=10):
        if not self.json_path or not self.page_index.is_loaded or not keywords:
            return []
        
        results = []
        try:
            def traverse_search(node_id, node_data):
                if self.stop_flag: return
                text = node_data['text']
                text_lower = text.lower()
                hit_count = 0
                for kw in keywords:
                    if kw.lower() in text_lower:
                        hit_count += 1
                
                if hit_count > 0 and len(text) > 10:
                    score = 10.0 + (hit_count * 2.0)
                    path_str = " > ".join(node_data['path'])
                    results.append({
                        "id": node_id,
                        "content": text,
                        "path": path_str,
                        "score": score,
                        "hit_count": hit_count,
                        "source": "JSON_Source" 
                    })

            for nid in self.page_index.ordered_ids:
                if self.stop_flag: break
                node = self.page_index.get_node(nid)
                traverse_search(nid, node)

            results.sort(key=lambda x: x['score'], reverse=True)
            return results[:limit_k]
        except Exception:
            return []

    def _search_vectors(self, query_vec, limit_k=10, enable_local_filter=False):
        if not query_vec or not os.path.exists(self.db_path):
            return [], [] 
        
        logs = []
        raw_candidates = []
        conn = None
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id, embedding, section_id FROM vectors")
            rows = cursor.fetchall()
            
            use_faiss_now = self.use_faiss and (faiss is not None)
            initial_recall_k = 50 if enable_local_filter else limit_k
            
            if use_faiss_now:
                try:
                    logs.append(f"⚡ [FAISS] 正在构建索引 (数据量: {len(rows)})...")
                    embeddings = []
                    ids = []
                    section_ids = []
                    for row in rows:
                        try:
                            vec = json.loads(row[1])
                            embeddings.append(vec)
                            ids.append(row[0])
                            section_ids.append(row[2])
                        except: continue
                    
                    if embeddings:
                        data_np = np.array(embeddings).astype('float32')
                        faiss.normalize_L2(data_np)
                        dim = data_np.shape[1]
                        index = faiss.IndexFlatIP(dim)
                        index.add(data_np)
                        
                        q_np = np.array([query_vec]).astype('float32')
                        faiss.normalize_L2(q_np)
                        
                        search_k = min(len(embeddings), initial_recall_k)
                        scores, indices = index.search(q_np, search_k)
                        
                        for rank, idx in enumerate(indices[0]):
                            if idx == -1: continue
                            raw_candidates.append({
                                "id": ids[idx],
                                "vec_score": float(scores[0][rank]),
                                "section_id": str(section_ids[idx])
                            })
                        logs.append(f"⚡ [FAISS] 检索完成，候选数量: {len(raw_candidates)}")
                except Exception as e:
                    use_faiss_now = False 
                    logs.append(f"❌ FAISS 失败: {e}，回退到暴力计算")

            if not use_faiss_now:
                logs.append("🐢 [Brute-Force] 使用 Python 逐行计算余弦相似度...")
                query_vec_np = np.array(query_vec, dtype=np.float32)
                for row in rows:
                    if self.stop_flag: break
                    try:
                        doc_vec = np.array(json.loads(row[1]), dtype=np.float32)
                        score = cosine_similarity(query_vec_np, doc_vec)
                        raw_candidates.append({"id": row[0], "vec_score": score, "section_id": str(row[2])})
                    except: continue
                raw_candidates.sort(key=lambda x: x["vec_score"], reverse=True)
                raw_candidates = raw_candidates[:initial_recall_k]

            # 2. 填充内容
            filled_candidates = []
            for item in raw_candidates:
                if self.stop_flag: break
                sec_id = item["section_id"]
                node_info = self.page_index.get_node(sec_id)
                
                # 如果 PageIndex 没找到，尝试 DB 兜底
                if not node_info:
                    try:
                        cursor.execute("SELECT embedding_text, section_path FROM documents WHERE id=?", (sec_id,))
                        db_row = cursor.fetchone()
                        if db_row:
                            node_info = {'text': db_row[0], 'path': [str(db_row[1])], 'summary': ''}
                    except: pass

                if node_info:
                    raw_text = node_info['text']
                    path_str = " > ".join(node_info['path'])
                    summary_text = node_info.get('summary', '')
                    display_content = f"[Summary]\n{summary_text}\n\n[Text]\n{raw_text}" if summary_text else raw_text
                    
                    filled_candidates.append({
                        "id": sec_id, 
                        "vec_score": item["vec_score"],
                        "path": path_str,
                        "content": display_content,
                        "source": "VECTOR"
                    })
            
            return filled_candidates, logs
            
        except Exception as e:
            logs.append(f"❌ DB 异常: {str(e)}")
            return [], logs
        finally:
            if conn: conn.close()

    def _apply_rrf_fusion(self, vector_items, json_items, query, doc_type="不指定类型", search_mode="smart"):
        k = 60
        fused_scores = defaultdict(float)
        item_map = {}
        
        for rank, item in enumerate(vector_items):
            doc_id = item['id']
            item_map[doc_id] = item
            fused_scores[doc_id] += 1.0 / (k + rank + 1)
            
        is_precise = is_precise_intent(query)
        json_boost = 1.0
        is_book_mode = doc_type in ["书籍/教材", "长篇论文"]
        
        if search_mode == 'precise': json_boost = 5.0 
        elif search_mode == 'smart':
            if is_book_mode: json_boost = 0.5
            elif is_precise: json_boost = 3.0
        elif search_mode == 'fuzzy': json_boost = 0.5 

        for rank, item in enumerate(json_items):
            doc_id = item['id']
            if doc_id not in item_map:
                item_map[doc_id] = item
                item_map[doc_id]['debug_score'] = "JSON_New"
            fused_scores[doc_id] += json_boost * (1.0 / (k + rank + 1))
            if "JSON" not in item_map[doc_id].get('source', ''):
                item_map[doc_id]['source'] = "MIXED (Vec+JSON)"

        # 航司置顶逻辑
        if self.airline_names:
            target_airlines = [name for name in self.airline_names if name.lower() in query.lower()]
            if target_airlines:
                for doc_id, score in fused_scores.items():
                    content = item_map[doc_id].get('content', '')
                    for air in target_airlines:
                        if air in content:
                            fused_scores[doc_id] += 10.0
                            break

        sorted_ids = sorted(fused_scores.keys(), key=lambda x: fused_scores[x], reverse=True)
        final_results = []
        seen_hashes = set()
        
        for doc_id in sorted_ids:
            item = item_map[doc_id]
            item['final_score'] = fused_scores[doc_id]
            h = get_text_hash(item.get('content', ''))
            if h in seen_hashes: continue
            seen_hashes.add(h)
            final_results.append(item)
            
        return final_results[:12] 

    # --- MAIN GENERATOR (CRITICAL FIXES HERE) ---
    def search(self, query, 
               search_mode="smart", 
               doc_type="不指定类型", 
               model_name="DeepSeek-R1", 
               limit_vector=10, 
               limit_json=10, 
               enable_local_filter=False,
               enable_routing=False):
        """
        全流程生成器，Yield 各种类型的事件字典。
        包含 Crash 保护逻辑。
        """
        self.stop_flag = False
        
        try:
            yield self._log_event(f"🚀 初始化任务... | 策略: {search_mode} | 模型: {model_name}")
            
            # 1. 检查本地模型状态
            if enable_local_filter:
                if self.local_model_instance and self.local_model_instance.is_loaded:
                    yield self._log_event(f"🧠 本地过滤: [启用] 使用 {self.local_model_name}")
                else:
                    # 如果未加载，自动降级而不报错
                    yield self._log_event(f"⚠️ 本地过滤: [启用失败] 模型未就绪，已自动跳过过滤步骤")
                    enable_local_filter = False
            else:
                yield self._log_event(f"⚪ 本地过滤: [禁用]")
                
            yield self._log_event(self.index_load_msg)

            # 2. Routing
            if enable_routing:
                try:
                    yield self._log_event("🔀 正在执行文件路由分析...")
                    routing_info = self.check_routing_suggestion(query)
                    if routing_info:
                        yield self._log_event(f"💡 [Routing] 建议文件: {routing_info['file']}")
                        yield {"type": "routing", "data": routing_info}
                    else:
                        yield self._log_event("🔀 [Routing] 未找到明确的路由建议")
                except Exception as e:
                    yield self._log_event(f"⚠️ 路由模块警告: {str(e)}")

            if self.stop_flag: return

            # 3. Rewrite Query
            search_query = query
            if search_mode != "precise":
                try:
                    yield self._log_event(f"🧠 正在请求 DeepSeek-V3 进行语义重写 (类型偏好: {doc_type})...")
                    start_t = time.time()
                    rewritten = self._rewrite_query(query, doc_type)
                    if rewritten:
                        yield self._log_event(f"✅ Rewrite 完成 ({time.time()-start_t:.2f}s)")
                        yield self._log_event(f"   Original: {query}")
                        yield self._log_event(f"   Rewritten: {rewritten}")
                        search_query = rewritten
                except Exception as e:
                    yield self._log_event(f"⚠️ Rewrite 跳过: {str(e)}")

            if self.stop_flag: return

            # 4. JSON Search
            json_results = []
            if search_mode != 'fuzzy':
                try:
                    keywords = extract_keywords_with_jieba(query, self.stop_words, self.airline_names)
                    yield self._log_event(f"🔍 [三步走策略] 提取关键词: {keywords}")
                    yield self._log_event("🚀 启动 JSON 原文硬查询...")
                    json_results = self._search_json_hard(query, keywords, limit_json)
                    yield self._log_event(f"📄 JSON 原文检索命中: {len(json_results)} 条")
                except Exception as e:
                    yield self._log_event(f"⚠️ JSON 检索跳过: {str(e)}")

            if self.stop_flag: return

            # 5. Vector Search
            yield self._log_event(f"📡 正在计算向量 Embedding: {search_query[:30]}...")
            q_vec = self._get_remote_embedding(search_query)
            vector_results = []
            
            if q_vec:
                yield self._log_event(f"📂 正在连接数据库: {os.path.basename(self.db_path)}")
                res, db_logs = self._search_vectors(q_vec, limit_vector, enable_local_filter)
                for l in db_logs: yield self._log_event(l)
                vector_results = res
                
                # Local Filter Logic
                if enable_local_filter and vector_results:
                    try:
                        target_k = limit_vector
                        yield self._log_event(f"🧠 [Local Filter] 正在使用本地模型对 {len(vector_results)} 条候选进行精排...")
                        
                        original_ids = set(item['id'] for item in vector_results[:target_k])
                        texts = [c['content'] for c in vector_results]
                        
                        scores = self.local_model_instance.compute_similarity(search_query, texts)
                        for i, c in enumerate(vector_results):
                            c['local_score'] = scores[i]
                        
                        vector_results.sort(key=lambda x: x['local_score'], reverse=True)
                        vector_results = vector_results[:target_k]
                        
                        new_ids = set(item['id'] for item in vector_results)
                        rescued = len(new_ids - original_ids)
                        
                        yield self._log_event(f"📊 [效用检测] 本地小模型 '捞回' 数据量: {rescued}/{target_k}")
                        yield self._log_event(f"✅ [Local Filter] 筛选完成，保留 Top {len(vector_results)}")
                    except Exception as e:
                         yield self._log_event(f"⚠️ 本地过滤异常: {str(e)}")

                # Rerank
                if vector_results:
                    try:
                        yield self._log_event(f"⚖️ Reranker ({RERANK_MODEL_NAME}) 正在重排 {len(vector_results)} 条数据...")
                        start_t = time.time()
                        vector_results = self._rerank_candidates(search_query, vector_results, doc_type)
                        yield self._log_event(f"✅ Reranker 完成，耗时: {time.time()-start_t:.2f}s")
                    except Exception as e:
                        yield self._log_event(f"⚠️ Rerank 异常: {str(e)}")

            # 6. Fusion
            yield self._log_event("⚖️ 执行 RRF 融合与内容指纹去重...")
            final_results = self._apply_rrf_fusion(vector_results, json_results, query, doc_type, search_mode)
            yield self._log_event(f"✅ 最终召回: {len(final_results)} 条唯一内容")
            yield {"type": "sources", "data": final_results}

            if self.stop_flag: return

            # 7. LLM Generation (Anti-Crash Wrapper)
            yield self._log_event(f"🧠 正在请求 {model_name} 生成最终回答 (Stream=True)...")
            
            system_prompt = DEEPSEEK_R1_BASE_PROMPT
            if doc_type and doc_type != "不指定类型":
                system_prompt += f"\n⚠️ 用户期望文档类型：【{doc_type}】。"
            
            context_str = ""
            for i, item in enumerate(final_results):
                context_str += f"\n---\n[Rank {i+1}] [Source: {item.get('source')}]\nPath: {item['path']}\nContent:\n{item['content']}\n"
            
            user_msg = f"Query: {query}\n\nRetrieved Chunks:{context_str}"
            
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg}
                ],
                "stream": True,
                "temperature": 0.6
            }
            
            headers = { 'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}' }
            
            # 使用 Session 保持连接稳定，增加 TimeOut 300s
            try:
                with requests.Session() as session:
                    # 禁用环境代理，防止代理设置干扰内网请求导致崩溃
                    session.trust_env = False 
                    
                    resp = session.post(
                        DEEPSEEK_API_URL, 
                        headers=headers, 
                        json=payload, 
                        verify=False, 
                        stream=True, 
                        timeout=300 # DeepSeek-R1 思考时间长，增加超时
                    )
                    
                    if resp.status_code == 200:
                        # 安全的流式读取，强制忽略错误解码
                        for line in resp.iter_lines(decode_unicode=False):
                            if self.stop_flag: break
                            if line:
                                try:
                                    # 手动解码，防崩溃
                                    decoded = line.decode('utf-8', errors='ignore')
                                    if decoded.startswith("data: "):
                                        data_str = decoded[6:]
                                        if data_str.strip() == "[DONE]": break
                                        
                                        chunk = json.loads(data_str)
                                        delta = chunk['choices'][0]['delta']
                                        yield {"type": "answer", "data": delta}
                                except Exception:
                                    # 忽略单行错误，不中断整体流程
                                    continue
                        yield self._log_event(f"✅ {model_name} 总结生成完毕")
                    else:
                        yield self._log_event(f"❌ API 请求失败: {resp.status_code}")
                        yield {"type": "answer", "data": {"content": f"**API Error**: {resp.status_code}"}}

            except requests.exceptions.ReadTimeout:
                yield self._log_event("❌ 错误: 模型生成超时 (Timeout > 300s)")
                yield {"type": "answer", "data": {"content": "\n\n**Error**: Generating response timed out."}}
            except Exception as e:
                # 捕获 requests 底层连接错误
                yield self._log_event(f"❌ LLM 连接中断: {str(e)}")
                yield {"type": "answer", "data": {"content": f"\n\n**Connection Error**: {str(e)}"}}

            yield self._log_event("✅ 全流程结束")

        except Exception as e:
            # 捕获整个流程中的任何未预料异常，防止线程Crash
            err_trace = traceback.format_exc()
            yield self._log_event(f"❌ 严重运行时错误: {str(e)}")
            yield {"type": "answer", "data": {"content": f"\n\n**System Critical Error**: {str(e)}"}}

if __name__ == "__main__":
    print("Run test_rag_engine.py to verify.")