import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import torch
from faster_whisper import WhisperModel
from pydub import AudioSegment

from tools import print_verbose

MODEL_NAME = "base"
DEVICE = "cpu"
COMPUTE_TYPE = "int8"
BEAM_SIZE = 5

DIARIZATION_MODEL = "pyannote/speaker-diarization-3.1"
DIARIZATION_SAMPLE_RATE = 16000

_MODEL: WhisperModel | None = None
_DIARIZATION_PIPELINE = None
_DIARIZATION_UNAVAILABLE = False


def _get_model() -> WhisperModel:
    global _MODEL
    if _MODEL is None:
        print_verbose(f"[transcription] loading whisper model {MODEL_NAME!r} on {DEVICE}/{COMPUTE_TYPE}")
        start = time.monotonic()
        _MODEL = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)
        print_verbose(f"[transcription] whisper model loaded in {time.monotonic() - start:.1f}s")
    return _MODEL


def _get_diarization_pipeline():
    """Lazily load the pyannote speaker-diarization pipeline. Returns None if no HF_TOKEN
    is configured or the model fails to load, so callers can fall back to an unlabeled transcript."""
    global _DIARIZATION_PIPELINE, _DIARIZATION_UNAVAILABLE
    if _DIARIZATION_PIPELINE is not None or _DIARIZATION_UNAVAILABLE:
        return _DIARIZATION_PIPELINE

    token = os.getenv("HF_TOKEN")
    if not token:
        print_verbose("[transcription] HF_TOKEN not set, skipping speaker diarization")
        _DIARIZATION_UNAVAILABLE = True
        return None

    try:
        from pyannote.audio import Pipeline

        print_verbose(f"[transcription] loading diarization model {DIARIZATION_MODEL!r}")
        start = time.monotonic()
        _DIARIZATION_PIPELINE = Pipeline.from_pretrained(DIARIZATION_MODEL, token=token)
        print_verbose(f"[transcription] diarization model loaded in {time.monotonic() - start:.1f}s")
    except Exception as exc:
        print_verbose(f"[transcription] failed to load diarization model, skipping: {exc}")
        _DIARIZATION_UNAVAILABLE = True
        return None

    return _DIARIZATION_PIPELINE


def _load_waveform(file_path: str) -> dict:
    """Decode audio via pydub/ffmpeg (already a project dependency) instead of pyannote's
    default torchcodec-based loader, which isn't reliably installed on Windows."""
    audio = AudioSegment.from_file(file_path).set_channels(1).set_frame_rate(DIARIZATION_SAMPLE_RATE)
    samples = np.array(audio.get_array_of_samples(), dtype=np.float32) / 32768.0
    waveform = torch.from_numpy(samples).unsqueeze(0)
    return {"waveform": waveform, "sample_rate": DIARIZATION_SAMPLE_RATE}


def _diarization_progress_hook(step_name, step_artifact, file=None, total=None, completed=None) -> None:
    """Plain-text stand-in for pyannote's rich-rendered ProgressHook, since this app's logs
    are plain text (subprocess stdout piped to a log file and shown as-is in the web UI)."""
    if total and completed is not None:
        print_verbose(f"[transcription] diarization step {step_name!r}: {completed}/{total}")
    else:
        print_verbose(f"[transcription] diarization step {step_name!r} starting")


def _diarize_speakers(file_path: str) -> list[tuple[float, float, str]] | None:
    """Return a list of (start, end, speaker_id) turns from real audio diarization, or None
    if diarization isn't configured/available."""
    pipeline = _get_diarization_pipeline()
    if pipeline is None:
        return None

    start = time.monotonic()
    try:
        diarization = pipeline(_load_waveform(file_path), hook=_diarization_progress_hook)
    except Exception as exc:
        print_verbose(f"[transcription] diarization failed, falling back to unlabeled transcript: {exc}")
        return None
    print_verbose(f"[transcription] diarization inference finished in {time.monotonic() - start:.1f}s")

    # pyannote.audio 4.x wraps the annotation in a DiarizeOutput with a `speaker_diarization`
    # attribute; older versions (and legacy-mode pipelines) return the Annotation directly.
    annotation = getattr(diarization, "speaker_diarization", diarization)
    return [(turn.start, turn.end, speaker) for turn, _, speaker in annotation.itertracks(yield_label=True)]


def _speaker_for_segment(turns: list[tuple[float, float, str]], start: float, end: float) -> str | None:
    """Pick the diarized speaker with the greatest time overlap against a whisper segment."""
    best_speaker, best_overlap = None, 0.0
    for turn_start, turn_end, speaker in turns:
        overlap = min(end, turn_end) - max(start, turn_start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = speaker
    return best_speaker


def _build_labeled_transcript(segments, turns: list[tuple[float, float, str]]) -> str:
    display_names: dict[str, str] = {}
    turn_texts: list[tuple[str, list[str]]] = []

    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        raw_speaker = _speaker_for_segment(turns, segment.start, segment.end)
        if raw_speaker is None:
            continue
        if raw_speaker not in display_names:
            display_names[raw_speaker] = f"Speaker {len(display_names) + 1}"
        display_name = display_names[raw_speaker]

        if turn_texts and turn_texts[-1][0] == display_name:
            turn_texts[-1][1].append(text)
        else:
            turn_texts.append((display_name, [text]))

    return "\n\n".join(f"{speaker}:\n\n{' '.join(texts)}" for speaker, texts in turn_texts)


def _transcribe_segments(file_path: str) -> list:
    model = _get_model()
    print_verbose(f"[transcription] using model={MODEL_NAME!r}")
    start = time.monotonic()
    segments, _ = model.transcribe(
        file_path,
        beam_size=BEAM_SIZE,
    )
    result = list(segments)
    print_verbose(f"[transcription] whisper transcription finished in {time.monotonic() - start:.1f}s")
    return result


def load_audio_file(file_path: str) -> str:
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"

    try:
        # Whisper transcription and speaker diarization only need the raw audio and don't
        # depend on each other's output, so run them concurrently instead of back-to-back —
        # both release the GIL during their heavy native compute, so this is real parallelism.
        with ThreadPoolExecutor(max_workers=2) as executor:
            transcribe_future = executor.submit(_transcribe_segments, file_path)
            diarize_future = executor.submit(_diarize_speakers, file_path)
            segments = transcribe_future.result()
            turns = diarize_future.result()

        if not turns:
            return " ".join(segment.text.strip() for segment in segments)

        return _build_labeled_transcript(segments, turns)

    except Exception as e:
        return f"Transcription error: {str(e)}"
