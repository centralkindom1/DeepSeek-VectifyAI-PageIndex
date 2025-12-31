import os
import re
import ssl
import json
import time
import copy
import asyncio
import logging
import requests
import urllib3
import yaml
import random
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as config

import tiktoken
from dotenv import load_dotenv

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False
    import PyPDF2 

# 1. Network & Environment Config
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
ssl._create_default_https_context = ssl._create_unverified_context
os.environ['CURL_CA_BUNDLE'] = ''

# 彻底清理代理，防止连接错误
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(k, None)

# 2. API Config
load_dotenv()
# 默认 Key，如果环境变量中有则优先使用环境变量
CHATGPT_API_KEY = os.getenv("CHATGPT_API_KEY", "YOUR API KEY")

# --- Universal Fallback Object ---
class UniversalFallback(dict):
    """防止解析失败导致 crash 的安全字典"""
    def __init__(self):
        super().__init__()
        self['toc_detected'] = 'no'
        self['page_index_given_in_toc'] = 'no'
        self['completed'] = 'no'
        self['answer'] = 'no'
    def extend(self, other): pass 
    def __iter__(self): return iter([])
    def __len__(self): return 0
    def get(self, key, default=None): return super().get(key, default)

def request_api_stream_sync(model, messages, timeout=600): 
    target_model = "DeepSeek-V3"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CHATGPT_API_KEY}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" 
    }
    
    payload = {
        "model": target_model,
        "messages": messages,
        "stream": True,
        "temperature": 0.1
    }
    
    # === 关键修正：确保 URL 是纯净的字符串，没有任何 Markdown 标记 ===
    raw_urls = [
        "https://WWW.DEEPSEEK.COM:10000/v1/chat/completions",
        "https://WWW.DEEPSEEK.COM:100000/chat/completions"      
    ]

    for url in raw_urls:
        try:
            # === 鲁棒性修正：自动清洗 URL ===
            # 去除首尾空格
            url = url.strip()
            # 如果 URL 意外包含了 Markdown 格式 [url](url)，自动提取前半部分
            if url.startswith("[") and "](" in url:
                url = url.split("](")[0].replace("[", "")
            
            # 最终检查：必须以 http 开头
            if not url.startswith("http"):
                logging.warning(f"⚠️ Skipping invalid URL format: {url}")
                continue

            response = requests.post(
                url, 
                headers=headers, 
                json=payload, 
                timeout=timeout, 
                verify=False,
                stream=True 
            )
            
            response.encoding = 'utf-8'
            
            if "text/html" in response.headers.get("Content-Type", ""):
                logging.warning(f"⚠️ URL {url} returned HTML (Login Page/Proxy Block). Skipping...")
                continue
            
            if response.status_code != 200:
                logging.warning(f"⚠️ URL {url} failed with status {response.status_code}")
                continue

            full_content = ""
            for line in response.iter_lines():
                if not line: continue
                line_str = line.decode('utf-8', errors='ignore').strip()
                
                if line_str.startswith("data:"):
                    data_part = line_str[5:].strip()
                    if data_part == "[DONE]": break
                    try:
                        data_json = json.loads(data_part)
                        delta = data_json['choices'][0].get('delta', {})
                        if 'content' in delta:
                            content_str = delta['content']
                            full_content += content_str
                            print(f"DEBUG_AI_CHAR:{content_str}", flush=True)
                    except: continue
            
            if full_content:
                return full_content
                
        except Exception as e:
            logging.error(f"❌ Connection error to {url}: {str(e)}")
            continue

    return "Error"

def clean_deepseek_content(content):
    if not content or not isinstance(content, str): return ""
    content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
    return content.strip()

