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
from tools.quality_assurance_tools import validate_json_structure

SUPPORTED_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".flac"}

APP_STATE = {
    "process": None,
    "logs": [],
    "status": "Idle",
    "raw_output": "",
    "lock": threading.Lock(),
    "last_target_prompt": "",     # Tracks the current AI question
    "typed_prompt_length": 0,     # Tracks how much of the question is revealed
}


def _build_chat_messages(logs: list[str]) -> list[dict]:
    """Parses raw logs into a format the Gradio Chatbot can display (Left/Right bubbles)."""
    messages = []
    current_role = None
    current_content = []

    def flush_message():
        if current_role and current_content:
            text = "\n".join(current_content).strip()
            if text:
                messages.append({"role": current_role, "content": text})
        current_content.clear()

    for line in logs:
        # Detect User Replies
        if line.startswith("User(UI): "):
            flush_message()
            messages.append({"role": "user", "content": line[10:].strip()})
        # Detect Agent Prompts
        elif line.strip().startswith("AI:"):
            flush_message()
            current_role = "assistant"
            # Remove "AI:" prefix
            current_content.append(line[line.find("AI:")+3:].lstrip())
        # Continue capturing Agent Prompt until the separator
        elif current_role == "assistant":
            # Keep capturing if it's the internal reasoning block
            if line.strip().startswith("----") and "REASONED" not in line:
                flush_message()
                current_role = None
            else:
                # Intercept the backend log leak and replace "User:" with a sparkle
                clean_line = line
                if clean_line.startswith("User: ----"):
                    clean_line = clean_line.replace("User: ", "✨ ")
                current_content.append(clean_line)
                
    flush_message()
    return messages

def _reader_thread(process: subprocess.Popen) -> None:
    assert process.stdout is not None
    for line in process.stdout:
        with APP_STATE["lock"]:
            APP_STATE["logs"].append(line.rstrip("\n"))

    return_code = process.wait()
    with APP_STATE["lock"]:
        APP_STATE["raw_output"] = "\n".join(APP_STATE["logs"]).strip()
        APP_STATE["status"] = "Completed" if return_code == 0 else f"Failed (exit {return_code})"


def transcribe(audio_path: str | None) -> tuple[str, str, str, str]:
    if not audio_path:
        return "No file uploaded. Please choose an audio file first.", "", "", "Idle"

    path = Path(audio_path)
    if not path.exists() or not path.is_file():
        return f"Invalid file path: {path}", "", "", "Idle"

    if path.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_SUFFIXES))
        return f"Unsupported file type '{path.suffix}'. Supported types: {supported}", "", "", "Idle"

    with APP_STATE["lock"]:
        existing = APP_STATE["process"]
        if existing is not None and existing.poll() is None:
            current_logs = "\n".join(APP_STATE["logs"])
            return "A transcription is already running.", current_logs, APP_STATE["raw_output"], APP_STATE["status"]

    command = [sys.executable, "-u", "agent.py", "-v", audio_path]
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
        APP_STATE["process"] = process
        APP_STATE["logs"] = [f"Running: {' '.join(command)}"]
        APP_STATE["status"] = "Running"
        APP_STATE["raw_output"] = ""
        # Reset chat states
        APP_STATE["last_target_prompt"] = ""
        APP_STATE["typed_prompt_length"] = 0

    threading.Thread(target=_reader_thread, args=(process,), daemon=True).start()
    return "Transcription started. Live logs are updating below.", "\n".join(APP_STATE["logs"]), "", "Running"


