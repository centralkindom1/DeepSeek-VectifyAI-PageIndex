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

# PyQt Core 组件用于线程和信号，虽然是后端逻辑，但为了保持原有的异步架构
from PyQt5.QtCore import QThread, pyqtSignal

# ================= 配置与环境 =================
# 禁用 HTTPS 警告 (Win7/内网适配)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
os.environ['CURL_CA_BUNDLE'] = ''

# API 配置 (硬编码 Key)
API_KEY = "sk-fXM4W0CdcKnNp3NVDfF85f2b90284b11AfDdF9F5627f627b"

# 1. Embedding API
EMBEDDING_API_URL = "https://aiplus.airchina.com.cn:18080/v1/embeddings" 
EMBEDDING_MODEL_NAME = "bge-m3"

# 2. Rerank API
RERANK_API_URL = "https://aiplus.airchina.com.cn:18080/v1/rerank" 
RERANK_MODEL_NAME = "bge-reranker-v2-m3"

# 3. DeepSeek API (Chat Completion)
DEEPSEEK_API_URL = "https://aiplus.airchina.com.cn:18080/v1/chat/completions"
DEEPSEEK_R1_MODEL_NAME = "DeepSeek-R1"
DEEPSEEK_V3_MODEL_NAME = "DeepSeek-V3"

# ================= System Prompts =================

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

重写规则（必须严格遵守）：
- 如果用户查询过短（≤3 个词），必须进行语义扩展
- 如果查询包含歧义词（如 model、train、data、method 等），需根据「技术文档检索」场景进行消歧
- 优先使用完整自然语言描述，而不是关键词堆叠
- 查询应覆盖用户最可能关注的方面，例如：定义、过程、机制、配置、方法、策略、实验设置、实现细节等
- 输出长度建议为 1 句话，最多不超过 2 句话
- 不要加入任何格式符号（如列表、引号、编号）"""

DEEPSEEK_R1_SYSTEM_PROMPT = """🎯【角色定义】
你是一个 RAG Final Answer Composer（检索增强生成的最终答案生成器）。
你的任务 不是检索、不是排序、不是猜测，而是：
严格基于已提供的召回结果，对用户问题生成最终、可读、准确的回答。

📥【输入说明】
你将收到一个结构化输入，包含：
1. query: 用户的原始问题
2. retrieved_chunks: 包含来自 [VECTOR] (向量召回) 和 [JSON_Source] (原文硬匹配) 的混合内容。

🔒【强制约束（非常重要）】
1️⃣ 事实来源约束（防幻觉）
❌ 禁止 使用任何外部知识
❌ 禁止 补充未在 retrieved_chunks 中出现的事实
✅ 只允许 基于提供内容进行归纳、重写、总结
如果证据不足：必须明确说明「当前召回内容不足以完整回答该问题」

2️⃣ 内容使用规则（防遗漏）
优先使用 Rank 靠前的内容。
注意区分来源：[JSON_Source] 来源的内容直接来自原始文档，具有最高的事实参考价值。
若多个 chunk 语义重复，应：合并信息、去除重复表述。

3️⃣ 噪声处理规则（适配 PDF / OCR）
允许你：修复断行、合并被拆散的句子、去除明显乱码
❌ 不允许“合理猜测”缺失内容

✍️【输出要求】
输出必须满足：
✅ 语言清晰、技术准确
✅ **必须使用 Markdown 格式，包含清晰的段落、列表和加粗**
✅ 不直接大段复制原文（允许短引用）
✅ 不提及“召回 / reranker / 向量 / chunk / SQL”等系统概念

📐【推荐输出结构（自动选择）】
根据问题复杂度，自适应选择：
- 简单问题：直接给出 1–2 段 concise 回答
- 技术型问题（推荐）：简要结论（1–2 句） + 详细说明（要点列表） + 补充说明

⚠️【失败兜底策略】
如果所有 retrieved_chunks 与 query 相关性都很弱，或内容彼此矛盾、无法整合，
你必须输出：“根据当前召回的文档内容，无法对该问题给出可靠回答。”

