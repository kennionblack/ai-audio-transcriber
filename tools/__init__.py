"""
This file registers the tool directory as an importable package and 
provides a method for agent.py to register all functions from *_tools.py files.
"""

import importlib
import inspect
from pathlib import Path

def register_all_tools(tool_box):
    tools_dir = Path(__file__).parent
    tool_modules = tools_dir.glob("*_tools.py")
    
    for module_path in tool_modules:
        module_name = module_path.stem
        module = importlib.import_module(f"tools.{module_name}")
        
        for name, obj in inspect.getmembers(module, inspect.isfunction):
            # Skip private functions and imported functions
            if not name.startswith('_') and obj.__module__ == module.__name__:
                tool_box.tool(obj)
