import json
import logging
import os
import time
from colorama import Fore
from .audio_manager import AudioManager

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QLineEdit, QPushButton, QLabel, QFrame, QTextEdit,
    QSizePolicy, QGraphicsDropShadowEffect, QApplication,
    QDialog,  QProgressBar
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QSize, QRect, QObject
from PyQt5.QtGui import QFont, QPainter, QPainterPath, QColor, QPixmap, QIcon
from qgis.utils import iface
from qgis.core import QgsProject, Qgis

from .chat_model import chat_with_openai, call_qwen_with_prompt
from .layout_management import execute_layout_task
from .hotword_manager import QGISHotwordManager
from .workflow_graph import create_workflow_graph
from .prompts import FINAL_SUMMARY_PROMPT, ERROR_REPORT_PROMPT

INITIAL_MESSAGE = ("你好！我是你的QGIS智能制图助手，你可以向我提出任何关于QGIS的制图任务。例如，你可以对我说：\n"
                   "1.绘制一幅湖北省普通地图；\n"
                   "2.加载武汉市行政区边界数据；\n"
                   "3.将河流图层的样式设置为蓝色；\n")

os.environ['NO_PROXY'] = 'dashscope.aliyuncs.com'

# ---配置部分---
API_KEY = "sk-a2cddd46f8924031b2888c97c73c6e43"
MODEL_TYPE = "qwen-plus"
MODEL_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
ROUND_LIMIT = 10


# --- 自定义气泡组件 ---
class ChatBubble(QWidget):
    def __init__(self, text, sender, avatar_path=None, parent=None, typing_effect=False):
        super().__init__(parent)
        self.sender = sender
        self.full_text = text
        self.avatar_path = avatar_path
        self.typing_effect = typing_effect
        self.current_text = ""
        self.init_ui()
        
        if self.typing_effect and sender == "ai":
            self.message_label.setText("")
            self.start_typing()
        else:
            self.message_label.setText(text)

    def init_ui(self):
        # 主布局
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignTop)

        # 1. 头像区域
        avatar_label = QLabel()
        avatar_size = 26 # 缩小头像尺寸
        avatar_label.setFixedSize(avatar_size, avatar_size)
        
        # 加载头像
        if self.avatar_path and os.path.exists(self.avatar_path):
             pixmap = QPixmap(self.avatar_path)
        else:
             pixmap = QPixmap(avatar_size, avatar_size)
             pixmap.fill(QColor("#10a37f" if self.sender == "ai" else "#8e8e8e"))
        
        # 绘制圆形头像
        rounded = QPixmap(avatar_size, avatar_size)
        rounded.fill(Qt.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addEllipse(0, 0, avatar_size, avatar_size)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, avatar_size, avatar_size, pixmap)
        painter.end()
        avatar_label.setPixmap(rounded)
        
        # 设置头像对齐方式 (顶部对齐，并增加一点上边距以对齐文字)
        avatar_container = QVBoxLayout()
        avatar_container.setContentsMargins(0, 2, 0, 0) #微调上边距
        avatar_container.addWidget(avatar_label)
        avatar_container.addStretch()

        # 2. 气泡内容容器
        bubble_frame = QFrame()
        bubble_layout = QVBoxLayout(bubble_frame)
        bubble_layout.setContentsMargins(12, 10, 12, 10)
        
        # 3. 消息文本标签
        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setFont(QFont("Microsoft YaHei", 10))
        self.message_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.message_label.setStyleSheet("border: none; background: transparent;")
        self.message_label.setTextFormat(Qt.PlainText)
        
        # 关键修改：设置 Label 的尺寸策略，使其能够正确换行和伸缩
        self.message_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
        
        bubble_layout.addWidget(self.message_label)

        # 4. 根据发送者配置样式和布局
        if self.sender == "user":
            layout.addStretch()
            
            # 用户气泡样式
            bubble_frame.setStyleSheet("""
                QFrame {
                    background-color: #f0f0f0;
                    border-radius: 12px;
                    border-top-right-radius: 2px;
                }
            """)
            
            # 用户消息布局：气泡 + 头像
            layout.addWidget(bubble_frame, 1) # 伸缩因子设为1，允许伸缩但不强占
            
            # 为防止气泡过宽，限制最大宽度 (可选，但为了自适应最好不限)
            # layout.addLayout(avatar_container) # 用户头像可选，这里保留
            layout.addWidget(avatar_label) # 直接添加 Label 也可以
            
        else:
            # AI 气泡样式
            bubble_frame.setStyleSheet("""
                QFrame {
                    background-color: transparent;
                }
            """)
            
            # AI 消息布局：头像 + 气泡
            layout.addLayout(avatar_container)
            layout.addWidget(bubble_frame, 1) # 伸缩因子1，占据剩余空间
            layout.addStretch() # 右侧弹簧，确保靠左

    def start_typing(self):
        self.typing_timer = QTimer(self)
        self.typing_timer.timeout.connect(self.update_text)
        self.typing_timer.start(30) # 打字速度: 30ms/字

    def update_text(self):
        if len(self.current_text) < len(self.full_text):
            self.current_text += self.full_text[len(self.current_text)]
            self.message_label.setText(self.current_text)
            self.message_label.adjustSize()
        else:
            self.typing_timer.stop()


