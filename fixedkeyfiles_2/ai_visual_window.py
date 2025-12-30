# -*- coding: utf-8 -*-
import sys
import random
import math
from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore import Qt, QTimer, QPointF
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont, QFontMetrics

class Particle:
    def __init__(self, w, h):
        self.x = random.random() * w
        self.y = random.random() * h
        self.vx = (random.random() - 0.5) * 1.5
        self.vy = (random.random() - 0.5) * 1.5
        self.size = random.random() * 2 + 1
        self.color_alpha = random.randint(100, 200)

    def move(self, w, h):
        self.x += self.vx
        self.y += self.vy
        # 边界反弹
        if self.x < 0 or self.x > w: self.vx *= -1
        if self.y < 0 or self.y > h: self.vy *= -1

class AIVisualWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PageIndex AI Core")
        self.resize(800, 500)
        # 无边框 + 窗口置顶
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 粒子系统初始化
        self.particles = [Particle(self.width(), self.height()) for _ in range(60)]
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(30) # 30ms 刷新率
        
        # 文本缓冲区
        self.display_lines = []
        self.current_line = ""
        self.max_lines = 18 # 适应窗口高度
        
        # 字体设置
        self.font = QFont("Consolas", 10)
        self.font.setBold(True)
        
        # 拖动窗口逻辑
        self.old_pos = None

    def update_animation(self):
        w, h = self.width(), self.height()
        for p in self.particles:
            p.move(w, h)
        self.update() # 触发 paintEvent

    def add_stream_char(self, text_chunk):
        """处理流式文本，增加自动换行逻辑"""
        if not text_chunk: return

        # 简单的宽度计算来进行软换行
        fm = QFontMetrics(self.font)
        max_width = self.width() - 40 # Padding

        for char in text_chunk:
            if char == '\n':
                self.display_lines.append(self.current_line)
                self.current_line = ""
            else:
                if fm.width(self.current_line + char) > max_width:
                    self.display_lines.append(self.current_line)
                    self.current_line = char
                else:
                    self.current_line += char
        
        # 保持缓冲区大小
        while len(self.display_lines) > self.max_lines:
            self.display_lines.pop(0)
        
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 1. 绘制半透明黑色背景 (Cyberpunk Dark)
        painter.fillRect(self.rect(), QColor(10, 15, 20, 245))
        
        # 2. 绘制边框
        pen = QPen(QColor(0, 255, 200))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawRect(1, 1, self.width()-2, self.height()-2)

        # 3. 绘制粒子连线 (神经网络效果)
        painter.setPen(QPen(QColor(0, 255, 200, 50), 1))
        for i, p1 in enumerate(self.particles):
            for p2 in self.particles[i+1:]:
                dist = math.hypot(p1.x - p2.x, p1.y - p2.y)
                if dist < 100: # 距离小于100则连线
                    painter.setPen(QPen(QColor(0, 255, 200, int((1 - dist/100)*150)), 1))
                    painter.drawLine(QPointF(p1.x, p1.y), QPointF(p2.x, p2.y))
            
            # 绘制粒子点
            painter.setBrush(QBrush(QColor(0, 255, 200, p1.color_alpha)))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(p1.x, p1.y), p1.size, p1.size)

        # 4. 绘制 AI 文本流
        painter.setFont(self.font)
        
        line_height = 22
        start_y = 60
        
        # 标题
        painter.setPen(QPen(QColor(0, 255, 200)))
        title_font = QFont("Segoe UI", 12)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(20, 35, "⚡ DEEPSEEK NEURAL STREAM ⚡")
        
        # 内容
        painter.setFont(self.font)
        painter.setPen(QPen(QColor(0, 255, 100)))
        
        # 绘制历史行
        for i, line in enumerate(self.display_lines):
            painter.drawText(20, start_y + i * line_height, line)
            
        # 绘制当前行 + 光标
        current_y = start_y + len(self.display_lines) * line_height
        if len(self.display_lines) < self.max_lines:
            painter.drawText(20, current_y, self.current_line + "█")

    # 允许鼠标拖动无边框窗口
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.old_pos = event.globalPos()

    def mouseMoveEvent(self, event):
        if self.old_pos:
            delta = event.globalPos() - self.old_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.old_pos = event.globalPos()

    def mouseReleaseEvent(self, event):
        self.old_pos = None

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = AIVisualWindow()
    win.show()
    # 测试数据流
    QTimer.singleShot(500, lambda: win.add_stream_char("Initializing Neural Link...\nConnecting to DeepSeek V3...\nStream established."))
    sys.exit(app.exec_())