"""Gradio frontend for running `agent.py` and showing streamed results."""

import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import gradio as gr
from runtime_events import EVENT_PREFIX

# Audio file types the app accepts.
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
LOG_DIR = Path(__file__).parent / "logs"

# Human-readable labels shown as the compact event status.
_EVENT_LABELS = {
    "partial_transcript": "Transcribing audio...",
    "transcript_ready":   "Transcription complete. Cleaning...",
    "summary_ready":      "Summary generated.",
    "export_files_ready": "Export files ready.",
    "final_result":       "Pipeline complete.",
}

# Shared state for the current Gradio session.
APP_STATE = {
    "process": None,
    "status": IDLE_STATUS,
    "output": "",
    "transcription_output": "",
    "summary_output": "",
    "pdf_output": None,
    # Compact label of the most recent event.
    "current_event": "",
    # Full timestamped event log for the accordion detail view.
    "event_log": [],
    # Log file for the current run.
    "log_path": None,
    # The UI and the background reader both use this state, so the lock keeps
    # them from updating it at the same time.
    "lock": threading.Lock(),
}


def _reset_session_outputs() -> None:
    """Clear the result fields for the current session."""
    APP_STATE["output"] = ""
    APP_STATE["transcription_output"] = ""
    APP_STATE["summary_output"] = ""
    APP_STATE["pdf_output"] = None
    APP_STATE["current_event"] = ""
    APP_STATE["event_log"] = []


def _set_running_session(process: subprocess.Popen) -> None:
    """Store the active process and initialize state for a new transcription run."""
    APP_STATE["process"] = process
    APP_STATE["status"] = RUNNING_STATUS
    APP_STATE["log_path"] = LOG_DIR / f"transcription-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    _reset_session_outputs()


def _snapshot_results() -> tuple[str, str, str | None, str]:
    """Read the UI-visible result state under a single lock."""
    with APP_STATE["lock"]:
        # Read everything at once so the UI gets one consistent view of the state.
        return (
            APP_STATE["output"],
            APP_STATE["transcription_output"],
            APP_STATE["summary_output"],
            APP_STATE["pdf_output"],
            APP_STATE["status"],
        )


def _handle_event(process: subprocess.Popen, payload: dict) -> None:
    """Apply a backend event to the shared app state."""
    event_type = payload.get("type")

    with APP_STATE["lock"]:
        # Ignore events from an older run.
        if APP_STATE["process"] is not process:
            return

    label = _EVENT_LABELS.get(event_type, event_type)
    timestamp = datetime.now().strftime("%H:%M:%S")
    with APP_STATE["lock"]:
        APP_STATE["current_event"] = label
        # Only log distinct labels — skip noisy partial_transcript repeats.
        if event_type != "partial_transcript":
            APP_STATE["event_log"].append(f"[{timestamp}] {label}")

    if event_type == "partial_transcript":
        with APP_STATE["lock"]:
            APP_STATE["transcription_output"] = str(payload.get("text", "")).strip()
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
    # This runs in the background and listens to what agent.py prints.
    # If the backend does not send a final event, we can still show these lines.
    fallback_output_lines: list[str] = []
    with APP_STATE["lock"]:
        log_path = APP_STATE["log_path"]

    log_file = None
    if log_path is not None:
        LOG_DIR.mkdir(exist_ok=True)
        log_file = log_path.open("a", encoding="utf-8")

    try:
        for line in process.stdout:
            stripped_line = line.rstrip("\n")

            if log_file is not None:
                log_file.write(stripped_line + "\n")
                log_file.flush()

            if stripped_line.startswith(EVENT_PREFIX):
                event_json = stripped_line[len(EVENT_PREFIX):].strip()
                try:
                    _handle_event(process, json.loads(event_json))
                except json.JSONDecodeError:
                    fallback_output_lines.append(stripped_line)
                continue

            fallback_output_lines.append(stripped_line)
    finally:
        if log_file is not None:
            log_file.close()

    return_code = process.wait()
    with APP_STATE["lock"]:
        APP_STATE["process"] = None
        if APP_STATE["status"] == "Completed":
            if not APP_STATE["output"]:
                APP_STATE["output"] = "\n".join(fallback_output_lines).strip()
            return

        # If no final event arrived, fall back to exit code and raw stdout.
        APP_STATE["status"] = "Completed" if return_code == 0 else f"Failed (exit {return_code})"
        APP_STATE["output"] = APP_STATE["output"] or "\n".join(fallback_output_lines).strip()
        if APP_STATE["status"] == "Completed" and not APP_STATE["transcription_output"]:
            APP_STATE["transcription_output"] = APP_STATE["output"]


