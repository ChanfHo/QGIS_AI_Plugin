from .model_config import ASR_MODEL
import dashscope
from dashscope.audio.asr import VocabularyService
from qgis.core import QgsProject


class QGISHotwordManager:
    """基于阿里云定制热词文档实现的自动化管理类"""

    def __init__(self, target_model=ASR_MODEL):
        self.service = VocabularyService()
        self.target_model = target_model
        self.vocab_id = None
        self.prefix = "qgisai"  # 自定义前缀，仅允许数字和小写字母

        # 1. 尝试初始化/获取已有的热词表
        self._init_vocabulary()

        # 2. 绑定 QGIS 信号
        QgsProject.instance().layersAdded.connect(self.sync_to_cloud)
        QgsProject.instance().layersRemoved.connect(self.sync_to_cloud)

    def _init_vocabulary(self):
        """查询是否已有该前缀的热词表，若无则创建"""
        try:
            existing = self.service.list_vocabularies(prefix=self.prefix)
            if existing:
                self.vocab_id = existing[0]['vocabulary_id']
            else:
                # 创建一个初始热词表
                initial_vocab = [{"text": "地理信息系统", "weight": 4}]
                self.vocab_id = self.service.create_vocabulary(
                    target_model=self.target_model,
                    prefix=self.prefix,
                    vocabulary=initial_vocab
                )
        except Exception as e:
            print(f"热词初始化失败: {e}")

    def sync_to_cloud(self):
        """抓取 QGIS 图层名并更新云端热词表"""
        if not self.vocab_id: return

        layers = QgsProject.instance().mapLayers().values()
        # 构造符合格式的 JSON 数组
        new_vocabulary = []
        for layer in layers:
            name = layer.name()
            # 文本长度限制：含非ASCII字符不超过15个
            if 1 < len(name) <= 15:
                new_vocabulary.append({"text": name, "weight": 4})

        # 添加通用 GIS 核心热词
        base_words = ["缓冲区", "矢量图层", "栅格数据", "裁剪"]
        for word in base_words:
            new_vocabulary.append({"text": word, "weight": 4})

        # 限制单个列表最多 500 个热词
        final_list = new_vocabulary[:500]

        try:
            # 调用更新接口覆盖已有列表
            self.service.update_vocabulary(self.vocab_id, final_list)
            print(f"云端热词已更新，ID: {self.vocab_id}")
        except Exception as e:
            print(f"热词同步失败: {e}")