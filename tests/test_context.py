import pytest
from unittest.mock import patch

from tools.context import get_context, _reset_context


@pytest.fixture(autouse=True)
def reset_context():
    """Ensure each test gets a clean singleton context."""
    _reset_context()


# Validation Tests

def test_set_raw_transcript_rejects_empty():
    ctx = get_context()
    errors = ctx.set_raw_transcript("   ")
    assert errors is not None
    assert any("must not be empty" in e for e in errors)


def test_set_summary_invalid_type():
    ctx = get_context()
    errors = ctx.set_summary("not a list")
    assert errors is not None
    assert any("must be a list" in e for e in errors)


def test_set_summary_enforces_min_max():
    ctx = get_context()
    ctx.min_bullets = 2
    ctx.max_bullets = 3

    errors = ctx.set_summary(["only one"])
    assert errors is not None
    assert any("minimum is 2" in e for e in errors)


# State Mutation Tests

def test_set_and_get_transcript():
    ctx = get_context()
    ctx.set_raw_transcript("hello")
    assert ctx.get_raw_transcript() == "hello"


def test_get_transcript_before_set():
    ctx = get_context()
    result = ctx.get_raw_transcript()
    assert "not yet available" in result


def test_set_and_get_summary():
    ctx = get_context()
    bullets = ["a", "b", "c"]

    ctx.set_summary(bullets)
    assert ctx.get_summary() == bullets

    # Assert changing bullets doesn't affect summary.
    bullets.append("d")
    assert ctx.get_summary() == ["a", "b", "c"]


# Event Emission Tests

def test_set_cleaned_transcript_emits_event():
    ctx = get_context()

    with patch("tools.context.emit_event") as mock_emit:
        ctx.set_cleaned_transcript("clean text")

    mock_emit.assert_called_once_with(
        "transcript_ready", transcript="clean text"
    )


def test_set_summary_emits_event_and_triggers_complete():
    ctx = get_context()

    with patch("tools.context.emit_event") as mock_emit, \
         patch("tools.context.write_outputs") as mock_write:

        mock_write.return_value = {}

        ctx.cleaned_transcript = "clean"
        ctx.audio_filename = "file.mp3"

        ctx.set_summary(["a", "b", "c"])

    # summary_ready event
    assert any(call.args[0] == "summary_ready" for call in mock_emit.call_args_list)

    # export_files_ready event
    assert any(call.args[0] == "export_files_ready" for call in mock_emit.call_args_list)


# Output / Side Effect Tests

def test_on_complete_calls_write_outputs():
    ctx = get_context()

    with patch("tools.context.write_outputs") as mock_write, \
         patch("tools.context.emit_event"):

        mock_write.return_value = {"json": "file.json"}

        ctx.cleaned_transcript = "clean"
        ctx.audio_filename = "audio.mp3"

        ctx.set_summary(["a", "b", "c"])

    mock_write.assert_called_once()
    _, kwargs = mock_write.call_args

    assert kwargs["cleaned_transcript"] == "clean"
    assert kwargs["summary"] == ["a", "b", "c"]


def test_on_complete_handles_write_failure():
    ctx = get_context()

    with patch("tools.context.write_outputs", side_effect=Exception("error")), \
         patch("tools.context.emit_event"), \
         patch("tools.context.print_verbose"):

        ctx.cleaned_transcript = "clean"
        ctx.set_summary(["a", "b", "c"])

    # Should not raise even though error sideeffect. 


# Translation Tests

def test_set_translation_stores_and_emits():
    ctx = get_context()

    with patch("tools.context.emit_event") as mock_emit:
        ctx.set_translation("fr", "bonjour")

    assert ctx.get_translation("fr") == "bonjour"

    mock_emit.assert_called_once_with(
        "translation_ready", language="fr", transcript="bonjour"
    )


def test_translated_summary_roundtrip():
    ctx = get_context()

    ctx.set_translated_summary("es", ["uno", "dos"])
    assert ctx.get_translated_summary("es") == ["uno", "dos"]


# Snapshot Tests

def test_snapshot_structure():
    ctx = get_context()

    ctx.set_raw_transcript("raw")
    ctx.cleaned_transcript = "clean"
    ctx.summary = ["a"]

    snap = ctx.snapshot()

    assert snap["raw_transcript"] == "raw"
    assert snap["cleaned_transcript"] == "clean"
    assert snap["summary"] == ["a"]


def test_snapshot_json_serializable():
    ctx = get_context()

    ctx.set_raw_transcript("raw")
    json_str = ctx.snapshot_json()

    assert isinstance(json_str, str)
    assert "raw" in json_str


# Stem Generation Tests

def test_next_output_stem_no_conflict(tmp_path):
    from tools.context import TranscriptContext

    result = TranscriptContext._next_output_stem("file")
    assert result == "file"


def test_next_output_stem_with_conflicts(tmp_path, monkeypatch):
    from tools.context import TranscriptContext

    monkeypatch.setattr("tools.context.OUTPUT_DIR", tmp_path)

    (tmp_path / "file.json").touch()
    (tmp_path / "file_1.json").touch()

    result = TranscriptContext._next_output_stem("file")
    assert result == "file_2"