def _validate_audio_path(audio_path: str | None) -> str | None:
    """Return an error message for invalid input, otherwise None."""
    if not audio_path:
        return "No file uploaded. Please choose an audio file first."

    path = Path(audio_path)
    if not path.exists() or not path.is_file():
        return f"Invalid file path: {path}"

    if path.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_SUFFIXES))
        return f"Unsupported file type '{path.suffix}'. Supported types: {supported}"

    return None


def transcribe(audio_path: str | None) -> tuple[str, str, str | None]:
    """Start agent.py in the background."""
    error = _validate_audio_path(audio_path)
    if error:
        return error, "", None

    with APP_STATE["lock"]:
        existing = APP_STATE["process"]
        if existing is not None and existing.poll() is None:
            return "A transcription is already running.", "", None

    command = [sys.executable, "agent.py", "-v", "--mode", "auto", audio_path]
    # Run agent.py in the background.
    # We read stdout for events.

    process = subprocess.Popen(
        command,
        cwd=Path(__file__).parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    with APP_STATE["lock"]:
        # Start a fresh session for this new run.
        _set_running_session(process)

    # Keep reading backend output without blocking the page.
    threading.Thread(target=_reader_thread, args=(process,), daemon=True).start()
    return TRANSCRIPTION_STARTED_TEXT, "", None


def refresh_outputs() -> tuple[str, str, str | None]:
    """Read current state and build the main output text."""
    # Take one snapshot of the current results, then build the UI response from it.
    output, transcription_text, summary_text, pdf_path, status = _snapshot_results()

    if status.startswith("Completed"):
        return transcription_text or output or NO_OUTPUT_TEXT, summary_text, pdf_path
    if status.startswith("Failed"):
        return f"Transcription failed.\n\n{output or NO_OUTPUT_TEXT}", "", None
    if status == RUNNING_STATUS:
        return transcription_text or TRANSCRIPTION_RUNNING_TEXT, summary_text, None
    return READY_TEXT, "", None


def refresh_events() -> tuple[str, str]:
    """Return the compact event status and the full event log."""
    with APP_STATE["lock"]:
        current = APP_STATE["current_event"]
        log = list(APP_STATE["event_log"])
    return current or "Idle", "\n".join(log)


def _build_lookup_matches(section_name: str, text: str, query_pattern: re.Pattern[str]) -> list[str]:
    """Return a small set of snippet matches from one text section."""
    if not text.strip():
        return []

    snippets: list[str] = []
    for match_index, match in enumerate(query_pattern.finditer(text), start=1):
        # Show a little text before and after each match so the result is useful
        # even when we are not displaying the full transcript line-by-line.
        start = max(0, match.start() - LOOKUP_CONTEXT_CHARS)
        end = min(len(text), match.end() + LOOKUP_CONTEXT_CHARS)
        snippet = text[start:end].replace("\n", " ").strip()
        snippets.append(f"{section_name}: ...{snippet}...")
        # Limit the number of snippets so a common word does not flood the results box.
        if match_index >= MAX_LOOKUP_MATCHES_PER_SECTION:
            break
    return snippets


def lookup_text(query: str | None) -> str:
    """Search the current transcript and summary for a query string."""
    query = (query or "").strip()
    if not query:
        return "Enter a search term."

    with APP_STATE["lock"]:
        # Search whatever text is currently loaded in the UI state.
        # If we have a cleaned transcript, use it. Otherwise fall back to the final output.
        transcript = APP_STATE["transcription_output"] or APP_STATE["output"] or ""
        summary = APP_STATE["summary_output"] or ""

    # re.escape makes the query safe to search literally, so characters like "." or "?"
    # are treated as normal text instead of regex operators.
    query_pattern = re.compile(re.escape(query), re.IGNORECASE)
    # Search transcript and summary separately so each result can say where it came from.
    matches = _build_lookup_matches("Transcript", transcript, query_pattern)
    matches.extend(_build_lookup_matches("Summary", summary, query_pattern))

    if not matches:
        return f'No matches found for "{query}".'

    return "\n".join(matches)


def clear_all() -> tuple:
    """Reset file input and output."""
    with APP_STATE["lock"]:
        active_process = APP_STATE["process"]
        if active_process is not None and active_process.poll() is None:
            active_process.terminate()
        APP_STATE["process"] = None
        APP_STATE["status"] = IDLE_STATUS
        APP_STATE["log_path"] = None
        _reset_session_outputs()
    return None, READY_TEXT, "", None, "", "", "Idle", ""

CSS = ""


with gr.Blocks(title="AI Audio Transcriber Demo", css=CSS) as app:
    gr.Markdown("## AI Audio Transcriber Demo")
    gr.Markdown("Upload audio, run the transcription pipeline, then search the transcript and summary.")

    with gr.Row():
        with gr.Column(scale=1, min_width=320):
            with gr.Group():
                gr.Markdown("### Run A File")
                gr.Markdown("Upload audio, start a run, or clear the current session.")
                audio_input = gr.Audio(
                    label="File Upload",
                    sources=["upload"],
                    type="filepath",
                )
                with gr.Row():
                    transcribe_button = gr.Button("Transcribe", variant="primary")
                    clear_button = gr.Button("Clear")

            with gr.Group():
                gr.Markdown("### Lookup")
                gr.Markdown("Search the current transcript and summary.")
                lookup_input = gr.Textbox(label="Search", placeholder="Enter a word or phrase")
                lookup_button = gr.Button("Lookup")
                lookup_results = gr.Textbox(label="Lookup Results", lines=8, interactive=False)

        with gr.Column(scale=2, min_width=420):
            gr.Markdown("### Results")
            gr.Markdown("The transcript appears first. Summary and PDF follow when ready.")
            with gr.Tabs():
                with gr.Tab("Transcript"):
                    transcription_display = gr.Textbox(label="Transcription", lines=18)
                with gr.Tab("Summary"):
                    summary_display = gr.Textbox(label="Summary", lines=14)
                with gr.Tab("Exports"):
                    pdf_download = gr.File(label="PDF Download", interactive=False)

    with gr.Accordion("Pipeline Events", open=False):
        event_status = gr.Markdown("Idle")
        event_log_display = gr.Textbox(label="Event Log", lines=6, interactive=False)

    poll_timer = gr.Timer(0.5)

    transcribe_button.click(
        fn=transcribe,
        inputs=[audio_input],
        outputs=[transcription_display, summary_display, pdf_download],
    )

    poll_timer.tick(
        fn=refresh_outputs,
        inputs=[],
        outputs=[transcription_display, summary_display, pdf_download],
    )

    poll_timer.tick(
        fn=refresh_events,
        inputs=[],
        outputs=[event_status, event_log_display],
    )

    lookup_button.click(
        fn=lookup_text,
        inputs=[lookup_input],
        outputs=[lookup_results],
    )

    # Let the user press Enter in the search box instead of having to click the button.
    lookup_input.submit(
        fn=lookup_text,
        inputs=[lookup_input],
        outputs=[lookup_results],
    )

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
            event_status,
            event_log_display,
        ],
    )


if __name__ == "__main__":
    # Start app.
    app.queue().launch()
