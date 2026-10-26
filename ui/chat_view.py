"""Configure presentation without connecting business actions."""
from ..core.localization import t

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTextEdit
from .ui_theme import CHAT_STYLE


def configure_chat_view(controller):
    dock = controller.dock_widget
    dock.setObjectName("qgisAiMapperDock")
    dock.setStyleSheet(CHAT_STYLE)
    dock.setMinimumWidth(260)
    controller.chat_layout.setContentsMargins(12, 14, 12, 14)
    controller.chat_layout.setSpacing(10)
    controller.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    controller.scrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    controller.user_inputBox.setAcceptRichText(False)
    controller.user_inputBox.setLineWrapMode(QTextEdit.WidgetWidth)
    controller.user_inputBox.setPlaceholderText(t('Describe your QGIS task…'))
    controller.user_inputBox.setToolTip(t('Enter to send, Shift+Enter for a new line'))
    dock.horizontalLayout.setContentsMargins(10, 8, 10, 12)
    dock.horizontalLayout_2.setContentsMargins(10, 6, 6, 6)
    dock.horizontalLayout_2.setSpacing(5)
    for button in (controller.send_button, controller.stop_button, controller.voice_btn):
        button.setAccessibleName(button.toolTip())
    resize_composer(controller.user_inputBox)


def resize_composer(editor):
    editor.document().setTextWidth(max(20, editor.viewport().width()))
    height = int(editor.document().size().height()) + 16
    editor.setFixedHeight(max(44, min(120, height)))
    editor.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