def ChatGPT_API_with_finish_reason(model, prompt, api_key=None, chat_history=None):
    messages = chat_history + [{"role": "user", "content": prompt}] if chat_history else [{"role": "user", "content": prompt}]
    
    max_retries = 5
    for i in range(max_retries):
        raw = request_api_stream_sync(model, messages)
        if raw != "Error" and raw.strip():
            # 简单校验 JSON 结构
            if '{' in raw or '[' in raw:
                return clean_deepseek_content(raw), "finished"
        
        wait_time = 3 * (2 ** i)
        print(f'************* API Retry ({i+1}/{max_retries}) - Waiting {wait_time}s *************')
        time.sleep(wait_time)
        
    return "Error", "failed"

def ChatGPT_API(model, prompt, api_key=None, chat_history=None):
    res, _ = ChatGPT_API_with_finish_reason(model, prompt, api_key, chat_history)
    return res

async def ChatGPT_API_async(model, prompt, api_key=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, ChatGPT_API, model, prompt)

def get_json_content(content):
    if not content: return ""
    match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
    if match: return match.group(1)
    return content

# === ROBUST EXTRACTION FIX ===
def extract_json(content):
    """
    Robust JSON extraction capable of handling markdown blocks, extra commas, 
    and non-standard JSON often returned by LLMs.
    """
    if content == "Error" or not content: 
        return UniversalFallback()
    
    try:
        content = clean_deepseek_content(content)
        json_str = ""
        
        # 1. Try Markdown Block
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 2. Find outermost brackets (non-greedy logic for safety)
            start_idx = content.find('{')
            end_idx = content.rfind('}')
            list_start = content.find('[')
            list_end = content.rfind(']')
            
            # Determine if it's likely a dict or a list
            if start_idx != -1 and (list_start == -1 or start_idx < list_start):
                 if end_idx != -1: json_str = content[start_idx : end_idx + 1]
            elif list_start != -1:
                 if list_end != -1: json_str = content[list_start : list_end + 1]
            else:
                 json_str = content
        
        if not json_str: return UniversalFallback()
        
        # 3. Clean up common errors
        # Remove trailing commas like ", }" -> "}"
        json_str = re.sub(r',\s*([\]}])', r'\1', json_str)
        
        return json.loads(json_str)

    except json.JSONDecodeError:
        # 4. Fallback for specific known fields if strict parsing fails
        if "summary" in content:
            match = re.search(r'"summary"\s*:\s*"(.*?)"', content, re.DOTALL)
            if match: return {"summary": match.group(1)}
            
        logging.warning(f"JSON Parsing failed strictly. Raw content start: {content[:50]}...")
        return UniversalFallback()
    except Exception as e:
        logging.error(f"JSON Parsing fatal error: {e}")
        return UniversalFallback()

def count_tokens(text, model=None):
    return len(text) // 2

def write_node_id(data, node_id=0):
    if isinstance(data, dict):
        data['node_id'] = str(node_id).zfill(4); node_id += 1
        for k in list(data.keys()):
            if 'nodes' in k: node_id = write_node_id(data[k], node_id)
    elif isinstance(data, list):
        for i in range(len(data)): node_id = write_node_id(data[i], node_id)
    return node_id

def get_nodes(structure):
    # NOTE: This original version uses deepcopy, which prevents in-place modification.
    # For in-place modifications (like summaries), use collect_nodes_by_reference in page_index.py
    if isinstance(structure, dict):
        sn = copy.deepcopy(structure); sn.pop('nodes', None)
        nodes = [sn]
        for k in list(structure.keys()):
            if 'nodes' in k: nodes.extend(get_nodes(structure[k]))
        return nodes
    elif isinstance(structure, list):
        res = []
        for i in structure: res.extend(get_nodes(i))
        return res

def get_pdf_name(pdf_path):
    if hasattr(pdf_path, 'name'): return pdf_path.name
    return os.path.basename(pdf_path)

