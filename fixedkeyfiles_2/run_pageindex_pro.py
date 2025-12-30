import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QTabWidget, QVBoxLayout, QWidget
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

# 导入两个子页面的类
import pgui
import pgirecallwindow

# --- 样式定义 ---
PRO_STYLE = """
QMainWindow { background-color: #0d1117; }
QTabWidget::pane { border: 1px solid #30363d; top: -1px; background: #0d1117; }
QTabBar::tab {
    background: #161b22;
    color: #8b949e;
    padding: 12px 30px;
    border: 1px solid #30363d;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #0d1117;
    color: #58a6ff;
    border-bottom: 2px solid #58a6ff;
}
"""

class PageIndexProApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PageIndex Pro - 综合知识处理套件")
        self.resize(1300, 900)
        self.setStyleSheet(PRO_STYLE)
        
        # 初始化中央 Tab 组件
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        
        # 设置 Tab 字体
        tab_font = QFont("Microsoft YaHei", 10, QFont.Bold)
        self.tabs.tabBar().setFont(tab_font)

        self.init_tabs()

    def init_tabs(self):
        # 1. 实例化 Indexer 页面 (来自 pgui.py)
        self.indexer_page = pgui.MainWindow()
        # 移除内层窗口的边框，使其完美嵌入 Tab
        self.indexer_page.setWindowFlags(Qt.Widget)
        
        # 2. 实例化 Recall 页面 (来自 pgirecallwindow.py)
        self.recall_page = pgirecallwindow.PGIRecallWindow()
        self.recall_page.setWindowFlags(Qt.Widget)

        # 3. 将它们作为 Tab 添加
        self.tabs.addTab(self.indexer_page, "🔧 索引构建器 (Indexer)")
        self.tabs.addTab(self.recall_page, "🔎 知识召回中心 (Recall)")

if __name__ == "__main__":
    # --- 修复报错：正确设置高分屏自适应 ---
    # 之前报错是因为第一个参数传了 sys.path[0] (字符串)
    try:
        # 针对 4K 等高分屏的优化设置
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    except AttributeError:
        pass # 防止某些极旧版本的 PyQt 不支持该属性

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    main_window = PageIndexProApp()
    main_window.show()
    
    sys.exit(app.exec_())