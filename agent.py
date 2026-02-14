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

load_dotenv()

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
tool_box = ToolBox()

def get_audio_file_path() -> str:
    """Get the audio file path that was passed as a command-line argument.
    
    Returns the absolute path to the audio file that needs to be processed.
    """
    audio_path = tool_box.get_audio_path()
    return audio_path if audio_path else "No audio file path provided"

tool_box.tool(get_audio_file_path)
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

def main(audio_path: Path):
    if not validate_audio_path(audio_path):
        sys.exit(1)
    
    tool_box.set_audio_path(str(audio_path))
    
    config = load_config(Path("agents.yaml"))
    agents = {agent["name"]: agent for agent in config["agents"]}
    add_agent_tools(agents, tool_box)
    main_agent = config["main"]
    asyncio.run(run_agent(agents[main_agent], tool_box, None))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agent.py [audio_file_path]")
        sys.exit(1)
    
    main(Path(sys.argv[1]))
