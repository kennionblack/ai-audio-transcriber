# def validate_json_structure(transcription: str) -> str:
#     """
#     Validate the JSON structure of the transcription.
#     """
#     print(f"---- Validating JSON structure ----")
#     return "JSON structure is valid"

import json
import re
from typing import Any


def _strip_code_fences(text: str) -> str:
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()
    return text.strip()


def _extract_json_candidate(text: str) -> str:
    cleaned = _strip_code_fences(text)
    if not cleaned:
        return ""

    first_curly = cleaned.find("{")
    first_bracket = cleaned.find("[")
    first_indices = [i for i in [first_curly, first_bracket] if i != -1]
    if not first_indices:
        return cleaned

    first = min(first_indices)
    last_curly = cleaned.rfind("}")
    last_bracket = cleaned.rfind("]")
    last_indices = [i for i in [last_curly, last_bracket] if i != -1]
    if not last_indices:
        return cleaned[first:]

    last = max(last_indices)
    if last <= first:
        return cleaned

    return cleaned[first:last + 1]


def _validate_segments(segments: list[Any]) -> list[str]:
    errors: list[str] = []
    for index, segment in enumerate(segments[:50]):
        if not isinstance(segment, dict):
            errors.append(f"segments[{index}] must be an object")
            break

        if "text" in segment and not isinstance(segment["text"], str):
            errors.append(f"segments[{index}].text must be a string")

        if "speaker" in segment and not isinstance(segment["speaker"], str):
            errors.append(f"segments[{index}].speaker must be a string")

        if "start" in segment and not isinstance(segment["start"], (int, float)):
            errors.append(f"segments[{index}].start must be a number")

        if "end" in segment and not isinstance(segment["end"], (int, float)):
            errors.append(f"segments[{index}].end must be a number")

        if "start" in segment and "end" in segment:
            start = segment.get("start")
            end = segment.get("end")
            if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                if end < start:
                    errors.append(f"segments[{index}] has end before start")

    return errors


def validate_json_structure(transcription: str) -> str:
    """
    Validate the JSON structure of the transcription.
    """
    print("---- Validating JSON structure ----")

    if not transcription or not transcription.strip():
        return "Invalid JSON: empty input"

    candidate = _extract_json_candidate(transcription)
    if not candidate:
        return "Invalid JSON: empty input"

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return f"Invalid JSON: {exc.msg} (line {exc.lineno}, col {exc.colno})"

    if not isinstance(payload, dict):
        return "Invalid JSON: top-level must be an object"

    errors: list[str] = []

    if "transcription" not in payload:
        errors.append("missing required field: transcription")

    if "summary" not in payload:
        errors.append("missing required field: summary")

    if "transcription" in payload and not isinstance(payload["transcription"], str):
        errors.append("transcription must be a string")

    if "text" in payload and not isinstance(payload["text"], str):
        errors.append("text must be a string")

    if "summary" in payload:
        summary = payload["summary"]
        if isinstance(summary, list):
            if not all(isinstance(item, str) for item in summary):
                errors.append("summary list must contain only strings")
        elif not isinstance(summary, str):
            errors.append("summary must be a string or list of strings")

    if "segments" in payload:
        segments = payload["segments"]
        if not isinstance(segments, list):
            errors.append("segments must be a list")
        else:
            errors.extend(_validate_segments(segments))

    if errors:
        return "Invalid JSON structure: " + "; ".join(errors)

    return "JSON structure is valid"