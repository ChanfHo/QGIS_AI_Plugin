"""Presentation widgets; no workflow or QGIS execution dependencies."""
from ..core.localization import t
import os
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QPushButton,
    QSizePolicy,
    QProgressBar,
    QStylePainter,
    QStyleOptionButton,
    QStyle,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRect, QSize
from PyQt5.QtGui import QFont, QPainter, QPainterPath, QColor, QPixmap, QPalette
from ..core.error_handling import format_user_report, format_technical_report

class WrappedButton(QPushButton):
    """Wrap recovery actions without changing their signals or labels."""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        policy = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMinimumWidth(0)
        self.setCursor(Qt.PointingHandCursor)

    def heightForWidth(self, width):
        bounds = self.fontMetrics().boundingRect(
            QRect(0, 0, max(20, width - 24), 1000),
            Qt.AlignCenter | Qt.TextWordWrap, self.text())
        return max(36, bounds.height() + 16)

    def sizeHint(self):
        return QSize(180, self.heightForWidth(max(80, self.width())))

    def minimumSizeHint(self):
        return QSize(0, 36)

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        text = option.text
        option.text = ""
        painter.drawControl(QStyle.CE_PushButton, option)
        painter.setPen(option.palette.color(QPalette.ButtonText))
        painter.drawText(self.rect().adjusted(10, 6, -10, -6),
                         Qt.AlignCenter | Qt.TextWordWrap, text)

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
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)
        self.avatar_label = QLabel()
        avatar_size = 28
        self.avatar_label.setFixedSize(avatar_size, avatar_size)
        if self.avatar_path and os.path.exists(self.avatar_path):
            pixmap = QPixmap(self.avatar_path)
        else:
            pixmap = QPixmap(avatar_size, avatar_size)
            pixmap.fill(QColor("#10a37f" if self.sender == "ai" else "#8e8e8e"))
        rounded = QPixmap(avatar_size, avatar_size)
        rounded.fill(Qt.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addEllipse(0, 0, avatar_size, avatar_size)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, avatar_size, avatar_size, pixmap)
        painter.end()
        self.avatar_label.setPixmap(rounded)
        self.bubble_frame = QFrame()
        self.bubble_frame.setObjectName("messageBubble")
        bubble_layout = QVBoxLayout(self.bubble_frame)
        bubble_layout.setContentsMargins(10, 4, 10, 6)
        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setFont(QFont("Microsoft YaHei", 10))
        self.message_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.message_label.setTextFormat(Qt.PlainText)
        self.message_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.message_label.setMinimumWidth(0)
        bubble_layout.addWidget(self.message_label)
        self.bubble_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if self.sender == "user":
            self.bubble_frame.setStyleSheet(
                "QFrame#messageBubble {background:#edf5f2;border-radius:10px;}"
                "QLabel {background:transparent;color:#1f2937;border:0;}")
            layout.addSpacing(24)
            layout.addWidget(self.bubble_frame, 1)
            layout.addWidget(self.avatar_label, 0, Qt.AlignTop)
        else:
            self.bubble_frame.setStyleSheet(
                "QFrame#messageBubble {background:transparent;border:0;}"
                "QLabel {background:transparent;color:#1f2937;border:0;}")
            layout.addWidget(self.avatar_label, 0, Qt.AlignTop)
            layout.addWidget(self.bubble_frame, 1)

    def start_typing(self):
        if hasattr(self, 'typing_timer'):
            self.typing_timer.stop()
            self.typing_timer.deleteLater()
        self.typing_timer = QTimer(self)
        self.typing_timer.timeout.connect(self.update_text)
        self.typing_timer.start(30) # Typing speed: 30 ms per character.

    def update_text(self):
        if len(self.current_text) < len(self.full_text):
            self.current_text += self.full_text[len(self.current_text)]
            self.message_label.setText(self.current_text)
            self.message_label.updateGeometry()
        else:
            self.typing_timer.stop()


