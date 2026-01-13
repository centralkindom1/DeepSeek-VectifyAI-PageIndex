import sys
import json
import os
import subprocess
import time
import warnings
from datetime import timedelta

# 屏蔽 SIP 弃用警告，保持控制台干净
warnings.filterwarnings("ignore", category=DeprecationWarning)

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QTextEdit, QComboBox, 
                             QFileDialog, QMessageBox, QFrame, QTabWidget, QSplitter, QProgressBar)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QProcessEnvironment, QTimer, QTime
from PyQt5.QtGui import QTextCursor, QColor, QFont

# ==================================================================================
# [配置区域]
# ==================================================================================
CONFIG_FILE = "gui_configs.json"

# 尝试导入可视化窗口，如果不存在则使用占位符
try:
    from ai_visual_window import AIVisualWindow
except ImportError:
    class AIVisualWindow(QWidget):
        def add_stream_char(self, c): pass
        def show(self): pass
        def hide(self): pass
        def move(self, x, y): pass

# ==================================================================================
# [后端向量化脚本 - 已修复进度条反馈逻辑]
# ==================================================================================
VECTOR_GEN_SCRIPT = r'''
import sys
import json
import os
import time
import argparse
import requests
import urllib3
import re

# 1. 网络与环境配置
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 清理代理
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(k, None)

# 2. API 配置 (保持内网配置)
API_KEY = "YOUR API KEY"
BASE_URL = "https://WWW.DEEPSEEK.COM:18080/v1" 

# ================= PROMPTS =================
SYSTEM_PROMPT = """你是一个高精度的元数据分析师。你的任务是分析给定的文档片段，并生成一段简短的、富含上下文的“语义导语”。

【注意】
你不需要重写原始数据，只需要生成“导语”。
导语必须明确指出：这段内容属于哪个章节路径，包含什么类型的数据。"""

USER_PROMPT_TEMPLATE = """请分析以下文档片段的元数据。

【输入信息】
- 文档标题：{doc_title}
- 章节路径：{path_str}
- 数据片段长度：{length} 字符
- 数据预览：
{content_preview}

【任务要求】
1. 生成 `semantic_intro`：一段 50-100 字的描述，说明这段数据在文档中的位置（基于章节路径）以及它主要包含什么实体（如“包含从北京(PKX)出发的航班时刻表”）。
2. **绝对不要** 列举具体数据（因为我会把原始数据拼接到后面），只需要描述数据的性质和范围。
3. 输出为 JSON 格式。

【JSON 结构】：
{{
  "semantic_intro": "这是关于 [路径] 的详细数据表，包含...",
  "section_hint": "航班时刻表 / 票价列表 / ..."
}}
"""
# ======================================================

def log(msg, level="INFO"):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{level}] {msg}", flush=True)

# 新增：发送进度给前端 GUI
def report_progress(current, total, start_time):
    if total <= 0: return
    elapsed = time.time() - start_time
    avg_time = elapsed / max(1, current)
    remaining = total - current
    eta_sec = int(avg_time * remaining)
    
    data = {
        "phase": "Vectorizing",
        "current": current,
        "total": total,
        "eta_sec": eta_sec
    }
    print(f"@@PROGRESS@@{json.dumps(data)}", flush=True)

def count_total_nodes(nodes):
    count = 0
    for node in nodes:
        count += 1
        if "nodes" in node and isinstance(node["nodes"], list):
            count += count_total_nodes(node["nodes"])
    return count

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
    # 尝试多种正则匹配
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

    # 清理常见的 JSON 错误
    json_str = re.sub(r',\s*([\]}])', r'\1', json_str) # 去掉尾部逗号
    
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
                                # === [FIX] 恢复可视化输出 ===
                                print(f"DEBUG_AI_CHAR:{content}", flush=True) 
                    except: pass
        return full_content
    except Exception as e:
        return f"[FAILED] {str(e)}"

def main():
    # 强制 UTF-8 输出
    if sys.stdout: sys.stdout.reconfigure(encoding='utf-8')
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--strategy", type=int, default=0) # 0: Lossless, 1: Semantic, 2: Mixed
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
        
        # [FIX] 预计算总节点数，以便进度条工作
        total_nodes = count_total_nodes(root_nodes)
        log(f"Document Structure Loaded. Total Nodes detected: {total_nodes}", "INFO")

        output_data = []
        processed_count = 0
        start_time = time.time()
        
        for item in recursive_walk(root_nodes):
            node = item["node"]
            path = item["path"]
            depth = item["depth"]
            content = node.get("text", node.get("content", ""))
            node_id = node.get("node_id", f"{processed_count:04d}")
            
            # 1. 过滤逻辑
            has_children = "nodes" in node and isinstance(node["nodes"], list) and len(node["nodes"]) > 0
            
            # 跳过太短且没有子节点的
            if (not content or len(content.strip()) < 10) and not has_children:
                # 即使跳过，进度计数也要增加
                processed_count += 1
                report_progress(processed_count, total_nodes, start_time)
                continue
            
            # 2. 准备 Prompt
            path_str = " > ".join(path)
            content_preview = content[:1000] + "..." if len(content) > 1000 else content
            
            prompt = USER_PROMPT_TEMPLATE.format(
                doc_title=doc_title,
                path_str=path_str,
                length=len(content),
                content_preview=content_preview
            )
            
            log(f"Processing Node {node_id}: {path[-1][:30]}...", "INFO")
            
            # 3. 调用 LLM
            response_text = call_llm_api(SYSTEM_PROMPT, prompt, args.model)
            
            # 4. 解析结果
            vector_obj = extract_json_robust(response_text)
            if not vector_obj:
                vector_obj = {
                    "semantic_intro": f"这是文档 {doc_title} 中章节 {path_str} 的数据内容。",
                    "section_hint": "数据片段"
                }
                log(f"JSON Parse Failed for {node_id}, using fallback.", "WARN")

            # 5. [核心] 策略分支
            semantic_intro = vector_obj.get("semantic_intro", "")
            raw_data_block = content.strip()
            
            if args.strategy == 0: # 数据无损模式 (Table/Schedule)
                if not raw_data_block and has_children:
                     final_text = f"{semantic_intro}\n(包含子章节数据)"
                else:
                     final_text = f"{semantic_intro}\n\n【原始数据内容】:\n{raw_data_block}"
            
            elif args.strategy == 1: # 公文语义总结 (Policy/Doc)
                final_text = semantic_intro
            
            else: # 混合模式
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
                "original_snippet": content[:500] 
            }

            output_data.append(final_item)
            processed_count += 1
            
            # 报告进度
            report_progress(processed_count, total_nodes, start_time)
            
            # 避免 API 过载
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
'''