✅【总结一句话】
你是一个“只基于证据的答案生成器”，不是一个自由发挥的聊天模型。"""

# ================= 核心工具函数 =================
def cosine_similarity(vec1, vec2):
    try:
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return np.dot(vec1, vec2) / (norm1 * norm2)
    except Exception:
        return 0.0

def get_text_hash(text):
    """生成文本的 SHA256 哈希，用于严格去重"""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def extract_keywords_with_jieba(query, top_n=5):
    """
    使用 jieba 提取关键词，优先保留名词 (n)、英文 (eng) 和 动词 (v)
    """
    if not jieba:
        return query.split() # Fallback
    
    words = pseg.cut(query)
    keywords = []
    
    # 权重规则：名词/英文 > 动词 > 其他
    for w in words:
        word = w.word.strip()
        flag = w.flag
        if len(word) < 2: continue # 跳过单字
        
        if flag.startswith('n') or flag == 'eng': # 名词或英文 (如 PKX, JMU)
            keywords.append((word, 3))
        elif flag.startswith('v'): # 动词
            keywords.append((word, 2))
        else:
            keywords.append((word, 1))
            
    # 按权重排序并去重
    keywords.sort(key=lambda x: x[1], reverse=True)
    seen = set()
    result = []
    for k, score in keywords:
        if k not in seen:
            result.append(k)
            seen.add(k)
            
    return result[:top_n]

# ================= PageIndex Loader =================
class PageIndexLoader:
    def __init__(self):
        self.index = {}          
        self.ordered_ids = []    
        self.is_loaded = False

    def load_json(self, json_path):
        if not json_path or not os.path.exists(json_path):
            return False, "文件不存在"
        
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

# ================= Worker: JSON Hard Query (独立线程) =================
class JsonHardQueryWorker(QThread):
    finished_signal = pyqtSignal(list, str) # results, status_msg

    def __init__(self, json_path, keywords):
        super().__init__()
        self.json_path = json_path
        self.keywords = keywords

    def run(self):
        if not self.json_path or not os.path.exists(self.json_path) or not self.keywords:
            self.finished_signal.emit([], "JSON 路径无效或无关键词")
            return

        results = []
        try:
            with open(self.json_path, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
            
            structure = data.get("structure", []) if isinstance(data, dict) else data
            
            def traverse_search(node, path_stack):
                current_title = node.get("title", "未命名章节")
                current_text = node.get("text", "")
                node_id = str(node.get("node_id", "unknown"))
                current_path = path_stack + [current_title]
                
                text_lower = current_text.lower()
                hit_count = 0
                for kw in self.keywords:
                    if kw.lower() in text_lower:
                        hit_count += 1
                
                if hit_count > 0:
                    if len(current_text) > 10:
                        path_str = " > ".join(current_path)
                        score = 10.0 + (hit_count * 2.0)
                        
                        results.append({
                            "id": node_id,
                            "content": current_text,
                            "path": path_str,
                            "score": score,
                            "source": "JSON_Source" 
                        })

                if "nodes" in node and isinstance(node["nodes"], list):
                    for child in node["nodes"]:
                        traverse_search(child, current_path)

            for item in structure:
                traverse_search(item, [])
            
            results.sort(key=lambda x: x['score'], reverse=True)
            top_results = results[:15]
            
            self.finished_signal.emit(top_results, f"JSON 原文检索命中: {len(top_results)} 条 (关键词: {self.keywords})")
            
        except Exception as e:
            self.finished_signal.emit([], f"JSON 查询异常: {str(e)}")

# ================= 工作线程：工业级鲁棒召回 + DeepSeek V3/R1 =================
class RecallWorker(QThread):
    log_signal = pyqtSignal(str)          
    result_signal = pyqtSignal(list)      
    summary_signal = pyqtSignal(str)      
    finish_signal = pyqtSignal(bool)      

    def __init__(self, query_text, db_path, json_path, enable_json_search=False):
        super().__init__()
        self.original_query = query_text 
        self.search_query = query_text   
        self.db_path = db_path
        self.json_path = json_path
        self.enable_json_search = enable_json_search 
        self.page_index = PageIndexLoader()
        self.json_search_results = [] 

    def log(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        self.log_signal.emit(f"[{timestamp}] {msg}")

    def on_json_search_finished(self, results, msg):
        self.json_search_results = results
        self.log(f"📄 {msg}")

    # --- Step 0: Query Rewrite (DeepSeek V3) ---
    def rewrite_query(self, original_query):
        self.log(f"🧠 正在请求 DeepSeek-V3 进行语义重写...")
        
        headers = { 'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}' }
        messages = [
            {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": f"用户查询：\n{original_query}\n\n请输出重写后的查询："}
        ]
        payload = {
            "model": DEEPSEEK_V3_MODEL_NAME,
            "messages": messages,
            "temperature": 0.7, 
            "stream": False     
        }

        try:
            start_time = time.time()
            response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, verify=False, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                content = data['choices'][0]['message']['content'].strip()
                content = content.replace('"', '').replace("'", "")
                
                self.log(f"✅ Rewrite 完成 ({time.time() - start_time:.2f}s)")
                self.log(f"   Original: {original_query}")
                self.log(f"   Rewritten: {content}")
                return content
            else:
                self.log(f"⚠️ Rewrite API 返回错误: {response.status_code}，将使用原始查询。")
                return original_query
        except Exception as e:
            self.log(f"⚠️ Rewrite 调用异常: {str(e)}，将使用原始查询。")
            return original_query

    # --- Step 1: Embedding ---
    def get_remote_embedding(self, text):
        self.log(f"📡 正在计算向量 Embedding: {text[:30]}...")
        headers = { 'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}' }
        payload = { "model": EMBEDDING_MODEL_NAME, "input": [text] }
        
        try:
            response = requests.post(EMBEDDING_API_URL, headers=headers, json=payload, verify=False, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if 'data' in data and len(data['data']) > 0:
                    return data['data'][0]['embedding']
        except Exception as e:
            self.log(f"❌ Embedding 网络异常: {str(e)}")
        return None

    # --- Step 2: Rerank API ---
    def rerank_with_bge(self, query, candidates_text_list):
        self.log(f"⚖️ Reranker ({RERANK_MODEL_NAME}) 正在重排 {len(candidates_text_list)} 条数据...")
        headers = { 'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}' }
        
        payload = {
            "model": RERANK_MODEL_NAME,
            "query": query, 
            "documents": candidates_text_list 
        }

        try:
            start_time = time.time()
            response = requests.post(RERANK_API_URL, headers=headers, json=payload, verify=False, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                scores = [0.0] * len(candidates_text_list)
                
                if "results" in data:
                    for res in data["results"]:
                        idx = res.get("index")
                        score = res.get("relevance_score", 0.0)
                        if idx is not None and 0 <= idx < len(scores):
                            scores[idx] = score
                elif isinstance(data, list):
                     scores = data
                else:
                    self.log("⚠️ Reranker 返回格式未知，降级处理。")
                    return None

                self.log(f"✅ Reranker 完成，耗时: {time.time() - start_time:.2f}s")
                return scores
            else:
                self.log(f"⚠️ Reranker 请求失败: {response.status_code}")
                return None
        except Exception as e:
            self.log(f"⚠️ Reranker 调用异常: {str(e)}")
            return None

    # --- Step 3: 规则裁决 ---
    def apply_industrial_rules(self, query, path_str, original_score):
        q_lower = query.lower()
        p_lower = path_str.lower()
        final_adj_score = original_score

        technical_terms = ["train", "optimi", "loss", "layer", "struct", "arch"]
        if any(t in q_lower for t in technical_terms):
            negative_sections = ["introduction", "background", "preface", "motivation", "overview", "why", "related work"]
            for neg in negative_sections:
                if neg in p_lower:
                    final_adj_score -= 3.0 
                    break
            if "train" in q_lower and "train" in p_lower:
                final_adj_score += 1.0
        
        return final_adj_score

    # --- Step 4: DeepSeek R1 Summary (流式) ---
    def call_deepseek_summary(self, user_original_query, top_results):
        self.log("🧠 正在请求 DeepSeek-R1 生成最终回答 (Stream=True)...")
        self.summary_signal.emit("> 🚀 **DeepSeek-R1 已连接，准备生成...**\n\n")

        context_str = ""
        for item in top_results:
            source_tag = item.get('source', 'VECTOR')
            context_str += f"""
