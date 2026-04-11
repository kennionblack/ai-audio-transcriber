# ai-audio-transcriber

An end-to-end, multi-agent pipeline that turns raw audio input into structured qualitative insights. Upload an audio file (interview, lecture, meeting, etc.) and the pipeline will transcribe, clean, and summarize it automatically.

## Prerequisites

- **Python 3.12+**
- **ffmpeg** — required by the audio processing libraries (`pydub`, `faster-whisper`)
  - Linux: `sudo apt install ffmpeg`
  - macOS: `brew install ffmpeg`
  - Windows: [download from ffmpeg.org](https://ffmpeg.org/download.html)
- **OpenAI API key** with access to the Chat/Responses API and access to the `gpt-5-mini` model

## Environment setup

This project assumes a Unix-based terminal (Linux, macOS, WSL). Your mileage may vary on Windows, Powershell, or other terminals.

Secrets are loaded from a `.env` file at the project root. Create one and add your API key:

```bash
echo "OPENAI_API_KEY=your_api_key_here" >> .env
```

## Usage

This project can be run in two modes. The first mode is a pure command line executable, while the second mode creates a web GUI. Both are explained below.

### Command line

```bash
python3 agent.py [-h] [-v] [-t lang_code] path/to/audio/file
```

| Flag | Description |
|------|-------------|
| `-h` | Show help and exit |
| `-v` | Enable verbose/debug logging for each pipeline step |
| `-t` | Translate output to a target language |

Supported audio formats: `.mp3`, `.wav`, `.m4a`, `.flac`

Supported translation languages: `en`, `zh`, `fr`, `es`, `de`, `ja`, `ko`, `pt`, `ar`, `ru`. Translation runs concurrently after the transcript and summary are ready, and writes a separate set of output files with a language suffix (e.g. `test_1_es.json`).

Output files (cleaned transcript, summary JSON) are written to the `output/` directory.

### GUI (Gradio frontend)

```bash
python3 gradio_app.py
```

This launches a web UI at **http://localhost:7860** where you can:
- Upload an audio file via drag-and-drop or file picker
- Click **Transcribe** to run the full agent pipeline
- View the cleaned transcription and bullet-point summary as they complete

Under the hood, `gradio_app.py` spawns `agent.py` as a subprocess and communicates via a structured event protocol (`runtime_events.py`). The UI auto-replies to the coordinator agent so the pipeline runs hands-free. Logs for each run are saved to a `logs/` directory.

## Installation

### Local (no container)

```bash
pip install -r requirements.txt
```

### Docker Compose

```bash
docker compose up --build
docker compose exec app bash
```

This builds from `Dockerfile.dev` and volume-mounts the project into the container, so local edits are reflected immediately.

### VS Code Dev Container (recommended for development)

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/).
2. Install the [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) extension for VS Code.
3. Clone the repository and open the folder in VS Code.
4. When prompted, select **Re-open in Container** in the bottom right corner (or use the command palette: `Dev Containers: Re-open in container`).
5. The first build will take a few minutes to install everything, but subsequent starts should be fast.
6. If dependencies change, rebuild via the command palette: `Dev Containers: Rebuild Container Without Cache`.

**Notes:**
- If import squiggles appear, use the command palette → `Python: Select Interpreter` → choose `/usr/local/bin/python` (3.12).
- Place audio files in your local repo's `audio/` folder as these contents will be mirrored to the container. The contents of this folder are included in the .gitignore to avoid large file uploads.

## Linting

This project uses [ruff](https://docs.astral.sh/ruff/) for linting. A [pre-commit](https://pre-commit.com/) hook runs ruff automatically on every push.

```bash
# install the pre-push hook (done automatically in the dev container)
pre-commit install --hook-type pre-push

# run the linter manually
ruff check .

# auto-fix what ruff can fix
ruff check --fix .
```

## Pipeline

The agent pipeline is defined in `agents.yaml` and consists of two agents:

1. **Coordinator** — Greets the user, gathers preferences, retrieves the transcript, delegates to the cleaner, and presents the final result.
2. **Cleaner** — Cleans and formats the raw transcription (filler-word removal, grammar fixes, punctuation) and generates a bullet-point summary, then returns the result to the coordinator.

Audio transcription is handled by [faster-whisper](https://github.com/SYSTRAN/faster-whisper) running locally (no external API call for transcription). The Whisper model runs on CPU by default (`base.en`, int8 precision).

test