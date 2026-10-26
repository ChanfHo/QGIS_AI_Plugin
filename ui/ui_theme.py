"""Plugin-local styles shared by the dock and credential dialog."""

CONTROLS = """
QPushButton { min-height:28px; padding:3px 9px; border:1px solid #d8e2df;
    border-radius:7px; background:#ffffff; color:#334155; }
QPushButton:hover { background:#edf5f2; border-color:#8abbaa; }
QPushButton:pressed { background:#dcece5; }
QPushButton:disabled { color:#9ca3af; background:#f3f4f6; border-color:#e5e7eb; }
QPushButton:focus { border:1px solid #10a37f; }
QLineEdit { min-height:30px; padding:4px 8px; border:1px solid #d8e2df; border-radius:6px; }
QLineEdit:focus { border-color:#10a37f; }
QTextEdit:focus { selection-background-color:#bce5d8; }
QScrollBar:vertical { width:7px; background:transparent; margin:0; }
QScrollBar::handle:vertical { min-height:28px; background:#cbd5d1; border-radius:3px; }
QScrollBar::handle:vertical:hover { background:#91aca2; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical { background:transparent; }
"""

CHAT_STYLE = """
QDockWidget#qgisAiMapperDock { background:#ffffff; color:#1f2937; }
QDockWidget#qgisAiMapperDock QWidget#dockWidgetContents { background:#ffffff; }
QDockWidget#qgisAiMapperDock QLabel#authStatus { color:#64748b; font-size:11px; }
QDockWidget#qgisAiMapperDock QPushButton#apiKeyButton { text-align:left; }
""" + CONTROLS

DIALOG_STYLE = "QDialog#mapperKeyDialog {background:#ffffff;}" + CONTROLS
