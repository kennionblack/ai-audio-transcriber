"""Gradio frontend for running `agent.py` with `-v` in the background and showing live logs/output.

Flow:
1) Upload a file
2) Click Transcribe (runs `agent.py -v`)
3) Enter a term and click Lookup
4) Read outputs
"""

import json
import subprocess
import sys
import threading
from pathlib import Path
import gradio as gr
# Checks if output looks like valid transcription JSON.
from tools.quality_assurance_tools import validate_json_structure

# File types we allow.
SUPPORTED_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".flac"}

# Shared app state.
# We keep one running job at a time.
APP_STATE = {
    "process": None,  # Running process, or None.
    "logs": [],  # Live console lines.
    "status": "Idle",  # Idle / Running / Completed / Failed.
    "raw_output": "",  # Full final output text.
    "lock": threading.Lock(),  # Keeps thread updates safe.
}


def _extract_latest_ai_prompt(logs: list[str]) -> str:
    """Get the most recent AI question block from logs."""
    # Find the latest line that starts with "AI:".
    start_index = -1
    for i, line in enumerate(logs):
        if line.strip().startswith("AI:"):
            start_index = i

    # No AI prompt found.
    if start_index == -1:
        return ""

    # Copy lines until we hit the next section marker.
    collected: list[str] = []
    for line in logs[start_index:]:
        # Stop when a new section starts.
        if collected and line.strip().startswith("---- "):
            break
        collected.append(line)
    return "\n".join(collected).strip()


def _reader_thread(process: subprocess.Popen) -> None:
    """Read process output and save it to APP_STATE."""
    # We expect stdout to be available.
    assert process.stdout is not None

    # Save each new output line.
    for line in process.stdout:
        with APP_STATE["lock"]:
            APP_STATE["logs"].append(line.rstrip("\n"))

    # When done, store status and full output.
    return_code = process.wait()
    with APP_STATE["lock"]:
        APP_STATE["raw_output"] = "\n".join(APP_STATE["logs"]).strip()
        APP_STATE["status"] = "Completed" if return_code == 0 else f"Failed (exit {return_code})"


def transcribe(audio_path: str | None) -> tuple[str, str, str, str]:
    """Start agent.py in the background."""
    # Check file input.
    if not audio_path:
        return "No file uploaded. Please choose an audio file first.", "", "", "Idle"

    path = Path(audio_path)
    if not path.exists() or not path.is_file():
        return f"Invalid file path: {path}", "", "", "Idle"

    # Check file extension.
    if path.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_SUFFIXES))
        return f"Unsupported file type '{path.suffix}'. Supported types: {supported}", "", "", "Idle"

    # Do not start a second run if one is already active.
    with APP_STATE["lock"]:
        existing = APP_STATE["process"]
        if existing is not None and existing.poll() is None:
            current_logs = "\n".join(APP_STATE["logs"])
            return "A transcription is already running.", current_logs, APP_STATE["raw_output"], APP_STATE["status"]

    # Start backend process.
    # `-u` = unbuffered output (live logs), `-v` = verbose mode.
    command = [sys.executable, "-u", "agent.py", "-v", audio_path]
    process = subprocess.Popen(
        command,
        cwd=Path(__file__).parent,  # Run in project folder.
        stdout=subprocess.PIPE,  # Capture output for UI.
        stderr=subprocess.STDOUT,  # Keep all output in one stream.
        stdin=subprocess.PIPE,  # Needed for Send Reply.
        text=True,  # Read/write strings.
        bufsize=1,  # Line buffering.
    )

    # Reset state for this new run.
    with APP_STATE["lock"]:
        APP_STATE["process"] = process
        APP_STATE["logs"] = [f"Running: {' '.join(command)}"]
        APP_STATE["status"] = "Running"
        APP_STATE["raw_output"] = ""

    # Start background log reader.
    threading.Thread(target=_reader_thread, args=(process,), daemon=True).start()
    return "Transcription started. Live logs are updating below.", "\n".join(APP_STATE["logs"]), "", "Running"


def refresh_outputs() -> tuple[str, str, str, str, str]:
    """Read current state and build values for the UI."""
    # Read shared state safely.
    with APP_STATE["lock"]:
        logs = list(APP_STATE["logs"])
        raw_output = APP_STATE["raw_output"]
        status = APP_STATE["status"]

    # Build verbose log text.
    verbose_text = "\n".join(logs).strip()
    # Show latest AI question in its own box.
    latest_ai_prompt = _extract_latest_ai_prompt(logs)

    # Main output text depends on status.
    if status.startswith("Completed"):
        qa_status = validate_json_structure(raw_output)
        output_text = f"Transcription complete.\nQA: {qa_status}\n\n{raw_output or '[No output returned]'}"
    elif status.startswith("Failed"):
        output_text = f"Transcription failed.\n\n{raw_output or '[No output returned]'}"
    elif status == "Running":
        output_text = "Transcription running... watch logs below.\n\nIf agent asks a question, type reply and click Send Reply."
    else:
        output_text = "Ready."

    return output_text, verbose_text, raw_output, latest_ai_prompt, status


