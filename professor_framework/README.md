# Agent Framework

This is the framework for running multiple concurrent agents (synchronously) developed by Dr. Bean. Most of the agent configuration is handled in `.yaml` files, of which there are already a few examples.

## Environment setup

This project assumes that you are using a standard Unix-based terminal to run operations (e.g. Linux, WSL, or whatever flavor you like). This has not been tested directly on Windows so your mileage may vary if you prefer developing there.

Instead of storing environment variables in the kernel or in the PATH, this framework loads all secrets from a `.env` file, which will need to be created either at root level or within the `professor_framework`directory.

To run any of the agent configurations, you will need an OpenAI API key stored as `OPENAI_API_KEY` in your `.env` file. You can either add this key manually or run the below command to add the API key.

```bash
cd professor_framework && echo "OPENAI_API_KEY=your_api_key_here" >> .env
```

## Usage

```bash
python3 agent.py [config.yaml/config.json/config.md]
```

`agent.py` expects the next command line parameter to be the path to the configuration file storing the system prompts and tool lists. If this path is not provided, the program will crash. YAML is used for readability, but JSON and regular Markdown files are also supported.

## Constructing your own agents

To build your own agents, you can write your own YAML (or JSON/Markdown) configuration files. The YAML structure is given below:

```yaml
agents:
  - name: Agent name (visible to other agents when added as tool).
    description: |
      Description of the agent that is loaded as a tool description.
    model: OpenAI model name (e.g. gpt-5, gpt-4o-mini, etc.)
    prompt: |
      System prompt for this specific subagent. This is where you put initial instructions, guidelines, and examples of how the agent should behave.

      You will often need to specify how to use custom tools within this prompt as the agent does not know by default how to use them.
    tools:
      - This is the list of tools available to the agent.
      - These are decorated with @tool_box.tool in agent.py.
      - If a tool exists but the tool name is not included in this list, the agent will not be able to use it.
      - If one agent should talk to another agent, put the other agent's name here as a tool.

main: Name of the agent that will initiate conversation with the user.
```

Adding your own tools is possible using the ToolBox class in `tools.py`. This allows functions to be annotated with the `@tool_box.tool` decorator such that they can be used by an agent. You can define your own custom sets of tools as well in separate files as long as they are loaded into agent.py.

The docstring in any tool function is crucial to helping the agent understand how a tool should be used. If you have trouble getting an agent to use a specific tool, you can explicitly ask it to use that tool and see if it has issues when attempting to access/run the tool. When the code inside a tool crashes, the agent will receive the error trace and often attempt to interpret that log to the user.

Note that you may get type import errors with the ToolBox if you use a type that is not a str, int, float, or bool within a new custom tool. In this case, you should be able to add a new mapping in `_get_strict_json_schema_type`.
