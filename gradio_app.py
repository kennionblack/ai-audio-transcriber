"""Gradio frontend for running `agent.py` and showing streamed results."""

import json
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
    "reply_count": 0,
    # Save logs for this run here.
    "log_path": None,
    # The UI thread and reader thread both use this state.
    # The lock keeps them from stepping on each other.
    "lock": threading.Lock(),
}


def _split_final_output(output: str) -> tuple[str, str]:
    """Split final plain-text output into transcription and summary sections."""
    if not output:
        return "", ""

    # The final result currently puts the summary after a "Summary" heading.
    marker = "\n\nSummary\n"
    if marker in output:
        transcription, summary = output.split(marker, 1)
        return transcription.strip(), summary.strip()

    marker = "\nSummary\n"
    if marker in output:
        transcription, summary = output.split(marker, 1)
        return transcription.strip(), summary.strip()

    lines = output.strip().splitlines()
    summary_start = None
    for index, line in enumerate(lines):
        if line.startswith("- "):
            summary_start = index
            break

    if summary_start is not None:
        transcription_lines = lines[:summary_start]
        summary_lines = lines[summary_start:]
        return "\n".join(transcription_lines).strip(), "\n".join(summary_lines).strip()

    return output.strip(), ""


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

    if event_type == "final_result":
        # Save the finished result so the UI can show it.
        content = str(payload.get("content", "")).strip()
        transcription = str(payload.get("transcription", "")).strip()
        summary = str(payload.get("summary", "")).strip()
        if not transcription and not summary:
            transcription, summary = _split_final_output(content)
        with APP_STATE["lock"]:
            APP_STATE["output"] = content
            APP_STATE["transcription_output"] = transcription
            APP_STATE["summary_output"] = summary
            APP_STATE["status"] = "Completed"


def _reader_thread(process: subprocess.Popen) -> None:
    """Read process output and react to structured runtime events."""
    assert process.stdout is not None
    # This runs on a background thread.
    # Its job is to watch what agent.py prints without freezing the UI.
    # As lines come in, it looks for EVENT messages and updates APP_STATE.
    # Keep plain stdout lines here in case we need them as a fallback result.
    fallback_output: list[str] = []
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
                    fallback_output.append(stripped_line)
                continue

            fallback_output.append(stripped_line)
    finally:
        if log_file is not None:
            log_file.close()

    return_code = process.wait()
    with APP_STATE["lock"]:
        APP_STATE["process"] = None
        if APP_STATE["status"] == "Completed":
            if not APP_STATE["output"]:
                # If we never got a final event, fall back to raw stdout.
                APP_STATE["output"] = "\n".join(fallback_output).strip()
            return

        # If the process ended without a final event, use the exit code.
        APP_STATE["status"] = "Completed" if return_code == 0 else f"Failed (exit {return_code})"
        APP_STATE["output"] = APP_STATE["output"] or "\n".join(fallback_output).strip()
        if APP_STATE["status"] == "Completed":
            transcription, summary = _split_final_output(APP_STATE["output"])
            APP_STATE["transcription_output"] = transcription
            APP_STATE["summary_output"] = summary


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


def transcribe(audio_path: str | None) -> tuple[str, str]:
    """Start agent.py in the background."""
    # Stop now if the upload is missing or invalid.
    error = _validate_audio_path(audio_path)
    if error:
        return error, ""

    with APP_STATE["lock"]:
        # Do not start a second job while one is already running.
        existing = APP_STATE["process"]
        if existing is not None and existing.poll() is None:
            return "A transcription is already running.", ""

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
        # Reset the app state for the new run.
        APP_STATE["process"] = process
        APP_STATE["status"] = RUNNING_STATUS
        APP_STATE["output"] = ""
        APP_STATE["transcription_output"] = ""
        APP_STATE["summary_output"] = ""
        APP_STATE["reply_count"] = 0
        # Give this run its own log file.
        APP_STATE["log_path"] = LOG_DIR / f"transcription-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"

    # Start a background thread to watch stdout while the UI keeps running.
    # That thread notices events, saves logs, and stores the final result.
    threading.Thread(target=_reader_thread, args=(process,), daemon=True).start()
    return "Transcription started.", ""


def refresh_outputs() -> tuple[str, str]:
    """Read current state and build the main output text."""
    with APP_STATE["lock"]:
        # Copy the shared state before building the UI output.
        output = APP_STATE["output"]
        transcription_output = APP_STATE["transcription_output"]
        summary_output = APP_STATE["summary_output"]
        status = APP_STATE["status"]

    # Show a simple status while work is still running.
    if status.startswith("Completed"):
        return transcription_output or output or "[No output returned]", summary_output
    if status.startswith("Failed"):
        return f"Transcription failed.\n\n{output or '[No output returned]'}", ""
    if status == RUNNING_STATUS:
        return "Transcription running...", ""
    return READY_TEXT, ""


def clear_all() -> tuple[None, str, str]:
    """Reset file input and output."""
    with APP_STATE["lock"]:
        # Clear what the page shows.
        # This does not stop a job that is already running.
        APP_STATE["process"] = None
        APP_STATE["output"] = ""
        APP_STATE["transcription_output"] = ""
        APP_STATE["summary_output"] = ""
        APP_STATE["status"] = IDLE_STATUS
        APP_STATE["reply_count"] = 0
        APP_STATE["log_path"] = None
    return None, READY_TEXT, ""


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

    # Ask for updates every half second.
    poll_timer = gr.Timer(0.5)

    # Start the background job.
    transcribe_button.click(
        fn=transcribe,
        inputs=[audio_input],
        outputs=[transcription_display, summary_display],
    )

    # Refresh what the page shows.
    poll_timer.tick(
        fn=refresh_outputs,
        inputs=[],
        outputs=[transcription_display, summary_display],
    )

    # Clear the page inputs and outputs.
    clear_button.click(
        fn=clear_all,
        inputs=[],
        outputs=[
            audio_input,
            transcription_display,
            summary_display,
        ],
    )


if __name__ == "__main__":
    # Start app.
    app.queue().launch()
