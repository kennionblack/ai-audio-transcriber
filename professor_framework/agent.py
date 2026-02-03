import asyncio
import json
import sys
from pathlib import Path

from openai import AsyncOpenAI

from config import Agent, load_config
from tools import ToolBox

from dotenv import load_dotenv
import os

load_dotenv()

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
tool_box = ToolBox()


@tool_box.tool
def talk_to_user(message: str) -> str:
    """Send a message to the user and get the user's response.

    This is the ONLY way to communicate with the user,
    so all information to and from the user will come through this function.
    """
    print()
    print("AI: ", message)
    return input("User: ")


@tool_box.tool
def talk_to_named_user(name: str, message: str) -> str:
    """Send a message to the specified user and get the user's response.

    This is the ONLY way to communicate with a user,
    so all information to and from a user will come through this function.
    """
    print()
    print(f"AI (to {name}): ", message)
    return input(f"{name}: ")


@tool_box.tool
def plan(thoughts: str):
    """
    Plan out what you want to do over the next few interactions with the user.

    Write your thoughts and strategy here.

    For example, if you need to ask the user a series of questions,
    you can enumerate them here to make sure you cover them all.

    Or if you need to call a series of functions, list them here
    so you remember what you planned to do.
    """
    print()
    print("----- PLAN ------")
    print(thoughts)
    print("-----------------")


@tool_box.tool
def reason(thoughts: str):
    """
    Reason about the task at hand.

    Write your thoughts here.
    You can also record information here you need to keep track of,
    but don't need to send to the user.

    IMPORTANT: This information is NOT visible to the user.
    If you need to send information to the user, use a different function.
    """
    print()
    print("--- REASONING ---")
    print(thoughts)
    print("-----------------")
    return None


@tool_box.tool
def make_dir(path: str):
    Path(path).mkdir(parents=True, exist_ok=True)


@tool_box.tool
def write_file(path: str, content: str):
    Path(path).resolve().write_text(content)


@tool_box.tool
def read_file(path: str) -> str:
    return Path(path).resolve().absolute().read_text()


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
            input=history, model="gpt-5-mini", tools=tools, **agent.get("kwargs", {})
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


def main(config_file: Path):
    config = load_config(config_file)
    agents = {agent["name"]: agent for agent in config["agents"]}
    add_agent_tools(agents, tool_box)
    main_agent = config["main"]
    asyncio.run(run_agent(agents[main_agent], tool_box, None))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