class JsonLogger:
    def __init__(self, file_path):
        name = get_pdf_name(file_path)
        self.filename = f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        os.makedirs("./logs", exist_ok=True); self.log_data = []
    
    def log(self, level, message, **kwargs):
        entry = {'message': str(message), 'level': level, 'timestamp': datetime.now().isoformat()}
        self.log_data.append(entry)
        try:
            with open(os.path.join("logs", self.filename), "w", encoding="utf-8-sig") as f:
                json.dump(self.log_data, f, indent=2, ensure_ascii=False)
        except Exception: pass

    def info(self, m): self.log("INFO", m)
    def error(self, m): self.log("ERROR", m)

def get_page_tokens(pdf_path, model=None):
    page_list = []
    
    if HAS_PDFPLUMBER:
        print("[INFO] Using pdfplumber for text extraction (Reliable for CJK).")
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text() or "" 
                    t = t.replace('\x00', '')
                    page_list.append((t, len(t)))
            return page_list
        except Exception as e:
            print(f"[ERROR] pdfplumber failed: {e}. Falling back to PyPDF2.")
            
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(pdf_path)
        for page in reader.pages:
            t = page.extract_text() or ""
            t = t.replace('\x00', '')
            page_list.append((t, len(t)))
    except Exception as e:
        print(f"[ERROR] PDF Read Error: {e}")
        return []
    
    return page_list

def get_text_of_pages(pdf_path, start, end, tag=True):
    text = ""
    start = max(1, start)
    
    if HAS_PDFPLUMBER:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                loop_end = min(end, total_pages)
                for i in range(start-1, loop_end):
                    t = pdf.pages[i].extract_text() or ""
                    text += f"<start_index_{i+1}>\n{t}\n<end_index_{i+1}>\n" if tag else t
            return text
        except: pass

    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(pdf_path)
        total_pages = len(reader.pages)
        loop_end = min(end, total_pages)
        for i in range(start-1, loop_end):
            t = reader.pages[i].extract_text() or ""
            text += f"<start_index_{i+1}>\n{t}\n<end_index_{i+1}>\n" if tag else t
    except: pass
    return text

def list_to_tree(data):
    nodes, roots = {}, []
    for item in data:
        c = item.get('structure')
        try:
            s_idx = int(item.get('start_index', 0))
            e_idx = int(item.get('end_index', 0))
        except: s_idx, e_idx = 0, 0
        
        node = {
            'title': item.get('title', 'Untitled'), 
            'start_index': s_idx, 
            'end_index': e_idx, 
            'nodes': []
        }
        
        key = str(c) if c else str(item.get('title')) + str(s_idx)
        nodes[key] = node
        p_c = '.'.join(str(c).split('.')[:-1]) if c and '.' in str(c) else None
        
        if p_c and p_c in nodes: nodes[p_c]['nodes'].append(node)
        else: roots.append(node)
    return roots

def post_processing(structure, end_idx):
    if not structure: return []
    for i, item in enumerate(structure):
        try:
            curr_idx = int(item.get('physical_index', 0))
            if i < len(structure) - 1:
                next_idx_val = int(structure[i+1]['physical_index'])
                if next_idx_val > curr_idx: item['end_index'] = next_idx_val
                else: item['end_index'] = curr_idx 
            else:
                item['end_index'] = end_idx
            item['start_index'] = curr_idx
        except: continue
    return list_to_tree(structure)

def reorder_dict(data, key_order):
    return {k: data[k] for k in key_order if k in data}

def format_structure(structure, order=None):
    if isinstance(structure, dict):
        if 'nodes' in structure: structure['nodes'] = format_structure(structure['nodes'], order)
        return reorder_dict(structure, order) if order else structure
    elif isinstance(structure, list):
        return [format_structure(i, order) for i in structure]
    return structure

class ConfigLoader:
    def __init__(self, default_path=None):
        if default_path is None: default_path = Path(__file__).parent / "config.yaml"
        if not os.path.exists(default_path): self._default_dict = {}
        else:
            with open(default_path, "r", encoding="utf-8") as f: self._default_dict = yaml.safe_load(f) or {}
    def load(self, user_opt=None) -> config:
        u_dict = vars(user_opt) if isinstance(user_opt, config) else (user_opt or {})
        return config(**{**self._default_dict, **u_dict})

