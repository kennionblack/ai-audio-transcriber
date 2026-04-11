from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import agent
from tools.context import get_context


def make_agent(name: str):
    return {
        "name": name,
        "description": f"{name} agent",
        "prompt": "You are a test agent.",
        "tools": [],
        "model": "gpt-5-mini",
        "kwargs": {},
    }


def test_print_verbose_respects_flag(monkeypatch, capsys):
    monkeypatch.setattr(agent, "VERBOSE", False)
    agent.print_verbose("hidden")
    assert capsys.readouterr().out == ""

    monkeypatch.setattr(agent, "VERBOSE", True)
    agent.print_verbose("visible")
    assert "visible" in capsys.readouterr().out


async def test_translate_flag_sets_callback(monkeypatch):
    ctx = get_context()

    monkeypatch.setattr(agent, "run_agent", AsyncMock(return_value="done"))

    monkeypatch.setattr(agent, "load_config", lambda _: {
        "agents": [make_agent("main")],
        "main": "main",
    })

    mock_translation = AsyncMock()
    monkeypatch.setattr(agent, "run_translation", mock_translation)

    audio_path = Path("test.mp3")

    with patch("agent.validate_audio_path", return_value=True):
        await agent.async_main(audio_path, translate_lang="fr")

    assert ctx.on_translation_ready is not None


@pytest.mark.asyncio
async def test_mode_auto_selects_automated_agent(monkeypatch):
    called_agents = []

    async def fake_run_agent(agent_obj, *_):
        called_agents.append(agent_obj["name"])
        return "done"

    monkeypatch.setattr(agent, "run_agent", fake_run_agent)

    monkeypatch.setattr(agent, "load_config", lambda _: {
        "agents": [
            make_agent("main"),
            make_agent("auto_agent"),
        ],
        "main": "main",
        "automated": "auto_agent",
    })

    audio_path = Path("test.mp3")

    with patch("agent.validate_audio_path", return_value=True):
        await agent.async_main(audio_path, mode="auto")

    assert called_agents[0] == "auto_agent"
