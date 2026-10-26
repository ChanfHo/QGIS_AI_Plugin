"""Coordinate authentication, presentation, and existing task actions."""
from ..core.localization import t, install_language, split_new_task, SETTING
import os
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel
from PyQt5.QtCore import Qt, QTimer, QObject, QEvent
from qgis.utils import iface
from qgis.core import QgsProject
from ..services.credentials import session
from .api_key_dialog import ApiKeyDialog
from ..cartography.layout_management import execute_layout_task
from ..core.error_handling import failure
from ..workflow.recovery_session import PENDING_SESSIONS, resume_session
from .chat_widgets import ChatBubble, ThinkingBubble, StepProgressWidget, ErrorWidget
from ..workflow.workflow_worker import AgentsWorkgroupThread
from .chat_view import configure_chat_view, resize_composer
from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtWidgets import QComboBox

INITIAL_MESSAGE = 'Hello! I am your QGIS mapping assistant. Ask me about any QGIS mapping task. For example:\n1. Draw a general map of Hubei Province;\n2. Load Wuhan administrative boundaries;\n3. Set the river layer style to blue;\n'

os.environ['NO_PROXY'] = 'dashscope.aliyuncs.com'

class ChatBox(QObject):
    """Chat logic controller."""
    
    def __init__(self, dock_widget):
        super().__init__()
        self.dock_widget = dock_widget
        
        # Bind UI controls.
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
        self.current_step_widget = None # Current step component reference.
        self.current_thinking_bubble = None # Current reasoning component reference.
        self.session_key = id(QgsProject.instance())
        self.pending_recovery_state = PENDING_SESSIONS.get(self.session_key)
        QgsProject.instance().cleared.connect(self.clear_recovery_session)
        
        configure_chat_view(self)
        self.setup_connections()
        self.key_button = QPushButton(t('Configure / change API Key'))
        self.auth_status = QLabel()
        self.auth_status.setWordWrap(True)
        bar = QWidget(dock_widget)
        row = QVBoxLayout(bar)
        row.addWidget(self.auth_status)
        row.addWidget(self.key_button)
        self.language_selector = QComboBox()
        for label, value in (("Follow QGIS / 跟随QGIS", "auto"), ("中文", "zh"), ("English", "en")):
            self.language_selector.addItem(label, value)
        self.language_selector.setCurrentIndex(max(0, self.language_selector.findData(QSettings().value(SETTING, "auto"))))
        self.language_selector.currentIndexChanged.connect(self.change_language)
        row.addWidget(self.language_selector)
        dock_widget.verticalLayout.insertWidget(0, bar)
        self.key_button.setObjectName('apiKeyButton')
        self.auth_status.setObjectName('authStatus')
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(6)
        self.key_button.clicked.connect(self.configure_api_key)
        self.refresh_auth_state()
        self.auth_timer = QTimer(self)
        self.auth_timer.setInterval(500)
        self.auth_timer.timeout.connect(self.refresh_auth_state)
        self.auth_timer.start()

    def configure_api_key(self):
        if self.agents_workgroup and self.agents_workgroup.isRunning():
            return
        dialog = ApiKeyDialog(self.dock_widget)
        self.refresh_auth_state()
        dialog.exec_()
        self.language_selector.blockSignals(True)
        self.language_selector.setCurrentIndex(max(0, self.language_selector.findData(QSettings().value(SETTING, 'auto'))))
        self.language_selector.blockSignals(False)
        self.change_language()

    def change_language(self):
        install_language(self.language_selector.currentData())
        self.dock_widget.retranslateUi(self.dock_widget)
        configure_chat_view(self)
        self.key_button.setText(t('Configure / change API Key'))
        if hasattr(self, "initial_bubble"):
            self.initial_bubble.full_text = t(INITIAL_MESSAGE)
            self.initial_bubble.message_label.setText(self.initial_bubble.full_text)
        for card in self.chat_container.findChildren(ErrorWidget):
            card.retranslate_actions()
        self.refresh_auth_state()

    def refresh_auth_state(self):
        ready = session.ready
        busy = bool(self.agents_workgroup and self.agents_workgroup.isRunning())
        self.user_inputBox.setEnabled(ready)
        self.send_button.setEnabled(ready)
        self.voice_btn.setEnabled(False)
        self.voice_btn.setToolTip(t('Voice input is not enabled in this version'))
        self.key_button.setEnabled(not busy)
        self.language_selector.setEnabled(not busy)
        for button in self.chat_container.findChildren(QPushButton):
            if button.property("requires_api_key"):
                button.setEnabled(ready and not busy)
        self.auth_status.setText(t('API Key verified (valid for this loading session)') if ready else
                                 t('Configure and verify an API Key to use chat and tasks.'))

    def setup_connections(self):
        """Connect signals and slots."""
        # Send button.
        self.send_button.clicked.connect(self.send_message)
        # Stop button.
        self.stop_button.clicked.connect(self.stop_process)

        # Install the event filter for Enter/Shift+Enter.
        self.user_inputBox.installEventFilter(self)
        self.user_inputBox.textChanged.connect(lambda: resize_composer(self.user_inputBox))

    def eventFilter(self, obj, event):
        """Handle keyboard events in the event filter."""
        if obj == self.user_inputBox and event.type() == QEvent.Resize:
            resize_composer(self.user_inputBox)
        if obj == self.user_inputBox and event.type() == event.KeyPress:
            if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
                if event.modifiers() & Qt.ShiftModifier:
                    # Shift+Enter inserts a normal line break.
                    return False
                else:
                    # Enter alone sends the message.
                    self.send_message()
                    return True
        return super().eventFilter(obj, event)

    # UI insertion methods.
    def add_message(self, text, sender, msg_type="text", typing_effect=False):
        """Add a message bubble."""
        avatar = None
        # Set the avatar path here for AI messages.
        if sender == "ai":
             avatar = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets', 'chat_icon.png')
            
        bubble = ChatBubble(text, sender, avatar_path=avatar, typing_effect=typing_effect)
        self.chat_layout.addWidget(bubble)
        self.scroll_to_bottom()
        return bubble

    def scroll_to_bottom(self):
        """Scroll to the bottom."""
        # Use QTimer to scroll after the UI refreshes.
        QTimer.singleShot(100, lambda: self.scrollArea.verticalScrollBar().setValue(
            self.scrollArea.verticalScrollBar().maximum()
        ))

    def add_step_widget(self, steps):
        """Add a step progress component."""
        if not steps:
            return
            
        # Keep the reasoning bubble visible and do not remove it.
        
        self.current_step_widget = StepProgressWidget(steps)
        self.chat_layout.addWidget(self.current_step_widget)
        self.scroll_to_bottom()

    def add_thinking_bubble(self, text):
        if self.current_thinking_bubble:
            # Update the existing reasoning bubble if present.
            self.current_thinking_bubble.set_text(text)
        else:
            # Otherwise create a new one.
            self.current_thinking_bubble = ThinkingBubble(text)
            self.chat_layout.addWidget(self.current_thinking_bubble)
            self.scroll_to_bottom()
        return self.current_thinking_bubble

    def send_message(self):
        if not session.ready:
            self.refresh_auth_state()
            return
        if self.agents_workgroup and self.agents_workgroup.isRunning():
            return
        user_text = self.user_inputBox.toPlainText().strip()
        if not user_text:
            return

        is_new_task, task_text = split_new_task(user_text)
        if is_new_task:
            self.clear_recovery_session()
            user_text = task_text
            if not user_text:
                return
        resume_state = None
        if self.pending_recovery_state:
            resume_state = resume_session(self.pending_recovery_state, user_text,
                                           self.pending_recovery_state["resume_token"])

        self.add_message(user_text, "user")
        self.user_inputBox.clear()
        
        layers = list(QgsProject.instance().mapLayers().values())

        # Prepare the UI.
        self.send_button.setVisible(False)
        self.stop_button.setVisible(True)

        # Show the thinking placeholder immediately.
        self.current_thinking_bubble = ThinkingBubble(t('Thinking...'))
        self.chat_layout.addWidget(self.current_thinking_bubble)
        self.scroll_to_bottom()

        # Start the thread.
        self.agents_workgroup = AgentsWorkgroupThread(user_text, layers, resume_state)
        
        # Connect the new signals.
        self.agents_workgroup.thought_signal.connect(self.add_thinking_bubble)
        self.agents_workgroup.init_steps_signal.connect(self.add_step_widget)
        self.agents_workgroup.update_step_signal.connect(self.update_step_status)
        self.agents_workgroup.final_response_signal.connect(self.show_final_response)
        self.agents_workgroup.error_report_signal.connect(self.show_error_popup)
        self.agents_workgroup.recovery_state_signal.connect(self.store_recovery_state)
        
        self.agents_workgroup.message_signal.connect(self.receive_ai_message) # Support the legacy signal.
        
        self.agents_workgroup.finished.connect(self.on_thread_finished)
        self.agents_workgroup.refresh_map_canvas_signal.connect(self.refresh_map_canvas)
        self.agents_workgroup.layout_task_signal.connect(self.handle_layout_tasks)
        self.agents_workgroup.download_progress_signal.connect(self.handle_download_progress)

        self.agents_workgroup.start()
        self.refresh_auth_state()

    def stop_process(self):
        self.clear_recovery_session()
        if self.agents_workgroup and self.agents_workgroup.isRunning():
            self.agents_workgroup.stop()
            self.stop_button.setEnabled(False)

    def on_thread_finished(self):
        self.stop_button.setVisible(False)
        self.stop_button.setEnabled(True)
        self.send_button.setVisible(True)
        self.agents_workgroup = None
        self.current_step_widget = None
        self.refresh_auth_state()

    def handle_download_progress(self, target_name: str, percent: int):
        """Forward worker download progress to its progress component."""
        if self.current_step_widget:
            self.current_step_widget.update_download_progress(target_name, percent)

    def handle_layout_tasks(self, tasks):
        results = []
        worker = self.agents_workgroup
        if not worker or worker._is_stopped:
            return
        completed = worker.layout_operation_results
        if completed and (len(tasks) <= len(completed) or any(
                tasks[i] != item["request"] for i, item in enumerate(completed))):
            worker.layout_op_result = failure("INVALID_CONTRACT", "agent_d",
                                               t('The recovery plan changed completed layout operations. Modify only the failed request.'))
            return
        final_msg = None
        for index, req in enumerate(tasks):
            if worker._is_stopped:
                final_msg = failure("USER_CANCELLED", "agent_d", t('Task stopped by the user'))
                break
            if index < len(completed):
                results.append(completed[index]["result"])
                continue
            res_msg = execute_layout_task(req)
            if isinstance(res_msg, dict):
                final_msg = res_msg
                break
            results.append(res_msg)
            completed.append({"request": req, "result": res_msg})
        if final_msg is None:
            final_msg = " | ".join(results)
        
        # Layout tasks are usually last; return their result to the worker for subsequent handling or error capture.
        if self.agents_workgroup:
            self.agents_workgroup.layout_op_result = final_msg
        
        self.refresh_map_canvas()

    def receive_ai_message(self, text, sender, msg_type="text"):
        # Handle plain text only; dedicated components handle steps.
        if msg_type == "text":
            self.add_message(text, sender, msg_type)

    def update_step_status(self, index, status, result):
        if self.current_step_widget:
            self.current_step_widget.update_step_status(index, status, result)

    def show_final_response(self, text):
        self.clear_recovery_session()
        self.add_message(text, "ai", typing_effect=True)

    def store_recovery_state(self, state):
        """Save the task checkpoint for the next message."""
        if self.agents_workgroup and self.agents_workgroup._is_stopped:
            return
        self.pending_recovery_state = state or None
        if state:
            PENDING_SESSIONS[self.session_key] = state
        else:
            PENDING_SESSIONS.pop(self.session_key, None)

    def clear_recovery_session(self):
        """Clear checkpoints only on success, cancellation or an explicit new task."""
        self.pending_recovery_state = None
        PENDING_SESSIONS.pop(self.session_key, None)

    def start_new_task(self, request=None):
        if not session.ready:
            return
        if self.agents_workgroup and self.agents_workgroup.isRunning():
            return
        if request and self.pending_recovery_state and request.get("resume_token") != self.pending_recovery_state.get("resume_token"):
            return
        self.clear_recovery_session()
        self.user_inputBox.setFocus()

    def resume_from_card(self, request):
        """Allow recovery buttons to act only on the currently valid checkpoint."""
        if not session.ready:
            return
        state = self.pending_recovery_state
        if not state or request.get("resume_token") != state.get("resume_token"):
            self.add_message(t('This recovery entry has expired. Use the latest error card.'), "ai")
            return
        if not self.user_inputBox.toPlainText().strip():
            self.user_inputBox.setPlainText(t("Retry current step"))
        self.send_message()

    def add_error_widget(self, report):
        """Add an error report component."""
        error_widget = ErrorWidget(report)
        error_widget.resume_requested.connect(self.resume_from_card)
        error_widget.new_task_requested.connect(self.start_new_task)
        self.chat_layout.addWidget(error_widget)
        self.refresh_auth_state()
        self.scroll_to_bottom()

    def show_error_popup(self, report):
        # Support the legacy signal by inserting a widget directly.
        self.add_error_widget(report)

    def auto_sort_layers(self):
        """Sort layers with points on top, then lines, polygons and rasters at the bottom."""
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
        self.initial_bubble = self.add_message(t(INITIAL_MESSAGE), "ai")
