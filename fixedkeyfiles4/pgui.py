import sys
import json
import os
import subprocess
import time
import warnings

# 屏蔽 SIP 弃用警告，保持控制台干净
warnings.filterwarnings("ignore", category=DeprecationWarning)

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QTextEdit, QComboBox, 
                             QFileDialog, QMessageBox, QFrame, QTabWidget, QSplitter, QProgressBar)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QProcessEnvironment
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
# [后端向量化脚本 - 内置最新版]
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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(k, None)

API_KEY = "YOUR API KEY"
BASE_URL = "https://WWW.DEEPSEEK.COM:18080/v1" 

SYSTEM_PROMPT = """你是一个高精度的元数据分析师。你的任务是分析给定的文档片段，并生成一段简短的、富含上下文的“语义导语”。
不需要重写原始数据，只需要生成“导语”。导语必须明确指出：这段内容属于哪个章节路径，包含什么类型的数据。"""

USER_PROMPT_TEMPLATE = """请分析以下文档片段的元数据。
【输入信息】
- 文档标题：{doc_title}
- 章节路径：{path_str}
- 数据片段长度：{length} 字符
- 数据预览：
{content_preview}

【任务要求】
1. 生成 `semantic_intro`：50-100字描述，说明数据位置及主要实体。
2. 输出为 JSON 格式。
"""

def log(msg, level="INFO"):
    print(f"[{level}] {msg}", flush=True)

def recursive_walk(nodes, path=[], depth=1):
    for node in nodes:
        current_title = node.get("title", "Untitled").replace('\n', ' ').strip()
        current_path = path + [current_title]
        yield {"node": node, "path": current_path, "depth": depth}
        if "nodes" in node and isinstance(node["nodes"], list):
            yield from recursive_walk(node["nodes"], current_path, depth + 1)

def extract_json_robust(content):
    if not content: return None
    patterns = [r'```json\s*([\s\S]*?)\s*```', r'```\s*([\s\S]*?)\s*```', r'(\{[\s\S]*\})']
    for p in patterns:
        match = re.search(p, content)
        if match:
            try: return json.loads(re.sub(r',\s*([\]}])', r'\1', match.group(1)))
            except: continue
    return None

def call_llm_api(system_prompt, user_prompt, model_name):
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": model_name,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        "max_tokens": 1000, "temperature": 0.1, "stream": True
    }
    try:
        session = requests.Session()
        session.trust_env = False
        resp = session.post(f"{BASE_URL.rstrip('/')}/chat/completions", headers=headers, json=data, stream=True, timeout=60, verify=False)
        full_content = ""
        for line in resp.iter_lines():
            if line:
                d_line = line.decode('utf-8', errors='ignore')
                if d_line.startswith("data:"):
                    j_str = d_line[5:].strip()
                    if j_str == "[DONE]": break
                    try:
                        chunk = json.loads(j_str)
                        if "choices" in chunk and len(chunk["choices"]) > 0:
                            content = chunk["choices"][0]["delta"].get("content", "")
                            if content:
                                full_content += content
                                print(f"DEBUG_AI_CHAR:{content}", flush=True)
                    except: pass
        return full_content
    except Exception as e: return str(e)

