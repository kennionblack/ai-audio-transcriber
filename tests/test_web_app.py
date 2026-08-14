import asyncio
import json
import shutil

import pytest

import web_app
from runtime_events import EVENT_PREFIX


@pytest.fixture(autouse=True)
def restore_state():
    with web_app.STATE_LOCK:
        original = {
            key: value.copy() if isinstance(value, (dict, list)) else value for key, value in web_app.STATE.items()
        }
    yield
    with web_app.STATE_LOCK:
        web_app.STATE.clear()
        web_app.STATE.update(original)


class DummyProcess:
    def __init__(self, stdout_lines: list[str], return_code: int):
        self.stdout = iter(stdout_lines)
        self.return_code = return_code

    def wait(self) -> int:
        return self.return_code


def prepare_reader_state(process: DummyProcess) -> None:
    with web_app.STATE_LOCK:
        web_app.STATE.update(
            {
                "process": process,
                "status": web_app.RUNNING_STATUS,
                "notice": "Run started. Streaming updates.",
                "output": "",
                "transcription_output": "",
                "summary_output": "",
                "translations": {},
                "translated_summaries": {},
                "pdf_output": None,
                "export_files": {},
                "bundle_output": None,
                "translate_lang": None,
                "started_at": None,
                "completed_at": None,
                "timeline": [],
                "log_path": None,
                "active_audio_name": None,
            }
        )


def final_result_line(content: str) -> str:
    return f"{EVENT_PREFIX} {json.dumps({'type': 'final_result', 'content': content})}\n"


def test_reader_thread_nonzero_exit_overrides_final_result_completed_status():
    process = DummyProcess([final_result_line("Final output")], return_code=1)
    prepare_reader_state(process)

    web_app._reader_thread(process)

    with web_app.STATE_LOCK:
        assert web_app.STATE["process"] is None
        assert web_app.STATE["status"] == "Failed (exit 1)"
        assert web_app.STATE["notice"] == "Run failed. Check logs."
        assert web_app.STATE["output"] == "Final output"
        assert web_app.STATE["timeline"][-1]["label"] == "Run failed"


def test_reader_thread_zero_exit_keeps_final_result_completed_status():
    process = DummyProcess([final_result_line("Final output")], return_code=0)
    prepare_reader_state(process)

    web_app._reader_thread(process)

    with web_app.STATE_LOCK:
        assert web_app.STATE["process"] is None
        assert web_app.STATE["status"] == web_app.COMPLETED_STATUS
        assert web_app.STATE["notice"] == "Run completed."
        assert web_app.STATE["output"] == "Final output"


def test_read_log_tail_limits_bytes_for_single_line_log(monkeypatch):
    log_path = web_app.BASE_DIR / ".tmp" / "test-web-app-tail.log"
    log_path.parent.mkdir(exist_ok=True)
    log_path.write_bytes(b"0123456789abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setattr(web_app, "LOG_TAIL_MAX_BYTES", 8)

    try:
        assert web_app._read_log_tail(log_path) == "stuvwxyz"
    finally:
        log_path.unlink(missing_ok=True)


def test_upload_path_for_name_rejects_path_traversal(monkeypatch):
    upload_dir = web_app.BASE_DIR / ".tmp" / "test-web-app-uploads"
    monkeypatch.setattr(web_app, "UPLOAD_DIR", upload_dir)

    with pytest.raises(web_app.HTTPException) as exc_info:
        web_app._upload_path_for_name("../audio.mp3")

    assert exc_info.value.status_code == 400


def test_delete_uploads_removes_selected_files_and_returns_remaining(monkeypatch):
    upload_dir = web_app.BASE_DIR / ".tmp" / "test-web-app-uploads"
    shutil.rmtree(upload_dir, ignore_errors=True)
    upload_dir.mkdir(parents=True)
    delete_path = upload_dir / "delete-me.mp3"
    keep_path = upload_dir / "keep-me.wav"
    ignored_path = upload_dir / "notes.txt"
    delete_path.write_bytes(b"delete")
    keep_path.write_bytes(b"keep")
    ignored_path.write_text("ignore", encoding="utf-8")
    monkeypatch.setattr(web_app, "UPLOAD_DIR", upload_dir)

    try:
        result = asyncio.run(web_app.delete_uploads(web_app.DeleteUploadsPayload(file_names=["delete-me.mp3"])))
        assert result["deleted"] == ["delete-me.mp3"]
        assert result["missing"] == []
        assert not delete_path.exists()
        assert keep_path.exists()
        assert [file["name"] for file in result["files"]] == ["keep-me.wav"]
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)
