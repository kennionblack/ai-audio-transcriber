import os
from threading import Lock

from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio

from tools import print_verbose

MODEL_NAME = os.getenv("WHISPER_MODEL", "base")
DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "5"))
BEST_OF = int(os.getenv("WHISPER_BEST_OF", "5"))

_MODEL: WhisperModel | None = None
_MODEL_LOCK = Lock()


def _get_model() -> WhisperModel:
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            print_verbose(
                f"[transcription] loading whisper model {MODEL_NAME!r} on {DEVICE}/{COMPUTE_TYPE}"
            )
            _MODEL = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)
        return _MODEL


def load_audio_file(file_path: str) -> str:
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"

    try:
        audio = decode_audio(file_path)
        model = _get_model()
        print_verbose(f"[transcription] using model={MODEL_NAME!r}")
        segments, _ = model.transcribe(
            audio,
            beam_size=BEAM_SIZE,
            best_of=BEST_OF,
        )

        full_transcript = []
        for segment in segments:
            text = segment.text.strip()
            full_transcript.append(text)

        return " ".join(full_transcript)

    except Exception as e:
        return f"Transcription error: {str(e)}"