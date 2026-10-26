"""Sanitized logging and retained plugin-owned download directories."""

import logging
import tempfile
from .error_handling import sanitize


def log_message(message, tag="QGIS-AI-Mapper", level=None):
    from qgis.core import QgsMessageLog, Qgis
    QgsMessageLog.logMessage(str(sanitize(message)), tag=tag,
                             level=Qgis.Info if level is None else level)


class SanitizedLogger:
    def __init__(self, name):
        self.logger = logging.getLogger(name)

    def error(self, message, *args):
        self.logger.error(str(sanitize(message % args if args else message)))

    def info(self, message, *args):
        self.logger.info(str(sanitize(message % args if args else message)))


def download_directory():
    """Retain files referenced by QGIS layers; never remove user data on unload."""
    return tempfile.mkdtemp(prefix="qgis-ai-mapper-")
