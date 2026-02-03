import inspect
import traceback
from types import UnionType
from typing import Any, Callable, get_type_hints, Literal, get_origin, get_args, Union

from openai.types.responses import FunctionToolParam

from config import Agent

_tools: dict[str, Callable] = {}


def _is_optional(annotation) -> bool:
    origin = get_origin(annotation)
    args = get_args(annotation)
    return (origin is UnionType or origin is Union) and type(None) in args


def _get_strict_json_schema_type(annotation) -> dict:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if _is_optional(annotation):
        non_none_args = [arg for arg in args if arg is not type(None)]
        if len(non_none_args) == 1:
            return _get_strict_json_schema_type(non_none_args[0])
        raise TypeError(f"Unsupported Union with multiple non-None values: {annotation}")

    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
    }

    if annotation in type_map:
        return {"type": type_map[annotation]}

    if origin in type_map:
        return {"type": type_map[origin]}

    if origin is Literal:
        values = args
        if all(isinstance(v, (str, int, bool)) for v in values):
            return {"type": "string" if all(isinstance(v, str) for v in values) else "number", "enum": list(values)}
        raise TypeError("Unsupported Literal values in annotation")

    raise TypeError(f"Unsupported parameter type: {annotation}")


def generate_function_schema(func: Callable[..., Any]) -> FunctionToolParam:
    sig = inspect.signature(func)
    type_hints = get_type_hints(func)

    params = {}
    required = []

    for name, param in sig.parameters.items():
        if name in {"self", "ctx"}:
            continue

        ann = type_hints.get(name, param.annotation)
        if ann is inspect._empty:
            raise TypeError(f"Missing type annotation for parameter: {name}")

        schema_entry = _get_strict_json_schema_type(ann)

        required.append(name)
        params[name] = schema_entry

    return {
        "type": "function",
        "name": func.__name__,
        "description": func.__doc__ or "",
        "parameters": {
            "type": "object",
            "properties": params,
            "required": required,
            "additionalProperties": False
        },
        "strict": True
    }


class ToolBox:
    _tools: list[FunctionToolParam]

    def __init__(self):
        self._funcs = {}
        self._tools = []

    def tool(self, func):
        self._tools.append(generate_function_schema(func))

        if inspect.iscoroutinefunction(func):
            async def safe_func(*args, **kwargs):
                try:
                    return await func(*args, **kwargs)
                except:
                    return traceback.format_exc()

        else:
            def safe_func(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except:
                    return traceback.format_exc()

        self._funcs[func.__name__] = safe_func
        return func

    def get_tools(self, tool_names: list[str]):
        return [tool for tool in self._tools if tool['name'] in set(tool_names)]

    async def run_tool(self, tool_name: str, **kwargs):
        tool = self._funcs.get(tool_name)
        result = tool(**kwargs)
        if inspect.iscoroutine(result):
            return await result
        else:
            return result

    def add_agent_tool(self, agent: Agent, run_agent):
        async def function(message: str) -> str:
            return await run_agent(agent, self, message)

        function.__name__ = agent['name']
        function.__doc__ = agent['description']

        self.tool(function)
