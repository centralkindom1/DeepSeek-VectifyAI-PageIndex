import sys
import os
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QTextEdit, QLabel, QGroupBox, QMessageBox)
from PyQt5.QtCore import QProcess, Qt
from PyQt5.QtGui import QFont, QTextCursor, QColor

# ================= 配置区域 =================
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

SCRIPTS = {
    "step1": {"name": "工序1: 索引构建 (front_pgui)", "file": "front_pgui.py"},
    "step2": {"name": "工序2: 向量处理 (bge_gui)", "file": "bge_gui.py"},
    "step3": {"name": "工序3: RAG前端 (RAG_Frontend)", "file": "RAG_Frontend.py"}
}

STYLESHEET = """
QMainWindow { background-color: #2b2b2b; color: #f0f0f0; }
QGroupBox { font-weight: bold; border: 1px solid #555; margin-top: 10px; border-radius: 5px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #00a8e8; }
QPushButton {
    background-color: #3e3e42; color: white; border: 1px solid #555;
    padding: 10px; border-radius: 4px; font-size: 14px; font-weight: bold;
}
QPushButton:hover { background-color: #505055; border-color: #007acc; }
QPushButton:pressed { background-color: #007acc; }
QTextEdit { background-color: #1e1e1e; color: #00ff00; font-family: Consolas, monospace; border: 1px solid #444; }
QLabel { font-size: 18px; font-weight: bold; color: #00a8e8; margin-bottom: 10px; }
"""

class ScriptRunner(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RAG 流水线综合控制台 - v2.0")
        self.resize(1100, 800)
        self.setStyleSheet(STYLESHEET)
        self.processes = {} 
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        title_label = QLabel("🚀 RAG 项目流水线管理系统")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        btn_group = QGroupBox("工序启动面板")
        btn_layout = QHBoxLayout()
        
        self.btn_step1 = self.create_button("step1", SCRIPTS["step1"]["name"])
        self.btn_step2 = self.create_button("step2", SCRIPTS["step2"]["name"])
        self.btn_step3 = self.create_button("step3", SCRIPTS["step3"]["name"])
        self.btn_step3.setStyleSheet("background-color: #2da44e; color: white;") 

        btn_layout.addWidget(self.btn_step1)
        btn_layout.addWidget(self.btn_step2)
        btn_layout.addWidget(self.btn_step3)
        btn_group.setLayout(btn_layout)
        main_layout.addWidget(btn_group)

        console_group = QGroupBox("调试控制台 (System Console)")
        console_layout = QVBoxLayout()
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setLineWrapMode(QTextEdit.NoWrap)
        console_layout.addWidget(self.console)
        
        btn_clear = QPushButton("🧹 清空日志")
        btn_clear.setFixedHeight(30)
        btn_clear.clicked.connect(self.console.clear)
        console_layout.addWidget(btn_clear)
        
        console_group.setLayout(console_layout)
        main_layout.addWidget(console_group, stretch=1)

        self.log_system(f"系统就绪。Python版本: {sys.version.split()[0]}")
        self.log_system(f"当前目录: {PROJECT_ROOT}")

    def create_button(self, key, text):
        btn = QPushButton(text)
        btn.clicked.connect(lambda: self.run_script(key))
        return btn

    def run_script(self, key):
        script_info = SCRIPTS[key]
        script_file = script_info["file"]
        full_path = os.path.join(PROJECT_ROOT, script_file)

        if not os.path.exists(full_path):
            self.log_system(f"❌ 错误: 找不到文件 {full_path}", color="red")
            return

        if key in self.processes:
            self.log_system(f"⚠️ {script_file} 已经在运行", color="orange")
            return

        self.log_system(f"▶️ 正在启动: {script_file} ...", color="yellow")
        
        process = QProcess(self)
        # 关键：合并错误和正常输出，并设置为不缓冲
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.setWorkingDirectory(PROJECT_ROOT)
        
        process.readyReadStandardOutput.connect(lambda: self.handle_output(key, process))
        process.finished.connect(lambda code, status: self.process_finished(key, code, status))
        
        # 使用 python -u 解决 Windows 环境下的输出死锁问题
        process.start("python", ["-u", script_file])
        
        if not process.waitForStarted():
            self.log_system(f"❌ 启动失败!", color="red")
        else:
            self.processes[key] = process

    def handle_output(self, key, process):
        data = process.readAllStandardOutput().data()
        try:
            text = data.decode('gbk') # Windows 默认
        except:
            text = data.decode('utf-8', errors='ignore')
        
        if text.strip():
            self.log_console(f"[{SCRIPTS[key]['file']}] {text.strip()}")

    def process_finished(self, key, exit_code, exit_status):
        script_name = SCRIPTS[key]["file"]
        color = "#ff5555" if exit_code != 0 else "#aaaaaa"
        self.log_system(f"🛑 {script_name} 已停止 (代码: {exit_code})", color=color)
        if key in self.processes:
            del self.processes[key]

    def log_system(self, message, color="#00a8e8"):
        self.console.append(f'<span style="color:{color}; font-weight:bold;">>>> {message}</span>')
        self.scroll_to_bottom()

    def log_console(self, text):
        # 实时输出子进程日志
        self.console.append(f'<span style="color:#00ff00;">{text}</span>')
        self.scroll_to_bottom()

    def scroll_to_bottom(self):
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.console.setTextCursor(cursor)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ScriptRunner()
    window.show()
    sys.exit(app.exec_())