def refresh_outputs() -> tuple[str, str, str, list[dict], str]:
    with APP_STATE["lock"]:
        logs = list(APP_STATE["logs"])
        raw_output = APP_STATE["raw_output"]
        status = APP_STATE["status"]

    verbose_text = "\n".join(logs).strip()
    
    # Generate chat history bubbles
    messages = _build_chat_messages(logs)

    # --- TYPEWRITER LOGIC FOR CHATBOT ---
    with APP_STATE["lock"]:
        # If the very last message is from the agent, stream it
        if messages and messages[-1]["role"] == "assistant":
            latest_ai_text = messages[-1]["content"]
            
            if APP_STATE["last_target_prompt"] != latest_ai_text:
                APP_STATE["last_target_prompt"] = latest_ai_text
                APP_STATE["typed_prompt_length"] = 0
                
            if APP_STATE["typed_prompt_length"] < len(latest_ai_text):
                APP_STATE["typed_prompt_length"] += 45 
                APP_STATE["typed_prompt_length"] = min(APP_STATE["typed_prompt_length"], len(latest_ai_text))

            display_text = latest_ai_text[:APP_STATE["typed_prompt_length"]]
            
            # Add cursor if still typing
            if APP_STATE["typed_prompt_length"] < len(latest_ai_text):
                display_text += " █"
                
            messages[-1]["content"] = display_text
    # ------------------------------------

    if status.startswith("Completed"):
        qa_status = validate_json_structure(raw_output)
        output_text = f"Transcription complete.\nQA: {qa_status}\n\n{raw_output or '[No output returned]'}"
    elif status.startswith("Failed"):
        output_text = f"Transcription failed.\n\n{raw_output or '[No output returned]'}"
    elif status == "Running":
        output_text = "Transcription running... watch the 'Live Logs' tab.\n\nIf agent asks a question, type your reply above."
    else:
        output_text = "Ready."

    return output_text, verbose_text, raw_output, messages, status


def send_reply(reply_text: str) -> tuple[str, str]:
    reply = reply_text.strip()
    if not reply:
        return "", "Reply is empty. Type a response first."

    with APP_STATE["lock"]:
        process = APP_STATE["process"]
        if process is None or process.poll() is not None or process.stdin is None:
            return "", "No running process is waiting for input."

        try:
            process.stdin.write(reply + "\n")
            process.stdin.flush()
            APP_STATE["logs"].append(f"User(UI): {reply}")
        except Exception as exc:
            return reply_text, f"Failed to send reply: {exc}"

    return "", "Reply sent to agent."


def lookup(term: str, raw_transcript: str) -> str:
    if not raw_transcript.strip():
        return "No transcription result available yet. Click Transcribe first."

    query = term.strip()
    if not query:
        return "Enter a lookup term first."

    search_text = raw_transcript
    try:
        data = json.loads(raw_transcript)
        if isinstance(data, dict):
            parts: list[str] = []
            if isinstance(data.get("transcription"), str):
                parts.append(data["transcription"])
            if isinstance(data.get("text"), str):
                parts.append(data["text"])
            summary = data.get("summary")
            if isinstance(summary, str):
                parts.append(summary)
            elif isinstance(summary, list):
                parts.extend(str(item) for item in summary)
            if parts:
                search_text = "\n".join(parts)
    except json.JSONDecodeError:
        pass

    matches = [line for line in search_text.splitlines() if query.lower() in line.lower()]
    if not matches:
        return f"No matches found for '{query}'."

    preview = "\n".join(matches[:20])
    return f"Found {len(matches)} matching line(s) for '{query}':\n\n{preview}"


def clear_all() -> tuple[None, str, str, str, str, list, str, str]:
    with APP_STATE["lock"]:
        APP_STATE["logs"] = []
        APP_STATE["raw_output"] = ""
        APP_STATE["status"] = "Idle"
        APP_STATE["last_target_prompt"] = ""
        APP_STATE["typed_prompt_length"] = 0
    return None, "Ready.", "", "", "", [], "Idle", ""


# --- UI LAYOUT STARTS HERE ---
CSS = """
#app-title {
  letter-spacing: 0.01em;
  font-weight: 700;
  margin-bottom: 0.2em;
}
.status-text {
  font-size: 0.9em;
  color: #666;
  margin-top: 0.5rem;
}
/* Ensure tab text is always visible */
.tab-nav button {
  color: inherit !important;
}
"""

