import os

from faster_whisper import WhisperModel

from tools import print_verbose

MODEL_NAME = "base"
DEVICE = "cpu"
COMPUTE_TYPE = "int8"
BEAM_SIZE = 5

_MODEL: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _MODEL
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
        model = _get_model()
        print_verbose(f"[transcription] using model={MODEL_NAME!r}")
        segments, _ = model.transcribe(
            file_path,
            beam_size=BEAM_SIZE,
        )

        full_transcript = []
        for segment in segments:
            text = segment.text.strip()
            full_transcript.append(text)

        return " ".join(full_transcript)

    except Exception as e:
        return f"Transcription error: {str(e)}"