# --- 思考气泡组件 (打字机效果) ---
class ThinkingBubble(QWidget):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.full_text = text
        self.current_text = ""
        self.init_ui()
        if text and text != "正在思考中...":
            self.start_typing()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(0)
        
        # 思考内容容器
        content_frame = QFrame()
        content_frame.setStyleSheet("""
            QFrame {
                background-color: transparent;
                border: none;
            }
        """)
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(10, 8, 10, 8)
        
        # 思考文本
        self.text_label = QLabel(self.full_text if self.full_text == "正在思考中..." else "")
        self.text_label.setWordWrap(True)
        self.text_label.setFont(QFont("Consolas", 9, QFont.StyleItalic))
        self.text_label.setStyleSheet("color: #6c757d; border: none;")
        self.text_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
        
        content_layout.addWidget(self.text_label)
        
        # 折叠按钮
        self.toggle_btn = QPushButton("收起思考过程 ▲")
        self.toggle_btn.setFlat(True)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                text-align: left;
                color: #adb5bd;
                font-size: 10px;
                border: none;
                padding-left: 10px;
            }
            QPushButton:hover { color: #6c757d; }
        """)
        self.toggle_btn.clicked.connect(self.toggle_content)
        self.toggle_btn.setVisible(False) # 初始隐藏，有真实内容时显示

        self.content_frame = content_frame
        
        layout.addWidget(content_frame)
        layout.addWidget(self.toggle_btn)

    def set_text(self, text):
        """更新思考内容并开始打字"""
        self.full_text = text
        self.current_text = ""
        self.text_label.setText("")
        self.toggle_btn.setVisible(True)
        self.start_typing()

    def toggle_content(self):
        visible = not self.content_frame.isVisible()
        self.content_frame.setVisible(visible)
        self.toggle_btn.setText("收起思考过程 ▲" if visible else "展开思考过程 ▼")

    def start_typing(self):
        self.typing_timer = QTimer(self)
        self.typing_timer.timeout.connect(self.update_text)
        self.typing_timer.start(20) # 思考打字速度稍快

    def update_text(self):
        if len(self.current_text) < len(self.full_text):
            self.current_text += self.full_text[len(self.current_text)]
            self.text_label.setText(self.current_text)
            self.text_label.adjustSize()
        else:
            self.typing_timer.stop()


# --- 步骤进度组件 (轮播+折叠) ---
class StepProgressWidget(QWidget):
    def __init__(self, steps, parent=None):
        super().__init__(parent)
        self.steps = steps  # List of dict: {'task': str, 'status': 'pending'}
        self.current_step_index = 0
        self.init_ui()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 5, 0, 5)
        self.main_layout.setSpacing(0)

        # 1. 容器 Frame
        self.container = QFrame()
        self.container.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #e9ecef;
                border-radius: 6px;
            }
        """)
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # 2. 头部：当前步骤轮播 (始终可见)
        self.header_frame = QFrame()
        self.header_frame.setStyleSheet("background-color: #e3f2fd; border-top-left-radius: 6px; border-top-right-radius: 6px;")
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(10, 8, 10, 8)

        self.status_icon = QLabel("⏳") 
        self.status_text = QLabel("正在初始化任务...")
        self.status_text.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
        self.status_text.setStyleSheet("color: #0d47a1;")
        
        self.toggle_btn = QPushButton("展开详情 ▼")
        self.toggle_btn.setFlat(True)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.setStyleSheet("color: #666; font-size: 10px; text-align: right;")
        self.toggle_btn.clicked.connect(self.toggle_details)

        header_layout.addWidget(self.status_icon)
        header_layout.addWidget(self.status_text, 1)
        header_layout.addWidget(self.toggle_btn)

        # 3. 详情列表 (默认隐藏)
        self.details_frame = QFrame()
        self.details_frame.setVisible(False)
        self.details_layout = QVBoxLayout(self.details_frame)
        self.details_layout.setContentsMargins(10, 5, 10, 10)
        self.details_layout.setSpacing(5)

        # 初始化步骤列表项
        self.step_labels = []
        self.step_progress_bars = [] # 存储每个步骤对应的进度条组件(包含标签和进度条)
        
        for i, step in enumerate(self.steps):
            # 步骤容器
            step_container = QWidget()
            step_layout = QVBoxLayout(step_container)
            step_layout.setContentsMargins(0, 0, 0, 0)
            step_layout.setSpacing(2)
            
            # 步骤文本标签
            lbl = QLabel(f"{i+1}. {step['task']}")
            lbl.setFont(QFont("Microsoft YaHei", 9))
            lbl.setStyleSheet("color: #adb5bd;") # 默认灰色
            lbl.setWordWrap(True)
            
            # 进度条容器 (默认隐藏)
            progress_widget = QWidget()
            progress_layout = QVBoxLayout(progress_widget)
            progress_layout.setContentsMargins(15, 0, 0, 0) # 稍微缩进
            progress_layout.setSpacing(2)
            
            target_lbl = QLabel("")
            target_lbl.setFont(QFont("Microsoft YaHei", 8))
            target_lbl.setStyleSheet("color: #6c757d;")
            
            p_bar = QProgressBar()
            p_bar.setRange(0, 100)
            p_bar.setValue(0)
            p_bar.setFixedHeight(10)
            p_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #e9ecef;
                    border-radius: 4px;
                    text-align: center;
                    background-color: #f8f9fa;
                }
                QProgressBar::chunk {
                    background-color: #007bff;
                    border-radius: 3px;
                }
            """)
            p_bar.setTextVisible(False) # 隐藏自带文本，因为太窄了
            
            progress_layout.addWidget(target_lbl)
            progress_layout.addWidget(p_bar)
            progress_widget.setVisible(False)
            
            step_layout.addWidget(lbl)
            step_layout.addWidget(progress_widget)
            
            self.details_layout.addWidget(step_container)
            self.step_labels.append(lbl)
            self.step_progress_bars.append({
                "widget": progress_widget,
                "label": target_lbl,
                "bar": p_bar
            })

        container_layout.addWidget(self.header_frame)
        container_layout.addWidget(self.details_frame)
        
        self.main_layout.addWidget(self.container)

    def toggle_details(self):
        visible = not self.details_frame.isVisible()
        self.details_frame.setVisible(visible)
        self.toggle_btn.setText("收起详情 ▲" if visible else "展开详情 ▼")

    def update_step_status(self, index, status, result_text=None):
        """
        status: 'running', 'success', 'fail'
        """
        if index < 0 or index >= len(self.steps):
            return
        
        self.current_step_index = index
        task_name = self.steps[index]['task']
        total_steps = len(self.steps)
        completed_steps = sum(1 for step in self.steps[:index] if True) # 简单计算，实际上应该根据状态
        if status == 'success':
            completed_steps += 1
        
        # 更新头部轮播
        if status == 'running':
            self.status_icon.setText("🔄")
            self.status_text.setText(f"共{total_steps}个执行流程，{index}/{total_steps}已完成，步骤{index+1}正在执行中")
            self.step_labels[index].setStyleSheet("color: #007bff; font-weight: bold;")
            self.step_labels[index].setText(f"➤ {index+1}. {task_name} (执行中...)")
        elif status == 'success':
            self.status_icon.setText("✅")
            self.status_text.setText(f"共{total_steps}个执行流程，{index+1}/{total_steps}已完成，步骤{index+1}执行成功")
            self.step_labels[index].setStyleSheet("color: #28a745;")
            self.step_labels[index].setText(f"✔ {index+1}. {task_name}")
            # 成功后隐藏进度条
            if index < len(self.step_progress_bars):
                self.step_progress_bars[index]["widget"].setVisible(False)
        elif status == 'fail':
            self.status_icon.setText("❌")
            self.status_text.setText(f"共{total_steps}个执行流程，{index}/{total_steps}已完成，步骤{index+1}执行失败")
            self.step_labels[index].setStyleSheet("color: #dc3545;")
            self.step_labels[index].setText(f"✘ {index+1}. {task_name} - {result_text}")
            # 失败后隐藏进度条
            if index < len(self.step_progress_bars):
                self.step_progress_bars[index]["widget"].setVisible(False)

    def update_download_progress(self, target_name: str, percent: int):
        """更新当前执行步骤的下载进度"""
        idx = self.current_step_index
        if idx >= 0 and idx < len(self.step_progress_bars):
            p_data = self.step_progress_bars[idx]
            
            # 如果是新的下载任务或首次显示，强制显示详情并展开进度条
            if not p_data["widget"].isVisible():
                p_data["widget"].setVisible(True)
                # 自动展开详情面板以便用户看到进度条
                if not self.details_frame.isVisible():
                    self.toggle_details()
                    
            p_data["label"].setText(f"正在下载: {target_name} ({percent}%)")
            p_data["bar"].setValue(percent)
            
            # 当达到100%时，为了平滑体验，稍微停留一下再重置/隐藏
            if percent >= 100:
                # 不立刻隐藏，等成功状态再隐藏，但可以将文本变为完成状态
                p_data["label"].setText(f"下载完成: {target_name}")


# --- 错误展示组件 (嵌入式) ---
class ErrorWidget(QWidget):
    def __init__(self, error_report, parent=None):
        super().__init__(parent)
        self.init_ui(error_report)

    def init_ui(self, report):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 5, 0, 5)
        self.main_layout.setSpacing(0)

        # 容器 Frame
        self.container = QFrame()
        self.container.setStyleSheet("""
            QFrame {
                background-color: #fff5f5;
                border: 1px solid #ffc9c9;
                border-radius: 6px;
            }
        """)
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # 头部：错误警示 (始终可见)
        self.header_frame = QFrame()
        self.header_frame.setStyleSheet("""
            background-color: #ffe3e3; 
            border-top-left-radius: 6px; 
            border-top-right-radius: 6px;
            border-bottom: 1px solid #ffc9c9;
        """)
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(10, 8, 10, 8)

        self.status_icon = QLabel("⚠️") 
        self.status_icon.setFont(QFont("Segoe UI Emoji", 12))
        self.status_text = QLabel("任务执行遇到错误")
        self.status_text.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
        self.status_text.setStyleSheet("color: #c92a2a;")
        
        header_layout.addWidget(self.status_icon)
        header_layout.addWidget(self.status_text, 1)

        # 详情区域
        self.details_frame = QFrame()
        self.details_layout = QVBoxLayout(self.details_frame)
        self.details_layout.setContentsMargins(10, 10, 10, 10)
        
        self.report_label = QLabel(report)
        self.report_label.setWordWrap(True)
        self.report_label.setFont(QFont("Microsoft YaHei", 9))
        self.report_label.setStyleSheet("color: #862e9c;") # 深紫色或深红色文字
        self.report_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        self.details_layout.addWidget(self.report_label)

        container_layout.addWidget(self.header_frame)
        container_layout.addWidget(self.details_frame)
        
        self.main_layout.addWidget(self.container)


# ---创建智能体工作小组处理工作线程---
class AgentsWorkgroupThread(QThread):
    """
        负责在后台运行的 LangGraph 工作小组逻辑
    """
    # 消息信号: (text, sender, msg_type)
    message_signal = pyqtSignal(str, str, str)
    
    # 新增信号
    thought_signal = pyqtSignal(str) # 思考内容
    init_steps_signal = pyqtSignal(list) # 初始化步骤列表
    update_step_signal = pyqtSignal(int, str, str) # 更新步骤状态 (index, status, result)
    final_response_signal = pyqtSignal(str) # 最终自然语言回复
    error_report_signal = pyqtSignal(str) # 错误报告弹窗
    
    remove_thinking_signal = pyqtSignal()
    create_msg_bar_signal = pyqtSignal(str)
    refresh_map_canvas_signal = pyqtSignal()

    # 下载进度信号: target_name, percent
    download_progress_signal = pyqtSignal(str, int)

    # 用于传递布局任务列表的信号
    layout_task_signal = pyqtSignal(list)
    # 停止信号
    stop_signal = pyqtSignal()

    def __init__(self, user_text, layers, parent=None):
        super().__init__(parent)
        self.user_text = user_text
        self.layers = layers
        # 用于接收主线程执行结果的变量
        self.layout_op_result = None
        self._is_stopped = False
        self.execution_log = [] # 记录执行日志用于总结

    def stop(self):
        """停止线程任务"""
        self._is_stopped = True
        self.stop_signal.emit()

    def emit_download_progress(self, target_name: str, percent: int):
        """发送下载进度信号"""
        self.download_progress_signal.emit(target_name, percent)

    def execute_layout_op(self, tasks):
        """执行布局操作（需在主线程运行）"""
        self.layout_op_result = None
        if self._is_stopped: return "任务已停止"
        
        # 发送布局任务信号
        self.layout_task_signal.emit(tasks)
        
        # 简单自旋锁等待主线程执行完成并获取结果
        while self.layout_op_result is None:
            if self._is_stopped: return "任务已停止"
            self.msleep(50)
            
        return self.layout_op_result
        
    def refresh_layers(self):
        """刷新并返回最新的图层列表"""
        if self._is_stopped: return []
        # 触发主线程刷新（UI）
        self.refresh_map_canvas_signal.emit()
        # 获取最新图层（注意：QgsProject 实例在多线程访问可能不安全，但读取通常还好）
        self.layers = list(QgsProject.instance().mapLayers().values())
        return self.layers

    def generate_final_summary(self, thought):
        """生成最终自然语言总结"""
        log_str = "\n".join(self.execution_log)
        prompt = FINAL_SUMMARY_PROMPT.format(
            user_request=self.user_text,
            thought=thought,
            execution_log=log_str
        )
        try:
            summary = call_qwen_with_prompt(prompt)
            return summary
        except Exception:
            return "任务已完成。"

    def generate_error_report(self, current_step, error_msg):
        """生成错误报告"""
        prompt = ERROR_REPORT_PROMPT.format(
            user_request=self.user_text,
            current_step=current_step,
            error_msg=error_msg
        )
        try:
            report = call_qwen_with_prompt(prompt)
            return report
        except Exception:
            return f"执行出错：{error_msg}"

    # 运行智能体工作小组
    def run(self):
        # 创建 Workflow Graph
        app = create_workflow_graph()

        # 初始状态
        inputs = {
            "user_request": self.user_text,
            "layers": self.layers,
            "task_plan": [],
            "current_step": 0,
            "current_task": "",
            "assigned_agent": "",
            "execution_result": None,
            "error": "",
            "is_gis_task": True,
            "thought": "",
            "executor": self
        }

        current_thought = ""
        task_plan = []

        try:
            # 使用 stream 模式运行
            config = {"recursion_limit": 150}
            for event in app.stream(inputs, config=config):
                if self._is_stopped:
                    self.message_signal.emit("用户已手动停止流程。", "ai", "text")
                    return

                for node_name, state_update in event.items():
                    if self._is_stopped: return
                    
                    # 错误处理
                    if "error" in state_update and state_update["error"]:
                        err_msg = state_update["error"]
                        current_step_info = f"步骤 {state_update.get('current_step', 0)+1}"
                        report = self.generate_error_report(current_step_info, err_msg)
                        self.error_report_signal.emit(report)
                        return 

                    # 处理 TaskPlanner 输出
                    if node_name == "task_planner":
                        # 无论是否是GIS任务，如果有思考内容，先发送思考
                        current_thought = state_update.get("thought", "")
                        if current_thought:
                             self.thought_signal.emit(current_thought)

                        if not state_update.get("is_gis_task", True):
                            # 非GIS任务，直接走普通对话
                            ai_response = chat_with_openai(self.user_text)
                            self.final_response_signal.emit(ai_response)
                            return 

                        # 发送计划步骤
                        task_plan = state_update.get("task_plan", [])
                        self.init_steps_signal.emit(task_plan)
                        
                        # 记录日志
                        self.execution_log.append(f"任务规划: {len(task_plan)} 个步骤")

                    # 2. Router Node (任务开始)
                    elif node_name == "task_router":
                        step_idx = state_update.get("current_step", 0)
                        task_desc = state_update.get("current_task", "")
                        
                        # 更新UI为"运行中"
                        self.update_step_signal.emit(step_idx, "running", "")
                        self.execution_log.append(f"步骤 {step_idx+1} 开始: {task_desc}")

                    # 3. Executor Node (任务完成)
                    elif node_name == "agent_executor":
                        result = state_update.get("execution_result", {})
                        step_idx = state_update.get("current_step", 0) # 这里还是当前的step index
                        
                        if result.get("is_process_complete"):
                            tool_res = result.get("tool_result", "完成")
                            self.update_step_signal.emit(step_idx, "success", tool_res)
                            self.execution_log.append(f"步骤 {step_idx+1} 成功: {tool_res}")
                            self.refresh_map_canvas_signal.emit()
                        else:
                            prob = result.get("possible_problem", "未知错误")
                            self.update_step_signal.emit(step_idx, "fail", prob)
                            # 触发错误弹窗
                            report = self.generate_error_report(f"第 {step_idx+1} 步", prob)
                            self.error_report_signal.emit(report)
                            return # 终止
                            
            # 流程正常结束
            if not self._is_stopped and task_plan:
                summary = self.generate_final_summary(current_thought)
                self.final_response_signal.emit(summary)

        except Exception as e:
            if not self._is_stopped:
                report = self.generate_error_report("系统内部错误", str(e))
                self.error_report_signal.emit(report)


class ChatBox(QObject):
    """
    逻辑控制器类
    """
    
    def __init__(self, dock_widget):
        super().__init__()
        self.dock_widget = dock_widget
        
        # 绑定 UI 控件
        self.scrollArea = dock_widget.scrollArea
        self.user_inputBox = dock_widget.user_inputBox
        self.send_button = dock_widget.send_button
        self.voice_btn = dock_widget.voice_btn
        self.stop_button = dock_widget.stop_button
        
        self.chat_container = dock_widget.scrollAreaWidgetContents
        if self.chat_container.layout() is None:
            self.chat_layout = QVBoxLayout(self.chat_container)
            self.chat_layout.setAlignment(Qt.AlignTop)
            self.chat_layout.setSpacing(20)
            self.chat_layout.setContentsMargins(20, 20, 20, 20)
        else:
            self.chat_layout = self.chat_container.layout()
            self.chat_layout.setAlignment(Qt.AlignTop)

        self.agents_workgroup = None
        self.current_step_widget = None # 当前的步骤组件引用
        self.current_thinking_bubble = None # 当前的思考组件引用
        
        self.setup_connections()

    def setup_connections(self):
        """绑定信号与槽"""
        # 发送按钮
        self.send_button.clicked.connect(self.send_message)
        # 停止按钮
        self.stop_button.clicked.connect(self.stop_process)
        # 语音按钮
        # self.voice_btn.clicked.connect(self.start_voice_input) 

        # 安装事件过滤器以处理 Enter/Shift+Enter
        self.user_inputBox.installEventFilter(self)

    def eventFilter(self, obj, event):
        """事件过滤器：处理键盘事件"""
        if obj == self.user_inputBox and event.type() == event.KeyPress:
            if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
                if event.modifiers() & Qt.ShiftModifier:
                    # Shift + Enter: 正常换行
                    return False
                else:
                    # 仅 Enter: 发送消息
                    self.send_message()
                    return True
        return super().eventFilter(obj, event)

    # --- UI 添加方法 ---
    def add_message(self, text, sender, msg_type="text", typing_effect=False):
        """添加一条消息气泡"""
        avatar = None
        # 如果是AI，这里可以指定头像路径
        if sender == "ai":
             avatar = os.path.join(os.path.dirname(__file__), 'chat_icon.png')
            
        bubble = ChatBubble(text, sender, avatar_path=avatar, typing_effect=typing_effect)
        self.chat_layout.addWidget(bubble)
        self.scroll_to_bottom()
        return bubble

    def scroll_to_bottom(self):
        """滚动到底部"""
        # 使用 QTimer 确保在 UI 刷新后执行滚动
        QTimer.singleShot(100, lambda: self.scrollArea.verticalScrollBar().setValue(
            self.scrollArea.verticalScrollBar().maximum()
        ))

    def add_step_widget(self, steps):
        """添加步骤进度组件"""
        if not steps:
            return
            
        # 思考气泡保留，不隐藏也不移除
        
        self.current_step_widget = StepProgressWidget(steps)
        self.chat_layout.addWidget(self.current_step_widget)
        self.scroll_to_bottom()

    def add_thinking_bubble(self, text):
        if self.current_thinking_bubble:
            # 如果已经有思考气泡，更新它
            self.current_thinking_bubble.set_text(text)
        else:
            # 否则创建新的
            self.current_thinking_bubble = ThinkingBubble(text)
            self.chat_layout.addWidget(self.current_thinking_bubble)
            self.scroll_to_bottom()
        return self.current_thinking_bubble

    def send_message(self):
        user_text = self.user_inputBox.toPlainText().strip()
        if not user_text:
            return

        self.add_message(user_text, "user")
        self.user_inputBox.clear()
        
        layers = list(QgsProject.instance().mapLayers().values())

        # 准备 UI
        self.send_button.setVisible(False)
        self.stop_button.setVisible(True)

        # 立即显示“正在思考中...”
        self.current_thinking_bubble = ThinkingBubble("正在思考中...")
        self.chat_layout.addWidget(self.current_thinking_bubble)
        self.scroll_to_bottom()

        # 启动线程
        self.agents_workgroup = AgentsWorkgroupThread(user_text, layers)
        
        # 绑定新信号
        self.agents_workgroup.thought_signal.connect(self.add_thinking_bubble)
        self.agents_workgroup.init_steps_signal.connect(self.add_step_widget)
        self.agents_workgroup.update_step_signal.connect(self.update_step_status)
        self.agents_workgroup.final_response_signal.connect(self.show_final_response)
        self.agents_workgroup.error_report_signal.connect(self.show_error_popup)
        
        self.agents_workgroup.message_signal.connect(self.receive_ai_message) # 兼容旧信号
        
        self.agents_workgroup.finished.connect(self.on_thread_finished)
        self.agents_workgroup.refresh_map_canvas_signal.connect(self.refresh_map_canvas)
        self.agents_workgroup.layout_task_signal.connect(self.handle_layout_tasks)
        self.agents_workgroup.download_progress_signal.connect(self.handle_download_progress)

        self.agents_workgroup.start()

    def stop_process(self):
        if self.agents_workgroup and self.agents_workgroup.isRunning():
            self.agents_workgroup.stop()
            self.stop_button.setEnabled(False)

    def on_thread_finished(self):
        self.stop_button.setVisible(False)
        self.stop_button.setEnabled(True)
        self.send_button.setVisible(True)
        self.agents_workgroup = None
        self.current_step_widget = None

    def handle_download_progress(self, target_name: str, percent: int):
        """处理子线程发来的下载进度，交由对应的进度组件处理"""
        if self.current_step_widget:
            self.current_step_widget.update_download_progress(target_name, percent)

    def handle_layout_tasks(self, tasks):
        results = []
        for req in tasks:
            res_msg = execute_layout_task(req)
            results.append(res_msg)
        final_msg = " | ".join(results)
        
        # 布局任务通常是最后一步，我们将结果写回给工作线程，方便后续处理或错误捕获
        if self.agents_workgroup:
            self.agents_workgroup.layout_op_result = final_msg
        
        self.refresh_map_canvas()

    def receive_ai_message(self, text, sender, msg_type="text"):
        # 仅处理普通文本，步骤信息已由专用组件处理
        if msg_type == "text":
            self.add_message(text, sender, msg_type)

    def update_step_status(self, index, status, result):
        if self.current_step_widget:
            self.current_step_widget.update_step_status(index, status, result)

    def show_final_response(self, text):
        self.add_message(text, "ai", typing_effect=True)

    def add_error_widget(self, report):
        """添加错误报告组件"""
        error_widget = ErrorWidget(report)
        self.chat_layout.addWidget(error_widget)
        self.scroll_to_bottom()

    def show_error_popup(self, report):
        # 兼容旧信号，改为直接添加 Widget
        self.add_error_widget(report)

    def auto_sort_layers(self):
        """
        自动排序图层树，将点图层放在最上面，线图层居中，面图层靠下，栅格最底层。
        """
        from qgis.core import QgsProject, QgsMapLayerType, QgsWkbTypes
        root = QgsProject.instance().layerTreeRoot()
        
        def get_weight(node):
            if hasattr(node, 'layer') and node.layer():
                layer = node.layer()
                if layer.type() == QgsMapLayerType.VectorLayer:
                    geom_type = layer.geometryType()
                    if geom_type == QgsWkbTypes.PointGeometry:
                        return 1
                    elif geom_type == QgsWkbTypes.LineGeometry:
                        return 2
                    elif geom_type == QgsWkbTypes.PolygonGeometry:
                        return 3
                    else:
                        return 4
                elif layer.type() == QgsMapLayerType.RasterLayer:
                    return 5
            return 10
            
        children = root.children()
        if not children:
            return
            
        nodes_with_weight = [(get_weight(node), i, node) for i, node in enumerate(children)]
        sorted_nodes = sorted(nodes_with_weight, key=lambda x: (x[0], x[1]))
        
        is_sorted = all(nodes_with_weight[i] == sorted_nodes[i] for i in range(len(children)))
        if is_sorted:
            return
            
        for _, _, node in sorted_nodes:
            clone = node.clone()
            root.addChildNode(clone)
            root.removeChildNode(node)

    def refresh_map_canvas(self):
        self.auto_sort_layers()
        if iface and iface.mapCanvas():
            iface.mapCanvas().refresh()

    def show_initial_message(self):
        self.add_message(INITIAL_MESSAGE, "ai")

    def on_recording_started(self):
        self.voice_btn.setStyleSheet("background-color: #ffcccc; border-radius: 16px; border: 1px solid red;")
        self.user_inputBox.setPlaceholderText("正在听...")

    def on_recording_stopped(self):
        self.voice_btn.setStyleSheet("background-color: transparent; border-radius: 16px; color: #666666;")
        self.user_inputBox.setPlaceholderText("给QGIS AI Mapper发送信息...")
        self.user_inputBox.setEnabled(False)

    def on_voice_text_received(self, text):
        self.user_inputBox.setReadOnly(False)
        self.user_inputBox.setEnabled(True)
        self.user_inputBox.setPlainText(text)
        cursor = self.user_inputBox.textCursor()
        cursor.movePosition(cursor.End)
        self.user_inputBox.setTextCursor(cursor)

    def on_voice_error(self, error_msg):
        self.user_inputBox.setReadOnly(False)
        self.user_inputBox.setEnabled(True)
        self.user_inputBox.setPlaceholderText(f"错误: {error_msg}")


def create_msg_bar(msg, level=Qgis.Info):
    bar = iface.messageBar()
    widget = bar.createMessage("AI助手", msg)
    bar.pushWidget(widget, level, 7)