# Reasoning bubble with a typing effect.
class ThinkingBubble(QWidget):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.full_text = text
        self.current_text = ""
        self.init_ui()
        if text and text != t('Thinking...'):
            self.start_typing()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(0)
        
        # Reasoning content container.
        content_frame = QFrame()
        content_frame.setStyleSheet("""
            QFrame#statusCard {
                background-color: transparent;
                border: none;
            }
        """)
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(10, 8, 10, 8)
        
        # Reasoning text.
        self.text_label = QLabel(self.full_text if self.full_text == t('Thinking...') else "")
        self.text_label.setWordWrap(True)
        self.text_label.setFont(QFont("Consolas", 9, QFont.StyleItalic))
        self.text_label.setStyleSheet("color: #6c757d; border: none;")
        self.text_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
        
        content_layout.addWidget(self.text_label)
        
        # Collapse button.
        self.toggle_btn = QPushButton(t('Hide reasoning ▲'))
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
        self.toggle_btn.setVisible(False) # Hide initially; show when actual content is available.

        self.content_frame = content_frame
        
        layout.addWidget(content_frame)
        layout.addWidget(self.toggle_btn)

    def set_text(self, text):
        """Update reasoning content and start typing."""
        self.full_text = text
        self.current_text = ""
        self.text_label.setText("")
        self.toggle_btn.setVisible(True)
        self.start_typing()

    def toggle_content(self):
        visible = not self.content_frame.isVisible()
        self.content_frame.setVisible(visible)
        self.toggle_btn.setText(t('Hide reasoning ▲') if visible else t('Show reasoning ▼'))

    def start_typing(self):
        if hasattr(self, 'typing_timer'):
            self.typing_timer.stop()
            self.typing_timer.deleteLater()
        self.typing_timer = QTimer(self)
        self.typing_timer.timeout.connect(self.update_text)
        self.typing_timer.start(20) # Use a slightly faster reasoning typing speed.

    def update_text(self):
        if len(self.current_text) < len(self.full_text):
            self.current_text += self.full_text[len(self.current_text)]
            self.text_label.setText(self.current_text)
            self.text_label.updateGeometry()
        else:
            self.typing_timer.stop()