# === Cyberpunk Style Sheet ===
STYLESHEET = """
QMainWindow { background-color: #0d1117; }
QTabWidget::pane { border: 1px solid #30363d; background-color: #0d1117; top: -1px; }
QTabBar::tab { background: #161b22; color: #8b949e; padding: 10px 20px; border: 1px solid #30363d; margin-right: 2px; }
QTabBar::tab:selected { background: #0d1117; color: #00ffcc; border-bottom: 2px solid #00ffcc; }
QLabel { color: #c9d1d9; font-family: 'Segoe UI', sans-serif; font-weight: bold; }
QLabel#TimerLabel { font-family: 'Consolas', monospace; color: #00ffcc; font-size: 14px; font-weight: bold; }
QLabel#EtaLabel { font-family: 'Consolas', monospace; color: #8b949e; font-size: 14px; }
QLineEdit { background-color: #161b22; border: 1px solid #30363d; border-radius: 4px; color: #c9d1d9; padding: 5px; }
QLineEdit:focus { border: 1px solid #00ffcc; }
QPushButton { background-color: #238636; color: white; border: none; padding: 8px 16px; border-radius: 6px; font-weight: bold; }
QPushButton:hover { background-color: #2ea043; }
QPushButton#VisualBtn { background-color: #1f6feb; }
QPushButton#StopBtn { background-color: #da3633; }
QTextEdit { background-color: #0d1117; border: 1px solid #30363d; color: #00ff99; font-family: 'Consolas', monospace; font-size: 12px; }
QComboBox { background-color: #161b22; color: #c9d1d9; border: 1px solid #30363d; padding: 5px; border-radius: 4px; }
QFrame#ConfigFrame { background-color: #161b22; border-radius: 8px; border: 1px solid #30363d; }
QProgressBar { border: 1px solid #30363d; border-radius: 5px; text-align: center; color: white; background-color: #161b22; }
QProgressBar::chunk { background-color: #238636; width: 10px; margin: 0.5px; }
"""

