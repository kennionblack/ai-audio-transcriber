"""VoxAI web frontend with FastAPI + WebSocket for the transcriber pipeline."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import threading
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from runtime_events import EVENT_PREFIX
from tools.translation import SUPPORTED_LANGUAGES

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
UPLOAD_DIR = BASE_DIR / "uploads"
LOG_DIR = BASE_DIR / "logs"
BUNDLE_DIR = OUTPUT_DIR / "bundles"
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

SUPPORTED_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".flac"}
IDLE_STATUS = "Idle"
RUNNING_STATUS = "Running"
COMPLETED_STATUS = "Completed"
READY_NOTICE = "Ready. Upload audio and start a run."
SUMMARY_LOADING_TEXT = "Summary loading..."
MAX_TIMELINE_ITEMS = 12
MAX_LOOKUP_MATCHES_PER_SECTION = 6
LOOKUP_CONTEXT_CHARS = 45
LOG_TAIL_LINES = 150

app = FastAPI(title="VoxAI")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

STATE_LOCK = threading.RLock()
STATE = {
    "process": None,
    "status": IDLE_STATUS,
    "notice": READY_NOTICE,
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


class LookupPayload(BaseModel):
    query: str
    language: str | None = None


class BundlePayload(BaseModel):
    language: str | None = None


def _append_timeline_locked(label: str, detail: str) -> None:
    STATE["timeline"].append(
        {
            "time": datetime.now().strftime("%H:%M:%S"),
            "label": label,
            "detail": detail,
        }
    )
    STATE["timeline"] = STATE["timeline"][-MAX_TIMELINE_ITEMS:]


def _reset_outputs_locked() -> None:
    STATE["output"] = ""
    STATE["transcription_output"] = ""
    STATE["summary_output"] = ""
    STATE["translations"] = {}
    STATE["translated_summaries"] = {}
    STATE["pdf_output"] = None
    STATE["export_files"] = {}
    STATE["bundle_output"] = None
    STATE["translate_lang"] = None
    STATE["started_at"] = None
    STATE["completed_at"] = None
    STATE["timeline"] = []
    STATE["active_audio_name"] = None


def _language_value_to_code(language_value: str | None) -> str | None:
    if not language_value:
        return None
    code = str(language_value).strip().lower()
    return code if code in SUPPORTED_LANGUAGES else None


def _normalize_export_files(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def _find_translated_export(source_pdf_path: str | None, language_code: str, extension: str) -> str | None:
    if not source_pdf_path:
        return None
    source = Path(source_pdf_path)
    parent = source.parent if source.parent.exists() else OUTPUT_DIR
    pattern = re.compile(
        rf"^{re.escape(source.stem)}_{re.escape(language_code)}(?:_(\d+))?{re.escape(extension)}$",
        re.IGNORECASE,
    )
    best_path, highest = None, -1
    for path in parent.iterdir():
        match = pattern.match(path.name)
        if match:
            index = int(match.group(1)) if match.group(1) else 0
            if index > highest:
                best_path = path
                highest = index
    return str(best_path) if best_path else None


def _read_log_tail(log_path: Path | None) -> str:
    if not log_path or not log_path.exists():
        return ""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-LOG_TAIL_LINES:])


def _snapshot_state() -> dict:
    with STATE_LOCK:
        log_path = STATE["log_path"]
        snapshot = {
            "status": STATE["status"],
            "notice": STATE["notice"],
            "output": STATE["output"],
            "transcription_output": STATE["transcription_output"],
            "summary_output": STATE["summary_output"],
            "translations": dict(STATE["translations"]),
            "translated_summaries": dict(STATE["translated_summaries"]),
            "pdf_output": STATE["pdf_output"],
            "export_files": dict(STATE["export_files"]),
            "bundle_output": STATE["bundle_output"],
            "translate_lang": STATE["translate_lang"],
            "started_at": STATE["started_at"].isoformat() if STATE["started_at"] else None,
            "completed_at": STATE["completed_at"].isoformat() if STATE["completed_at"] else None,
            "timeline": list(STATE["timeline"]),
            "active_audio_name": STATE["active_audio_name"],
        }
    snapshot["log_tail"] = _read_log_tail(log_path)
    snapshot["supported_languages"] = SUPPORTED_LANGUAGES
    return snapshot


def _handle_event(process: subprocess.Popen, payload: dict) -> None:
    event_type = payload.get("type")
    with STATE_LOCK:
        if STATE["process"] is not process:
            return
    if event_type == "transcript_ready":
        with STATE_LOCK:
            STATE["transcription_output"] = str(payload.get("transcript", "")).strip()
            if not STATE["summary_output"]:
                STATE["summary_output"] = SUMMARY_LOADING_TEXT
            STATE["notice"] = "Transcript ready. Summary generation in progress."
            _append_timeline_locked("Transcript ready", "Cleaner returned transcript.")
        return
    if event_type == "summary_ready":
        bullets = payload.get("summary") or []
        summary = "\n".join(f"- {b}" for b in bullets if isinstance(b, str) and b.strip())
        with STATE_LOCK:
            STATE["summary_output"] = summary
            STATE["notice"] = "Summary ready. Preparing export files."
            _append_timeline_locked("Summary ready", f"{len([b for b in bullets if isinstance(b, str)])} bullets.")
        return
    if event_type == "translation_ready":
        language = str(payload.get("language", "")).strip().lower()
        transcript = str(payload.get("transcript", "")).strip()
        if language:
            with STATE_LOCK:
                STATE["translations"][language] = transcript
                STATE["notice"] = f"Translated transcript ready for {SUPPORTED_LANGUAGES.get(language, language)}."
                _append_timeline_locked("Translation ready", language)
        return
    if event_type == "translated_summary_ready":
        language = str(payload.get("language", "")).strip().lower()
        bullets = payload.get("summary") or []
        summary = "\n".join(f"- {b}" for b in bullets if isinstance(b, str) and b.strip())
        if language:
            with STATE_LOCK:
                STATE["translated_summaries"][language] = summary
                STATE["notice"] = f"Translated summary ready for {SUPPORTED_LANGUAGES.get(language, language)}."
                _append_timeline_locked("Translated summary ready", language)
        return
    if event_type == "export_files_ready":
        export_files = _normalize_export_files(payload.get("export_files"))
        with STATE_LOCK:
            STATE["export_files"] = export_files
            STATE["pdf_output"] = export_files.get("pdf")
            STATE["notice"] = "Export files ready."
            _append_timeline_locked("Exports ready", "JSON, DOCX, and PDF written.")
        return
    if event_type == "translation_complete":
        language = str(payload.get("language", "")).strip().lower() or "unknown"
        with STATE_LOCK:
            _append_timeline_locked("Translation complete", language)
        return
    if event_type == "final_result":
        with STATE_LOCK:
            STATE["output"] = str(payload.get("content", "")).strip()
            STATE["status"] = COMPLETED_STATUS
            STATE["completed_at"] = datetime.now()
            STATE["notice"] = "Run completed."
            _append_timeline_locked("Run completed", "Final package returned.")


def _reader_thread(process: subprocess.Popen) -> None:
    assert process.stdout is not None
    fallback_output_lines: list[str] = []
    with STATE_LOCK:
        log_path = STATE["log_path"]
    log_file = None
    if log_path:
        LOG_DIR.mkdir(exist_ok=True)
        log_file = log_path.open("a", encoding="utf-8")
    try:
        for line in process.stdout:
            stripped_line = line.rstrip("\n")
            if log_file is not None:
                log_file.write(stripped_line + "\n")
                log_file.flush()
            if stripped_line.startswith(EVENT_PREFIX):
                event_json = stripped_line[len(EVENT_PREFIX):].strip()
                try:
                    _handle_event(process, json.loads(event_json))
                except json.JSONDecodeError:
                    fallback_output_lines.append(stripped_line)
                continue
            fallback_output_lines.append(stripped_line)
            if len(fallback_output_lines) > 3000:
                fallback_output_lines = fallback_output_lines[-3000:]
    finally:
        if log_file is not None:
            log_file.close()
    return_code = process.wait()
    with STATE_LOCK:
        STATE["process"] = None
        if STATE["status"] == COMPLETED_STATUS:
            if not STATE["output"]:
                STATE["output"] = "\n".join(fallback_output_lines).strip()
            if STATE["completed_at"] is None:
                STATE["completed_at"] = datetime.now()
            return
        STATE["status"] = COMPLETED_STATUS if return_code == 0 else f"Failed (exit {return_code})"
        STATE["output"] = STATE["output"] or "\n".join(fallback_output_lines).strip()
        if STATE["status"] == COMPLETED_STATUS and not STATE["transcription_output"]:
            STATE["transcription_output"] = STATE["output"]
        STATE["completed_at"] = datetime.now()
        if STATE["status"].startswith("Failed"):
            STATE["notice"] = "Run failed. Check logs."
            _append_timeline_locked("Run failed", STATE["status"])
        else:
            STATE["notice"] = "Run completed."
            _append_timeline_locked("Run completed", "Process exited successfully.")


def _terminate_process_locked() -> None:
    process = STATE["process"]
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
    STATE["process"] = None


def _build_lookup_matches(section_name: str, text: str, query_pattern: re.Pattern[str]) -> list[str]:
    if not text.strip():
        return []
    snippets: list[str] = []
    for index, match in enumerate(query_pattern.finditer(text), start=1):
        start = max(0, match.start() - LOOKUP_CONTEXT_CHARS)
        end = min(len(text), match.end() + LOOKUP_CONTEXT_CHARS)
        snippets.append(f"{section_name}: ...{text[start:end].replace('\n', ' ').strip()}...")
        if index >= MAX_LOOKUP_MATCHES_PER_SECTION:
            break
    return snippets


@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "languages": SUPPORTED_LANGUAGES,
        },
    )


@app.get("/api/state")
async def get_state():
    return JSONResponse(_snapshot_state())


@app.websocket("/ws/state")
async def websocket_state(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(_snapshot_state())
            await asyncio.sleep(0.7)
    except WebSocketDisconnect:
        return


@app.post("/api/transcribe")
async def transcribe(audio_file: UploadFile = File(...), language: str | None = Form(None)):
    suffix = Path(audio_file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_AUDIO_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_SUFFIXES))
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Supported: {supported}")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{Path(audio_file.filename or 'audio').name}"
    upload_path = UPLOAD_DIR / safe_name
    data = await audio_file.read()
    upload_path.write_bytes(data)

    with STATE_LOCK:
        existing = STATE["process"]
        if existing is not None and existing.poll() is None:
            raise HTTPException(status_code=409, detail="A transcription is already running.")

    command = [sys.executable, "agent.py", "-v", "--mode", "auto", str(upload_path)]
    translate_lang = _language_value_to_code(language)
    if translate_lang:
        command.extend(["--translate", translate_lang])
    process = subprocess.Popen(
        command,
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    with STATE_LOCK:
        _reset_outputs_locked()
        STATE["process"] = process
        STATE["status"] = RUNNING_STATUS
        STATE["translate_lang"] = translate_lang
        STATE["started_at"] = datetime.now()
        STATE["notice"] = "Run started. Streaming updates."
        STATE["log_path"] = LOG_DIR / f"transcription-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        STATE["active_audio_name"] = upload_path.name
        _append_timeline_locked("Run started", upload_path.name)

    threading.Thread(target=_reader_thread, args=(process,), daemon=True).start()
    return JSONResponse(_snapshot_state())


@app.post("/api/clear")
async def clear_state():
    with STATE_LOCK:
        _terminate_process_locked()
        STATE["status"] = IDLE_STATUS
        STATE["notice"] = READY_NOTICE
        STATE["log_path"] = None
        _reset_outputs_locked()
    return JSONResponse(_snapshot_state())


@app.post("/api/lookup")
async def lookup(payload: LookupPayload):
    query = payload.query.strip()
    if not query:
        return {"result": "Enter a search term."}

    language_code = _language_value_to_code(payload.language)
    with STATE_LOCK:
        if language_code:
            transcript = (
                STATE["translations"].get(language_code)
                or STATE["transcription_output"]
                or STATE["output"]
                or ""
            )
            summary = (
                STATE["translated_summaries"].get(language_code)
                or STATE["summary_output"]
                or ""
            )
        else:
            transcript = STATE["transcription_output"] or STATE["output"] or ""
            summary = STATE["summary_output"] or ""
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    matches = _build_lookup_matches("Transcript", transcript, pattern)
    matches.extend(_build_lookup_matches("Summary", summary, pattern))
    return {"result": "\n".join(matches) if matches else f'No matches found for "{query}".'}


@app.post("/api/bundle")
async def create_bundle(payload: BundlePayload):
    language_code = _language_value_to_code(payload.language)
    with STATE_LOCK:
        status = str(STATE["status"])
        export_files = dict(STATE["export_files"])
        source_pdf = STATE["pdf_output"]
        run_language = STATE["translate_lang"]
        log_path = STATE["log_path"]
    if not status.startswith(COMPLETED_STATUS):
        raise HTTPException(status_code=400, detail="Complete a run before building a bundle.")

    sources: list[Path] = []
    for out_path in export_files.values():
        candidate = Path(out_path)
        if candidate.exists() and candidate.is_file():
            sources.append(candidate)

    if language_code and language_code == run_language:
        for extension in (".json", ".docx", ".pdf"):
            translated = _find_translated_export(source_pdf, language_code, extension)
            if translated:
                translated_path = Path(translated)
                if translated_path.exists() and translated_path.is_file():
                    sources.append(translated_path)

    if log_path and log_path.exists() and log_path.is_file():
        sources.append(log_path)

    if not sources:
        raise HTTPException(status_code=404, detail="No export files found.")

    unique_sources: list[Path] = []
    seen: set[str] = set()
    for source in sources:
        key = str(source.resolve())
        if key not in seen:
            seen.add(key)
            unique_sources.append(source)

    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base_stem = Path(source_pdf).stem if source_pdf else "transcriber-output"
    bundle_path = BUNDLE_DIR / f"{base_stem}-bundle-{timestamp}.zip"
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in unique_sources:
            folder = "logs" if source.suffix.lower() == ".log" else "exports"
            archive.write(source, arcname=f"{folder}/{source.name}")

    with STATE_LOCK:
        STATE["bundle_output"] = str(bundle_path)
        STATE["notice"] = f"Bundle ready: {bundle_path.name}"
        _append_timeline_locked("Bundle ready", bundle_path.name)

    return {"bundle_url": "/api/download/bundle", "bundle_name": bundle_path.name}


@app.get("/api/download/pdf")
async def download_pdf(language: str | None = None):
    language_code = _language_value_to_code(language)
    with STATE_LOCK:
        pdf_path = STATE["pdf_output"]
        run_language = STATE["translate_lang"]
    if language_code and language_code == run_language:
        translated = _find_translated_export(pdf_path, language_code, ".pdf")
        if translated:
            pdf_path = translated
    if not pdf_path:
        raise HTTPException(status_code=404, detail="No PDF available.")
    file_path = Path(pdf_path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="PDF file not found.")
    return FileResponse(path=file_path, filename=file_path.name, media_type="application/pdf")


@app.get("/api/download/docx")
async def download_docx(language: str | None = None):
    language_code = _language_value_to_code(language)
    with STATE_LOCK:
        docx_path = STATE["export_files"].get("docx")
        pdf_path = STATE["pdf_output"]
        run_language = STATE["translate_lang"]

    source_path = pdf_path or docx_path
    if language_code and language_code == run_language:
        translated = _find_translated_export(source_path, language_code, ".docx")
        if translated:
            docx_path = translated

    if not docx_path:
        raise HTTPException(status_code=404, detail="No DOCX available.")

    file_path = Path(docx_path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="DOCX file not found.")

    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.get("/api/download/json")
async def download_json(language: str | None = None):
    language_code = _language_value_to_code(language)
    with STATE_LOCK:
        json_path = STATE["export_files"].get("json")
        pdf_path = STATE["pdf_output"]
        run_language = STATE["translate_lang"]

    source_path = pdf_path or json_path
    if language_code and language_code == run_language:
        translated = _find_translated_export(source_path, language_code, ".json")
        if translated:
            json_path = translated

    if not json_path:
        raise HTTPException(status_code=404, detail="No JSON export available.")

    file_path = Path(json_path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="JSON file not found.")

    return FileResponse(path=file_path, filename=file_path.name, media_type="application/json")


@app.get("/api/download/bundle")
async def download_bundle():
    with STATE_LOCK:
        bundle_path = STATE["bundle_output"]
    if not bundle_path:
        raise HTTPException(status_code=404, detail="No bundle available.")
    file_path = Path(bundle_path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Bundle file not found.")
    return FileResponse(path=file_path, filename=file_path.name, media_type="application/zip")


@app.on_event("startup")
async def startup_event():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=7860)