# Step progress component with a rotating header and collapsible details.
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

        # 1. Container frame.
        self.container = QFrame()
        self.container.setObjectName("statusCard")
        self.container.setStyleSheet("""
            QFrame#statusCard {
                background-color: #ffffff;
                border: 1px solid #e9ecef;
                border-radius: 6px;
            }
        """)
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # 2. Always-visible header showing the current step.
        self.header_frame = QFrame()
        self.header_frame.setObjectName("progressHeader")
        self.header_frame.setStyleSheet("QFrame#progressHeader {background-color:#edf5f2; border-top-left-radius:6px; border-top-right-radius:6px;}")
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(10, 8, 10, 8)

        self.status_icon = QLabel("⏳") 
        self.status_text = QLabel(t('Initializing task...'))
        self.status_text.setWordWrap(True)
        self.status_text.setMinimumWidth(0)
        self.status_text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.status_text.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
        self.status_text.setStyleSheet("color: #245c4a;")
        
        self.toggle_btn = QPushButton(t('Show details ▼'))
        self.toggle_btn.setFlat(True)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.setStyleSheet("color: #666; font-size: 10px; text-align: right;")
        self.toggle_btn.clicked.connect(self.toggle_details)

        header_layout.addWidget(self.status_icon)
        header_layout.addWidget(self.status_text, 1)
        header_layout.addWidget(self.toggle_btn)

        # 3. Details list, hidden by default.
        self.details_frame = QFrame()
        self.details_frame.setVisible(False)
        self.details_layout = QVBoxLayout(self.details_frame)
        self.details_layout.setContentsMargins(10, 5, 10, 10)
        self.details_layout.setSpacing(5)

        # Initialize step list entries.
        self.step_labels = []
        self.step_progress_bars = [] # Store each step's progress component, including label and progress bar.
        
        for i, step in enumerate(self.steps):
            # Step container.
            step_container = QWidget()
            step_layout = QVBoxLayout(step_container)
            step_layout.setContentsMargins(0, 0, 0, 0)
            step_layout.setSpacing(2)
            
            # Step text label.
            lbl = QLabel(f"{i+1}. {step['task']}")
            lbl.setFont(QFont("Microsoft YaHei", 9))
            lbl.setStyleSheet("color: #adb5bd;") # Default gray.
            lbl.setWordWrap(True)
            
            # Progress container, hidden by default.
            progress_widget = QWidget()
            progress_layout = QVBoxLayout(progress_widget)
            progress_layout.setContentsMargins(15, 0, 0, 0) # Indent slightly.
            progress_layout.setSpacing(2)
            
            target_lbl = QLabel("")
            target_lbl.setWordWrap(True)
            target_lbl.setMinimumWidth(0)
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
            p_bar.setTextVisible(False) # Hide built-in text because the bar is too narrow.
            
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
        self.toggle_btn.setText(t('Hide details ▲') if visible else t('Show details ▼'))

    def update_step_status(self, index, status, result_text=None):
        """
        status: 'running', 'success', 'waiting', 'fail'
        """
        if index < 0 or index >= len(self.steps):
            return
        
        self.current_step_index = index
        task_name = self.steps[index]['task']
        total_steps = len(self.steps)
        completed_steps = sum(1 for step in self.steps[:index] if True) # Simple calculation; it should actually depend on status.
        if status == 'success':
            completed_steps += 1
        
        # Update the rotating header.
        if status == 'running':
            self.status_icon.setText("🔄")
            self.status_text.setText(t('{v0} steps, {v1}/{v2} completed; step {v3} is running', v0=total_steps, v1=index, v2=total_steps, v3=index + 1))
            self.step_labels[index].setStyleSheet("color: #007bff; font-weight: bold;")
            self.step_labels[index].setText(t('➤ {v0}. {v1} (running...)', v0=index + 1, v1=task_name))
        elif status == 'success':
            self.status_icon.setText("✅")
            self.status_text.setText(t('{v0} steps, {v1}/{v2} completed; step {v3} succeeded', v0=total_steps, v1=index + 1, v2=total_steps, v3=index + 1))
            self.step_labels[index].setStyleSheet("color: #28a745;")
            self.step_labels[index].setText(f"✔ {index+1}. {task_name}")
            # Hide the progress bar after success.
            if index < len(self.step_progress_bars):
                self.step_progress_bars[index]["widget"].setVisible(False)
        elif status == 'fail':
            self.status_icon.setText("❌")
            self.status_text.setText(t('{v0} steps, {v1}/{v2} completed; step {v3} stopped', v0=total_steps, v1=index, v2=total_steps, v3=index + 1))
            self.step_labels[index].setStyleSheet("color: #dc3545;")
            self.step_labels[index].setText(f"✘ {index+1}. {task_name} - {result_text}")
            # Hide the progress bar after failure.
            if index < len(self.step_progress_bars):
                self.step_progress_bars[index]["widget"].setVisible(False)
        elif status in ('waiting', 'waiting_retry'):
            self.status_icon.setText("⚠️")
            waiting_text = t('Waiting for retry') if status == 'waiting_retry' else t('Waiting for parameters')
            self.status_text.setText(t('{v0} steps; step {v1}: {v2}', v0=total_steps, v1=index + 1, v2=waiting_text))
            self.step_labels[index].setStyleSheet("color: #e67700; font-weight: bold;")
            self.step_labels[index].setText(f"⚠ {index+1}. {task_name} - {result_text}")
            if index < len(self.step_progress_bars):
                self.step_progress_bars[index]["widget"].setVisible(False)

    def update_download_progress(self, target_name: str, percent: int):
        """Update download progress for the current step."""
        idx = self.current_step_index
        if idx >= 0 and idx < len(self.step_progress_bars):
            p_data = self.step_progress_bars[idx]
            
            # Show details and expand the progress bar for a new download or first display.
            if not p_data["widget"].isVisible():
                p_data["widget"].setVisible(True)
                # Expand details automatically so users can see the progress bar.
                if not self.details_frame.isVisible():
                    self.toggle_details()
                    
            p_data["label"].setText(t('Downloading: {v0} ({v1}%)', v0=target_name, v1=percent))
            p_data["bar"].setValue(percent)
            
            # At 100%, keep visible briefly before resetting/hiding for a smooth transition.
            if percent >= 100:
                # Keep visible until success; the text may indicate completion first.
                p_data["label"].setText(t('Download completed: {v0}', v0=target_name))


