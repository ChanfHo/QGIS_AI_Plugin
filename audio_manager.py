from .model_config import ASR_MODEL
import os
import threading
from PyQt5.QtCore import QObject, pyqtSignal, QIODevice
from PyQt5.QtMultimedia import QAudioFormat, QAudioInput

try:
    import dashscope
    from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

    DASH_SCOPE_AVAILABLE = True
except ImportError:
    DASH_SCOPE_AVAILABLE = False


class RealTimeCallback(RecognitionCallback):
    """实时流式回调"""

    def __init__(self, signal_emitter):
        super().__init__()
        self.emitter = signal_emitter

    def on_event(self, result: RecognitionResult):
        # 核心：从结果中提取当前句子的实时转写文本
        sentence = result.get_sentence()
        if sentence and 'text' in sentence:
            # 实时发送给 UI
            self.emitter.transcription_ready.emit(sentence['text'])

    def on_error(self, result: RecognitionResult):
        self.emitter.error_occurred.emit(f"在线识别错误: {result.message}")


class AudioManager(QObject):
    transcription_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    recording_started = pyqtSignal()
    recording_stopped = pyqtSignal()

    def __init__(self, api_key: str):
        super().__init__()
        dashscope.api_key = api_key
        self.recognition = None
        self.audio_input = None
        self.device = None
        self.hotword_manager = None

        # 配置 Fun-ASR 要求的 16k 单声道音频格式
        self.format = QAudioFormat()
        self.format.setSampleRate(16000)
        self.format.setChannelCount(1)
        self.format.setSampleSize(16)
        self.format.setCodec("audio/pcm")
        self.format.setByteOrder(QAudioFormat.LittleEndian)
        self.format.setSampleType(QAudioFormat.SignedInt)

    def set_hotword_manager(self, manager):
        """供外部调用，绑定热词管理器"""
        self.hotword_manager = manager

    def start_recording(self):
        if not DASH_SCOPE_AVAILABLE:
            self.error_occurred.emit("请先安装 dashscope SDK")
            return

        vocab_id = None
        if self.hotword_manager and hasattr(self.hotword_manager, 'vocab_id'):
            vocab_id = self.hotword_manager.vocab_id

        # 1. 初始化在线识别对象
        self.recognition = Recognition(
            model=ASR_MODEL,
            format='pcm',  # 直接发送原始流
            sample_rate=16000,
            callback=RealTimeCallback(self),
            vocabulary_id = self.hotword_manager.vocab_id  # 传入动态维护的 ID
        )
        self.recognition.start()

        # 2. 启动麦克风监听
        self.audio_input = QAudioInput(self.format, self)
        self.device = self.audio_input.start()

        # 3. 绑定数据处理：当麦克风有数据时立即发送
        self.device.readyRead.connect(self._stream_to_cloud)

        self.recording_started.emit()

    def _stream_to_cloud(self):
        """将麦克风捕获的数据实时推送到云端"""
        if self.device and self.recognition:
            data = self.device.readAll()
            if data:
                # 建议每包大小在 1KB~16KB 之间
                self.recognition.send_audio_frame(data.data())

    def stop_recording(self):
        if self.audio_input:
            self.audio_input.stop()
        if self.recognition:
            self.recognition.stop()

        self.recording_stopped.emit()