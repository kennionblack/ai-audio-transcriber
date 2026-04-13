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
from tools.translation import SUPPORTED_LANGUAGES

# Audio file types the app accepts.
SUPPORTED_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".flac"}
IDLE_STATUS = "Idle"
RUNNING_STATUS = "Running"
READY_TEXT = "Ready."
SUMMARY_LOADING_TEXT = "Summary loading..."
TRANSCRIPTION_STARTED_TEXT = "Transcription started."
TRANSCRIPTION_RUNNING_TEXT = "Transcription running..."
TRANSLATION_LOADING_TEMPLATE = "Translation to {language_name} loading..."
TRANSLATION_READY_TEMPLATE = "Showing translated output in {language_name}."
TRANSLATION_HINT_TEMPLATE = (
    "Selected output language: {language_name}. Choose the language before clicking "
    "Transcribe. The original transcript appears first, then the translated transcript "
    "and summary replace it when translation is ready."
)
ORIGINAL_HINT_TEXT = "Showing the original cleaned transcript and summary."
NO_OUTPUT_TEXT = "[No output returned]"
MAX_LOOKUP_MATCHES_PER_SECTION = 5
LOOKUP_CONTEXT_CHARS = 40
NO_TRANSLATION_OPTION = "Original output"
DEFAULT_AUTO_REPLY = (
    "You have the correct audio file. Please transcribe it and return the full "
    "cleaned transcription plus a summary of key points, action items, and decisions. "
    "Use reasonable defaults and do not wait for further clarification."
)
FINAL_AUTO_REPLY = "No, that's all. Please end the conversation and return the final result."
LOG_DIR = Path(__file__).parent / "logs"

