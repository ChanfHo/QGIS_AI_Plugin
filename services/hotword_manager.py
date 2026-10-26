from . import model_config
from .credentials import session
from dashscope.audio.asr import VocabularyService
from qgis.core import QgsProject, Qgis
from ..core.runtime_support import log_message


class QGISHotwordManager:
    """Automated manager based on Alibaba Cloud custom hotword documentation."""

    def __init__(self, target_model=None):
        self.service = None
        self.generation = None
        self.target_model = target_model or model_config.ASR_MODEL
        self.vocab_id = None
        self.prefix = "qgisai"  # Custom prefix: digits and lowercase letters only.

        # 1. Initialize or retrieve an existing vocabulary.
        if session.ready:
            self._init_vocabulary()

        # 2. Connect QGIS signals.
        QgsProject.instance().layersAdded.connect(self.sync_to_cloud)
        QgsProject.instance().layersRemoved.connect(self.sync_to_cloud)

    def _init_vocabulary(self):
        """Find a vocabulary with this prefix, or create one if absent."""
        key, self.generation = session.snapshot()
        self.service = VocabularyService(api_key=key)
        self.vocab_id = None
        try:
            existing = self.service.list_vocabularies(prefix=self.prefix)
            if existing:
                self.vocab_id = existing[0]['vocabulary_id']
            else:
                # Create an initial vocabulary.
                initial_vocab = [{"text": "地理信息系统", "weight": 4}]
                self.vocab_id = self.service.create_vocabulary(
                    target_model=self.target_model,
                    prefix=self.prefix,
                    vocabulary=initial_vocab
                )
        except Exception:
            log_message("ASR vocabulary initialization failed; check permissions and network.", level=Qgis.Warning)

    def sync_to_cloud(self):
        """Collect QGIS layer names and update the cloud vocabulary."""
        if not session.ready:
            self.vocab_id = None
            self.service = None
            return
        _, generation = session.snapshot()
        if generation != self.generation:
            self._init_vocabulary()
        if not self.vocab_id: return

        layers = QgsProject.instance().mapLayers().values()
        # Build a correctly formatted JSON array.
        new_vocabulary = []
        for layer in layers:
            name = layer.name()
            # Limit text containing non-ASCII characters to 15 characters.
            if 1 < len(name) <= 15:
                new_vocabulary.append({"text": name, "weight": 4})

        # Add common core GIS hotwords.
        base_words = ["缓冲区", "矢量图层", "栅格数据", "裁剪"]
        for word in base_words:
            new_vocabulary.append({"text": word, "weight": 4})

        # Limit each vocabulary to 500 hotwords.
        final_list = new_vocabulary[:500]

        try:
            # Call the update endpoint to replace the existing list.
            self.service.update_vocabulary(self.vocab_id, final_list)
            log_message("ASR vocabulary updated.")
        except Exception:
            log_message("ASR vocabulary synchronization failed; check permissions and network.", level=Qgis.Warning)
