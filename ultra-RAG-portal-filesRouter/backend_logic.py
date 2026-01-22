# -*- coding: utf-8 -*-
import json
import requests
import urllib3
import sqlite3
import datetime
import os
import traceback
import sys

# 抑制 SSL 警告
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =================配置区域=================
# Chat Completions API
API_URL = "https://www.qwenplus.com:18080/v1/chat/completions"
# Embeddings API
EMBEDDING_URL = "https://www.siconflow.cn:18080/v1/embeddings"
API_KEY = "your api key"

# 数据库名称升级为 v4
DB_NAME = "doc_summary_v4.db"

# 模型名称
MODEL_NAME = "DeepSeek-V3" 
EMBEDDING_MODEL_NAME = "bge-m3"
# =========================================

def log_to_file(msg):
    """同步写入本地文件"""
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    try:
        with open("debug_log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {msg}\n")
    except Exception:
        pass
    print(msg)

class DatabaseManager:
    @staticmethod
    def init_db():
        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            # 升级：增加 summary_vector 字段用于存储向量 (TEXT 类型存储 JSON 字符串)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS document_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_name TEXT,
                    file_path TEXT,
                    extracted_context TEXT,
                    summary_result TEXT,
                    summary_vector TEXT,
                    model_used TEXT,
                    created_at DATETIME
                )
            ''')
            conn.commit()
            conn.close()
            log_to_file("[DB] 数据库(V4)就绪，包含向量字段")
        except Exception:
            log_to_file(f"[DB Error] 初始化失败: {traceback.format_exc()}")

    # 查重功能
    @staticmethod
    def check_is_duplicate(file_name):
        """
        检查文件是否已存在于数据库中。
        返回: (bool, str) -> (是否存在, 历史总结内容)
        """
        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            # 根据文件名查找，按时间倒序取最新的一条
            cursor.execute('''
                SELECT summary_result, created_at FROM document_summaries 
                WHERE file_name = ? 
                ORDER BY id DESC LIMIT 1
            ''', (file_name,))
            row = cursor.fetchone()
            conn.close()

            if row:
                summary_content = row[0]
                created_time = row[1]
                log_msg = f"[DB Check] 发现重复文件: {file_name} (入库时间: {created_time})"
                log_to_file(log_msg)
                return True, summary_content
            else:
                return False, ""
        except Exception:
            log_to_file(f"[DB Error] 查重查询失败: {traceback.format_exc()}")
            return False, ""

    @staticmethod
    def save_summary(file_name, file_path, context, summary, vector_json="[]"):
        # 增加校验，防止把 "[API 报错...]" 这种错误信息存入数据库
        if "[API 报错" in summary or "[ERROR]" in summary:
            log_to_file(f"[DB Warning] 检测到生成内容包含错误，跳过入库: {file_name}")
            return False

        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            # 升级：插入向量数据
            cursor.execute('''
                INSERT INTO document_summaries 
                (file_name, file_path, extracted_context, summary_result, summary_vector, model_used, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (file_name, file_path, context, summary, vector_json, MODEL_NAME, datetime.datetime.now()))
            conn.commit()
            conn.close()
            log_to_file(f"[DB] 数据入库成功(含向量): {file_name}")
            return True
        except Exception:
            log_to_file(f"[DB Error] 入库失败: {traceback.format_exc()}")
            return False

class EmbeddingClient:
    """处理向量化请求"""
    def __init__(self):
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {API_KEY}'
        }
    
    def get_embedding(self, text):
        """获取文本的 bge-m3 向量"""
        # 防止文本过长，简单截断（bge-m3 支持 8192 token，这里保守截断）
        safe_text = text[:8000]
        
        data = {
            "model": EMBEDDING_MODEL_NAME,
            "input": [safe_text]
        }
        
        try:
            log_to_file(f"[Embedding API] 请求模型: {EMBEDDING_MODEL_NAME}")
            response = requests.post(
                EMBEDDING_URL,
                headers=self.headers,
                data=json.dumps(data),
                verify=False,
                timeout=30,
                proxies={"http": None, "https": None}
            )
            
            if response.status_code == 200:
                res_json = response.json()
                # 根据 OpenAI 格式提取 embedding
                # 格式通常是 data[0]['embedding']
                if "data" in res_json and len(res_json["data"]) > 0:
                    vector = res_json["data"][0]["embedding"]
                    log_to_file(f"[Embedding API] 成功获取向量，维度: {len(vector)}")
                    return vector
                else:
                    log_to_file(f"[Embedding API Warning] 返回格式异常: {response.text}")
                    return None
            else:
                log_to_file(f"[Embedding API Error] 状态码: {response.status_code}, 详情: {response.text}")
                return None
        except Exception:
            log_to_file(f"[Embedding API Error] 网络或处理异常:\n{traceback.format_exc()}")
            return None

class DeepSeekV3Client:
    def __init__(self):
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {API_KEY}'
        }

    def stream_chat(self, messages):
        payload = {
            "model": MODEL_NAME, 
            "messages": messages,
            "stream": True,
            "temperature": 0.6 
        }
        try:
            log_to_file(f"[Chat API] 请求模型: {MODEL_NAME}")
            
            # 必须 verify=False 且禁用代理
            response = requests.post(
                API_URL,
                headers=self.headers,
                json=payload,
                stream=True,
                verify=False, 
                timeout=(5, 120),
                proxies={"http": None, "https": None} # 强制直连
            )
            
            if response.status_code != 200:
                log_to_file(f"[Chat API Error] 状态码: {response.status_code}")
                # 将错误信息 yield 出去显示在界面上
                yield f"\n[API 报错 {response.status_code}]: {response.text}\n"
                return

            # 解析流式响应
            for line in response.iter_lines():
                if line:
                    decoded = line.decode('utf-8').strip()
                    if decoded.startswith("data: "):
                        data_str = decoded[6:]
                        if data_str == "[DONE]": break
                        try:
                            data_json = json.loads(data_str)
                            # 兼容不同的返回结构
                            choices = data_json.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content", "")
                                if content: yield content
                        except: 
                            continue
        except Exception:
            log_to_file(f"[Chat API Error] 网络异常:\n{traceback.format_exc()}")
            yield f"\n[网络连接异常，请检查 VPN 或内网连接]\n"

    def generate_summary(self, text, callback_signal=None):
        # 构建 Prompt，截断以防超长
        prompt = f"文件内容如下：\n{text[:15000]}\n\n请对上述内容进行结构化总结，列出关键点："
        full_res = ""
        
        # 实时流式处理
        for chunk in self.stream_chat([{"role": "user", "content": prompt}]):
            full_res += chunk
            if callback_signal: 
                # 实时发送到 UI
                callback_signal.emit(chunk)
                
        return full_res

class JsonProcessor:
    @staticmethod
    def extract_structure(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
            
            # 尝试提取 content 或 structure
            extracted = ""
            
            if isinstance(data, dict):
                # 优先找 content 字段（常见的解析输出）
                if "content" in data:
                    extracted = data["content"]
                # 其次找 structure 列表
                elif "structure" in data:
                    nodes = data["structure"]
                    for n in nodes:
                        t = n.get("title", "")
                        s = n.get("summary", "")
                        if s: extracted += f"【{t}】\n{s}\n\n"
                else:
                    # 如果是很简单的键值对，直接转字符串
                    extracted = json.dumps(data, ensure_ascii=False, indent=2)
            else:
                extracted = str(data)
                
            return extracted, "提取成功"
        except Exception:
            err = traceback.format_exc()
            log_to_file(f"[IO Error] 解析 JSON 失败:\n{err}")

            return None, f"解析失败: {err}"
