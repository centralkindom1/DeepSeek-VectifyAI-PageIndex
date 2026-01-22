# -*- coding: utf-8 -*-
import sys
import os
import traceback
import warnings
import json

# 1. 打印启动标记
print("--- [DEBUG] 脚本开始执行 ---")

try:
    from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                 QHBoxLayout, QPushButton, QTextEdit, QLabel, 
                                 QFileDialog, QMessageBox, QSplitter)
    from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
    from PyQt5.QtGui import QTextCursor
    print("--- [DEBUG] PyQt5 导入成功 ---")
except ImportError as e:
    print(f"!!! [FATAL] PyQt5 导入失败: {e}")
    input("按回车键退出...")
    sys.exit(1)

import backend_logic
print("--- [DEBUG] 后端逻辑导入成功 ---")

# ================= 修复核心：日志重定向类 =================
class LogSignal(QObject):
    """用于在非 GUI 线程向 GUI 发送日志文本"""
    text_written = pyqtSignal(str)

class LogRedirector(object):
    """重定向 sys.stdout 和 sys.stderr 到 PyQt 信号"""
    def __init__(self, original_stream, signal_obj):
        self.original_stream = original_stream
        self.signal_obj = signal_obj

    def write(self, text):
        # 1. 输出到原始控制台（IDLE/CMD）
        self.original_stream.write(text)
        # 2. 发送信号给 UI
        self.signal_obj.text_written.emit(str(text))

    def flush(self):
        self.original_stream.flush()
# ========================================================

class WorkerThread(QThread):
    chunk_signal = pyqtSignal(str)
    # 修改信号定义：发送 (总结内容, 向量JSON字符串)
    done_signal = pyqtSignal(str, str)

    def __init__(self, text):
        super().__init__()
        self.text = text

    def run(self):
        try:
            backend_logic.log_to_file("[Thread] 总结线程启动")
            
            # 1. 生成总结 (DeepSeek-V3)
            summary_client = backend_logic.DeepSeekV3Client()
            summary_result = summary_client.generate_summary(self.text, self.chunk_signal)
            
            # 如果生成过程出错，直接返回错误，不进行向量化
            if "[API 报错" in summary_result or "[网络连接异常" in summary_result:
                 self.done_signal.emit(summary_result, "[]")
                 return

            # 2. 生成向量 (BGE-M3)
            backend_logic.log_to_file("[Thread] 正在调用 Embedding 模型生成向量...")
            self.chunk_signal.emit("\n\n------------------------------\n[系统] 正在进行 BGE-M3 向量化处理...\n")
            
            embed_client = backend_logic.EmbeddingClient()
            vector_list = embed_client.get_embedding(summary_result)
            
            if vector_list:
                vector_json = json.dumps(vector_list)
                self.chunk_signal.emit("[系统] 向量化成功！正在入库...")
                self.done_signal.emit(summary_result, vector_json)
            else:
                self.chunk_signal.emit("[系统] 向量化失败，将仅保存文本。")
                self.done_signal.emit(summary_result, "[]")

        except Exception:
            err = traceback.format_exc()
            print(f"线程报错: {err}") 
            self.done_signal.emit("[ERROR]", "[]")

