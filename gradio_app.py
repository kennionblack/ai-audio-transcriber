"""Gradio frontend for running `agent.py` and showing streamed results."""

import json
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import gradio as gr
from runtime_events import EVENT_PREFIX

# File types we allow.
SUPPORTED_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".flac"}
IDLE_STATUS = "Idle"
RUNNING_STATUS = "Running"
READY_TEXT = "Ready."
SUMMARY_LOADING_TEXT = "Summary loading..."
TRANSCRIPTION_STARTED_TEXT = "Transcription started."
TRANSCRIPTION_RUNNING_TEXT = "Transcription running..."
NO_OUTPUT_TEXT = "[No output returned]"
MAX_LOOKUP_MATCHES_PER_SECTION = 5
LOOKUP_CONTEXT_CHARS = 40
DEFAULT_AUTO_REPLY = (
    "You have the correct audio file. Please transcribe it and return the full "
    "cleaned transcription plus a summary of key points, action items, and decisions. "
    "Use reasonable defaults and do not wait for further clarification."
)
FINAL_AUTO_REPLY = "No, that's all. Please end the conversation and return the final result."
LOG_DIR = Path(__file__).parent / "logs"

# Shared values for the current Gradio session.
APP_STATE = {
    "process": None,
    "status": IDLE_STATUS,
    "output": "",
    "transcription_output": "",
    "summary_output": "",
    "pdf_output": None,
    "reply_count": 0,
    # Save logs for this run here.
    "log_path": None,
    # The UI thread and reader thread both use this state.
    # The lock keeps them from stepping on each other.
    "lock": threading.Lock(),
}


def _reset_session_outputs() -> None:
    """Clear the result fields for the current session."""
    APP_STATE["output"] = ""
    APP_STATE["transcription_output"] = ""
    APP_STATE["summary_output"] = ""
    APP_STATE["pdf_output"] = None


def _set_running_session(process: subprocess.Popen) -> None:
    """Store the active process and initialize state for a new transcription run."""
    APP_STATE["process"] = process
    APP_STATE["status"] = RUNNING_STATUS
    APP_STATE["reply_count"] = 0
    APP_STATE["log_path"] = LOG_DIR / f"transcription-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    _reset_session_outputs()


def _snapshot_results() -> tuple[str, str, str | None, str]:
    """Read the UI-visible result state under a single lock."""
    with APP_STATE["lock"]:
        return (
            APP_STATE["output"],
            APP_STATE["transcription_output"],
            APP_STATE["summary_output"],
            APP_STATE["pdf_output"],
            APP_STATE["status"],
        )


def _send_default_reply(process: subprocess.Popen) -> None:
    """Send the next automatic reply to a running agent process."""
    with APP_STATE["lock"]:
        # We only auto-reply twice:
        # 1) start the work
        # 2) tell the coordinator we are done
        if APP_STATE["reply_count"] >= 2 or process.poll() is not None or process.stdin is None:
            return

        try:
            reply = DEFAULT_AUTO_REPLY if APP_STATE["reply_count"] == 0 else FINAL_AUTO_REPLY
            process.stdin.write(reply + "\n")
            process.stdin.flush()
            APP_STATE["reply_count"] += 1
        except Exception as exc:
            APP_STATE["output"] = f"Auto reply failed: {exc}"


def _handle_event(process: subprocess.Popen, payload: dict) -> None:
    """Apply a backend event to the shared app state."""
    event_type = payload.get("type")

    if event_type == "user_message":
        # The backend is waiting for input, so send the next auto-reply.
        _send_default_reply(process)
        return

    # Ignore events from a process that is no longer active.
    with APP_STATE["lock"]:
        if APP_STATE["process"] is not process:
            return

    if event_type == "transcript_ready":
        with APP_STATE["lock"]:
            APP_STATE["transcription_output"] = str(payload.get("transcript", "")).strip()
            if not APP_STATE["summary_output"]:
                APP_STATE["summary_output"] = SUMMARY_LOADING_TEXT
        return

    if event_type == "summary_ready":
        bullets = payload.get("summary") or []
        summary = "\n".join(f"- {b}" for b in bullets if isinstance(b, str) and b.strip())
        with APP_STATE["lock"]:
            APP_STATE["summary_output"] = summary
        return

    if event_type == "export_files_ready":
        export_files = payload.get("export_files") or {}
        pdf_path = export_files.get("pdf")
        with APP_STATE["lock"]:
            APP_STATE["pdf_output"] = pdf_path if pdf_path else None
        return

    if event_type == "final_result":
        with APP_STATE["lock"]:
            APP_STATE["output"] = str(payload.get("content", "")).strip()
            APP_STATE["status"] = "Completed"


