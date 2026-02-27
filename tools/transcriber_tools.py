import os
from faster_whisper import WhisperModel
from tools import print_verbose

# --- CONFIGURATION ---
MODEL_NAME = "base.en" 
DEVICE = "cpu"
COMPUTE_TYPE = "int8"

# Load model once
print_verbose(f"Loading Whisper '{MODEL_NAME}' to {DEVICE} using {COMPUTE_TYPE} precision...")
model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)

def load_audio_file(file_path: str) -> str:
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"

    try:
        print_verbose(f"Processing: {os.path.basename(file_path)}")
        
        segments, info = model.transcribe(file_path, beam_size=5)
        
        print_verbose(f"Detected language: '{info.language}' (Probability: {info.language_probability:.2f})")
        
        full_transcript = []
        
        for segment in segments:
            text = segment.text.strip()
            full_transcript.append(text)
            print_verbose(f"  > [{segment.start:.2f}s -> {segment.end:.2f}s] {text}")

        return " ".join(full_transcript)

    except Exception as e:
        return f"Transcription error: {str(e)}"