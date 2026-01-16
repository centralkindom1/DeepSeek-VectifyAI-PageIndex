import sys
import json
import os
import subprocess
import time
import warnings
from datetime import timedelta

# Suppress SIP deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QTextEdit, QComboBox, 
                             QFileDialog, QMessageBox, QFrame, QTabWidget, QProgressBar)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer

# ==================================================================================
# [CONFIGURATION]
# ==================================================================================
BACKEND_SCRIPT_NAME = "backend_pgui.py" # Tab B logic
PAGEINDEX_SCRIPT_NAME = "run_pageindex.py" # Tab A logic
CONVERTER_SCRIPT_NAME = "json_phase2_converter.py" # Tab C logic (NEW)
CONFIG_FILE = "gui_configs.json"

# Try importing the visual window, otherwise use a dummy class
try:
    from ai_visual_window import AIVisualWindow
except ImportError:
    class AIVisualWindow(QWidget):
        def add_stream_char(self, c): pass
        def show(self): pass
        def hide(self): pass
        def move(self, x, y): pass

# === Cyberpunk Style Sheet (Retained from Set 1) ===
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
# [WORKER THREAD] - High Robustness from Set 1
# ==================================================================================
class WorkerThread(QThread):
    log_signal = pyqtSignal(str)      
    stream_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(dict)
    finished_signal = pyqtSignal()

    def __init__(self, command):
        super().__init__()
        self.command = command
        self.is_running = True
        self.process = None
        self.line_buffer = "" 

    def run(self):
        try:
            # Prepare Environment
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONLEGACYWINDOWSSTDIO"] = "utf-8"
            env["PYTHONUTF8"] = "1"

            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            command_str = str(self.command)

            self.process = subprocess.Popen(
                command_str,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=0,
                env=env,
                startupinfo=startupinfo
            )

            while self.is_running:
                if self.process is None: break
                
                # Read character by character for smooth streaming
                char = self.process.stdout.read(1)
                
                if not char and self.process.poll() is not None:
                    break
                    
                if char:
                    self.process_char(char)
            
            self.flush_buffer()
            if self.process:
                self.process.wait()
                
        except Exception as e:
            import traceback
            error_msg = f"Critical Error in Thread: {str(e)}\n{traceback.format_exc()}"
            self.emit_log_line(f"[ERROR] {error_msg}")
        finally:
            self.finished_signal.emit()

    def stop(self):
        self.is_running = False
        if self.process:
            try:
                import signal
                self.process.terminate()
                if os.name == 'nt':
                     subprocess.run(f"taskkill /F /T /PID {self.process.pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except: pass

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
        
        # Handle Progress JSON
        if line.startswith(PROGRESS_PREFIX):
            try:
                json_str = line[len(PROGRESS_PREFIX):]
                data = json.loads(json_str)
                self.progress_signal.emit(data)
                return
            except: pass

        # Handle Stream Visualization
        if line.startswith("DEBUG_AI_CHAR:"):
            try:
                content = line.split("DEBUG_AI_CHAR:", 1)[1]
                self.stream_signal.emit(content)
            except: pass
            return

        # Handle Standard Logs
        self.emit_log_line(line)

    def emit_log_line(self, line):
        timestamp = time.strftime("%H:%M:%S")
        prefix = f"<span style='color:#555;'>[{timestamp}]</span> "
        
        if "[SUCCESS]" in line:
            formatted = f"{prefix}<span style='color:#00FF00; font-weight:bold;'>{line}</span>"
        elif "[ERROR]" in line or "Exception" in line or "Traceback" in line:
            formatted = f"{prefix}<span style='color:#FF3333; font-weight:bold; background-color:#330000;'>{line}</span>"
        elif "WARNING" in line or "WARN" in line:
            formatted = f"{prefix}<span style='color:#FFD700; font-weight:bold;'>{line}</span>"
        elif "[INFO]" in line:
            formatted = f"{prefix}<span style='color:#79c0ff;'>{line}</span>"
        else:
            formatted = f"{prefix}<span style='color:#c9d1d9;'>{line}</span>"
            
        self.log_signal.emit(formatted)

# ==================================================================================
# [MAIN WINDOW]
# ==================================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PageIndex Pro 2026 - Neural Interface (Hybrid Edition)")
        self.resize(1200, 900)
        self.visual_window = AIVisualWindow()
        
        # Load configs, creating default if missing
        self.configs = self.load_configs()
        
        self.worker = None
        
        self.start_time = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_timer_display)
        
        self.init_ui()
        self.apply_styles()
        
        # Load recent paths for Tab C if they exist
        self.load_recent_paths_tab_c()

    def apply_styles(self):
        self.setStyleSheet(STYLESHEET)

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        
        # Header
        header = QHBoxLayout()
        title = QLabel("PAGEINDEX PRO <sup>v2026.3</sup>")
        title.setStyleSheet("font-size: 26px; color: #00ffcc; letter-spacing: 2px;")
        header.addWidget(title)
        header.addStretch()
        main_layout.addLayout(header)

        # Tabs
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # TAB A: PDF Parsing (PageIndex)
        self.tab_pageindex = QWidget()
        self.init_tab_pageindex()
        self.tabs.addTab(self.tab_pageindex, "TAB A: PDF Parsing (PageIndex)")

        # TAB B: RAG Vectorization (LLM)
        self.tab_vector = QWidget()
        self.init_tab_vector()
        self.tabs.addTab(self.tab_vector, "TAB B: RAG Vectorization (LLM)")
        
        # TAB C: Rule-Based Conversion (NEW)
        self.tab_converter = QWidget()
        self.init_tab_converter()
        self.tabs.addTab(self.tab_converter, "TAB C: Rule-Based Conversion")

        # Console
        main_layout.addWidget(QLabel("SYSTEM KERNEL LOGS:"))
        self.txt_console = QTextEdit()
        self.txt_console.setReadOnly(True)
        main_layout.addWidget(self.txt_console, 1)
        
        self.init_status_area(main_layout)

    def init_status_area(self, layout):
        self.status_bar = QProgressBar()
        self.status_bar.setRange(0, 100) 
        self.status_bar.setValue(0)
        self.status_bar.setTextVisible(True)
        self.status_bar.setFormat("%p% - Processing...")
        self.status_bar.setFixedHeight(20)
        self.status_bar.hide()
        layout.addWidget(self.status_bar)

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

    # ==============================================================================
    # TAB A: PDF PARSING (Retained exactly from Set 1)
    # ==============================================================================
    def init_tab_pageindex(self):
        """ TAB A: IATA Optimization & Legacy Features """
        layout = QVBoxLayout(self.tab_pageindex)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Config Panel
        cfg_frame = QFrame()
        cfg_frame.setObjectName("ConfigFrame")
        cfg = QHBoxLayout(cfg_frame)
        self.cb_configs = QComboBox()
        self.cb_configs.addItems(self.configs.keys())
        # Filter out the special settings key from the combobox if it exists
        idx = self.cb_configs.findText("RecentSettings")
        if idx >= 0: self.cb_configs.removeItem(idx)
        
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
        
        # Schema Selection (IATA requirements)
        self.combo_schema = QComboBox()
        self.combo_schema.addItems([
            "0: Schema A: Full Intelligence (Legacy)",
            "1: Schema B: Data Warehouse (Legacy)",
            "2: Schema C: Structure Only (Legacy)",
            "3: IATA Hybrid (Concurrent + Skip Short Text) [FAST]",
            "4: IATA Keywords (Concurrent + Keyword Prompt) [EFFICIENT]",
            "5: IATA Batch Mode (Hybrid + Keywords) [EXPERIMENTAL]"
        ])
        
        row2.addWidget(QLabel("AI MODEL:"))
        row2.addWidget(self.combo_model, 1)
        row2.addWidget(QLabel("STRATEGY:"))
        row2.addWidget(self.combo_schema, 1)
        layout.addLayout(row2)

        # Thread Control
        row3 = QHBoxLayout()
        self.combo_threads = QComboBox()
        # 1-10 threads
        thread_opts = [str(i) for i in range(1, 11)]
        self.combo_threads.addItems(thread_opts)
        self.combo_threads.setCurrentText("2") 
        
        row3.addWidget(QLabel("CONCURRENCY (Threads):"))
        row3.addWidget(self.combo_threads, 1)
        row3.addStretch(1) # Spacer
        layout.addLayout(row3)

        # Controls
        controls = QHBoxLayout()
        self.btn_run = QPushButton("🚀 START INDEXING (OPTIMIZED)")
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

    # ==============================================================================
    # TAB B: RAG VECTORIZATION (From Set 2)
    # ==============================================================================
    def init_tab_vector(self):
        """ TAB B: RAG Vectorization (UI ported from GoodForTAB_B) """
        layout = QVBoxLayout(self.tab_vector)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        desc = QLabel("Transform PageIndex JSON structures into RAG-ready vector datasets using Semantic Summarization (LLM).")
        desc.setStyleSheet("color: #8b949e; font-style: italic; font-weight: normal;")
        layout.addWidget(desc)

        # 1. Input JSON Selection
        json_layout = QHBoxLayout()
        self.edit_json_path = QLineEdit()
        # Default path example
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

        # 3. Model & Options (Specific to Good Tab B)
        opts_layout = QHBoxLayout()
        self.combo_vector_model = QComboBox()
        self.combo_vector_model.addItems(AVAILABLE_MODELS)
        
        # Strategy selection from the Good Set
        self.combo_strategy_tabb = QComboBox()
        self.combo_strategy_tabb.addItems(["0: 数据无损模式 (Table/Schedule)", "1: 公文语义总结 (Policy/Doc)", "2: 标准混合模式"])
        
        opts_layout.addWidget(QLabel("SUMMARIZER MODEL:"))
        opts_layout.addWidget(self.combo_vector_model, 1)
        opts_layout.addWidget(QLabel("STRATEGY:"))
        opts_layout.addWidget(self.combo_strategy_tabb, 1)
        
        layout.addLayout(opts_layout)

        # 4. Action Button
        self.btn_gen_vector = QPushButton("⚡ GENERATE VECTOR JSON")
        self.btn_gen_vector.setFixedHeight(50)
        self.btn_gen_vector.setStyleSheet("background-color: #79c0ff; color: #0d1117; font-size: 15px; font-weight: bold;")
        self.btn_gen_vector.clicked.connect(self.start_vector_task)
        
        layout.addStretch()
        layout.addWidget(self.btn_gen_vector)

    # ==============================================================================
    # TAB C: Rule-Based Conversion (NEW)
    # ==============================================================================
    def init_tab_converter(self):
        """ TAB C: Rule-Based Tree-to-Flat JSON Converter """
        layout = QVBoxLayout(self.tab_converter)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        desc = QLabel("Transform PageIndex JSON Tree to Flat Vector JSON using Rule-Based Logic (No LLM). Ideal for high-speed conversion.")
        desc.setStyleSheet("color: #00ffcc; font-style: italic; font-weight: normal;")
        layout.addWidget(desc)

        # Input File
        row1 = QHBoxLayout()
        self.edit_c_input = QLineEdit()
        self.edit_c_input.setPlaceholderText("Select source JSON (Tree structure)...")
        btn_c_input = QPushButton("📂 SOURCE")
        btn_c_input.clicked.connect(self.get_converter_input)
        row1.addWidget(QLabel("SOURCE JSON:"))
        row1.addWidget(self.edit_c_input, 1)
        row1.addWidget(btn_c_input)
        layout.addLayout(row1)

        # Output File
        row2 = QHBoxLayout()
        self.edit_c_output = QLineEdit()
        self.edit_c_output.setPlaceholderText("Output JSON path...")
        btn_c_output = QPushButton("📂 TARGET")
        btn_c_output.clicked.connect(self.get_converter_output)
        row2.addWidget(QLabel("TARGET JSON:"))
        row2.addWidget(self.edit_c_output, 1)
        row2.addWidget(btn_c_output)
        layout.addLayout(row2)

        # Auto-update output path when input changes
        self.edit_c_input.textChanged.connect(self.update_converter_output_path)

        # Run Button
        self.btn_run_converter = QPushButton("⚡ RUN CONVERTER (RULE BASED)")
        self.btn_run_converter.setFixedHeight(50)
        self.btn_run_converter.setStyleSheet("background-color: #d2a8ff; color: #0d1117; font-size: 15px; font-weight: bold;")
        self.btn_run_converter.clicked.connect(self.start_converter_task)

        layout.addStretch()
        layout.addWidget(self.btn_run_converter)

    # ==============================================================================
    # LOGIC METHODS
    # ==============================================================================

    def load_configs(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f: return json.load(f)
            except: pass
        return {"Default": {"pdf": "", "model": DEFAULT_MODEL}}

    def save_config(self):
        name = self.cb_configs.currentText() or "Custom"
        if name == "RecentSettings": name = "Custom" # Protect special key
        
        self.configs[name] = {"pdf": self.edit_pdf.text(), "model": self.combo_model.currentText()}
        
        self.write_configs_to_disk()
        self.append_log("<span style='color:#00FF00'>[SYSTEM] Config saved.</span>")

    def write_configs_to_disk(self):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f: 
                json.dump(self.configs, f, indent=4)
        except Exception as e:
            self.append_log(f"<span style='color:red'>[ERROR] Failed to save config: {e}</span>")

    def save_recent_paths_tab_c(self):
        """ Saves Tab C paths to a special key in the config file """
        if "RecentSettings" not in self.configs:
            self.configs["RecentSettings"] = {}
        
        self.configs["RecentSettings"]["tab_c_input"] = self.edit_c_input.text()
        self.configs["RecentSettings"]["tab_c_output"] = self.edit_c_output.text()
        self.write_configs_to_disk()

    def load_recent_paths_tab_c(self):
        """ Loads Tab C paths from config """
        if "RecentSettings" in self.configs:
            settings = self.configs["RecentSettings"]
            self.edit_c_input.setText(settings.get("tab_c_input", ""))
            self.edit_c_output.setText(settings.get("tab_c_output", ""))
        
    def load_selected_config(self, name):
        if name in self.configs and name != "RecentSettings":
            c = self.configs[name]
            self.edit_pdf.setText(c.get('pdf', ''))
            self.combo_model.setCurrentText(c.get('model', DEFAULT_MODEL))

    # --- TAB A Handlers ---
    def get_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select PDF", self.edit_pdf.text(), "*.pdf")
        if f: self.edit_pdf.setText(f)

    # --- TAB B Handlers ---
    def get_json_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select JSON", self.edit_json_path.text(), "*.json")
        if f: 
            self.edit_json_path.setText(f)
            self.update_export_path(f)

    def get_export_path(self):
        f, _ = QFileDialog.getSaveFileName(self, "Save Vector JSON", self.edit_export_path.text(), "JSON Files (*.json)")
        if f: self.edit_export_path.setText(f)

    def update_export_path(self, input_path):
        if input_path:
            d, n = os.path.split(input_path)
            self.edit_export_path.setText(os.path.join(d, f"RAGjson_{n}"))

    # --- TAB C Handlers ---
    def get_converter_input(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select Source JSON", self.edit_c_input.text(), "JSON Files (*.json)")
        if f:
            self.edit_c_input.setText(f)
            self.update_converter_output_path(f)
            self.save_recent_paths_tab_c()

    def get_converter_output(self):
        f, _ = QFileDialog.getSaveFileName(self, "Select Target JSON", self.edit_c_output.text(), "JSON Files (*.json)")
        if f:
            self.edit_c_output.setText(f)
            self.save_recent_paths_tab_c()

    def update_converter_output_path(self, input_path):
        if input_path:
            d, n = os.path.split(input_path)
            base, ext = os.path.splitext(n)
            
            self.edit_c_output.setText(os.path.join(d, f"vector_RAG_{base}{ext}"))

    # --- Common UI ---
    def toggle_visual_window(self):
        if self.btn_visual.isChecked():
            self.visual_window.show()
            self.btn_visual.setText("👁 VISUALIZER: ON")
            self.visual_window.move(self.geometry().x() + self.width() + 10, self.geometry().y())
        else:
            self.visual_window.hide()
            self.btn_visual.setText("👁 VISUALIZER: OFF")

    def append_log(self, html):
        self.txt_console.append(html)
        cursor = self.txt_console.textCursor()
        cursor.movePosition(cursor.End)
        self.txt_console.setTextCursor(cursor)

    def update_timer_display(self):
        elapsed_seconds = int(time.time() - self.start_time)
        delta = timedelta(seconds=elapsed_seconds)
        self.lbl_elapsed.setText(f"ELAPSED: {str(delta)}")
        
    def update_progress_display(self, data):
        try:
            phase = data.get("phase", "Processing")
            current = data.get("current", 0)
            total = data.get("total", 0)
            
            if total > 0:
                percent = int((current / total) * 100)
                self.status_bar.setValue(percent)
                self.status_bar.setFormat(f"{phase}: %p% ({current}/{total})")
            else:
                self.status_bar.setFormat(f"{phase}: Working...")
        except Exception as e:
            pass

    def start_worker(self, cmd):
        if self.worker and self.worker.isRunning():
            return
        
        self.txt_console.clear()
        self.status_bar.show()
        self.status_bar.setValue(0)
        self.status_bar.setFormat("Initializing...")
        
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_gen_vector.setEnabled(False)
        self.btn_run_converter.setEnabled(False)
        
        self.start_time = time.time()
        self.lbl_elapsed.setText("ELAPSED: 00:00:00")
        self.lbl_eta.setText("REMAINING: Calculating...")
        self.timer.start(1000)
        
        self.worker = WorkerThread(cmd)
        self.worker.log_signal.connect(self.append_log)
        self.worker.stream_signal.connect(self.visual_window.add_stream_char)
        self.worker.progress_signal.connect(self.update_progress_display)
        self.worker.finished_signal.connect(self.on_worker_finished)
        
        # Tab A visualizer logic (optional for C but harmless)
        if self.tabs.currentIndex() == 0 and not self.btn_visual.isChecked():
            self.btn_visual.click()
            
        self.worker.start()

    def stop_worker(self):
        if self.worker:
            self.worker.stop()
            self.timer.stop()
            self.lbl_eta.setText("REMAINING: STOPPED")
            self.append_log("<span style='color:red'>[SYSTEM] Process terminated by user.</span>")

    def on_worker_finished(self):
        self.status_bar.setValue(100)
        self.status_bar.setFormat("COMPLETED")
        self.timer.stop()
        self.lbl_eta.setText("REMAINING: DONE")
        
        self.btn_run.setEnabled(True)
        self.btn_gen_vector.setEnabled(True)
        self.btn_run_converter.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.append_log("<span style='color:#00ffcc'>[SYSTEM] Task Completed.</span>")

    # ==============================================================================
    # TASK LAUNCHERS
    # ==============================================================================

    def start_pageindex_task(self):
        """ TAB A Task: PDF Parsing """
        pdf = self.edit_pdf.text()
        model = self.combo_model.currentText()
        if not pdf: return QMessageBox.warning(self, "Error", "Select PDF file!")
        
        strategy_idx = self.combo_schema.currentIndex()
        threads = self.combo_threads.currentText()
        
        self.append_log(f"<span style='color:#AAAAAA'>[CONFIG] IATA Optimization Mode: Strategy {strategy_idx}, Threads {threads}</span>")
        
        py = sys.executable
        # Note: Assuming run_pageindex.py accepts these args based on context
        cmd = f'"{py}" -u {PAGEINDEX_SCRIPT_NAME} --pdf_path "{pdf}" --model "{model}"'
        
        self.append_log(f"<span style='color:#79c0ff'>[CMD] {cmd}</span>")
        self.start_worker(cmd)

    def start_vector_task(self):
        """ TAB B Task: RAG Vectorization (LLM Based) """
        if not os.path.exists(BACKEND_SCRIPT_NAME):
             QMessageBox.critical(self, "Error", f"Backend script '{BACKEND_SCRIPT_NAME}' missing!")
             return

        inp = self.edit_json_path.text()
        out = self.edit_export_path.text()
        model = self.combo_vector_model.currentText()
        strat_idx = self.combo_strategy_tabb.currentIndex()
        
        if not inp: return QMessageBox.warning(self, "Error", "Select Input JSON!")
        
        py = sys.executable
        cmd = f'"{py}" -u {BACKEND_SCRIPT_NAME} --input "{inp}" --output "{out}" --model "{model}" --strategy {strat_idx}'
        
        self.append_log(f"<span style='color:#79c0ff'>[CMD] {cmd}</span>")
        self.start_worker(cmd)

    def start_converter_task(self):
        """ TAB C Task: Rule-Based Converter """
        if not os.path.exists(CONVERTER_SCRIPT_NAME):
             QMessageBox.critical(self, "Error", f"Converter script '{CONVERTER_SCRIPT_NAME}' missing!\nPlease ensure it's in the same folder.")
             return

        inp = self.edit_c_input.text()
        out = self.edit_c_output.text()
        
        if not inp: return QMessageBox.warning(self, "Error", "Select Input JSON!")
        if not out: self.update_converter_output_path(inp); out = self.edit_c_output.text()
        
        # Save paths before running
        self.save_recent_paths_tab_c()

        py = sys.executable
        cmd = f'"{py}" -u {CONVERTER_SCRIPT_NAME} "{inp}" "{out}"'
        
        self.append_log(f"<span style='color:#d2a8ff'>[CMD] {cmd}</span>")
        self.start_worker(cmd)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())