class SummaryApp(QMainWindow):
    def __init__(self):
        super().__init__()
        print("--- [DEBUG] 开始初始化主窗口 ---")
        self.extracted_text = ""
        self.file_path = ""
        self.threads = [] 
        
        # 1. 初始化 UI
        self.init_ui()
        
        # 2. 【关键修复】初始化日志重定向
        self.init_logger()
        print("--- [DEBUG] UI 初始化完成，日志系统已挂载 ---")
        
        # 3. 初始化数据库
        backend_logic.DatabaseManager.init_db()
        print("--- [DEBUG] 数据库初始化完成 ---")

    def init_ui(self):
        self.setWindowTitle("DeepSeek V3 文档助手 (智能查重 + 向量化版)")
        self.resize(1100, 850)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # 按钮区
        btns = QHBoxLayout()
        self.btn_file = QPushButton("📂 第一步：加载 JSON")
        self.btn_file.clicked.connect(self.load_file)
        self.btn_run = QPushButton("🚀 第二步：生成总结 -> 向量化 -> 入库")
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self.run_process)
        self.btn_run.setStyleSheet("background: #0078d4; color: white; font-weight: bold; height: 35px;")
        
        btns.addWidget(self.btn_file)
        btns.addWidget(self.btn_run)
        layout.addLayout(btns)

        # 分割区
        split_main = QSplitter(Qt.Vertical)
        
        # 上层
        split_up = QSplitter(Qt.Horizontal)
        self.txt_in = QTextEdit()
        self.txt_in.setPlaceholderText("JSON 内容预览...")
        self.txt_out = QTextEdit()
        self.txt_out.setPlaceholderText("AI 总结及系统状态输出...")
        
        split_up.addWidget(self.txt_in)
        split_up.addWidget(self.txt_out)
        split_main.addWidget(split_up)

        # 下层：调试控制台
        self.txt_console = QTextEdit()
        self.txt_console.setReadOnly(True)
        self.txt_console.setPlaceholderText("正在等待系统日志...")
        self.txt_console.setStyleSheet("background: #1e1e1e; color: #00ff00; font-family: 'Consolas'; font-size: 10pt;")
        split_main.addWidget(self.txt_console)
        
        split_main.setStretchFactor(0, 3)
        split_main.setStretchFactor(1, 1)
        layout.addWidget(split_main)

    def init_logger(self):
        """挂载日志系统，将 stdout 重定向到 txt_console"""
        self.log_signal = LogSignal()
        self.log_signal.text_written.connect(self.append_log)
        
        # 替换系统标准输出
        sys.stdout = LogRedirector(sys.stdout, self.log_signal)
        sys.stderr = LogRedirector(sys.stderr, self.log_signal)

    def append_log(self, text):
        """将捕获的文本追加到控制台窗口"""
        cursor = self.txt_console.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        self.txt_console.setTextCursor(cursor)
        self.txt_console.ensureCursorVisible()

    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 JSON", "", "JSON (*.json)")
        if path:
            self.file_path = path
            text, msg = backend_logic.JsonProcessor.extract_structure(path)
            if text:
                self.extracted_text = text
                self.txt_in.setPlainText(text)
                self.btn_run.setEnabled(True)
                self.txt_out.clear() 
                print(f"[UI] 加载成功: {os.path.basename(path)}")
            else:
                QMessageBox.warning(self, "解析失败", msg)

    def run_process(self):
        # 1. 准备工作
        self.txt_out.clear()
        
        # 2. 获取文件名用于查重
        if not self.file_path:
            return
        file_name = os.path.basename(self.file_path)
        
        # 3. 【查重逻辑核心】
        print(f"--- [DEBUG] 正在对 '{file_name}' 进行数据库查重 ---")
        is_exist, history_summary = backend_logic.DatabaseManager.check_is_duplicate(file_name)
        
        if is_exist:
            # === 如果重复 ===
            warn_msg = f"!!! [重复入库警告] 文件 '{file_name}' 已在数据库中存在记录。无需重复消耗 Token。"
            print(warn_msg)
            # 这一行会自动被 log_to_file 里的 print 捕获，所以不需要额外操作
            
            self.txt_out.setPlainText(f"【⚠️ 检测到历史记录，已自动加载】\n\n{history_summary}")
            QMessageBox.information(self, "重复入库提示", 
                                    f"文件 '{file_name}' 已存在！\n\n系统已自动从数据库加载历史总结，未进行 AI 调用。")
            self.btn_run.setEnabled(True)
            return

        # === 如果不重复，继续执行 AI 流程 ===
        print(f"--- [DEBUG] 查重通过，文件 '{file_name}' 为新文件，开始调用 API ---")
        self.btn_run.setEnabled(False)
        worker = WorkerThread(self.extracted_text)
        worker.chunk_signal.connect(lambda t: self.txt_out.insertPlainText(t))
        worker.done_signal.connect(self.finish_task)
        self.threads.append(worker)
        worker.start()

    def finish_task(self, summary_result, vector_json):
        self.btn_run.setEnabled(True)
        if summary_result != "[ERROR]":
            fname = os.path.basename(self.file_path)
            # 调用后端入库，同时传入 summary 和 vector
            success = backend_logic.DatabaseManager.save_summary(
                fname, 
                self.file_path, 
                self.extracted_text, 
                summary_result,
                vector_json
            )
            if success:
                QMessageBox.information(self, "成功", "总结已生成、向量化并成功入库 (V4)！")
            else:
                QMessageBox.warning(self, "入库失败", "数据保存过程中发生错误，请查看日志。")

# ================= 入口逻辑 =================
if __name__ == "__main__":
    print("--- [DEBUG] 准备启动 QApplication ---")
    
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    
    app = QApplication(sys.argv)
    
    window = SummaryApp()
    window.show()
    
    exit_code = app.exec_()
    sys.exit(exit_code)