def main():
    if sys.stdout: sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--strategy", type=int, default=0)
    args = parser.parse_args()

    log(f"Starting Vector Gen (Strategy: {args.strategy})...", "INFO")
    try:
        with open(args.input, 'r', encoding='utf-8-sig') as f: data = json.load(f)
        root_nodes = data if isinstance(data, list) else data.get("structure", [])
        doc_title = data.get("doc_name", data.get("title", "Unknown")) if isinstance(data, dict) else "Unknown"
        
        output_data = []
        for item in recursive_walk(root_nodes):
            node = item["node"]
            content = node.get("text", node.get("content", ""))
            if (not content or len(content.strip()) < 10) and not ("nodes" in node and node["nodes"]): continue
            
            prompt = USER_PROMPT_TEMPLATE.format(doc_title=doc_title, path_str=" > ".join(item["path"]), length=len(content), content_preview=content[:1000])
            resp = call_llm_api(SYSTEM_PROMPT, prompt, args.model)
            vec_obj = extract_json_robust(resp) or {"semantic_intro": f"章节 {item['path'][-1]} 数据", "section_hint": "General"}
            
            final_text = ""
            if args.strategy == 0: final_text = f"{vec_obj.get('semantic_intro','')}\n\n【原始数据】:\n{content.strip()}"
            elif args.strategy == 1: final_text = vec_obj.get('semantic_intro','')
            else: final_text = f"{vec_obj.get('semantic_intro','')}\n\n[Ref]:\n{content.strip()}"
            
            output_data.append({"embedding_text": final_text, "metadata": {"path": item["path"], "strategy": args.strategy}})
            
        with open(args.output, 'w', encoding='utf-8') as f: json.dump(output_data, f, indent=2, ensure_ascii=False)
        log(f"Complete! Saved to {args.output}", "SUCCESS")
    except Exception as e:
        log(f"Error: {e}", "ERROR")

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
QLineEdit { background-color: #161b22; border: 1px solid #30363d; border-radius: 4px; color: #c9d1d9; padding: 5px; }
QLineEdit:focus { border: 1px solid #00ffcc; }
QPushButton { background-color: #238636; color: white; border: none; padding: 8px 16px; border-radius: 6px; font-weight: bold; }
QPushButton:hover { background-color: #2ea043; }
QPushButton#VisualBtn { background-color: #1f6feb; }
QPushButton#StopBtn { background-color: #da3633; }
QTextEdit { background-color: #0d1117; border: 1px solid #30363d; color: #00ff99; font-family: 'Consolas', monospace; font-size: 12px; }
QComboBox { background-color: #161b22; color: #c9d1d9; border: 1px solid #30363d; padding: 5px; border-radius: 4px; }
QFrame#ConfigFrame { background-color: #161b22; border-radius: 8px; border: 1px solid #30363d; }
QProgressBar { border: 1px solid #30363d; border-radius: 5px; text-align: center; color: white; }
QProgressBar::chunk { background-color: #238636; width: 10px; margin: 0.5px; }
"""

AVAILABLE_MODELS = ["DeepSeek-V3", "qwen2.5-vl-72b", "DeepSeek-R1", "qwq-32b", "Qwen2.5-32B"]
DEFAULT_MODEL = "DeepSeek-V3"

# ==================================================================================
# [工作线程 - 核心引擎]
# ==================================================================================
class WorkerThread(QThread):
    log_signal = pyqtSignal(str)      
    stream_signal = pyqtSignal(str)   
    finished_signal = pyqtSignal()

    def __init__(self, command):
        super().__init__()
        self.command = command
        self.is_running = True
        self.process = None
        self.line_buffer = "" # 确保所有属性都在一个 __init__ 中初始化

    def run(self):
        try:
            # [关键修复] 注入环境变量，强制 UTF-8，防止乱码
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONLEGACYWINDOWSSTDIO"] = "utf-8" # 针对 Windows 兼容性

            # 确保命令是字符串类型
            command_str = str(self.command)

            self.process = subprocess.Popen(
                command_str,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=True,
                text=True,
                encoding='utf-8',       # 强制 UTF-8 解码
                errors='replace',       # 遇到无法解码的字符用 ? 代替，防止崩溃
                bufsize=0,              # 无缓冲实时输出
                env=env                 # 应用环境设置
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
                self.process.terminate()
            except:
                pass

    def flush_buffer(self):
        if self.line_buffer:
            self.emit_log_line(self.line_buffer.strip())
            self.line_buffer = ""

    def process_char(self, char):
        self.line_buffer += char
        if char == "\n":
            line = self.line_buffer.strip()
            if line: 
                if line.startswith("DEBUG_AI_CHAR:"):
                    try:
                        content = line.split("DEBUG_AI_CHAR:", 1)[1]
                        self.stream_signal.emit(content)
                    except: pass
                else:
                    self.emit_log_line(line)
            self.line_buffer = ""

    def emit_log_line(self, line):
        # 智能日志着色 - 让你一眼看清问题
        timestamp = time.strftime("%H:%M:%S")
        prefix = f"<span style='color:#555;'>[{timestamp}]</span> "
        
        if "[SUCCESS]" in line or "accuracy: 100.00%" in line:
            formatted = f"{prefix}<span style='color:#00FF00; font-weight:bold;'>{line}</span>"
        elif "[ERROR]" in line or "Exception" in line or "Traceback" in line:
            formatted = f"{prefix}<span style='color:#FF3333; font-weight:bold; background-color:#330000;'>{line}</span>"
        elif "WARNING" in line or "accuracy:" in line:
            # 黄色告警处理
            formatted = f"{prefix}<span style='color:#FFD700; font-weight:bold;'>{line}</span>"
        elif "large node" in line:
            # 标记大节点处理
            formatted = f"{prefix}<span style='color:#FF00FF;'>{line}</span>"
        elif "DEBUG_AI_CHAR" in line:
            return # 不显示 AI 思考过程的 raw data
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
        
        self.status_bar = QProgressBar()
        self.status_bar.setRange(0, 0) # Indeterminate state
        self.status_bar.setFixedWidth(200)
        self.status_bar.hide()
        header.addStretch()
        header.addWidget(self.status_bar)
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
        row2.addWidget(QLabel("AI MODEL:"))
        row2.addWidget(self.combo_model, 1)
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
        # 默认路径修复
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
        # 性能优化：如果日志太长，自动清理旧日志，防止界面卡死
        if len(self.txt_console.toPlainText()) > 100000:
            self.txt_console.clear()
            self.txt_console.append("<span style='color:orange'>[SYSTEM] Log cleared to release memory.</span>")

    def start_worker(self, cmd):
        if self.worker and self.worker.isRunning():
            return
        
        self.txt_console.clear()
        self.status_bar.show()
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        
        self.worker = WorkerThread(cmd)
        self.worker.log_signal.connect(self.append_log)
        self.worker.stream_signal.connect(self.visual_window.add_stream_char)
        self.worker.finished_signal.connect(self.on_worker_finished)
        
        if not self.btn_visual.isChecked():
            self.btn_visual.click()
            
        self.worker.start()

    def stop_worker(self):
        if self.worker:
            self.worker.stop()
            self.append_log("<span style='color:red'>[SYSTEM] Process terminated by user.</span>")

    def on_worker_finished(self):
        self.status_bar.hide()
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.append_log("<span style='color:#00ffcc'>[SYSTEM] Task Completed.</span>")

    # === Task Launchers ===

    def start_pageindex_task(self):
        pdf = self.edit_pdf.text()
        model = self.combo_model.currentText()
        if not pdf: return QMessageBox.warning(self, "Error", "Select PDF file!")
        
        py = sys.executable
        # 注意：这里增加了 toc-check-pages 参数，根据你之前的代码逻辑
        cmd = f'"{py}" -u run_pageindex.py --pdf_path "{pdf}" --model "{model}" --toc-check-pages 5'
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
        strat = self.combo_strategy.currentIndex() # 获取策略索引 0, 1, 2
        
        if not inp: return QMessageBox.warning(self, "Error", "Select Input JSON!")
        if not out: self.update_export_path(inp); out = self.edit_export_path.text()
        
        py = sys.executable
        # [关键] 传递 --strategy 参数
        cmd = f'"{py}" -u run_vector_gen.py --input "{inp}" --output "{out}" --model "{model}" --strategy {strat}'
        self.append_log(f"<span style='color:#79c0ff'>[CMD] {cmd}</span>")
        self.start_worker(cmd)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()

    sys.exit(app.exec_())