# Shared state for the current Gradio session.
APP_STATE = {
    "process": None,
    "status": IDLE_STATUS,
    "output": "",
    "transcription_output": "",
    "summary_output": "",
    "translations": {},
    "translated_summaries": {},
    "pdf_output": None,
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
    APP_STATE["translations"] = {}
    APP_STATE["translated_summaries"] = {}
    APP_STATE["pdf_output"] = None


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

    if event_type == "translation_ready":
        language = str(payload.get("language", "")).strip().lower()
        transcript = str(payload.get("transcript", "")).strip()
        if language:
            with APP_STATE["lock"]:
                APP_STATE["translations"][language] = transcript
        return

    if event_type == "translated_summary_ready":
        language = str(payload.get("language", "")).strip().lower()
        bullets = payload.get("summary") or []
        summary = "\n".join(f"- {b}" for b in bullets if isinstance(b, str) and b.strip())
        if language:
            with APP_STATE["lock"]:
                APP_STATE["translated_summaries"][language] = summary
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


def _language_value_to_code(language_value: str | None) -> str | None:
    """Convert a dropdown value into a translation code."""
    if not language_value or language_value == NO_TRANSLATION_OPTION:
        return None

    language_code = str(language_value).split(" ", 1)[0].strip().lower()
    return language_code if language_code in SUPPORTED_LANGUAGES else None


def transcribe(audio_path: str | None, language_value: str | None) -> tuple[str, str, str | None]:
    """Start agent.py in the background."""
    error = _validate_audio_path(audio_path)
    if error:
        return error, "", None

    with APP_STATE["lock"]:
        existing = APP_STATE["process"]
        if existing is not None and existing.poll() is None:
            return "A transcription is already running.", "", None

    command = [sys.executable, "agent.py", "-v", "--mode", "auto", audio_path]
    translate_lang = _language_value_to_code(language_value)
    if translate_lang:
        command.extend(["--translate", translate_lang])

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


def refresh_outputs(language_value: str | None) -> tuple[str, str, str | None]:
    """Read current state and build the main output text."""
    # Take one snapshot of the current results, then build the UI response from it.
    output, transcription_text, summary_text, pdf_path, status = _snapshot_results()
    language_code = _language_value_to_code(language_value)

    if language_code:
        language_name = SUPPORTED_LANGUAGES[language_code]
        with APP_STATE["lock"]:
            translated_transcript = APP_STATE["translations"].get(language_code, "")
            translated_summary = APP_STATE["translated_summaries"].get(language_code, "")

        displayed_transcript = translated_transcript or transcription_text
        if translated_summary:
            displayed_summary = translated_summary
        elif status == RUNNING_STATUS or summary_text:
            displayed_summary = TRANSLATION_LOADING_TEMPLATE.format(language_name=language_name)
        else:
            displayed_summary = ""

        if status.startswith("Completed"):
            return displayed_transcript or output or NO_OUTPUT_TEXT, displayed_summary, pdf_path
        if status.startswith("Failed"):
            return f"Transcription failed.\n\n{output or NO_OUTPUT_TEXT}", "", None
        if status == RUNNING_STATUS:
            return displayed_transcript or TRANSCRIPTION_RUNNING_TEXT, displayed_summary, None
        return READY_TEXT, "", None

    if status.startswith("Completed"):
        return transcription_text or output or NO_OUTPUT_TEXT, summary_text, pdf_path
    if status.startswith("Failed"):
        return f"Transcription failed.\n\n{output or NO_OUTPUT_TEXT}", "", None
    if status == RUNNING_STATUS:
        return transcription_text or TRANSCRIPTION_RUNNING_TEXT, summary_text, None
    return READY_TEXT, "", None


def _build_view_status(language_value: str | None) -> str:
    """Describe what the results panel is currently showing."""
    language_code = _language_value_to_code(language_value)
    if not language_code:
        return ORIGINAL_HINT_TEXT

    language_name = SUPPORTED_LANGUAGES[language_code]
    with APP_STATE["lock"]:
        has_translation = bool(APP_STATE["translations"].get(language_code))
        has_translated_summary = bool(APP_STATE["translated_summaries"].get(language_code))

    if has_translation or has_translated_summary:
        return TRANSLATION_READY_TEMPLATE.format(language_name=language_name)
    return TRANSLATION_HINT_TEMPLATE.format(language_name=language_name)


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


def lookup_text(query: str | None, language_value: str | None) -> str:
    """Search the current transcript and summary for a query string."""
    query = (query or "").strip()
    if not query:
        return "Enter a search term."

    language_code = _language_value_to_code(language_value)
    with APP_STATE["lock"]:
        if language_code:
            transcript = (
                APP_STATE["translations"].get(language_code)
                or APP_STATE["transcription_output"]
                or APP_STATE["output"]
                or ""
            )
            summary = (
                APP_STATE["translated_summaries"].get(language_code)
                or APP_STATE["summary_output"]
                or ""
            )
        else:
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


def clear_all() -> tuple[None, str, str, None, str, str]:
    """Reset file input and output."""
    with APP_STATE["lock"]:
        active_process = APP_STATE["process"]
        if active_process is not None and active_process.poll() is None:
            active_process.terminate()
        APP_STATE["process"] = None
        APP_STATE["status"] = IDLE_STATUS
        APP_STATE["log_path"] = None
        _reset_session_outputs()
    return None, READY_TEXT, "", None, "", ""

CSS = """
.scroll-box textarea {
    overflow-y: auto !important;
}

.transcript-box textarea {
    min-height: 28rem !important;
    max-height: 28rem !important;
}

.summary-box textarea {
    min-height: 22rem !important;
    max-height: 22rem !important;
}
"""

TRANSLATION_CHOICES = [NO_TRANSLATION_OPTION] + [
    f"{code} - {name}" for code, name in SUPPORTED_LANGUAGES.items()
]


with gr.Blocks(title="AI Audio Transcriber Demo") as app:
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
                translation_language = gr.Dropdown(
                    label="Output Language",
                    choices=TRANSLATION_CHOICES,
                    value=NO_TRANSLATION_OPTION,
                    info="Choose this before Transcribe. The selected language replaces the displayed transcript and summary when ready.",
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
            view_status = gr.Markdown(ORIGINAL_HINT_TEXT)
            with gr.Tabs():
                with gr.Tab("Transcript"):
                    transcription_display = gr.Textbox(
                        label="Transcription",
                        lines=18,
                        max_lines=18,
                        elem_classes=["scroll-box", "transcript-box"],
                    )
                with gr.Tab("Summary"):
                    summary_display = gr.Textbox(
                        label="Summary",
                        lines=14,
                        max_lines=14,
                        elem_classes=["scroll-box", "summary-box"],
                    )
                with gr.Tab("Exports"):
                    pdf_download = gr.File(label="PDF Download", interactive=False)

    poll_timer = gr.Timer(0.5)

    transcribe_button.click(
        fn=transcribe,
        inputs=[audio_input, translation_language],
        outputs=[transcription_display, summary_display, pdf_download],
    )

    poll_timer.tick(
        fn=refresh_outputs,
        inputs=[translation_language],
        outputs=[transcription_display, summary_display, pdf_download],
    )

    translation_language.change(
        fn=_build_view_status,
        inputs=[translation_language],
        outputs=[view_status],
    )

    poll_timer.tick(
        fn=_build_view_status,
        inputs=[translation_language],
        outputs=[view_status],
    )

    lookup_button.click(
        fn=lookup_text,
        inputs=[lookup_input, translation_language],
        outputs=[lookup_results],
    )

    # Let the user press Enter in the search box instead of having to click the button.
    lookup_input.submit(
        fn=lookup_text,
        inputs=[lookup_input, translation_language],
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
        ],
    )


if __name__ == "__main__":
    # Start app.
    app.queue().launch(css=CSS)
