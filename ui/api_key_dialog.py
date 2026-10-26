"""Validate credentials off the GUI thread and store only protected bytes."""
from ..core.localization import t, install_language, SETTING, canonical_message

from qgis.PyQt.QtCore import QStandardPaths, QThread, pyqtSignal, QSettings
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QComboBox,
)

from .ui_theme import DIALOG_STYLE
from ..services.credentials import CredentialError, ProtectedKeyStore, session

_pending_workers = set()


def _release_worker(worker):
    _pending_workers.discard(worker)
    worker.deleteLater()


def key_store():
    root = QStandardPaths.writableLocation(QStandardPaths.GenericConfigLocation)
    if not root:
        raise OSError("Application configuration directory is unavailable")
    return ProtectedKeyStore(root + "/QGIS-AI-Mapper")


class ValidationThread(QThread):
    completed = pyqtSignal(bool, str)

    def __init__(self, key, parent=None):
        super().__init__(parent)
        self.key = key

    def run(self):
        try:
            from ..services.chat_model import validate_api_key
            validate_api_key(self.key)
            self.completed.emit(True, t('Text model verified. Embedding, vision and ASR permissions will be checked separately when used.'))
        except CredentialError as exc:
            self.completed.emit(False, t(str(exc)))
        except Exception:
            self.completed.emit(False, t('Verification did not finish. Check the network, model configuration and dependencies.'))
        finally:
            self.key = ""


class ApiKeyDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t('QGIS-AI-Mapper: API Key Configuration'))
        self.setObjectName('mapperKeyDialog')
        self.setStyleSheet(DIALOG_STYLE)
        self.setMinimumWidth(360)
        self.resize(480, 300)
        self.worker = None
        self.validated_key = ""
        self.generation = None
        self.memory_only = False
        session.reset()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        self.notice = QLabel(t('This plugin uses Qwen models. Enter and verify your Qwen API Key each time the plugin loads; it is reused throughout that loading session.\nVisit https://platform.qianwenai.com/ to configure your personal Qwen API Key.'))
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.language_selector = QComboBox()
        for label, value in (("Follow QGIS / 跟随QGIS", "auto"), ("中文", "zh"), ("English", "en")):
            self.language_selector.addItem(label, value)
        self.language_selector.setCurrentIndex(max(0, self.language_selector.findData(QSettings().value(SETTING, "auto"))))
        self.language_selector.currentIndexChanged.connect(self.change_language)
        layout.addWidget(self.language_selector)
        self.input = QLineEdit()
        self.input.setEchoMode(QLineEdit.Password)
        self.input.setPlaceholderText(t('Enter API Key'))
        layout.addWidget(self.input)
        self.visible = QCheckBox(t('Show API Key'))
        self.visible.toggled.connect(lambda value: self.input.setEchoMode(
            QLineEdit.Normal if value else QLineEdit.Password))
        layout.addWidget(self.visible)
        self.status = QLabel(t('Not verified'))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.verify = QPushButton(t('Verify'))
        self.save = QPushButton(t('Save and enable'))
        self.clear = QPushButton(t('Clear Key'))
        self.cancel = QPushButton(t('Cancel'))
        for button in (self.verify, self.save, self.clear, self.cancel):
            row.addWidget(button)
        self.save.setEnabled(False)
        self.verify.clicked.connect(self.validate)
        self.save.clicked.connect(self.save_key)
        self.clear.clicked.connect(self.clear_key)
        self.cancel.clicked.connect(self.reject)
        self.input.textChanged.connect(self.invalidate_validation)

    def change_language(self):
        install_language(self.language_selector.currentData())
        self.setWindowTitle(t("QGIS-AI-Mapper: API Key Configuration"))
        self.notice.setText(t("This plugin uses Qwen models. Enter and verify your Qwen API Key each time the plugin loads; it is reused throughout that loading session.\nVisit https://platform.qianwenai.com/ to configure your personal Qwen API Key."))
        self.input.setPlaceholderText(t("Enter API Key"))
        self.visible.setText(t("Show API Key"))
        self.verify.setText(t("Verify"))
        self.save.setText(t("Enable for this loading session only" if self.memory_only else "Save and enable"))
        self.clear.setText(t("Clear Key"))
        self.cancel.setText(t("Cancel"))
        self.status.setText(t(canonical_message(self.status.text())))

    def invalidate_validation(self):
        self.validated_key = ""
        self.memory_only = False
        self.save.setText(t('Save and enable'))
        self.save.setEnabled(False)

    def validate(self):
        key = self.input.text().strip()
        self.generation = session.reset()
        self.invalidate_validation()
        if not key or any(char.isspace() for char in key):
            self.status.setText(t('Enter an API Key without whitespace.'))
            return
        self.set_busy(True)
        self.status.setText(t('Verifying the text model. Please wait…'))
        self.worker = ValidationThread(key, self)
        self.worker.completed.connect(self.validation_done)
        self.worker.finished.connect(lambda: self.set_busy(False))
        self.worker.start()

    def set_busy(self, busy):
        for control in (self.input, self.visible, self.verify, self.clear, self.language_selector):
            control.setEnabled(not busy)

    def validation_done(self, success, message):
        self.validated_key = self.input.text().strip() if success else ""
        self.save.setEnabled(success)
        self.status.setText(t(message))

    def save_key(self):
        if not self.validated_key or (self.worker and self.worker.isRunning()):
            return
        if self.memory_only:
            self.activate()
            return
        try:
            key_store().save(self.validated_key)
        except OSError:
            self.status.setText(t('Protected storage is unavailable. The key is used for this loading session only and was not saved to disk.'))
            try:
                key_store().clear()
            except OSError:
                pass
            self.save.setText(t('Enable for this loading session only'))
            self.memory_only = True
            return
        self.activate()

    def activate(self):
        try:
            session.activate(self.validated_key, self.generation)
        except CredentialError as exc:
            self.status.setText(t(str(exc)))
            return
        self.accept()

    def clear_key(self):
        session.reset()
        self.input.clear()
        try:
            key_store().clear()
            self.status.setText(t('Key cleared. Chat and tasks are disabled.'))
        except OSError:
            self.status.setText(t('Session cleared. The old local record could not be deleted; check configuration directory permissions.'))

    def reject(self):
        super().reject()

    def done(self, result):
        if self.worker and self.worker.isRunning():
            if result == QDialog.Accepted:
                return
            worker = self.worker
            worker.completed.disconnect(self.validation_done)
            worker.finished.disconnect()
            worker.setParent(None)
            _pending_workers.add(worker)
            worker.finished.connect(lambda: _release_worker(worker))
            self.worker = None
            session.reset()
        self.input.clear()
        self.validated_key = ""
        super().done(result)
