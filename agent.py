import argparse
import asyncio
import json
import signal
import sys
from pathlib import Path

from openai import AsyncOpenAI

from config import Agent, load_config
from runtime_events import emit_event
from tools.toolbox import ToolBox
from tools.context import get_context
import tools

from dotenv import load_dotenv
import os

from tools.transcription import load_audio_file

load_dotenv()

VERBOSE = False

def print_verbose(*args, **kwargs):
    """Print only when --verbose flag is set."""
    if VERBOSE:
        print(*args, **kwargs)

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
tool_box = ToolBox()
ctx = get_context()

def _format_final_package(message: str) -> str | None:
    """Return final user-facing text when `message` is a completed package."""
    # Try to read the message as JSON.
    try:
        payload = json.loads(message)
    except (TypeError, json.JSONDecodeError):
        return None

    # If this is not a JSON object, it is not a finished package.
    if not isinstance(payload, dict):
        return None

    transcription = payload.get("transcription")
    summary = payload.get("summary")
    # A finished package must have a transcription string and a summary list.
    if not isinstance(transcription, str):
        return None
    if not isinstance(summary, list) or not all(isinstance(item, str) for item in summary):
        return None

    # Turn the JSON package into the plain text format the UI expects.
    summary_lines = "\n".join(f"- {item}" for item in summary)
    return f"{transcription.strip()}\n\nSummary\n{summary_lines}".strip()


def _build_final_payload(result: str) -> dict[str, object]:
    """Build a structured final payload for the UI from shared context when possible."""
    transcription = (ctx.cleaned_transcript or "").strip()
    summary = [item.strip() for item in ctx.summary if isinstance(item, str) and item.strip()]

    if transcription or summary:
        summary_text = "\n".join(f"- {item}" for item in summary)
        content_parts = [part for part in [transcription, f"Summary\n{summary_text}".strip() if summary_text else ""] if part]
        return {
            "content": "\n\n".join(content_parts).strip(),
            "transcription": transcription,
            "summary": summary_text,
        }

    return {
        "content": result,
        "transcription": "",
        "summary": "",
    }

async def get_transcript() -> str:
    """Retrieve the raw transcript. Blocks until transcription is complete, then stores it in the shared context."""
    transcript = await tool_box.get_transcript()
    ctx.set_raw_transcript(transcript)
    return transcript

tool_box.tool(get_transcript)
tools.register_all_tools(tool_box)

def add_agent_tools(agents: dict[str, Agent], tool_box: ToolBox):
    def make_agent_tool(agent: Agent):
        async def function(message: str) -> str:
            if agent["name"] == "cleaner" and ctx.raw_transcript is None:
                # The cleaner depends on shared transcript state. Populate it
                # from the background transcription task if the coordinator
                # skipped get_transcript().
                transcript = await tool_box.get_transcript()
                ctx.set_raw_transcript(transcript)
            # If another agent sends the coordinator a finished package,
            # stop here and return the final text right away.
            if agent["name"] == "coordinator":
                final_output = _format_final_package(message)
                if final_output is not None:
                    return final_output
            # Otherwise run the agent normally.
            return await run_agent(agent, tool_box, message)

        function.__name__ = agent["name"]
        function.__doc__ = agent["description"]
        return function

    for name, agent in agents.items():
        tool_box.tool(make_agent_tool(agent))


async def run_agent(agent: Agent, tool_box: ToolBox, message: str | None):
    print_verbose("")
    print_verbose(f"---- RUNNING {agent['name']} ----")
    if message:
        print_verbose(message)
        print_verbose("----------------------------------")

    history = [{"role": "system", "content": agent["prompt"]}]
    if message is not None:
        history.append({"role": "user", "content": message})

    tools = tool_box.get_tools(agent["tools"])

    while True:
        response = await client.responses.create(
            input=history,
            model=agent.get("model", "gpt-5-mini"),
            tools=tools,
            **agent.get("kwargs", {}),
        )
        
        history += response.output

        for item in response.output:
            if item.type == "function_call":
                print_verbose(f"---- {agent['name']} calling {item.name} ----")
                result = await tool_box.run_tool(item.name, **json.loads(item.arguments))

                history.append(
                    {
                        "type": "function_call_output",
                        "call_id": item.call_id,
                        "output": json.dumps(result),
                    }
                )

            elif item.type == "message":
                return response.output_text

            elif item.type == "reasoning":
                print_verbose(f"---- {agent['name']} REASONED ----")

            else:
                print_verbose(item, file=sys.stderr)

def validate_audio_path(path: Path) -> bool:
    if not path.exists():
        print(f"Error: Path '{path}' does not exist")
        return False
    if not path.is_file():
        print(f"Error: Path '{path}' is not a file")
        return False
    # We can decide the specific supported audio formats later but these seem like reasonable defaults
    if path.suffix.lower() not in [".mp3", ".wav", ".m4a", ".flac"]:
        print(f"Error: Unsupported audio format '{path.suffix}'")
        return False
    return True

def _run_transcription(audio_path: str) -> str:
    """Wrapper function for transcription that runs on separate thread"""
    transcript = load_audio_file(audio_path)
    print_verbose("---- TRANSCRIPTION COMPLETE ----\n")
    return transcript

async def async_main(audio_path: Path):
    tool_box.set_audio_path(str(audio_path))
    ctx.audio_filename = audio_path.name

    # This allows the transcription to run in the background while the agent initializes and calls its own tools.
    # This also allows the user to interact with the coordinator while the transcript is processed concurrently
    transcription_task = asyncio.create_task(
        asyncio.to_thread(_run_transcription, str(audio_path))
    )
    tool_box.set_transcription_task(transcription_task)

    config = load_config(Path("agents.yaml"))
    agents = {agent["name"]: agent for agent in config["agents"]}
    add_agent_tools(agents, tool_box)
    main_agent = config["main"]
    result = await run_agent(agents[main_agent], tool_box, None)
    emit_event("final_result", **_build_final_payload(result))

def main(audio_path: Path):
    if not validate_audio_path(audio_path):
        sys.exit(1)
    asyncio.run(async_main(audio_path))


if __name__ == "__main__":
    # This allows us to kill the process with just one Ctrl+C
    signal.signal(signal.SIGINT, lambda *_: (print(), sys.exit(130)))

    parser = argparse.ArgumentParser(description="Run the agent pipeline on an audio file.")
    parser.add_argument("audio_file_path", type=Path, help="Path to the audio file to process")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging output")
    args = parser.parse_args()

    VERBOSE = args.verbose
    tools.VERBOSE = args.verbose
    main(args.audio_file_path)
