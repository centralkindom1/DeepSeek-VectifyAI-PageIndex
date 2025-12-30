import sys
import json
import os
import subprocess
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QTextEdit, QComboBox, 
                             QFileDialog, QMessageBox, QFrame)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QPalette, QFont, QTextCursor

# Import the visual window
from ai_visual_window import AIVisualWindow

CONFIG_FILE = "gui_configs.json"

# === Cyberpunk Style Sheet ===
STYLESHEET = """
QMainWindow {
    background-color: #0d1117;
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
/* Special Button Style: Visual Switch */
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
    color: #00ff99; /* Matrix Green */
    font-family: 'Consolas', monospace;
    font-size: 12px;
}
QComboBox {
    background-color: #161b22;
    color: #c9d1d9;
    border: 1px solid #30363d;
    padding: 5px;
}
QComboBox::drop-down {
    border: none;
}
"""

class WorkerThread(QThread):
    log_signal = pyqtSignal(str)      # Send normal logs to main console
    stream_signal = pyqtSignal(str)   # Send AI chars to visual window

    def __init__(self, command):
        super().__init__()
        self.command = command
        self.line_buffer = ""

    def run(self):
        # Must use bufsize=0 and text=True for unbuffered reading
        process = subprocess.Popen(
            self.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, # Merge stderr into stdout
            shell=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=0 # Critical for streaming!
        )

        while True:
            # Read character by character for the "typing" effect
            char = process.stdout.read(1)
            
            if not char and process.poll() is not None:
                break
                
            if char:
                self.process_char(char)
        
        # Flush any remaining buffer content when process ends
        self.flush_buffer()
        process.wait()

    def flush_buffer(self):
        """Force output of remaining buffer content."""
        if self.line_buffer:
            line = self.line_buffer.strip()
            if line:
                self.emit_log_line(line)
            self.line_buffer = ""

    def process_char(self, char):
        self.line_buffer += char
        
        if char == "\n":
            line = self.line_buffer.strip()
            # === FIX: Only output if line is not empty to prevent "loose" logs ===
            if line: 
                # Check for special hooks from utils.py
                if line.startswith("DEBUG_AI_CHAR:"):
                    try:
                        # Extract content
                        content = line.split("DEBUG_AI_CHAR:", 1)[1]
                        # Send to visual window
                        self.stream_signal.emit(content)
                    except: pass
                else:
                    # Normal log, send to main console
                    self.emit_log_line(line)
            
            self.line_buffer = ""

    def emit_log_line(self, line):
        # === FIX: Add Color Highlighting for Status Messages ===
        if "[SUCCESS]" in line:
            # Green Highlight
            formatted_line = f"<span style='color:#00FF00; font-weight:bold; font-size:13px;'>{line}</span>"
        elif "[ERROR]" in line or "Exception" in line or "Traceback" in line or "Error" in line:
            # Red Highlight
            formatted_line = f"<span style='color:#FF3333; font-weight:bold;'>{line}</span>"
        elif "[INFO]" in line:
            # Cyan Highlight
            formatted_line = f"<span style='color:#33CCFF;'>{line}</span>"
        elif "[Warning]" in line:
            # Yellow Highlight
            formatted_line = f"<span style='color:#FFFF00;'>{line}</span>"
        else:
            # Default Color
            formatted_line = line
            
        self.log_signal.emit(formatted_line)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PageIndex Pro - Neural Interface")
        self.resize(1100, 850)
        
        # Initialize Visual Window (Hidden)
        self.visual_window = AIVisualWindow()
        
        self.configs = self.load_configs()
        self.init_ui()
        self.apply_styles()

    def apply_styles(self):
        self.setStyleSheet(STYLESHEET)

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # === Header Area ===
        header_layout = QHBoxLayout()
        title_label = QLabel("PAGEINDEX PRO")
        title_label.setStyleSheet("font-size: 24px; color: #00ffcc; letter-spacing: 2px;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # === Config Section ===
        cfg_frame = QFrame()
        cfg_frame.setStyleSheet("background-color: #161b22; border-radius: 8px; padding: 10px;")
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

        # === Input Section ===
        input_layout = QVBoxLayout()
        
        # PDF Selection
        file_layout = QHBoxLayout()
        self.edit_pdf = QLineEdit()
        self.edit_pdf.setPlaceholderText("Select PDF document path...")
        btn_file = QPushButton("📂 BROWSE")
        btn_file.clicked.connect(self.get_file)
        file_layout.addWidget(QLabel("DOCUMENT:"))
        file_layout.addWidget(self.edit_pdf, 1)
        file_layout.addWidget(btn_file)
        input_layout.addLayout(file_layout)
        
        # Model Selection
        model_layout = QHBoxLayout()
        self.edit_model = QLineEdit("DeepSeek-V3")
        model_layout.addWidget(QLabel("AI MODEL:"))
        model_layout.addWidget(self.edit_model, 1)
        input_layout.addLayout(model_layout)
        
        layout.addLayout(input_layout)

        # === Action Buttons ===
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

        # === Console Output ===
        layout.addWidget(QLabel("SYSTEM LOGS:"))
        self.txt_console = QTextEdit()
        self.txt_console.setReadOnly(True)
        layout.addWidget(self.txt_console)

    def toggle_visual_window(self):
        if self.btn_visual.isChecked():
            self.visual_window.show()
            self.btn_visual.setText("👁 VISUALIZER: ON")
            # Move to right of main window
            geo = self.geometry()
            self.visual_window.move(geo.x() + geo.width() + 10, geo.y())
        else:
            self.visual_window.hide()
            self.btn_visual.setText("👁 VISUALIZER: OFF")

    def load_configs(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f: return json.load(f)
            except: pass
        return {"Default": {"pdf": "", "model": "DeepSeek-V3", "pages": "3"}}

    def save_config(self):
        name = self.cb_configs.currentText() or "NewConfig"
        self.configs[name] = {"pdf": self.edit_pdf.text(), "model": self.edit_model.text(), "pages": "3"}
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(self.configs, f)
        QMessageBox.information(self, "System", "Configuration Saved Successfully.")

    def load_selected_config(self, name):
        if name in self.configs:
            c = self.configs[name]
            self.edit_pdf.setText(c.get('pdf',''))
            self.edit_model.setText(c.get('model','DeepSeek-V3'))

    def get_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select PDF", "", "*.pdf")
        if f: self.edit_pdf.setText(f)

    def append_log(self, text):
        """Append log and auto-scroll to bottom."""
        self.txt_console.append(text)
        # Move cursor to end to ensure auto-scroll works
        cursor = self.txt_console.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.txt_console.setTextCursor(cursor)

    def start_task(self):
        pdf_path = self.edit_pdf.text()
        if not pdf_path:
            QMessageBox.warning(self, "Error", "Please select a PDF file first.")
            return

        py_exe = sys.executable
        # -u argument is crucial, forces stdout to be unbuffered
        cmd = f'"{py_exe}" -u run_pageindex.py --pdf_path "{pdf_path}" --model "{self.edit_model.text()}" --toc-check-pages 3'
        
        self.txt_console.clear()
        self.txt_console.append(f"<span style='color:#FFFF00'>[SYSTEM] Initializing subprocess...</span>")
        
        self.worker = WorkerThread(cmd)
        self.worker.log_signal.connect(self.append_log)
        
        # Connect visual signal
        self.worker.stream_signal.connect(self.visual_window.add_stream_char)
        
        # Auto open visual window
        if not self.btn_visual.isChecked():
            self.btn_visual.click()
            
        self.worker.start()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion') # Use Fusion style for better CSS support
    main = MainWindow()
    main.show()
    sys.exit(app.exec_())