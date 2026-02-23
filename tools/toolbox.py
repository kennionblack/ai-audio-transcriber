import torch
import os
import librosa
import soundfile as sf
from nemo.collections.speechlm2.models import SALM

# --- CONFIGURATION ---
MODEL_NAME = 'nvidia/canary-qwen-2.5b'
CHUNK_DURATION = 30  # Seconds per chunk
OVERLAP = 2          # Overlap to prevent cutting words
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Load model once
print(f"Loading {MODEL_NAME} to {DEVICE}...")
model = SALM.from_pretrained(MODEL_NAME).to(dtype=torch.bfloat16, device=DEVICE).eval()

def load_audio_file(file_path: str) -> str:
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"

    try:
        # 1. Load, Resample to 16kHz, and Mono-convert
        print(f"Processing: {os.path.basename(file_path)}")
        audio, sr = librosa.load(file_path, sr=16000, mono=True)
        duration = librosa.get_duration(y=audio, sr=sr)
        
        full_transcript = []
        
        # 2. Iterate through chunks
        step = CHUNK_DURATION - OVERLAP
        for start in range(0, int(duration), int(step)):
            end = min(start + CHUNK_DURATION, duration)
            chunk_audio = audio[int(start * sr):int(end * sr)]
            
            # Save temporary chunk
            temp_chunk_path = f"temp_chunk_{start}.wav"
            sf.write(temp_chunk_path, chunk_audio, 16000)

            # 3. Transcribe Chunk
            prompt_text = f"Transcribe the following: {model.audio_locator_tag}"
            answer_ids = model.generate(
                prompts=[[{"role": "user", "content": prompt_text, "audio": [temp_chunk_path]}]],
                max_new_tokens=512
            )
            
            chunk_text = model.tokenizer.ids_to_text(answer_ids[0].cpu())
            full_transcript.append(chunk_text.strip())

            # Cleanup
            os.remove(temp_chunk_path)
            
            if duration > CHUNK_DURATION:
                print(f"  > Chunk {start}-{end}s transcribed.")

        # Join and return
        return " ".join(full_transcript)

    except Exception as e:
        return f"Transcription error: {str(e)}"