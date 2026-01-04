import sys
import json
import os
import subprocess
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QTextEdit, QComboBox, 
                             QFileDialog, QMessageBox, QFrame, QTabWidget, QSplitter)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QTextCursor

# 尝试导入可视化窗口，如果不存在则使用占位符
try:
    from ai_visual_window import AIVisualWindow
except ImportError:
    class AIVisualWindow(QWidget):
        def add_stream_char(self, c): pass
        def show(self): pass
        def hide(self): pass
        def move(self, x, y): pass

CONFIG_FILE = "gui_configs.json"

# ==========================================
# [后端逻辑脚本模板]
# 修复说明：
# 1. 将 API_KEY 和 BASE_URL 替换为 utils.py 中验证通过的局域网配置
# 2. 增加 verify=False 以跳过 SSL 证书验证 (解决局域网 https 问题)
# 3. 增加 urllib3 警告禁用，保持控制台清爽
# ==========================================
VECTOR_GEN_SCRIPT = r'''
import sys
import json
import os
import time
import argparse
import requests
import urllib3

# 1. 网络与环境配置 (完全模仿 utils.py)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 清理代理，防止内网请求被转发
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(k, None)

# 2. API 配置 (从 utils.py 提取)
# 注意：这里使用的是 utils.py 中的 Key 和 内网 URL
API_KEY = "your api key"

BASE_URL = "https://www.deepseek.com:18080/v1" 

def log(msg, level="INFO"):
    color_map = {
        "INFO": "#33CCFF",
        "SUCCESS": "#00FF00",
        "ERROR": "#FF3333", 
        "WARN": "#FFFF00"
    }
    # 简单的 HTML 格式化，供 GUI 读取
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{level}] {msg}", flush=True)

def recursive_walk(nodes, path=[], depth=1):
    for node in nodes:
        current_path = path + [node.get("title", "Untitled")]
        yield {"node": node, "path": current_path, "depth": depth}
        if "nodes" in node and isinstance(node["nodes"], list):
            yield from recursive_walk(node["nodes"], current_path, depth + 1)

def call_llm_api(prompt, model_name):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    # 强制指定模型，或者使用传入的模型
    # 如果内网只支持特定模型名 (如 DeepSeek-V3)，可以在这里硬编码
    target_model = model_name if model_name else "DeepSeek-V3"

    data = {
        "model": target_model,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant for summarizing text."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 512,
        "temperature": 0.3,
        "stream": True 
    }

    try:
        # 建立会话，禁用环境代理
        session = requests.Session()
        session.trust_env = False 
        
        url = f"{BASE_URL.rstrip('/')}/chat/completions"
        
        # 关键参数 verify=False (模仿 utils.py)
        response = session.post(url, headers=headers, json=data, stream=True, timeout=60, verify=False)
        
        # 检查 HTTP 状态码
        if response.status_code != 200:
            return f"[ERROR] API returned {response.status_code}: {response.text[:200]}"

        full_content = ""
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8', errors='ignore')
                if decoded_line.startswith("data:"):
                    json_str = decoded_line[5:].strip() # 去掉 "data:"
                    if json_str == "[DONE]": break
                    try:
                        chunk = json.loads(json_str)
                        if "choices" in chunk and len(chunk["choices"]) > 0:
                            delta = chunk["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                full_content += content
                                # 实时推送到 GUI 可视化窗口
                                print(f"DEBUG_AI_CHAR:{content}", flush=True)
                    except:
                        pass
        return full_content

    except Exception as e:
        return f"[FAILED] Connection Error: {str(e)}"

def main():
    # 强制输出为 UTF-8，防止中文乱码
    if sys.stdout: sys.stdout.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    log(f"Starting Vector Generation Process...", "INFO")
    log(f"Input: {args.input}", "INFO")
    log(f"Target URL: {BASE_URL}", "INFO")

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
        skipped_count = 0

        # 遍历节点
        for item in recursive_walk(root_nodes):
            node = item["node"]
            path = item["path"]
            depth = item["depth"]
            content = node.get("text", node.get("content", ""))

            # 过滤逻辑：只处理 1、2 级标题，且内容长度大于 50
            if depth not in (1, 2):
                skipped_count += 1
                continue
            
            if not content or len(content) < 50: 
                skipped_count += 1
                continue

            # 构建提示词
            path_str = ' > '.join(path)
            prompt = f"请生成一段 100~200 字的摘要，用于判断“用户问题是否与该章节相关”。\n\n章节路径：{path_str}\n\n章节内容：\n{content[:2500]}"
            
            log(f"Processing: {path_str}", "INFO")
            
            summary = call_llm_api(prompt, args.model)
            
            # 如果调用失败，记录错误但继续
            if "[ERROR]" in summary or "[FAILED]" in summary:
                log(f"Summarization failed for node: {path_str}", "WARN")
            
            vector_obj = {
                "text": summary, 
                "metadata": {
                    "doc_title": doc_title,
                    "section_path": path_str,
                    "original_length": len(content),
                    "depth": depth
                },
                "original_content": content[:1000] + "..." 
            }
            
            output_data.append(vector_obj)
            processed_count += 1
            
            time.sleep(0.1) # 避免速率限制

        # 保存结果
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        log(f"Generation Complete! Saved {processed_count} items.", "SUCCESS")
        log(f"Skipped {skipped_count} items (depth/length criteria).", "WARN")
        log(f"Output File: {args.output}", "SUCCESS")

    except Exception as e:
        log(f"Critical Error: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
'''

