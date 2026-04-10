import os
from faster_whisper import WhisperModel
from runtime_events import emit_event

MODEL_NAME = "medium" 
DEVICE = "cpu"
COMPUTE_TYPE = "int8"

model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)

def load_audio_file(file_path: str) -> str:
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"

    try:
        
        segments, info = model.transcribe(file_path, beam_size=5)
        
        full_transcript = []
        
        for segment in segments:
            text = segment.text.strip()
            full_transcript.append(text)
            emit_event("partial_transcript", text=" ".join(full_transcript))


        return " ".join(full_transcript)

    except Exception as e:
        return f"Transcription error: {str(e)}"