def _reader_thread(process: subprocess.Popen) -> None:
    """Read process output and react to structured runtime events."""
    assert process.stdout is not None
    # This runs on a background thread.
    # Its job is to watch what agent.py prints without freezing the UI.
    # As lines come in, it looks for EVENT messages and updates APP_STATE.
    # Keep plain stdout lines here in case we need them as a fallback result.
    buffered_stdout_lines: list[str] = []
    with APP_STATE["lock"]:
        # Read the log path that was saved when this run started.
        log_path = APP_STATE["log_path"]

    log_file = None
    if log_path is not None:
        LOG_DIR.mkdir(exist_ok=True)
        # Open the log file once and keep adding lines to it.
        log_file = log_path.open("a", encoding="utf-8")

    try:
        for line in process.stdout:
            stripped_line = line.rstrip("\n")

            if log_file is not None:
                # Write each line right away so the log updates live.
                log_file.write(stripped_line + "\n")
                log_file.flush()

            if stripped_line.startswith(EVENT_PREFIX):
                # The backend prints EVENT lines to stdout.
                # Gradio reads them here so it knows when to reply or finish.
                event_json = stripped_line[len(EVENT_PREFIX):].strip()
                try:
                    _handle_event(process, json.loads(event_json))
                except json.JSONDecodeError:
                    buffered_stdout_lines.append(stripped_line)
                continue

            buffered_stdout_lines.append(stripped_line)
    finally:
        if log_file is not None:
            log_file.close()

    return_code = process.wait()
    with APP_STATE["lock"]:
        APP_STATE["process"] = None
        if APP_STATE["status"] == "Completed":
            if not APP_STATE["output"]:
                # If we never got a final event, fall back to raw stdout.
                APP_STATE["output"] = "\n".join(buffered_stdout_lines).strip()
            return

        # If the process ended without a final event, use the exit code.
        APP_STATE["status"] = "Completed" if return_code == 0 else f"Failed (exit {return_code})"
        APP_STATE["output"] = APP_STATE["output"] or "\n".join(buffered_stdout_lines).strip()
        if APP_STATE["status"] == "Completed" and not APP_STATE["transcription_output"]:
            # No transcript_ready event was received; show raw output as a fallback.
            APP_STATE["transcription_output"] = APP_STATE["output"]


def _validate_audio_path(audio_path: str | None) -> str | None:
    """Return an error message for invalid input, otherwise None."""
    # The user has to upload a file first.
    if not audio_path:
        return "No file uploaded. Please choose an audio file first."

    path = Path(audio_path)
    # Make sure the file still exists.
    if not path.exists() or not path.is_file():
        return f"Invalid file path: {path}"

    # Only allow the audio types this app supports.
    if path.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_SUFFIXES))
        return f"Unsupported file type '{path.suffix}'. Supported types: {supported}"

    return None


