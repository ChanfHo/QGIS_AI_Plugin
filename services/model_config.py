"""Central model settings and runtime credential access."""

from .credentials import session


def get_api_key():
    return session.require_key()

BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
EMBEDDING_URL = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"

TEXT_MODEL = "qwen-plus"
TEXT_MODEL_TIMEOUT = 90.0
TEXT_MODEL_CONNECT_TIMEOUT = 10.0
TEXT_MODEL_ENABLE_THINKING = False
VISION_MODEL = "qwen3-vl-plus"
EMBEDDING_MODEL = "text-embedding-v4"
ASR_MODEL = "fun-asr-realtime"