def convert_physical_index_to_int(data):
    if isinstance(data, list):
        for i in range(len(data)):
            if 'physical_index' in data[i]:
                try:
                    val = str(data[i]['physical_index'])
                    m = re.search(r'(\d+)', val)
                    if m: data[i]['physical_index'] = int(m.group(1))
                    else: data[i]['physical_index'] = None
                except: data[i]['physical_index'] = None
    return data

def add_preface_if_needed(toc_list):
    if not toc_list or not isinstance(toc_list, list): return toc_list
    try:
        first_item = toc_list[0]
        if not isinstance(first_item, dict): return toc_list
        start_index = first_item.get('start_index') or first_item.get('physical_index')
        if isinstance(start_index, str):
            nums = re.findall(r'\d+', start_index)
            start_val = int(nums[0]) if nums else 1
        else: start_val = int(start_index)
        if start_val > 1:
            preface_node = {
                'title': 'Preface / Abstract',
                'structure': '0',
                'start_index': 1,
                'end_index': start_val, 
                'physical_index': 1,
                'level': 1
            }
            toc_list.insert(0, preface_node)
    except: pass
    return toc_list

def convert_page_to_int(toc_list):
    if not isinstance(toc_list, list): return toc_list
    for item in toc_list:
        if isinstance(item, dict) and 'page' in item:
            try:
                original_page = str(item['page'])
                nums = re.findall(r'\d+', original_page)
                item['page'] = int(nums[0]) if nums else 1
            except: item['page'] = 1
        if isinstance(item, dict) and 'nodes' in item:
            convert_page_to_int(item['nodes'])
    return toc_list

def add_node_text(structure, page_list):
    if isinstance(structure, list):
        for node in structure: add_node_text(node, page_list)
    elif isinstance(structure, dict):
        try:
            start = int(structure.get('start_index') or 1)
            end = int(structure.get('end_index') or start)
            text_content = ""
            max_page = len(page_list)
            start_idx = max(0, start - 1)
            end_idx = min(max_page, end)
            for i in range(start_idx, end_idx):
                if i < len(page_list): text_content += page_list[i][0] + "\n"
            structure['text'] = text_content
            if 'nodes' in structure: add_node_text(structure['nodes'], page_list)
        except: pass

async def generate_summaries_for_structure(structure, model=None):
    # Fallback legacy function if used elsewhere, though page_index.py now has its own robust version
    nodes = get_nodes(structure)
    tasks = []
    async def summarize_node(node):
        text_content = node.get('text', '')
        if not text_content: 
            node['summary'] = ""
            return
        prompt = f"Summarize the following section text in one concise sentence:\n\n{text_content[:3000]}"
        summary = await ChatGPT_API_async(model, prompt)
        node['summary'] = summary.strip()
    for node in nodes: tasks.append(summarize_node(node))
    if tasks: await asyncio.gather(*tasks)
    return structure

def clean_page_numbers(data):
    if isinstance(data, dict):
        for k, v in data.items():
            if k in ['page_number', 'page', 'physical_index', 'start_index', 'end_index']:
                try:
                    if isinstance(v, str):
                        digits = ''.join(filter(str.isdigit, v))
                        data[k] = int(digits) if digits else 0
                    elif isinstance(v, (float, int)): data[k] = int(v)
                except: pass
        for k, v in data.items(): clean_page_numbers(v)
    elif isinstance(data, list):
        for item in data: clean_page_numbers(item)
    return data

def remove_structure_text(structure):
    if isinstance(structure, dict):
        structure.pop('text', None)
        if 'nodes' in structure: remove_structure_text(structure['nodes'])
    elif isinstance(structure, list):
        for item in structure: remove_structure_text(item)
