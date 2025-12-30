import sys
import json
import os
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QTextEdit, QListWidget, 
                             QListWidgetItem, QFileDialog, QSplitter, QMessageBox)
from PyQt5.QtCore import Qt

class PGIRecallWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PageIndex - 知识召回查询中心 (DeepSeek适配版)")
        self.resize(1200, 800)
        self.data = None
        self.all_nodes = [] # 用于扁平化存储所有节点，方便搜索
        
        self.init_ui()
        self.apply_styles()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # --- 顶部：加载与搜索栏 ---
        top_bar = QHBoxLayout()
        self.btn_load = QPushButton("加载索引JSON")
        self.btn_load.clicked.connect(self.load_json)
        
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("输入关键词进行内容召回...")
        self.edit_search.returnPressed.connect(self.search_content)
        
        self.btn_search = QPushButton("执行召回")
        self.btn_search.clicked.connect(self.search_content)
        
        top_bar.addWidget(self.btn_load)
        top_bar.addWidget(self.edit_search, 4)
        top_bar.addWidget(self.btn_search)
        layout.addLayout(top_bar)

        # --- 中部：结果列表与正文预览 (使用 Splitter 支持拖拽调整宽度) ---
        splitter = QSplitter(Qt.Horizontal)
        
        # 左侧容器
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("召回结果列表:"))
        self.list_results = QListWidget()
        self.list_results.itemClicked.connect(self.display_node_detail)
        left_layout.addWidget(self.list_results)
        
        # 右侧容器
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("详情预览 (包含正文及页码):"))
        self.txt_detail = QTextEdit()
        self.txt_detail.setReadOnly(True)
        right_layout.addWidget(self.txt_detail)
        
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1) # 左侧比例
        splitter.setStretchFactor(1, 3) # 右侧比例更大，方便阅读正文
        
        layout.addWidget(splitter)

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #0d1117; }
            QLabel { color: #58a6ff; font-family: 'Segoe UI'; font-weight: bold; font-size: 14px; }
            QLineEdit { 
                background-color: #161b22; 
                border: 1px solid #30363d; 
                border-radius: 6px; 
                color: #c9d1d9; 
                padding: 8px; 
                font-family: 'Microsoft YaHei'; 
            }
            QPushButton { 
                background-color: #238636; 
                color: white; 
                border: none; 
                padding: 8px 15px; 
                border-radius: 6px; 
                font-weight: bold; 
            }
            QPushButton:hover { background-color: #2ea043; }
            QPushButton:pressed { background-color: #238636; }
            QListWidget { 
                background-color: #0d1117; 
                border: 1px solid #30363d; 
                border-radius: 6px;
                color: #c9d1d9; 
                font-size: 14px; 
                padding: 5px;
            }
            QListWidget::item { padding: 5px; }
            QListWidget::item:selected { background-color: #1f6feb; border-radius: 4px; }
            QTextEdit { 
                background-color: #0d1117; 
                border: 1px solid #30363d; 
                border-radius: 6px;
                color: #c9d1d9; 
                font-size: 16px; 
                line-height: 1.6; 
                padding: 10px;
            }
            QSplitter::handle { background-color: #30363d; }
        """)

    def load_json(self):
        """
        鲁棒的 JSON 加载逻辑，兼容各种可能的 JSON 结构
        """
        file_path, _ = QFileDialog.getOpenFileName(self, "选择索引文件", "", "JSON Files (*.json);;All Files (*)")
        if not file_path:
            return

        try:
            # 使用 utf-8-sig 以兼容 Windows 记事本保存的带 BOM 的文件
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                self.data = json.load(f)
            
            self.all_nodes = []
            
            # --- 智能解析入口 ---
            root_nodes = self._smart_parse_structure(self.data)
            
            # 开始递归扁平化
            self._flatten_structure(root_nodes)

            if not self.all_nodes:
                self.txt_detail.setText(f"⚠️ 文件 {os.path.basename(file_path)} 加载成功，但未解析到有效节点。\n请检查 JSON 结构是否符合规范。")
                return

            self.txt_detail.setText(f"✅ 已成功加载文件: {os.path.basename(file_path)}\n📊 共解析出 {len(self.all_nodes)} 个知识节点。\n\n请在上方搜索框输入关键词进行召回。")
            
            # 初始显示所有节点
            self.list_results.clear()
            for node in self.all_nodes:
                self._add_item_to_list(node)
                
        except json.JSONDecodeError:
            QMessageBox.critical(self, "加载失败", "文件不是有效的 JSON 格式。")
        except Exception as e:
            import traceback
            error_msg = f"❌ 加载失败: {str(e)}\n\n{traceback.format_exc()}"
            self.txt_detail.setText(error_msg)
            print(error_msg)

    def _smart_parse_structure(self, data):
        """
        智能判断数据入口，兼容 List 和 Dict（及其变种）
        返回: List[Node]
        """
        # 情况1: 根就是列表 (旧版本格式)
        if isinstance(data, list):
            return data
        
        # 情况2: 根是字典
        elif isinstance(data, dict):
            # 优先查找 'structure' 键 (你的新格式)
            if 'structure' in data and isinstance(data['structure'], list):
                return data['structure']
            
            # 兼容其他可能的键名
            if 'nodes' in data and isinstance(data['nodes'], list):
                return data['nodes']
            
            if 'content' in data and isinstance(data['content'], list):
                return data['content']
            
            # 如果字典本身就是一个根节点（包含 title 和 nodes）
            return [data]
            
        return []

    def _flatten_structure(self, nodes):
        """
        递归展开所有节点，方便全文搜索
        """
        if not nodes or not isinstance(nodes, list):
            return
            
        for item in nodes:
            if not isinstance(item, dict):
                continue
                
            # 添加当前节点
            self.all_nodes.append(item)
            
            # 递归处理子节点
            if 'nodes' in item and isinstance(item['nodes'], list):
                self._flatten_structure(item['nodes'])

    def search_content(self):
        query = self.edit_search.text().strip().lower()
        self.list_results.clear()
        
        # 如果搜索框为空，显示所有节点
        if not query:
            for node in self.all_nodes:
                self._add_item_to_list(node)
            self.txt_detail.setText(f"显示所有 {len(self.all_nodes)} 个节点。")
            return
            
        results_found = 0
        for node in self.all_nodes:
            # 安全获取字段，防止 NoneType 报错
            title = str(node.get('title', '') or '').lower()
            text = str(node.get('text', '') or '').lower()
            summary = str(node.get('summary', '') or '').lower()
            
            # 搜索匹配逻辑：标题、正文或摘要包含关键词
            if query in title or query in text or query in summary:
                self._add_item_to_list(node)
                results_found += 1
        
        if results_found > 0:
            self.txt_detail.setText(f"🔍 查询关键字: '{query}'\n✅ 成功召回到 {results_found} 个匹配章节。\n请点击左侧列表查看详情。")
        else:
            self.txt_detail.setText(f"⚠️ 未找到包含 '{query}' 的内容。")

    def _add_item_to_list(self, node):
        """辅助函数：添加节点到列表"""
        title = node.get('title')
        if not title:
            title = "（无标题节点）"
            
        # 如果标题太长，截断显示
        display_title = (title[:50] + '...') if len(title) > 50 else title
        
        item = QListWidgetItem(display_title)
        item.setToolTip(title) # 鼠标悬停显示全名
        item.setData(Qt.UserRole, node) # 将节点数据绑定到 Item
        self.list_results.addItem(item)

    def display_node_detail(self, item):
        node = item.data(Qt.UserRole)
        if node:
            start = node.get('start_index', '-')
            end = node.get('end_index', '-')
            node_id = node.get('node_id', 'N/A')
            title = node.get('title', '未命名章节')
            
            # 获取文本，如果为空则提示
            raw_text = node.get('text', '')
            if not raw_text:
                raw_text = "<span style='color: #8b949e; font-style: italic;'>（该节点无正文内容，可能仅为目录标题）</span>"
            else:
                # 简单的 HTML 转义，防止正文内容破坏 HTML 结构
                import html
                raw_text = html.escape(raw_text)
            
            # 获取摘要
            summary = node.get('summary', '')
            summary_html = ""
            if summary:
                summary_html = f"""
                <div style='background-color: #1c2128; border-left: 4px solid #238636; padding: 8px; margin-bottom: 15px;'>
                    <span style='color: #238636; font-weight: bold;'>💡 AI 摘要:</span><br>
                    <span style='color: #c9d1d9;'>{summary}</span>
                </div>
                """

            display_html = f"""
            <h2 style='color: #58a6ff; margin-bottom: 5px;'>{title}</h2>
            
            <div style='background-color: #21262d; padding: 8px; border-radius: 5px; margin-bottom: 10px; font-size: 13px;'>
                <span style='color: #8b949e; font-weight: bold;'>📄 物理页码:</span> 
                <span style='color: #c9d1d9;'>{start} - {end}</span>
                &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
                <span style='color: #8b949e; font-weight: bold;'>🆔 Node ID:</span> 
                <span style='color: #c9d1d9;'>{node_id}</span>
            </div>
            
            {summary_html}
            
            <hr style='border: 0; height: 1px; background-color: #30363d; margin: 10px 0;'>
            
            <div style='color: #c9d1d9; white-space: pre-wrap; font-family: Consolas, "Microsoft YaHei"; font-size: 15px; line-height: 1.6;'>{raw_text}</div>
            """
            self.txt_detail.setHtml(display_html)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PGIRecallWindow()
    window.show()
    sys.exit(app.exec_())