# === Cyberpunk Style Sheet ===
STYLESHEET = """
QMainWindow {
    background-color: #0d1117;
}
QTabWidget::pane {
    border: 1px solid #30363d;
    background-color: #0d1117;
    top: -1px; 
}
QTabBar::tab {
    background: #161b22;
    color: #8b949e;
    padding: 10px 20px;
    border: 1px solid #30363d;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
    font-family: 'Segoe UI', sans-serif;
    font-weight: bold;
}
QTabBar::tab:selected {
    background: #0d1117;
    color: #00ffcc;
    border-bottom: 1px solid #0d1117; 
}
QTabBar::tab:hover {
    background: #21262d;
    color: #c9d1d9;
}
QLabel {
    color: #00ffcc;
    font-family: 'Segoe UI', sans-serif;
    font-weight: bold;
}
QLineEdit {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 4px;
    color: #c9d1d9;
    padding: 5px;
    font-family: 'Consolas';
}
QLineEdit:focus {
    border: 1px solid #00ffcc;
    background-color: #0d1117;
}
QPushButton {
    background-color: #238636;
    color: white;
    border: none;
    padding: 8px 16px;
    border-radius: 6px;
    font-weight: bold;
    font-size: 14px;
}
QPushButton:hover {
    background-color: #2ea043;
}
QPushButton:pressed {
    background-color: #1a6329;
}
QPushButton#VisualBtn {
    background-color: #1f6feb;
    border: 1px solid #1f6feb;
}
QPushButton#VisualBtn:hover {
    background-color: #388bfd;
}
QTextEdit {
    background-color: #0d1117;
    border: 1px solid #30363d;
    color: #00ff99; 
    font-family: 'Consolas', monospace;
    font-size: 12px;
}
QComboBox {
    background-color: #161b22;
    color: #c9d1d9;
    border: 1px solid #30363d;
    padding: 5px;
    border-radius: 4px;
}
QComboBox::drop-down {
    border: none;
}
QComboBox QAbstractItemView {
    background-color: #161b22;
    color: #c9d1d9;
    selection-background-color: #238636;
}
QFrame#ConfigFrame {
    background-color: #161b22; 
    border-radius: 8px; 
    border: 1px solid #30363d;
}
"""

AVAILABLE_MODELS = [
    "DeepSeek-V3",  # 调整顺序，优先使用内网常用的模型
    "qwen2.5-vl-72b",
    "DeepSeek-R1",
    "qwq-32b",
    "Qwen2.5-32B"
]
DEFAULT_MODEL = "DeepSeek-V3"