# Embedded error display component.
class ErrorWidget(QWidget):
    resume_requested = pyqtSignal(dict)
    new_task_requested = pyqtSignal(dict)

    def __init__(self, error_report, parent=None):
        super().__init__(parent)
        self.error_state = error_report if isinstance(error_report, dict) else {}
        if self.error_state:
            error_report = format_user_report(self.error_state)
        self.init_ui(error_report)

    def init_ui(self, report):
        self.action_buttons = []
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 5, 0, 5)
        self.main_layout.setSpacing(0)

        # Container frame.
        self.container = QFrame()
        self.container.setObjectName("statusCard")
        self.container.setStyleSheet("""
            QFrame#statusCard {
                background-color: #fff5f5;
                border: 1px solid #ffc9c9;
                border-radius: 6px;
            }
        """)
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # Always-visible error warning header.
        self.header_frame = QFrame()
        self.header_frame.setObjectName("errorHeader")
        self.header_frame.setStyleSheet("""
            QFrame#errorHeader {
            background-color: #ffe3e3; 
            border-top-left-radius: 6px; 
            border-top-right-radius: 6px;
            border-bottom: 1px solid #ffc9c9;
            }
        """)
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(10, 8, 10, 8)

        self.status_icon = QLabel("⚠️") 
        self.status_icon.setFont(QFont("Segoe UI Emoji", 12))
        self.status_text = QLabel(t('Task execution encountered an error'))
        self.status_text.setWordWrap(True)
        self.status_text.setMinimumWidth(0)
        self.status_text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.status_text.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
        self.status_text.setStyleSheet("color: #c92a2a;")
        
        header_layout.addWidget(self.status_icon)
        header_layout.addWidget(self.status_text, 1)

        # Details area.
        self.details_frame = QFrame()
        self.details_layout = QVBoxLayout(self.details_frame)
        self.details_layout.setContentsMargins(10, 10, 10, 10)
        
        self.report_label = QLabel(report)
        self.report_label.setTextFormat(Qt.PlainText)
        self.report_label.setWordWrap(True)
        self.report_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.report_label.setFont(QFont("Microsoft YaHei", 9))
        self.report_label.setStyleSheet("color: #475569;")
        self.report_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        self.details_layout.addWidget(self.report_label)
        if self.error_state:
            details = QLabel(format_technical_report(self.error_state))
            details.setTextFormat(Qt.PlainText)
            details.setWordWrap(True)
            details.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            details.setVisible(False)
            toggle = WrappedButton(t('Show technical details and context'))
            self.action_buttons.append((toggle, 'Show technical details and context'))
            toggle.clicked.connect(lambda: details.setVisible(details.isHidden()))
            self.details_layout.addWidget(toggle)
            self.details_layout.addWidget(details)
            if self.error_state.get("can_continue"):
                resume = WrappedButton(t('Resume current step / retry after adding information'))
                self.action_buttons.append((resume, 'Resume current step / retry after adding information'))
                resume.setProperty("requires_api_key", True)
                resume.clicked.connect(lambda: self.resume_requested.emit({
                    "resume_token": self.error_state.get("resume_token"),
                    "task_id": self.error_state.get("task_id")}))
                self.details_layout.addWidget(resume)
            new_task = WrappedButton(t('End this task and start a new task'))
            self.action_buttons.append((new_task, 'End this task and start a new task'))
            new_task.setProperty("requires_api_key", True)
            new_task.clicked.connect(lambda: self.new_task_requested.emit({
                "resume_token": self.error_state.get("resume_token")}))
            self.details_layout.addWidget(new_task)

        container_layout.addWidget(self.header_frame)
        container_layout.addWidget(self.details_frame)
        
        self.main_layout.addWidget(self.container)

    def retranslate_actions(self):
        for button, source in self.action_buttons:
            button.setText(t(source))
        self.status_text.setText(t('Task execution encountered an error'))


