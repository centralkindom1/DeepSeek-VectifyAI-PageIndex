# backend_pgui.py （已修改 Prompt 以支持跨语言检索）
import sys
import json
import os
import time
import argparse
import requests
import urllib3
import re

# ==================================================================================
# [BACKEND LOGIC - PORTED FROM 'GoodForTAB_B_Vector_pgui.py']
# This script handles the "TAB B" RAG Vectorization using the robust, sequential logic
# preferred by the user.
# ==================================================================================

# 1. Network & Environment Config
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Clear Proxies
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(k, None)

# 2. API Configuration (Internal Network)
API_KEY = "YOUR API KEY"
BASE_URL = "https://WWW.DEEPSEEK.COM.cn:18080/v1" 

# ================= PROMPTS (MODIFIED FOR CROSS-LINGUAL RAG) =================
SYSTEM_PROMPT = """你是一个高精度的元数据分析师。你的任务是分析给定的文档片段，并生成一段简短的、富含上下文的“语义导语”。

【关键原则】
1. **语言桥梁**：无论输入文档的原始语言是中文、英文还是其他语言，你的**输出分析（语义导语）必须始终使用简体中文**。这非常重要，用于跨语言检索。
2. **内容定位**：导语必须明确指出这段内容属于哪个章节路径，包含什么类型的数据。"""

USER_PROMPT_TEMPLATE = """请分析以下文档片段的元数据。

【输入信息】
- 文档标题：{doc_title}
- 章节路径：{path_str}
- 数据片段长度：{length} 字符
- 数据预览（可能包含英文/中文）：
{content_preview}

【任务要求】
1. 生成 `semantic_intro`：
   - 使用 **简体中文** 撰写。
   - 这是一段 50-100 字的描述，说明这段数据在文档中的位置以及它主要包含什么实体。
   - **如果是英文原文**，请翻译其核心主题（例如：原文是 "Flight Schedule from JFK"，导语应包含 "肯尼迪机场(JFK)出发的航班时刻表"）。
2. 生成 `section_hint`：
   - 使用 **简体中文** 提取 1-3 个关键词（如：航班时刻表 / 票价规则 / 维护手册）。
3. **绝对不要** 列举具体数据（因为我会把原始数据拼接到后面），只需要描述数据的性质和范围。
4. 输出为 JSON 格式。

【JSON 结构】：
{{
  "semantic_intro": "这是关于 [路径] 的详细数据表，包含...",
  "section_hint": "关键词1 / 关键词2"
}}
"""
# ======================================================

def log(msg, level="INFO"):
    # Standard output format compatible with Frontend worker
    print(f"[{level}] {msg}", flush=True)

def recursive_walk(nodes, path=[], depth=1):
    for node in nodes:
        current_title = node.get("title", "Untitled")
        current_title = current_title.replace('\n', ' ').strip()
        current_path = path + [current_title]
        
        yield {"node": node, "path": current_path, "depth": depth}
        
        if "nodes" in node and isinstance(node["nodes"], list):
            yield from recursive_walk(node["nodes"], current_path, depth + 1)

def extract_json_robust(content):
    if not content: return None
    # Try multiple regex patterns
    patterns = [
        r'```json\s*([\s\S]*?)\s*```',
        r'```\s*([\s\S]*?)\s*```',
        r'(\{[\s\S]*\})'
    ]
    json_str = None
    for p in patterns:
        match = re.search(p, content)
        if match:
            json_str = match.group(1)
            break
    
    if not json_str: 
        json_str = content

    # Clean common JSON errors
    json_str = re.sub(r',\s*([\]}])', r'\1', json_str) # Remove trailing commas
    
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None

def call_llm_api(system_prompt, user_prompt, model_name):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    target_model = model_name if model_name else "DeepSeek-V3"
    data = {
        "model": target_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": 1000, 
        "temperature": 0.1, 
        "stream": True 
    }
    try:
        session = requests.Session()
        session.trust_env = False 
        url = f"{BASE_URL.rstrip('/')}/chat/completions"
        response = session.post(url, headers=headers, json=data, stream=True, timeout=60, verify=False)
        
        full_content = ""
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8', errors='ignore')
                if decoded_line.startswith("data:"):
                    json_str = decoded_line[5:].strip()
                    if json_str == "[DONE]": break
                    try:
                        chunk = json.loads(json_str)
                        if "choices" in chunk and len(chunk["choices"]) > 0:
                            content = chunk["choices"][0]["delta"].get("content", "")
                            if content:
                                full_content += content
                                # === Visualizer Output (Caught by Frontend) ===
                                print(f"DEBUG_AI_CHAR:{content}", flush=True) 
                    except: pass
        return full_content
    except Exception as e:
        return f"[FAILED] {str(e)}"