# === Worker Thread (Standard Subprocess Handler) ===
class WorkerThread(QThread):
    log_signal = pyqtSignal(str)      
    stream_signal = pyqtSignal(str)   

    def __init__(self, command):
        super().__init__()
        self.command = command
        self.line_buffer = ""

    def run(self):
        process = subprocess.Popen(
            self.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=0
        )

        while True:
            char = process.stdout.read(1)
            if not char and process.poll() is not None:
                break
            if char:
                self.process_char(char)
        
        self.flush_buffer()
        process.wait()

    def flush_buffer(self):
        if self.line_buffer:
            line = self.line_buffer.strip()
            if line:
                self.emit_log_line(line)
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
        if "[SUCCESS]" in line:
            formatted_line = f"<span style='color:#00FF00; font-weight:bold; font-size:13px;'>{line}</span>"
        elif "[ERROR]" in line or "Exception" in line or "Traceback" in line or "Error" in line:
            formatted_line = f"<span style='color:#FF3333; font-weight:bold;'>{line}</span>"
        elif "[INFO]" in line:
            formatted_line = f"<span style='color:#33CCFF;'>{line}</span>"
        elif "[Warning]" in line or "WARN" in line:
            formatted_line = f"<span style='color:#FFFF00;'>{line}</span>"
        else:
            formatted_line = line
        self.log_signal.emit(formatted_line)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PageIndex Pro - Neural Interface")
        self.resize(1100, 850)
        
        self.visual_window = AIVisualWindow()
        
        self.configs = self.load_configs()
        self.init_ui()
        self.apply_styles()

    def apply_styles(self):
        self.setStyleSheet(STYLESHEET)

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # === Header Area ===
        header_layout = QHBoxLayout()
        title_label = QLabel("PAGEINDEX PRO")
        title_label.setStyleSheet("font-size: 24px; color: #00ffcc; letter-spacing: 2px;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        main_layout.addLayout(header_layout)

        # === Tabs ===
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # -- Tab 1: PageIndex --
        self.tab_pageindex = QWidget()
        self.init_tab_pageindex()
        self.tabs.addTab(self.tab_pageindex, "Page Index")

        # -- Tab 2: Vector JSON --
        self.tab_vector = QWidget()
        self.init_tab_vector()
        self.tabs.addTab(self.tab_vector, "Vector JSON")

        # === Console Output ===
        main_layout.addWidget(QLabel("SYSTEM LOGS:"))
        self.txt_console = QTextEdit()
        self.txt_console.setReadOnly(True)
        main_layout.addWidget(self.txt_console)

    def init_tab_pageindex(self):
        layout = QVBoxLayout(self.tab_pageindex)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Config Section
        cfg_frame = QFrame()
        cfg_frame.setObjectName("ConfigFrame")
        cfg_layout = QHBoxLayout(cfg_frame)
        
        self.cb_configs = QComboBox()
        self.cb_configs.addItems(self.configs.keys())
        self.cb_configs.currentTextChanged.connect(self.load_selected_config)
        
        btn_save = QPushButton("💾 SAVE CONFIG")
        btn_save.clicked.connect(self.save_config)
        btn_save.setStyleSheet("background-color: #21262d; border: 1px solid #30363d;")

        cfg_layout.addWidget(QLabel("CONFIGURATION:"))
        cfg_layout.addWidget(self.cb_configs, 1)
        cfg_layout.addWidget(btn_save)
        layout.addWidget(cfg_frame)

        # Input Section
        input_layout = QVBoxLayout()
        
        file_layout = QHBoxLayout()
        self.edit_pdf = QLineEdit()
        self.edit_pdf.setPlaceholderText("Select PDF document path...")
        btn_file = QPushButton("📂 BROWSE")
        btn_file.clicked.connect(self.get_file)
        file_layout.addWidget(QLabel("DOCUMENT:"))
        file_layout.addWidget(self.edit_pdf, 1)
        file_layout.addWidget(btn_file)
        input_layout.addLayout(file_layout)
        
        model_layout = QHBoxLayout()
        self.combo_model = QComboBox()
        self.combo_model.addItems(AVAILABLE_MODELS)
        default_index = AVAILABLE_MODELS.index(DEFAULT_MODEL) if DEFAULT_MODEL in AVAILABLE_MODELS else 0
        self.combo_model.setCurrentIndex(default_index)
        
        model_layout.addWidget(QLabel("AI MODEL:"))
        model_layout.addWidget(self.combo_model, 1)
        input_layout.addLayout(model_layout)
        
        layout.addLayout(input_layout)

        # Action Buttons
        btn_layout = QHBoxLayout()
        
        self.btn_run = QPushButton("🚀 INITIALIZE INDEXING")
        self.btn_run.setFixedHeight(45)
        self.btn_run.clicked.connect(self.start_task)
        
        self.btn_visual = QPushButton("👁 VISUALIZER: OFF")
        self.btn_visual.setObjectName("VisualBtn")
        self.btn_visual.setCheckable(True)
        self.btn_visual.setFixedHeight(45)
        self.btn_visual.clicked.connect(self.toggle_visual_window)
        
        btn_layout.addWidget(self.btn_run, 2)
        btn_layout.addWidget(self.btn_visual, 1)
        layout.addLayout(btn_layout)
        layout.addStretch()

    def init_tab_vector(self):
        layout = QVBoxLayout(self.tab_vector)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        desc = QLabel("Transform PageIndex JSON structures into RAG-ready vector datasets using Semantic Summarization.")
        desc.setStyleSheet("color: #8b949e; font-style: italic; font-weight: normal;")
        layout.addWidget(desc)

        # 1. Input JSON Selection
        json_layout = QHBoxLayout()
        self.edit_json_path = QLineEdit()
        # 默认路径
        default_json_path = r"E:\!!!PythonSTUDY\PageIndex-main-gittedgood20251226优化中\results"
        self.edit_json_path.setText(default_json_path)
        self.edit_json_path.setPlaceholderText("Select source JSON file...")
        
        btn_json = QPushButton("📂 SELECT JSON")
        btn_json.clicked.connect(self.get_json_file)
        
        json_layout.addWidget(QLabel("SOURCE JSON:"))
        json_layout.addWidget(self.edit_json_path, 1)
        json_layout.addWidget(btn_json)
        layout.addLayout(json_layout)

        # 2. Output & Export Config
        export_layout = QHBoxLayout()
        self.edit_export_path = QLineEdit()
        self.edit_export_path.setPlaceholderText("Export path (Auto-generated)...")
        
        btn_export_path = QPushButton("📂 SET OUTPUT")
        btn_export_path.clicked.connect(self.get_export_path)
        
        export_layout.addWidget(QLabel("EXPORT TO:"))
        export_layout.addWidget(self.edit_export_path, 1)
        export_layout.addWidget(btn_export_path)
        layout.addLayout(export_layout)
        
        self.edit_json_path.textChanged.connect(self.update_export_path)

        # 3. Model & Options
        opts_layout = QHBoxLayout()
        self.combo_vector_model = QComboBox()
        self.combo_vector_model.addItems(AVAILABLE_MODELS)
        
        opts_layout.addWidget(QLabel("SUMMARIZER MODEL:"))
        opts_layout.addWidget(self.combo_vector_model, 1)
        layout.addLayout(opts_layout)

        # 4. Action Button
        self.btn_gen_vector = QPushButton("⚡ GENERATE VECTOR JSON")
        self.btn_gen_vector.setFixedHeight(50)
        self.btn_gen_vector.setStyleSheet("background-color: #79c0ff; color: #0d1117; font-size: 15px;")
        self.btn_gen_vector.clicked.connect(self.start_vector_task)
        
        layout.addStretch()
        layout.addWidget(self.btn_gen_vector)

    def toggle_visual_window(self):
        if self.btn_visual.isChecked():
            self.visual_window.show()
            self.btn_visual.setText("👁 VISUALIZER: ON")
            geo = self.geometry()
            self.visual_window.move(geo.x() + geo.width() + 10, geo.y())
        else:
            self.visual_window.hide()
            self.btn_visual.setText("👁 VISUALIZER: OFF")

    def load_configs(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except: pass
        return {"Default": {"pdf": "", "model": DEFAULT_MODEL, "pages": "3"}}

    def save_config(self):
        name = self.cb_configs.currentText() or "NewConfig"
        current_model = self.combo_model.currentText()
        self.configs[name] = {
            "pdf": self.edit_pdf.text(),
            "model": current_model,
            "pages": "3"
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.configs, f)
        QMessageBox.information(self, "System", "Configuration Saved Successfully.")

    def load_selected_config(self, name):
        if name and name in self.configs:
            c = self.configs[name]
            self.edit_pdf.setText(c.get('pdf', ''))
            model_name = c.get('model', DEFAULT_MODEL)
            if model_name in AVAILABLE_MODELS:
                self.combo_model.setCurrentText(model_name)
            else:
                self.combo_model.setCurrentIndex(0)

    def get_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select PDF", "", "*.pdf")
        if f: self.edit_pdf.setText(f)

    def append_log(self, text):
        self.txt_console.append(text)
        cursor = self.txt_console.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.txt_console.setTextCursor(cursor)

    def start_task(self):
        pdf_path = self.edit_pdf.text()
        if not pdf_path:
            QMessageBox.warning(self, "Error", "Please select a PDF file first.")
            return
        
        py_exe = sys.executable
        current_model = self.combo_model.currentText()
        cmd = f'"{py_exe}" -u run_pageindex.py --pdf_path "{pdf_path}" --model "{current_model}" --toc-check-pages 3'
        
        self.txt_console.clear()
        self.txt_console.append(f"<span style='color:#FFFF00'>[SYSTEM] Initializing PageIndex subprocess...</span>")
        
        self.worker = WorkerThread(cmd)
        self.worker.log_signal.connect(self.append_log)
        self.worker.stream_signal.connect(self.visual_window.add_stream_char)
        
        if not self.btn_visual.isChecked():
            self.btn_visual.click()
            
        self.worker.start()

    def get_json_file(self):
        start_dir = self.edit_json_path.text() or ""
        f, _ = QFileDialog.getOpenFileName(self, "Select JSON", start_dir, "*.json")
        if f:
            self.edit_json_path.setText(f)
            self.update_export_path(f)

    def get_export_path(self):
        start_dir = os.path.dirname(self.edit_export_path.text()) if self.edit_export_path.text() else ""
        f, _ = QFileDialog.getSaveFileName(self, "Save Vector JSON", start_dir, "JSON Files (*.json)")
        if f: self.edit_export_path.setText(f)

    def update_export_path(self, input_path):
        if not input_path: return
        dir_name = os.path.dirname(input_path)
        base_name = os.path.basename(input_path)
        new_name = f"RAGjson_{base_name}"
        full_path = os.path.join(dir_name, new_name)
        self.edit_export_path.setText(full_path)

    def ensure_vector_script_exists(self):
        """确保 run_vector_gen.py 存在，如果不存在则写入更新后的内容"""
        script_name = "run_vector_gen.py"
        # 强制覆盖旧脚本，确保逻辑是最新的
        try:
            with open(script_name, "w", encoding="utf-8") as f:
                f.write(VECTOR_GEN_SCRIPT)
            self.append_log(f"<span style='color:#33CCFF'>[INFO] Generated/Updated backend script: {script_name}</span>")
            return True
        except Exception as e:
            self.append_log(f"<span style='color:#FF3333'>[ERROR] Failed to generate script: {e}</span>")
            return False

    def start_vector_task(self):
        in_path = self.edit_json_path.text()
        out_path = self.edit_export_path.text()
        model = self.combo_vector_model.currentText()
        
        if not in_path or not os.path.exists(in_path):
             QMessageBox.warning(self, "Error", "Invalid Input JSON path.")
             return
        
        if not out_path:
            self.update_export_path(in_path)
            out_path = self.edit_export_path.text()

        # 1. 确保后端脚本存在 (且被更新为内网配置版)
        if not self.ensure_vector_script_exists():
            return

        self.txt_console.append(f"<br><span style='color:#79c0ff; font-weight:bold;'>[VECTOR JOB] Initializing Vector Transformation Subprocess...</span>")
        
        # 2. 构造 subprocess 命令 (模仿 pguiback.py)
        py_exe = sys.executable
        cmd = f'"{py_exe}" -u run_vector_gen.py --input "{in_path}" --output "{out_path}" --model "{model}"'
        
        # 3. 使用 WorkerThread 执行
        self.vector_worker = WorkerThread(cmd)
        self.vector_worker.log_signal.connect(self.append_log)
        self.vector_worker.stream_signal.connect(self.visual_window.add_stream_char) # 开启可视化
        
        if not self.btn_visual.isChecked():
            self.btn_visual.click()
            
        self.vector_worker.start()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    main = MainWindow()
    main.show()

    sys.exit(app.exec_())
