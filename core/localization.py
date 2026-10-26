"""Plugin-scoped UI translation and per-request response language policy."""

from contextvars import ContextVar
from contextlib import contextmanager
from pathlib import Path
import json
import re

CONTEXT = "QGISAIMapper"
SETTING = "QGIS-AI-Mapper/language"
_response_language = ContextVar("mapper_response_language", default=None)
_translator = None
_catalog = json.loads((Path(__file__).resolve().parents[1] / "i18n" / "messages.json").read_text(encoding="utf-8"))
_legacy_messages = {translated: source for source, translated in _catalog.items()}


def ui_language():
    """Manual selection overrides QGIS; unsupported locales use English."""
    try:
        from qgis.PyQt.QtCore import QLocale, QSettings
    except ImportError:
        return "en"
    settings = QSettings()
    selected = settings.value(SETTING, "auto")
    if selected in ("zh", "en"):
        return selected
    locale = (settings.value("locale/userLocale", "en") if settings.value(
        "locale/overrideFlag", False, type=bool) else QLocale().name())
    return "zh" if str(locale).lower().startswith("zh") else "en"


def install_language(selection=None):
    """Keep translations local to the plugin's translation contexts."""
    from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTranslator
    global _translator
    if selection in ("auto", "zh", "en"):
        QSettings().setValue(SETTING, selection)
    app = QCoreApplication.instance()
    if app and _translator:
        app.removeTranslator(_translator)
    _translator = QTranslator()
    path = Path(__file__).resolve().parents[1] / "i18n" / f"qgis_ai_{ui_language()}.qm"
    loaded = _translator.load(str(path))
    if app and loaded:
        app.installTranslator(_translator)
    return loaded


def t(source, **values):
    """Translate only authored templates, never interpolated business data."""
    text = _catalog.get(source, source) if response_language() == "zh" else source
    return text.format(**values) if values else text


def canonical_message(message):
    """Resolve only known legacy authored messages, never arbitrary data values."""
    return _legacy_messages.get(message, message)


def response_language():
    return _response_language.get() or ui_language()


def choose_response_language(request, previous=None):
    """Explicit language requests override UI; recovery retains that choice."""
    patterns = {
        "en": r"(?:用|使用|以)\s*(?:英语|英文)|(?:answer|respond|reply|explain|write|speak)(?:\s+\w+){0,3}\s+in\s+english",
        "zh": r"(?:用|使用|以)\s*中文|(?:answer|respond|reply|explain|write|speak)(?:\s+\w+){0,3}\s+in\s+(?:chinese|mandarin)",
    }
    matches = [(match.start(), language) for language, pattern in patterns.items()
               for match in re.finditer(pattern, request, re.I)]
    return max(matches)[1] if matches else previous or ui_language()


@contextmanager
def response_scope(language):
    token = _response_language.set(language)
    try:
        yield
    finally:
        _response_language.reset(token)


def language_instruction():
    language = "Chinese" if response_language() == "zh" else "English"
    return (
        f"\nResponse language: {language}. Use it for user-visible reasoning, step explanations, "
        "summaries and error explanations. Preserve all JSON keys, algorithm IDs, enum values, "
        "numbers, SQL identifiers, actual layer/field names, paths and user-provided data. "
        "Keep Chinese retrieval keywords and required canonical Chinese data names unchanged. "
        "Do not translate the original request when the task requires preserving it verbatim.\n"
    )


def command_id(text):
    """Normalize bilingual commands while preserving legacy recovery inputs."""
    return {
        "重试当前步骤": "retry", "继续": "retry", "重试": "retry",
        "retry current step": "retry", "continue": "retry", "retry": "retry",
        "重新规划剩余步骤": "replan", "replan remaining steps": "replan",
    }.get(text.strip().lower(), "parameters")


def split_new_task(text):
    match = re.match(r"^(?:新任务[:：]|new task\s*[:：])\s*", text, re.I)
    return (True, text[match.end():].strip()) if match else (False, text)