def main():
    if sys.stdout: sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--strategy", type=int, default=0) # 0: Lossless, 1: Semantic, 2: Mixed
    # Note: Threads arg might be passed by frontend, but we ignore it to keep logic sequential/good
    parser.add_argument("--threads", type=int, default=1, required=False) 
    args = parser.parse_args()

    log(f"Starting Vector Gen (Strategy Mode: {args.strategy})...", "INFO")
    if not os.path.exists(args.input):
        log(f"Input file not found: {args.input}", "ERROR")
        return

    try:
        with open(args.input, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
        
        root_nodes = []
        doc_title = "Unknown Document"
        if isinstance(data, list):
            root_nodes = data
        elif isinstance(data, dict):
            root_nodes = data.get("structure", [])
            doc_title = data.get("doc_name", data.get("title", "Unknown Document"))
        
        output_data = []
        
        processed_count = 0
        
        for item in recursive_walk(root_nodes):
            node = item["node"]
            path = item["path"]
            depth = item["depth"]
            content = node.get("text", node.get("content", ""))
            node_id = node.get("node_id", f"{processed_count:04d}")
            
            # 1. Filtering Logic
            has_children = "nodes" in node and isinstance(node["nodes"], list) and len(node["nodes"]) > 0
            if (not content or len(content.strip()) < 10) and not has_children:
                continue
            
            # 2. Prepare Prompt
            path_str = " > ".join(path)
            content_preview = content[:1000] + "..." if len(content) > 1000 else content
            
            prompt = USER_PROMPT_TEMPLATE.format(
                doc_title=doc_title,
                path_str=path_str,
                length=len(content),
                content_preview=content_preview
            )
            
            log(f"Processing Node {node_id}: {path[-1][:30]}...", "INFO")
            
            # 3. Call LLM
            response_text = call_llm_api(SYSTEM_PROMPT, prompt, args.model)
            
            # 4. Parse Result
            vector_obj = extract_json_robust(response_text)
            if not vector_obj:
                vector_obj = {
                    "semantic_intro": f"这是文档 {doc_title} 中章节 {path_str} 的数据内容。",
                    "section_hint": "数据片段"
                }
                log(f"JSON Parse Failed for {node_id}, using fallback.", "WARN")

            # 5. [Core] Strategy Branching (From Good Tab B)
            semantic_intro = vector_obj.get("semantic_intro", "")
            raw_data_block = content.strip()
            
            if args.strategy == 0: 
                if not raw_data_block and has_children:
                     final_text = f"{semantic_intro}\n(包含子章节数据)"
                else:
                     final_text = f"{semantic_intro}\n\n【原始数据内容】:\n{raw_data_block}"
            
            elif args.strategy == 1: 
                final_text = semantic_intro
            
            else: 
                 final_text = f"{semantic_intro}\n\n[Reference Data]:\n{raw_data_block}"

            final_item = {
                "embedding_text": final_text, 
                "section_hint": vector_obj.get("section_hint", "General"),
                "metadata": {
                    "doc_title": doc_title,
                    "section_id": node_id,
                    "section_path": path,
                    "depth": depth,
                    "original_length": len(content),
                    "strategy": args.strategy
                },
                "original_snippet": content 
            }

            output_data.append(final_item)
            processed_count += 1
            
            print(f"@@PROGRESS@@{{\"phase\": \"Vectorizing\", \"current\": {processed_count}, \"total\": 0}}", flush=True)
            
            time.sleep(0.1)

        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        log(f"Generation Complete! Total: {processed_count}", "SUCCESS")
        log(f"Output: {args.output}", "SUCCESS")

    except Exception as e:
        log(f"Critical Error: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()