def send_reply(reply_text: str) -> tuple[str, str]:
    """Send user reply to the running process."""
    # Ignore blank input.
    reply = reply_text.strip()
    if not reply:
        return "", "Reply is empty. Type a response first."

    # Send reply only if process is running and stdin is available.
    with APP_STATE["lock"]:
        process = APP_STATE["process"]
        if process is None or process.poll() is not None or process.stdin is None:
            return "", "No running process is waiting for input."

        try:
            # input() reads one line, so send newline.
            process.stdin.write(reply + "\n")
            process.stdin.flush()
            # Add reply to log so users can see it.
            APP_STATE["logs"].append(f"User(UI): {reply}")
        except Exception as exc:
            return reply_text, f"Failed to send reply: {exc}"

    return "", "Reply sent to agent."


def lookup(term: str, raw_transcript: str) -> str:
    """Find lines containing the lookup term (case-insensitive)."""
    # A transcript is required for lookup.
    if not raw_transcript.strip():
        return "No transcription result available yet. Click Transcribe first."

    # A search term is required.
    query = term.strip()
    if not query:
        return "Enter a lookup term first."

    # Start by searching the full output text.
    search_text = raw_transcript
    try:
        # If output is JSON, search common text fields.
        data = json.loads(raw_transcript)
        if isinstance(data, dict):
            parts: list[str] = []
            # Common transcript fields.
            if isinstance(data.get("transcription"), str):
                parts.append(data["transcription"])
            if isinstance(data.get("text"), str):
                parts.append(data["text"])
            # Summary can be text or a list.
            summary = data.get("summary")
            if isinstance(summary, str):
                parts.append(summary)
            elif isinstance(summary, list):
                parts.extend(str(item) for item in summary)
            # Use extracted text when present.
            if parts:
                search_text = "\n".join(parts)
    except json.JSONDecodeError:
        # If not JSON, keep searching raw text.
        pass

    # Search line by line so results are easy to read.
    matches = [line for line in search_text.splitlines() if query.lower() in line.lower()]
    if not matches:
        return f"No matches found for '{query}'."

    # Show first 20 matches.
    preview = "\n".join(matches[:20])
    return f"Found {len(matches)} matching line(s) for '{query}':\n\n{preview}"


def clear_all() -> tuple[None, str, str, str, str, str, str, str]:
    """Reset file input, output boxes, and hidden state."""
    # Reset cached values.
    with APP_STATE["lock"]:
        APP_STATE["logs"] = []
        APP_STATE["raw_output"] = ""
        APP_STATE["status"] = "Idle"
    # Return values in the same order as clear button outputs.
    return None, "Ready.", "", "", "", "", "Idle", ""


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
    # Title and description.
    gr.Markdown("## AI Audio Transcriber Demo", elem_id="app-title")
    gr.Markdown("This GUI runs `agent.py -v` and supports transcript lookup.")

    # Hidden value that stores latest raw transcript text.
    transcript_state = gr.State("")

    # Layout: controls left, output right.
    with gr.Row():
        with gr.Column(elem_classes=["panel"]):
            # File upload.
            audio_input = gr.Audio(
                label="File Upload",
                sources=["upload"],
                type="filepath",
            )
            # Start transcription.
            transcribe_button = gr.Button("Transcribe", variant="primary")
            # Term to search for.
            lookup_input = gr.Textbox(
                label="Lookup Term",
                placeholder="Example: action item",
                lines=1,
            )
            # Your answer when agent asks questions.
            agent_reply_input = gr.Textbox(
                label="Your Reply To Agent",
                placeholder="Type your answer when agent asks a question, then click Send Reply.",
                lines=3,
            )
            # Send reply to running process.
            send_reply_button = gr.Button("Send Reply")
            # Shows reply result.
            reply_status = gr.Textbox(label="Reply Status", lines=2)
            # Run lookup.
            lookup_button = gr.Button("Lookup")
            # Clear the UI.
            clear_button = gr.Button("Clear")

        with gr.Column(elem_classes=["panel"]):
            # Main output area.
            output_display = gr.Textbox(label="Output Display", lines=14)
            # Latest AI question.
            agent_prompt_display = gr.Textbox(label="Latest Agent Question", lines=8)
            # Lookup matches.
            lookup_display = gr.Textbox(label="Lookup Results", lines=8)
            # Run status.
            run_status_display = gr.Textbox(label="Run Status", lines=2, value="Idle")
            # Live logs.
            verbose_display = gr.Textbox(label="Verbose Console (-v)", lines=12)

    # Refresh UI every 0.5 seconds.
    poll_timer = gr.Timer(0.5)

    # Start run button action.
    transcribe_button.click(
        fn=transcribe,
        inputs=[audio_input],
        outputs=[output_display, verbose_display, transcript_state, run_status_display],
    )

    # Auto-refresh action.
    poll_timer.tick(
        fn=refresh_outputs,
        inputs=[],
        outputs=[output_display, verbose_display, transcript_state, agent_prompt_display, run_status_display],
    )

    # Send reply action.
    send_reply_button.click(
        fn=send_reply,
        inputs=[agent_reply_input],
        outputs=[agent_reply_input, reply_status],
    )

    # Lookup action.
    lookup_button.click(
        fn=lookup,
        inputs=[lookup_input, transcript_state],
        outputs=[lookup_display],
    )

    # Clear action.
    clear_button.click(
        fn=clear_all,
        inputs=[],
        outputs=[
            audio_input,
            output_display,
            lookup_display,
            verbose_display,
            transcript_state,
            agent_prompt_display,
            run_status_display,
            reply_status,
        ],
    )


if __name__ == "__main__":
    # Start app.
    app.queue().launch()
