import asyncio
import json
import sys
from pathlib import Path

from openai import AsyncOpenAI

from config import Agent, load_config
from tools.toolbox import ToolBox
import tools

from dotenv import load_dotenv
import os

from tools.transcription import load_audio_file

load_dotenv()

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
tool_box = ToolBox()

async def get_transcript() -> str:
    """Retrieve the transcript of the audio file. Awaits until transcription is complete."""
    return await tool_box.get_transcript()

tool_box.tool(get_transcript)
tools.register_all_tools(tool_box)

def add_agent_tools(agents: dict[str, Agent], tool_box: ToolBox):
    for name, agent in agents.items():
        tool_box.add_agent_tool(agent, run_agent)


async def run_agent(agent: Agent, tool_box: ToolBox, message: str | None):
    print("")
    print(f"---- RUNNING {agent['name']} ----")
    if message:
        print(message)
        print("----------------------------------")

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
                print(f"---- {agent['name']} calling {item.name} ----")
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
                print(f"---- {agent['name']} REASONED ----")

            else:
                print(item, file=sys.stderr)

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
    print(f"---- TRANSCRIPTION COMPLETE ----\n")
    return transcript

async def async_main(audio_path: Path):
    tool_box.set_audio_path(str(audio_path))

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
    await run_agent(agents[main_agent], tool_box, None)

def main(audio_path: Path):
    if not validate_audio_path(audio_path):
        sys.exit(1)
    asyncio.run(async_main(audio_path))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agent.py [audio_file_path]")
        sys.exit(1)
    
    main(Path(sys.argv[1]))