def transcribe(audio_path: str | None) -> tuple[str, str, str | None]:
    """Start agent.py in the background."""
    # Stop now if the upload is missing or invalid.
    error = _validate_audio_path(audio_path)
    if error:
        return error, "", None

    with APP_STATE["lock"]:
        # Do not start a second job while one is already running.
        existing = APP_STATE["process"]
        if existing is not None and existing.poll() is None:
            return "A transcription is already running.", "", None

    command = [sys.executable, "agent.py", "-v", audio_path]
    # Run agent.py in the background.
    # We read stdout for events and write stdin for auto-replies.
    process = subprocess.Popen(
        command,
        cwd=Path(__file__).parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    with APP_STATE["lock"]:
        # Start a fresh session so polling and lookup read from a consistent state.
        _set_running_session(process)

    # Start a background thread to watch stdout while the UI keeps running.
    # That thread notices events, saves logs, and stores the final result.
    threading.Thread(target=_reader_thread, args=(process,), daemon=True).start()
    return TRANSCRIPTION_STARTED_TEXT, "", None


def refresh_outputs() -> tuple[str, str, str | None]:
    """Read current state and build the main output text."""
    output, transcription_text, summary_text, pdf_path, status = _snapshot_results()

    if status.startswith("Completed"):
        return transcription_text or output or NO_OUTPUT_TEXT, summary_text, pdf_path
    if status.startswith("Failed"):
        return f"Transcription failed.\n\n{output or NO_OUTPUT_TEXT}", "", None
    if status == RUNNING_STATUS:
        return transcription_text or TRANSCRIPTION_RUNNING_TEXT, summary_text, None
    return READY_TEXT, "", None


def _build_lookup_matches(section_name: str, text: str, query_pattern: re.Pattern[str]) -> list[str]:
    """Return a small set of snippet matches from one text section."""
    if not text.strip():
        return []

    snippets: list[str] = []
    for match_index, match in enumerate(query_pattern.finditer(text), start=1):
        start = max(0, match.start() - LOOKUP_CONTEXT_CHARS)
        end = min(len(text), match.end() + LOOKUP_CONTEXT_CHARS)
        snippet = text[start:end].replace("\n", " ").strip()
        snippets.append(f"{section_name}: ...{snippet}...")
        if match_index >= MAX_LOOKUP_MATCHES_PER_SECTION:
            break
    return snippets


def lookup_text(query: str | None) -> str:
    """Search the current transcript and summary for a query string."""
    query = (query or "").strip()
    if not query:
        return "Enter a search term."

    with APP_STATE["lock"]:
        transcript = APP_STATE["transcription_output"] or APP_STATE["output"] or ""
        summary = APP_STATE["summary_output"] or ""

    query_pattern = re.compile(re.escape(query), re.IGNORECASE)
    matches = _build_lookup_matches("Transcript", transcript, query_pattern)
    matches.extend(_build_lookup_matches("Summary", summary, query_pattern))

    if not matches:
        return f'No matches found for "{query}".'

    return "\n".join(matches)


def clear_all() -> tuple[None, str, str, None, str, str]:
    """Reset file input and output."""
    with APP_STATE["lock"]:
        # Kill the running process so the reader thread exits naturally.
        active_process = APP_STATE["process"]
        if active_process is not None and active_process.poll() is None:
            active_process.terminate()
        APP_STATE["process"] = None
        APP_STATE["status"] = IDLE_STATUS
        APP_STATE["reply_count"] = 0
        APP_STATE["log_path"] = None
        _reset_session_outputs()
    return None, READY_TEXT, "", None, "", ""


# UI style.
CSS = """
.gradio-container {
  background: linear-gradient(120deg, #f5f7f8 0%, #e9f0f2 45%, #f8f3e9 100%);
  font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
}
#app-title {
  letter-spacing: 0.01em;
  font-weight: 700;
}
.panel {
  border: 1px solid #c8d2d6;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.82);
}
"""


with gr.Blocks(title="AI Audio Transcriber Demo", css=CSS) as app:
    gr.Markdown("## AI Audio Transcriber Demo", elem_id="app-title")
    gr.Markdown("Upload an audio file to run the transcription pipeline.")

    # Lookup is session-scoped: it searches whatever transcript and summary are currently loaded.
    with gr.Row():
        lookup_input = gr.Textbox(label="Lookup", placeholder="Search the current transcript or summary")
        lookup_button = gr.Button("Lookup")

    # Left side: upload and buttons. Right side: results.
    with gr.Row():
        with gr.Column(elem_classes=["panel"]):
            audio_input = gr.Audio(
                label="File Upload",
                sources=["upload"],
                type="filepath",
            )
            transcribe_button = gr.Button("Transcribe", variant="primary")
            clear_button = gr.Button("Clear")

        with gr.Column(elem_classes=["panel"]):
            transcription_display = gr.Textbox(label="Transcription", lines=14)
            summary_display = gr.Textbox(label="Summary", lines=10)
            pdf_download = gr.File(label="PDF Download", interactive=False)
            lookup_results = gr.Textbox(label="Lookup Results", lines=8, interactive=False)

    # Ask for updates every half second.
    poll_timer = gr.Timer(0.5)

    # Start the background job.
    transcribe_button.click(
        fn=transcribe,
        inputs=[audio_input],
        outputs=[transcription_display, summary_display, pdf_download],
    )

    # Refresh what the page shows.
    poll_timer.tick(
        fn=refresh_outputs,
        inputs=[],
        outputs=[transcription_display, summary_display, pdf_download],
    )

    # Support both explicit button clicks and Enter in the search box.
    lookup_button.click(
        fn=lookup_text,
        inputs=[lookup_input],
        outputs=[lookup_results],
    )

    lookup_input.submit(
        fn=lookup_text,
        inputs=[lookup_input],
        outputs=[lookup_results],
    )

    # Clear the page inputs and outputs.
    clear_button.click(
        fn=clear_all,
        inputs=[],
        outputs=[
            audio_input,
            transcription_display,
            summary_display,
            pdf_download,
            lookup_input,
            lookup_results,
        ],
    )


if __name__ == "__main__":
    # Start app.
    app.queue().launch()