---
[Rank {item['rank']}] [Source: {source_tag}] (Score: {item['final_score']:.2f})
Section Path: {item['path']}
Content:
{item['content']}
"""
        
        user_prompt_content = f"Query: {user_original_query}\n\nRetrieved Chunks:{context_str}"

        headers = { 'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}' }
        payload = {
            "model": DEEPSEEK_R1_MODEL_NAME, 
            "messages": [
                {"role": "system", "content": DEEPSEEK_R1_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt_content}
            ],
            "stream": True,
            "temperature": 0.6
        }

        try:
            response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, verify=False, stream=True)
            
            if response.status_code == 200:
                full_reasoning = ""
                full_content = ""
                
                for line in response.iter_lines():
                    if line:
                        decoded_line = line.decode('utf-8')
                        if decoded_line.startswith("data: "):
                            data_str = decoded_line[6:] 
                            if data_str.strip() == "[DONE]":
                                break
                            try:
                                json_chunk = json.loads(data_str)
                                delta = json_chunk['choices'][0]['delta']
                                
                                current_reasoning_delta = delta.get('reasoning_content', '')
                                current_content_delta = delta.get('content', '')
                                updated = False
                                
                                if current_reasoning_delta:
                                    full_reasoning += current_reasoning_delta
                                    updated = True
                                if current_content_delta:
                                    full_content += current_content_delta
                                    updated = True

                                if updated:
                                    formatted_output = ""
                                    if full_reasoning:
                                        clean_reasoning = full_reasoning.replace('\n', '\n> ')
                                        formatted_output += f"> 🧠 **DeepSeek Thinking Process:**\n> {clean_reasoning}\n\n"
                                    
                                    if full_content:
                                        if full_reasoning:
                                            formatted_output += "---\n\n" 
                                        formatted_output += f"{full_content}"
                                        
                                    self.summary_signal.emit(formatted_output)
                            except Exception:
                                continue
                self.log("✅ DeepSeek 总结生成完毕")
            else:
                self.log(f"❌ DeepSeek API 错误: {response.status_code}")
                self.summary_signal.emit(f"⚠️ 无法生成总结: API Error {response.status_code}")

        except Exception as e:
            self.log(f"❌ DeepSeek 调用异常: {str(e)}")
            self.summary_signal.emit(f"⚠️ 总结生成失败: {str(e)}")


    def run(self):
        try:
            # 0. 加载 PageIndex 
            has_pageindex = False
            if self.json_path:
                self.log(f"加载 PageIndex: {os.path.basename(self.json_path)}...")
                success, msg = self.page_index.load_json(self.json_path)
                if success:
                    has_pageindex = True
                else:
                    self.log(f"⚠️ PageIndex 加载失败: {msg}")
            
            # --- 并发步骤: 启动 JSON 硬查询线程 ---
            json_thread = None
            if self.enable_json_search:
                keywords = extract_keywords_with_jieba(self.original_query)
                self.log(f"🔍 提取关键词: {keywords}")
                if keywords and self.json_path:
                    self.log("🚀 启动 JSON 原文硬查询线程...")
                    json_thread = JsonHardQueryWorker(self.json_path, keywords)
                    json_thread.finished_signal.connect(self.on_json_search_finished)
                    json_thread.start()
                else:
                    self.log("⚠️ 无有效关键词或 JSON 路径，跳过硬查询")
            
            # --- Step 0: Query Rewrite ---
            rewritten = self.rewrite_query(self.original_query)
            if rewritten and len(rewritten.strip()) > 0:
                self.search_query = rewritten
            else:
                self.search_query = self.original_query

            # --- Step 1: Query Vector ---
            query_vec_list = self.get_remote_embedding(self.search_query)
            if not query_vec_list:
                self.log("❌ 向量获取失败，无法继续")
                self.finish_signal.emit(False)
                return
            query_vec_np = np.array(query_vec_list, dtype=np.float32)

            # --- Step 2: SQLite Vector Search ---
            if not os.path.exists(self.db_path):
                self.log("❌ 数据库文件不存在")
                self.finish_signal.emit(False)
                return

            self.log(f"📂 正在连接数据库: {os.path.basename(self.db_path)}")
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 确认向量表状态
            cursor.execute("SELECT count(*) FROM vectors")
            count = cursor.fetchone()[0]
            self.log(f"📊 数据库检测: vectors表包含 {count} 条向量数据")

            cursor.execute("SELECT id, embedding, section_id FROM vectors")
            rows = cursor.fetchall()
            
            raw_candidates = []
            for row in rows:
                v_id, emb_json, sec_id_db = row
                try:
                    doc_vec = np.array(json.loads(emb_json), dtype=np.float32)
                    score = cosine_similarity(query_vec_np, doc_vec)
                    # 此处 id 是向量表主键，section_id 是关联文档表的主键
                    raw_candidates.append({"id": v_id, "vec_score": score, "section_id": str(sec_id_db)})
                except: continue

            raw_candidates.sort(key=lambda x: x["vec_score"], reverse=True)
            top_candidates_raw = raw_candidates[:30] 
            self.log(f"✅ 向量相似度计算完成，初步筛选前 {len(top_candidates_raw)} 条记录")

            # --- Step 3: 去重 & 构造输入 (关联修正点) ---
            rerank_input_texts = [] 
            processed_candidates = [] 
            seen_content_hashes = set()

            for item in top_candidates_raw:
                sec_id = item["section_id"]
                node_info = self.page_index.get_node(sec_id) if has_pageindex else None
                
                raw_text = ""
                path_str = ""
                summary_text = ""

                if node_info:
                    raw_text = node_info['text']
                    path_str = " > ".join(node_info['path'])
                    summary_text = node_info.get('summary', '')
                else:
                    # [Fallback] 如果 PageIndex 没找到，查 DB
                    # ================= 修正核心: 使用 section_id 关联 documents.id =================
                    # 修改点：同时读取 embedding_text (摘要) 和 original_snippet (详情)
                    cursor.execute("SELECT embedding_text, original_snippet, section_path FROM documents WHERE id=?", (sec_id,))
                    db_row = cursor.fetchone()
                    
                    if db_row:
                        emb_summary = db_row[0] if db_row[0] else ""
                        raw_detail = db_row[1] if db_row[1] else ""
                        
                        # 策略：将摘要和原始细节拼接，确保 DeepSeek 拥有完整信息
                        # 这样处理后，DeepSeek 既懂语义，又能看到具体的航班号
                        raw_text = f"【内容摘要】：{emb_summary}\n\n【原始数据】：{raw_detail}"
                        path_str = str(db_row[2])
                        
                        # self.log(f"✅ SQL 成功召回: ID={sec_id[:8]}，来源=documents表")
                    else:
                        # self.log(f"⚠️ 数据库回退查询失败: 找不到 section_id 为 {sec_id} 的文档")
                        continue

                content_hash = get_text_hash(raw_text)
                if content_hash in seen_content_hashes:
                    continue 
                seen_content_hashes.add(content_hash)

                context_aware_input = f"Section Path: {path_str}\nContent: {raw_text}"
                rerank_input_texts.append(context_aware_input)

                # 如果有 PageIndex 的 summary，则展示；否则展示我们合成的 raw_text
                display_content = f"[Summary]\n{summary_text}\n\n[Text]\n{raw_text}" if summary_text else raw_text
                
                processed_candidates.append({
                    "id": item["id"],
                    "vec_score": item["vec_score"],
                    "path": path_str,
                    "content": display_content,
                    "final_score": 0.0,
                    "source": "VECTOR" 
                })
                
                if len(processed_candidates) >= 15:
                    break

            conn.close()
            self.log(f"✅ 文档关联检索成功: 已从数据库获取 {len(processed_candidates)} 条文本详情")

            # --- Step 4: 执行 Rerank ---
            rerank_scores = self.rerank_with_bge(self.search_query, rerank_input_texts)
            
            if rerank_scores and len(rerank_scores) == len(processed_candidates):
                for idx, candidate in enumerate(processed_candidates):
                    raw_rerank_score = rerank_scores[idx]
                    adjusted_rerank_score = self.apply_industrial_rules(
                        self.search_query, 
                        candidate['path'], 
                        raw_rerank_score
                    )
                    candidate['final_score'] = 0.2 * candidate['vec_score'] + 0.8 * adjusted_rerank_score
                    candidate['debug_score'] = f"R:{adjusted_rerank_score:.2f} (Orig:{raw_rerank_score:.2f})"
                
                processed_candidates.sort(key=lambda x: x["final_score"], reverse=True)
            else:
                self.log("⚠️ 降级：仅使用向量分排序")
                for candidate in processed_candidates:
                    candidate['final_score'] = candidate['vec_score']
                    candidate['debug_score'] = "VecOnly"

            # --- Step 5: 等待 JSON Search 线程并融合结果 ---
            if json_thread:
                self.log("⏳ 等待 JSON 原文硬查询线程完成 (超时 3s)...")
                json_thread.wait(3000) 
                
                if self.json_search_results:
                    for json_item in self.json_search_results:
                        h = get_text_hash(json_item['content'])
                        if h not in seen_content_hashes:
                            processed_candidates.append({
                                "id": json_item['id'],
                                "vec_score": 1.0, 
                                "path": json_item['path'],
                                "content": json_item['content'],
                                "final_score": json_item['score'], 
                                "debug_score": "JSON_Hard",
                                "source": "JSON_Source"
                            })
                            seen_content_hashes.add(h)
                    
                    processed_candidates.sort(key=lambda x: x["final_score"], reverse=True)

            # --- Step 6: Top-K Result ---
            final_top_results = processed_candidates[:12] 
            for idx, res in enumerate(final_top_results):
                res['rank'] = idx + 1

            self.result_signal.emit(final_top_results)
            
            # --- Step 7: DeepSeek R1 Summary ---
            self.call_deepseek_summary(self.original_query, final_top_results)
            
            self.finish_signal.emit(True)

        except Exception as e:
            self.log(f"❌ 严重错误: {str(e)}")
            import traceback
            self.log(traceback.format_exc())
            self.finish_signal.emit(False)