with gr.Blocks(title="AI Audio Transcriber Demo") as app:
    
    gr.Markdown("## 🎙️ AI Audio Transcriber Workspace", elem_id="app-title")
    transcript_state = gr.State("")

    with gr.Row():
        
        # --- LEFT SIDEBAR ---
        with gr.Column(scale=1):
            gr.Markdown("### ⚙️ Setup & Run")
            audio_input = gr.Audio(label="Audio File", sources=["upload"], type="filepath")
            transcribe_button = gr.Button("Transcribe Audio", variant="primary")
            run_status_display = gr.Textbox(label="System Status", lines=1, value="Idle", interactive=False)
            
            gr.Markdown("---")
            
            gr.Markdown("### 🔍 Search Transcript")
            lookup_input = gr.Textbox(show_label=False, placeholder="Search term...", lines=1)
            lookup_button = gr.Button("Search", variant="secondary")
            lookup_display = gr.Textbox(label="Search Results", lines=4, max_lines=4)
            
            gr.Markdown("---")
            clear_button = gr.Button("🗑️ Clear Entire Workspace", variant="stop")

        # --- RIGHT COLUMN (MAIN WORKSPACE) ---
        with gr.Column(scale=3):
            
            gr.Markdown("### 💬 Agent Interaction")
            
            agent_chatbot = gr.Chatbot(
                label="Conversation", 
                height=450, 
                show_label=False,
                autoscroll=False,
                avatar_images=(
                    "https://cdn-icons-png.flaticon.com/512/1077/1077114.png", # Human Icon
                    "https://raw.githubusercontent.com/googlefonts/noto-emoji/main/png/512/emoji_u2728.png"  # Static Robot Icon
                )
            )
            
            with gr.Row(equal_height=True):
                agent_reply_input = gr.Textbox(
                    show_label=False, 
                    placeholder="Type your reply here and hit Enter...", 
                    lines=1,
                    scale=4
                )
                send_reply_button = gr.Button("Send Reply", variant="primary", scale=1)
                
            reply_status = gr.Markdown(value="", elem_classes=["status-text"])

            gr.Markdown("<br>")
            
            with gr.Tabs():
                with gr.TabItem("Live Agent Logs"):
                    verbose_display = gr.Textbox(show_label=False, lines=16, max_lines=16, interactive=False)
                
                with gr.TabItem("Final Transcript Output"):
                    output_display = gr.Textbox(show_label=False, lines=16, max_lines=16)

    # --- EVENT LISTENERS ---
    
    poll_timer = gr.Timer(0.5)

    transcribe_button.click(
        fn=transcribe,
        inputs=[audio_input],
        outputs=[output_display, verbose_display, transcript_state, run_status_display],
    )

    poll_timer.tick(
        fn=refresh_outputs,
        inputs=[],
        outputs=[output_display, verbose_display, transcript_state, agent_chatbot, run_status_display],
    )

    send_reply_button.click(
        fn=send_reply,
        inputs=[agent_reply_input],
        outputs=[agent_reply_input, reply_status],
    )
    agent_reply_input.submit(
        fn=send_reply,
        inputs=[agent_reply_input],
        outputs=[agent_reply_input, reply_status],
    )

    lookup_button.click(
        fn=lookup,
        inputs=[lookup_input, transcript_state],
        outputs=[lookup_display],
    )
    lookup_input.submit(
        fn=lookup,
        inputs=[lookup_input, transcript_state],
        outputs=[lookup_display],
    )

    clear_button.click(
        fn=clear_all,
        inputs=[],
        outputs=[
            audio_input,
            output_display,
            lookup_display,
            verbose_display,
            transcript_state,
            agent_chatbot,
            run_status_display,
            reply_status,
        ],
    )

if __name__ == "__main__":
    app.queue().launch(css=CSS, theme=gr.themes.Soft(primary_hue="slate"))