AVAILABLE_MODELS = ["DeepSeek-V3", "qwen2.5-vl-72b", "DeepSeek-R1", "qwq-32b", "Qwen2.5-32B"]
DEFAULT_MODEL = "DeepSeek-V3"
PROGRESS_PREFIX = "@@PROGRESS@@"

# ==================================================================================
# [工作线程 - 核心引擎]
# ==================================================================================
class WorkerThread(QThread):
    log_signal = pyqtSignal(str)      
    stream_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(dict) # 新增：进度信号  
    finished_signal = pyqtSignal()

    def __init__(self, command):
        super().__init__()
        self.command = command
        self.is_running = True
        self.process = None
        self.line_buffer = "" 

    def run(self):
        try:
            # [关键修复] 注入环境变量，强制 UTF-8，防止乱码
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONLEGACYWINDOWSSTDIO"] = "utf-8" # 针对 Windows 兼容性
            env["PYTHONUTF8"] = "1" # 强制 Python 3.7+ 使用 UTF-8 模式

            # [关键修复] 隐藏 Windows 下的黑色 CMD 窗口
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            # 确保命令是字符串类型
            command_str = str(self.command)

            self.process = subprocess.Popen(
                command_str,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=True,             # 保持 shell=True 以解析系统路径
                text=True,
                encoding='utf-8',       # 强制 UTF-8 解码
                errors='replace',       # 遇到无法解码的字符用 ? 代替，防止崩溃
                bufsize=0,              # 无缓冲实时输出
                env=env,                # 应用环境设置
                startupinfo=startupinfo # 应用隐藏窗口设置
            )

            while self.is_running:
                if self.process is None:
                    break
                    
                # 逐字符读取，实现实时打字机效果
                char = self.process.stdout.read(1)
                
                # 检查进程是否结束
                if not char and self.process.poll() is not None:
                    break
                    
                if char:
                    self.process_char(char)
            
            self.flush_buffer()
            if self.process:
                self.process.wait()
                
        except Exception as e:
            # 捕获所有异常，防止UI闪退，并显示错误信息
            import traceback
            error_msg = f"Critical Error in Thread: {str(e)}\n{traceback.format_exc()}"
            self.emit_log_line(f"[ERROR] {error_msg}")
        finally:
            self.finished_signal.emit()

    def stop(self):
        self.is_running = False
        if self.process:
            try:
                # 尝试优雅终止
                import signal
                self.process.terminate()
                # Windows 下 shell=True 创建的进程树需要更强力的杀手
                if os.name == 'nt':
                     subprocess.run(f"taskkill /F /T /PID {self.process.pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except:
                pass

    def flush_buffer(self):
        if self.line_buffer:
            self.process_line(self.line_buffer.strip())
            self.line_buffer = ""

    def process_char(self, char):
        self.line_buffer += char
        if char == "\n":
            self.process_line(self.line_buffer.strip())
            self.line_buffer = ""

    def process_line(self, line):
        if not line: return
        
        # 1. 检查是否为进度数据包
        if line.startswith(PROGRESS_PREFIX):
            try:
                json_str = line[len(PROGRESS_PREFIX):]
                data = json.loads(json_str)
                self.progress_signal.emit(data)
                return # 进度数据不显示在日志控制台
            except:
                pass # 解析失败则作为普通日志输出

        # 2. 检查是否为打字机字符流
        if line.startswith("DEBUG_AI_CHAR:"):
            try:
                content = line.split("DEBUG_AI_CHAR:", 1)[1]
                self.stream_signal.emit(content)
            except: pass
            return

        # 3. 普通日志处理
        self.emit_log_line(line)

    def emit_log_line(self, line):
        # 智能日志着色 - 让你一眼看清问题
        timestamp = time.strftime("%H:%M:%S")
        prefix = f"<span style='color:#555;'>[{timestamp}]</span> "
        
        if "[SUCCESS]" in line or "accuracy: 100.00%" in line:
            formatted = f"{prefix}<span style='color:#00FF00; font-weight:bold;'>{line}</span>"
        elif "[ERROR]" in line or "Exception" in line or "Traceback" in line:
            formatted = f"{prefix}<span style='color:#FF3333; font-weight:bold; background-color:#330000;'>{line}</span>"
        elif "WARNING" in line or "accuracy:" in line:
            formatted = f"{prefix}<span style='color:#FFD700; font-weight:bold;'>{line}</span>"
        elif "large node" in line:
            formatted = f"{prefix}<span style='color:#FF00FF;'>{line}</span>"
        elif "[INFO]" in line:
            formatted = f"{prefix}<span style='color:#79c0ff;'>{line}</span>"
        else:
            formatted = f"{prefix}<span style='color:#c9d1d9;'>{line}</span>"
            
        self.log_signal.emit(formatted)

# ==================================================================================
# [主界面]
# ==================================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PageIndex Pro 2026 - Neural Interface")
        self.resize(1200, 900)
        self.visual_window = AIVisualWindow()
        self.configs = self.load_configs()
        self.worker = None
        
        # 计时器相关
        self.start_time = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_timer_display)
        
        self.init_ui()
        self.apply_styles()

    def apply_styles(self):
        self.setStyleSheet(STYLESHEET)

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        
        # Header
        header = QHBoxLayout()
        title = QLabel("PAGEINDEX PRO <sup>v2026.1</sup>")
        title.setStyleSheet("font-size: 26px; color: #00ffcc; letter-spacing: 2px;")
        header.addWidget(title)
        header.addStretch()
        main_layout.addLayout(header)

        # Tabs
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        self.tab_pageindex = QWidget()
        self.init_tab_pageindex()
        self.tabs.addTab(self.tab_pageindex, "PDF Parsing (PageIndex)")

        self.tab_vector = QWidget()
        self.init_tab_vector()
        self.tabs.addTab(self.tab_vector, "RAG Vectorization")

        # Console
        main_layout.addWidget(QLabel("SYSTEM KERNEL LOGS:"))
        self.txt_console = QTextEdit()
        self.txt_console.setReadOnly(True)
        main_layout.addWidget(self.txt_console, 1) # Give console more space
        
        # === NEW: 底部状态栏与计时器 ===
        self.init_status_area(main_layout)

    def init_status_area(self, layout):
        # 进度条
        self.status_bar = QProgressBar()
        self.status_bar.setRange(0, 100) 
        self.status_bar.setValue(0)
        self.status_bar.setTextVisible(True)
        self.status_bar.setFormat("%p% - Processing...")
        self.status_bar.setFixedHeight(20)
        self.status_bar.hide()
        layout.addWidget(self.status_bar)

        # 时间显示区域
        time_layout = QHBoxLayout()
        time_layout.setContentsMargins(5, 5, 5, 5)
        
        self.lbl_elapsed = QLabel("ELAPSED: 00:00:00")
        self.lbl_elapsed.setObjectName("TimerLabel")
        
        self.lbl_eta = QLabel("REMAINING: --:--:--")
        self.lbl_eta.setObjectName("EtaLabel")
        
        time_layout.addWidget(self.lbl_elapsed)
        time_layout.addStretch()
        time_layout.addWidget(self.lbl_eta)
        
        layout.addLayout(time_layout)

    def init_tab_pageindex(self):
        layout = QVBoxLayout(self.tab_pageindex)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Config Panel
        cfg_frame = QFrame()
        cfg_frame.setObjectName("ConfigFrame")
        cfg = QHBoxLayout(cfg_frame)
        self.cb_configs = QComboBox()
        self.cb_configs.addItems(self.configs.keys())
        self.cb_configs.currentTextChanged.connect(self.load_selected_config)
        btn_save = QPushButton("💾 SAVE PRESET")
        btn_save.clicked.connect(self.save_config)
        btn_save.setStyleSheet("background-color: #21262d;")
        cfg.addWidget(QLabel("PRESET:"))
        cfg.addWidget(self.cb_configs, 1)
        cfg.addWidget(btn_save)
        layout.addWidget(cfg_frame)

        # PDF Input
        row1 = QHBoxLayout()
        self.edit_pdf = QLineEdit()
        self.edit_pdf.setPlaceholderText("Full path to PDF document...")
        btn_browse = QPushButton("📂 LOAD PDF")
        btn_browse.clicked.connect(self.get_file)
        row1.addWidget(QLabel("DOCUMENT:"))
        row1.addWidget(self.edit_pdf, 1)
        row1.addWidget(btn_browse)
        layout.addLayout(row1)

        # Model & Settings
        row2 = QHBoxLayout()
        self.combo_model = QComboBox()
        self.combo_model.addItems(AVAILABLE_MODELS)
        
        # 处理方案选择
        self.combo_schema = QComboBox()
        self.combo_schema.addItems([
            "Schema A: Full Intelligence (Text+Summary+Desc) [Slowest, Max Detail]",
            "Schema B: Data Warehouse (Text Only+Desc) [Fast, Big JSON]",
            "Schema C: Structure Only (Desc Only) [Fastest, Small JSON]"
        ])
        
        row2.addWidget(QLabel("AI MODEL:"))
        row2.addWidget(self.combo_model, 1)
        row2.addWidget(QLabel("SCHEMA:"))
        row2.addWidget(self.combo_schema, 1)
        layout.addLayout(row2)

        # Controls
        controls = QHBoxLayout()
        self.btn_run = QPushButton("🚀 START INDEXING")
        self.btn_run.setFixedHeight(45)
        self.btn_run.clicked.connect(self.start_pageindex_task)
        
        self.btn_stop = QPushButton("🛑 STOP")
        self.btn_stop.setObjectName("StopBtn")
        self.btn_stop.setFixedHeight(45)
        self.btn_stop.clicked.connect(self.stop_worker)
        self.btn_stop.setEnabled(False)

        self.btn_visual = QPushButton("👁 VISUALIZER: OFF")
        self.btn_visual.setObjectName("VisualBtn")
        self.btn_visual.setCheckable(True)
        self.btn_visual.setFixedHeight(45)
        self.btn_visual.clicked.connect(self.toggle_visual_window)

        controls.addWidget(self.btn_run, 3)
        controls.addWidget(self.btn_stop, 1)
        controls.addWidget(self.btn_visual, 1)
        layout.addLayout(controls)
        layout.addStretch()

    def init_tab_vector(self):
        layout = QVBoxLayout(self.tab_vector)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        layout.addWidget(QLabel("<i>Transform PageIndex JSON structure into semantic vectors.</i>"))

        # Source JSON
        row1 = QHBoxLayout()
        self.edit_json_path = QLineEdit()
        self.edit_json_path.setText(r"M:\RAG系统测试入库文档") 
        btn_json = QPushButton("📂 SELECT JSON")
        btn_json.clicked.connect(self.get_json_file)
        row1.addWidget(QLabel("INDEX JSON:"))
        row1.addWidget(self.edit_json_path, 1)
        row1.addWidget(btn_json)
        layout.addLayout(row1)

        # Export
        row2 = QHBoxLayout()
        self.edit_export_path = QLineEdit()
        self.edit_export_path.setPlaceholderText("Auto-generated output path...")
        btn_out = QPushButton("📂 SET OUTPUT")
        btn_out.clicked.connect(self.get_export_path)
        row2.addWidget(QLabel("EXPORT TO:"))
        row2.addWidget(self.edit_export_path, 1)
        row2.addWidget(btn_out)
        layout.addLayout(row2)
        
        self.edit_json_path.textChanged.connect(self.update_export_path)

        # Settings
        row3 = QHBoxLayout()
        self.combo_vector_model = QComboBox()
        self.combo_vector_model.addItems(AVAILABLE_MODELS)
        
        self.combo_strategy = QComboBox()
        self.combo_strategy.addItems(["0: Data Lossless (Table/Schedule)", "1: Semantic Summary (Policy)", "2: Hybrid"])
        
        row3.addWidget(QLabel("SUMMARIZER:"))
        row3.addWidget(self.combo_vector_model, 1)
        row3.addWidget(QLabel("STRATEGY:"))
        row3.addWidget(self.combo_strategy, 1)
        layout.addLayout(row3)

        # Execute
        self.btn_gen_vector = QPushButton("⚡ GENERATE VECTORS")
        self.btn_gen_vector.setFixedHeight(50)
        self.btn_gen_vector.setStyleSheet("background-color: #79c0ff; color: #0d1117; font-weight: bold; font-size: 14px;")
        self.btn_gen_vector.clicked.connect(self.start_vector_task)
        layout.addStretch()
        layout.addWidget(self.btn_gen_vector)

    # === Logic Methods ===

    def load_configs(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f: return json.load(f)
            except: pass
        return {"Default": {"pdf": "", "model": DEFAULT_MODEL}}

    def save_config(self):
        name = self.cb_configs.currentText() or "Custom"
        self.configs[name] = {"pdf": self.edit_pdf.text(), "model": self.combo_model.currentText()}
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(self.configs, f)
        self.append_log("<span style='color:#00FF00'>[SYSTEM] Config saved.</span>")

    def load_selected_config(self, name):
        if name in self.configs:
            c = self.configs[name]
            self.edit_pdf.setText(c.get('pdf', ''))
            self.combo_model.setCurrentText(c.get('model', DEFAULT_MODEL))

    def get_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select PDF", self.edit_pdf.text(), "*.pdf")
        if f: self.edit_pdf.setText(f)

    def get_json_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select JSON", self.edit_json_path.text(), "*.json")
        if f: 
            self.edit_json_path.setText(f)
            self.update_export_path(f)

    def get_export_path(self):
        f, _ = QFileDialog.getSaveFileName(self, "Save JSON", self.edit_export_path.text(), "JSON Files (*.json)")
        if f: self.edit_export_path.setText(f)

    def update_export_path(self, input_path):
        if input_path:
            d, n = os.path.split(input_path)
            self.edit_export_path.setText(os.path.join(d, f"RAG_{n}"))

    def toggle_visual_window(self):
        if self.btn_visual.isChecked():
            self.visual_window.show()
            self.btn_visual.setText("👁 VISUALIZER: ON")
            self.visual_window.move(self.geometry().x() + self.width(), self.geometry().y())
        else:
            self.visual_window.hide()
            self.btn_visual.setText("👁 VISUALIZER: OFF")

    def append_log(self, html):
        self.txt_console.append(html)
        if len(self.txt_console.toPlainText()) > 100000:
            self.txt_console.clear()
            self.txt_console.append("<span style='color:orange'>[SYSTEM] Log cleared to release memory.</span>")

    def update_timer_display(self):
        # 计算已用时间
        elapsed_seconds = int(time.time() - self.start_time)
        delta = timedelta(seconds=elapsed_seconds)
        self.lbl_elapsed.setText(f"ELAPSED: {str(delta)}")
        
    def update_progress_display(self, data):
        """处理来自后端的进度数据"""
        try:
            phase = data.get("phase", "Processing")
            current = data.get("current", 0)
            total = data.get("total", 0)
            eta_sec = data.get("eta_sec", None)
            
            # 更新 ETA
            if eta_sec is not None:
                if eta_sec > 0:
                    eta_str = str(timedelta(seconds=int(eta_sec)))
                    self.lbl_eta.setText(f"REMAINING: {eta_str}")
                else:
                    self.lbl_eta.setText("REMAINING: Calculating...")
            
            # 更新进度条
            if total > 0:
                percent = int((current / total) * 100)
                self.status_bar.setValue(percent)
                self.status_bar.setFormat(f"{phase}: %p% ({current}/{total})")
            else:
                self.status_bar.setFormat(f"{phase}: Working...")
                
        except Exception as e:
            print(f"UI Update Error: {e}")

    def start_worker(self, cmd):
        if self.worker and self.worker.isRunning():
            return
        
        self.txt_console.clear()
        self.status_bar.show()
        self.status_bar.setValue(0)
        self.status_bar.setFormat("Initializing...")
        
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        
        # 启动计时器
        self.start_time = time.time()
        self.lbl_elapsed.setText("ELAPSED: 00:00:00")
        self.lbl_eta.setText("REMAINING: Calculating...")
        self.timer.start(1000) # 每秒刷新一次
        
        self.worker = WorkerThread(cmd)
        self.worker.log_signal.connect(self.append_log)
        self.worker.stream_signal.connect(self.visual_window.add_stream_char)
        self.worker.progress_signal.connect(self.update_progress_display) # 连接进度信号
        self.worker.finished_signal.connect(self.on_worker_finished)
        
        if not self.btn_visual.isChecked():
            self.btn_visual.click()
            
        self.worker.start()

    def stop_worker(self):
        if self.worker:
            self.worker.stop()
            self.timer.stop() # 停止计时
            self.lbl_eta.setText("REMAINING: STOPPED")
            self.append_log("<span style='color:red'>[SYSTEM] Process terminated by user.</span>")

    def on_worker_finished(self):
        self.status_bar.setValue(100)
        self.status_bar.setFormat("COMPLETED")
        self.timer.stop() # 停止计时
        self.lbl_eta.setText("REMAINING: DONE")
        
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.append_log("<span style='color:#00ffcc'>[SYSTEM] Task Completed.</span>")

    # === Task Launchers ===

    def start_pageindex_task(self):
        pdf = self.edit_pdf.text()
        model = self.combo_model.currentText()
        if not pdf: return QMessageBox.warning(self, "Error", "Select PDF file!")
        
        # [CRITICAL FIX]
        # 虽然我们在 UI 上保留了 Schema 选项，但为了保证生成的 JSON 结构与 old_right_pgui.py 完全一致
        # 我们在这里忽略具体的 schema 参数，不再传递 --add_text, --add_summary, --add_desc。
        # 这样可以强制后端使用默认的正确逻辑，避免数据漂移和冗余。
        
        schema_name = self.combo_schema.currentText()
        self.append_log(f"<span style='color:#AAAAAA'>[CONFIG] Schema selected: {schema_name} (Using Standardized Output Kernel)</span>")
        
        py = sys.executable
        # 回归 old_right_pgui.py 的原始命令结构
        # 将 --toc-check-pages 恢复为 3
        cmd = f'"{py}" -u run_pageindex.py --pdf_path "{pdf}" --model "{model}" --toc-check-pages 3'
        
        self.append_log(f"<span style='color:#79c0ff'>[CMD] {cmd}</span>")
        self.start_worker(cmd)

    def ensure_backend_script(self):
        try:
            with open("run_vector_gen.py", "w", encoding="utf-8") as f:
                f.write(VECTOR_GEN_SCRIPT)
            return True
        except Exception as e:
            self.append_log(f"<span style='color:red'>[ERROR] Failed to update backend script: {e}</span>")
            return False

    def start_vector_task(self):
        if not self.ensure_backend_script(): return
        
        inp = self.edit_json_path.text()
        out = self.edit_export_path.text()
        model = self.combo_vector_model.currentText()
        strat = self.combo_strategy.currentIndex() 
        
        if not inp: return QMessageBox.warning(self, "Error", "Select Input JSON!")
        if not out: self.update_export_path(inp); out = self.edit_export_path.text()
        
        py = sys.executable
        cmd = f'"{py}" -u run_vector_gen.py --input "{inp}" --output "{out}" --model "{model}" --strategy {strat}'
        self.append_log(f"<span style='color:#79c0ff'>[CMD] {cmd}</span>")
        self.start_worker(cmd)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()

    sys.exit(app.exec_())

