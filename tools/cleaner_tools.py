import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_DEFAULT_MODEL = "gpt-5-mini"


def _base_stats() -> dict[str, int]:
    return {
        "strict_fillers_removed": 0,
        "soft_fillers_removed": 0,
        "stutters_collapsed": 0,
        "empty_speaker_lines_dropped": 0,
    }


def _clean_with_openai(transcript_text: str) -> tuple[str, str | None]:
    """Clean transcript text with the OpenAI API."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return transcript_text, "OPENAI_API_KEY is missing."

    model = os.getenv("CLEANER_MODEL", _DEFAULT_MODEL)
    client = OpenAI(api_key=api_key)

    system_prompt = (
        "You clean transcripts. Remove filler words and hesitation noise while preserving meaning, tone, "
        "proper nouns, and technical terms. Keep speaker labels and [inaudible]/[unclear] markers."
    )
    user_prompt = (
        "Return only cleaned transcript text, no explanation.\n\n"
        f"{transcript_text}"
    )

    try:
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        cleaned = (response.output_text or "").strip()
        if not cleaned:
            return transcript_text, "OpenAI returned empty output."
        return cleaned, None
    except Exception as exc:
        return transcript_text, f"OpenAI cleaner failed ({exc})."


def _parse_input_payload(text: str) -> tuple[dict[str, Any] | None, str]:
    """Try parsing input as JSON; if parsing fails, treat input as plain text."""
    raw = (text or "").strip()
    if not raw:
        return None, ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None, raw

    if isinstance(parsed, dict):
        return parsed, raw
    return None, raw


def remove_filler_words(text: str) -> str:
    """Clean transcript text with OpenAI. Expects a JSON payload string."""
    if not text or not text.strip():
        return ""

    payload, _raw = _parse_input_payload(text)

    # JSON-only input path.
    if payload is None:
        return "[cleaner_error] JSON payload required. Use {'transcript': '...'}."

    metadata = payload.get("metadata", {})
    transcript = payload.get("transcript")
    if transcript is None:
        return "[cleaner_error] JSON payload must include 'transcript'."

    warnings: list[str] = []
    base_text = str(transcript)
    cleaned_text, error = _clean_with_openai(base_text)
    if error:
        warnings.append(error)
        cleaned_text = base_text

    output: dict[str, Any] = {
        "mode": "cleaned",
        "use_openai": True,
        "cleaned_text": cleaned_text,
        "metadata": metadata if isinstance(metadata, dict) else {},
        "stats": _base_stats(),
        "warnings": warnings,
    }
    return json.dumps(output, ensure_ascii=True)
