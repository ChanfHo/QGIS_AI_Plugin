from . import model_config
from .credentials import session, service_error
from PyQt5.QtCore import QObject, pyqtSignal, QTimer
from PyQt5.QtMultimedia import QAudioFormat, QAudioInput

try:
    from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

    DASH_SCOPE_AVAILABLE = True
except ImportError:
    DASH_SCOPE_AVAILABLE = False
    RecognitionCallback = object
    RecognitionResult = object


class RealTimeCallback(RecognitionCallback):
    """Real-time streaming callback."""

    def __init__(self, signal_emitter):
        super().__init__()
        self.emitter = signal_emitter

    def on_event(self, result: RecognitionResult):
        # Extract the current sentence's real-time transcript from the result.
        sentence = result.get_sentence()
        if sentence and 'text' in sentence:
            # Send to the UI in real time.
            self.emitter.transcription_ready.emit(sentence['text'])

    def on_error(self, result: RecognitionResult):
        self.emitter.error_occurred.emit(str(service_error(
            getattr(result, "status_code", 0), getattr(result, "code", ""))))


class AudioManager(QObject):
    transcription_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    recording_started = pyqtSignal()
    recording_stopped = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.generation = None
        self.recognition = None
        self.audio_input = None
        self.device = None
        self.hotword_manager = None
        self.auth_timer = QTimer(self)
        self.auth_timer.setInterval(100)
        self.auth_timer.timeout.connect(self.check_credentials)

        # Configure the 16 kHz mono audio format required by Fun-ASR.
        self.format = QAudioFormat()
        self.format.setSampleRate(16000)
        self.format.setChannelCount(1)
        self.format.setSampleSize(16)
        self.format.setCodec("audio/pcm")
        self.format.setByteOrder(QAudioFormat.LittleEndian)
        self.format.setSampleType(QAudioFormat.SignedInt)

    def set_hotword_manager(self, manager):
        """Bind a hotword manager for external callers."""
        self.hotword_manager = manager

    def start_recording(self):
        key, self.generation = session.snapshot()
        if not DASH_SCOPE_AVAILABLE:
            self.error_occurred.emit('Install the dashscope SDK first')
            return

        vocab_id = None
        if self.hotword_manager and hasattr(self.hotword_manager, 'vocab_id'):
            self.hotword_manager.sync_to_cloud()
            vocab_id = self.hotword_manager.vocab_id

        # 1. Initialize the online recognizer.
        self.recognition = Recognition(
            api_key=key,
            model=model_config.ASR_MODEL,
            format='pcm',  # Send the raw stream directly.
            sample_rate=16000,
            callback=RealTimeCallback(self),
            vocabulary_id=vocab_id,
        )
        self.recognition.start()

        # 2. Start microphone capture.
        self.audio_input = QAudioInput(self.format, self)
        self.device = self.audio_input.start()

        # 3. Send captured microphone data immediately.
        self.device.readyRead.connect(self._stream_to_cloud)

        self.recording_started.emit()
        self.auth_timer.start()

    def check_credentials(self):
        try:
            session.check_generation(self.generation)
        except Exception:
            self.stop_recording()

    def _stream_to_cloud(self):
        """Stream captured microphone data to the cloud in real time."""
        try:
            session.check_generation(self.generation)
        except Exception:
            self.stop_recording()
            return
        if self.device and self.recognition:
            data = self.device.readAll()
            if data:
                # Recommended packet size: 1 KB to 16 KB.
                self.recognition.send_audio_frame(data.data())

    def stop_recording(self):
        self.auth_timer.stop()
        if self.audio_input:
            self.audio_input.stop()
        if self.recognition:
            self.recognition.stop()
        self.recognition = None
        self.audio_input = None
        self.device = None

        self.recording_stopped.emit()
