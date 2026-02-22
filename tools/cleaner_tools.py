import json
import os
import re
from typing import Any
from openai import OpenAI

# We split filler words into 2 groups:
# 1) strict fillers: almost always noise ("um", "uh"), so we remove them
# 2) soft fillers: words like "like" / "I mean" that can affect tone, so we
#    remove them only when stronger cleanup is requested
_STRICT_FILLERS = [
    r"\bum+\b",
    r"\buh+\b",
    r"\ber+\b",
    r"\bah+\b",
    r"\bmm+\b",
    r"\bhmm+\b",
]

# These are softer filler phrases. Keep them by default, remove for stronger cleanup.
_SOFT_FILLERS = [
    r"\byou know\b",
    r"\bi mean\b",
    r"\blike\b",
    r"\bsort of\b",
    r"\bkind of\b",
]


def _clean_with_openai(transcript_text: str, mode: str, aggressiveness: str) -> tuple[str, str | None]:
    """
    Ask an OpenAI model to clean transcript text.
    Returns (cleaned_text, error_message). If error_message is not None, caller should fallback.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return transcript_text, "OPENAI_API_KEY is missing; used local cleaner fallback."

    if mode == "verbatim":
        return transcript_text, None

    cleanup_style = "strong" if aggressiveness == "aggressive" else "light"
    model = os.getenv("CLEANER_MODEL", "gpt-5-mini")
    client = OpenAI(api_key=api_key)

    system_prompt = (
        "You clean transcripts. Remove filler words and hesitation noise while preserving meaning, tone, "
        "proper nouns, and technical terms. Keep speaker labels and [inaudible]/[unclear] markers."
    )
    user_prompt = (
        f"Cleanup style: {cleanup_style}\n"
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
            return transcript_text, "OpenAI returned empty output; used local cleaner fallback."
        return cleaned, None
    except Exception as exc:
        return transcript_text, f"OpenAI cleaner failed ({exc}); used local cleaner fallback."


def _normalize_whitespace_and_punctuation(text: str) -> str:
    """Clean up spacing and punctuation after filler words are removed."""
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,.;:!?]){2,}", r"\1", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    text = re.sub(r"^[,;:\-]+\s*", "", text)
    return text


def _remove_patterns(line: str, patterns: list[str]) -> tuple[str, int]:
    """Remove matching filler patterns from one line and count removals."""
    cleaned = line
    total_removed = 0
    for pattern in patterns:
        # Handles punctuation around fillers too (example: ", um," or "- uh -").
        compiled = re.compile(
            rf"(?i)(?<!\w)[,;:\-]?\s*{pattern}\s*[,;:\-]?(?!\w)"
        )
        cleaned, count = compiled.subn(" ", cleaned)
        total_removed += count
    return cleaned, total_removed


def _collapse_hesitations(line: str) -> tuple[str, int]:
    """Convert stutters like 'I-I-I' into 'I'."""
    collapsed, count = re.subn(
        r"\b(\w+)(?:-\1){1,}\b",
        r"\1",
        line,
        flags=re.IGNORECASE,
    )
    return collapsed, count


def _clean_content_line(line: str, aggressiveness: str) -> tuple[str, dict[str, int]]:
    """Clean one line and return both the cleaned line and change counts."""
    stats = {"strict_fillers_removed": 0, "soft_fillers_removed": 0, "stutters_collapsed": 0}
    cleaned = line

    # Always remove strict fillers.
    cleaned, removed = _remove_patterns(cleaned, _STRICT_FILLERS)
    stats["strict_fillers_removed"] += removed

    # Remove soft fillers only when stronger cleanup is requested.
    if aggressiveness == "aggressive":
        cleaned, removed = _remove_patterns(cleaned, _SOFT_FILLERS)
        stats["soft_fillers_removed"] += removed

    cleaned, stutters = _collapse_hesitations(cleaned)
    stats["stutters_collapsed"] += stutters
    cleaned = _normalize_whitespace_and_punctuation(cleaned)
    return cleaned, stats


def _clean_plain_transcript(text: str, mode: str, aggressiveness: str) -> tuple[str, dict[str, int], list[str]]:
    """Clean transcript text line-by-line while preserving labels and line breaks."""
    # Verbatim mode means "do not change wording".
    if mode == "verbatim":
        return text.strip(), {
            "strict_fillers_removed": 0,
            "soft_fillers_removed": 0,
            "stutters_collapsed": 0,
            "empty_speaker_lines_dropped": 0,
        }, []

    warnings: list[str] = []
    totals = {
        "strict_fillers_removed": 0,
        "soft_fillers_removed": 0,
        "stutters_collapsed": 0,
        "empty_speaker_lines_dropped": 0,
    }
    cleaned_lines: list[str] = []

    for raw_line in text.splitlines():
        if not raw_line.strip():
            # Keep blank lines so paragraph spacing stays the same.
            cleaned_lines.append("")
            continue

        # If a line starts like "Speaker 1: ...", clean only the content part.
        match = re.match(r"^(\s*[\w .'-]{1,40}:\s*)(.*)$", raw_line)
        if match:
            prefix, content = match.groups()
            cleaned_content, stats = _clean_content_line(content, aggressiveness)
            for key in ("strict_fillers_removed", "soft_fillers_removed", "stutters_collapsed"):
                totals[key] += stats[key]

            # If nothing is left after cleaning, skip that speaker line.
            if cleaned_content:
                cleaned_lines.append(f"{prefix}{cleaned_content}".rstrip())
            else:
                totals["empty_speaker_lines_dropped"] += 1
        else:
            # Normal line without a speaker label.
            cleaned, stats = _clean_content_line(raw_line, aggressiveness)
            for key in ("strict_fillers_removed", "soft_fillers_removed", "stutters_collapsed"):
                totals[key] += stats[key]
            if cleaned:
                cleaned_lines.append(cleaned)

    result = "\n".join(cleaned_lines).rstrip()
    if not result:
        warnings.append("All transcript content was removed by cleaning rules.")
    return result, totals, warnings


def _parse_input_payload(text: str) -> tuple[dict[str, Any] | None, str]:
    """Try parsing input as JSON; if that fails, treat input as plain text."""
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


def _clean_segments(
    segments: list[dict[str, Any]],
    mode: str,
    aggressiveness: str,
) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    """Clean segment-based transcript input and keep non-text segment fields."""
    cleaned_segments: list[dict[str, Any]] = []
    totals = {
        "strict_fillers_removed": 0,
        "soft_fillers_removed": 0,
        "stutters_collapsed": 0,
        "empty_speaker_lines_dropped": 0,
    }
    warnings: list[str] = []

    for seg in segments:
        if not isinstance(seg, dict):
            warnings.append("Encountered non-object segment; skipped.")
            continue

        # Reuse the same text-cleaning logic used for regular transcripts.
        text_value = str(seg.get("text", ""))
        cleaned_text, stats, seg_warnings = _clean_plain_transcript(text_value, mode, aggressiveness)
        for key in totals:
            totals[key] += stats.get(key, 0)
        warnings.extend(seg_warnings)

        if cleaned_text:
            copied = dict(seg)
            copied["text"] = cleaned_text
            cleaned_segments.append(copied)

    return cleaned_segments, totals, warnings


def remove_filler_words(text: str) -> str:
    """
    Main cleaner function for the Cleaner agent.

    Input can be either:
    - plain transcript text
    - JSON payload with transcript/segments and settings

    If input is plain text:
    - returns cleaned plain text (for backward compatibility)

    If input is JSON:
    - returns a JSON string with cleaned text, stats, and warnings

    Example JSON payload:
    {
      "transcript": "Speaker 1: um hello",
      "mode": "cleaned",
      "aggressiveness": "balanced",
      "use_openai": true,
      "metadata": {...}
    }
    or
    {
      "segments": [{"start": 0.0, "end": 1.2, "speaker": "S1", "text": "uh hello"}],
      "mode": "verbatim"
    }
    """
    print("---- Removing filler words ----")

    if not text or not text.strip():
        return ""

    payload, _raw = _parse_input_payload(text)

    # Backward-compatible path: plain text in, plain text out.
    if payload is None:
        cleaned_text, _stats, _warnings = _clean_plain_transcript(
            text=text,
            mode="cleaned",
            aggressiveness="balanced",
        )
        return cleaned_text

    mode = str(payload.get("mode", "cleaned")).lower()
    if mode not in {"cleaned", "verbatim"}:
        mode = "cleaned"

    aggressiveness = str(payload.get("aggressiveness", "balanced")).lower()
    if aggressiveness not in {"balanced", "aggressive"}:
        aggressiveness = "balanced"
    use_openai = bool(payload.get("use_openai", False))

    metadata = payload.get("metadata", {})
    transcript = payload.get("transcript")
    segments = payload.get("segments")

    warnings: list[str] = []
    totals = {
        "strict_fillers_removed": 0,
        "soft_fillers_removed": 0,
        "stutters_collapsed": 0,
        "empty_speaker_lines_dropped": 0,
    }

    if isinstance(segments, list):
        # Segment input: clean each segment and also build a combined cleaned_text.
        cleaned_segments, seg_stats, seg_warnings = _clean_segments(segments, mode, aggressiveness)
        for key in totals:
            totals[key] += seg_stats.get(key, 0)
        warnings.extend(seg_warnings)
        cleaned_text = "\n".join(seg.get("text", "") for seg in cleaned_segments if seg.get("text")).strip()
    else:
        # JSON payload with transcript text.
        cleaned_segments = None
        base_text = str(transcript if transcript is not None else "")
        if use_openai:
            llm_cleaned, llm_error = _clean_with_openai(base_text, mode, aggressiveness)
            if llm_error:
                warnings.append(llm_error)
                cleaned_text, text_stats, text_warnings = _clean_plain_transcript(
                    text=base_text,
                    mode=mode,
                    aggressiveness=aggressiveness,
                )
            else:
                cleaned_text = llm_cleaned
                text_stats = {
                    "strict_fillers_removed": 0,
                    "soft_fillers_removed": 0,
                    "stutters_collapsed": 0,
                    "empty_speaker_lines_dropped": 0,
                }
                text_warnings = []
        else:
            cleaned_text, text_stats, text_warnings = _clean_plain_transcript(
                text=base_text,
                mode=mode,
                aggressiveness=aggressiveness,
            )

        for key in totals:
            totals[key] += text_stats.get(key, 0)
        warnings.extend(text_warnings)

    output: dict[str, Any] = {
        "mode": mode,
        "aggressiveness": aggressiveness,
        "use_openai": use_openai,
        "cleaned_text": cleaned_text,
        "metadata": metadata if isinstance(metadata, dict) else {},
        "stats": totals,
        "warnings": warnings,
    }
    if cleaned_segments is not None:
        output["segments"] = cleaned_segments
    return json.dumps(output, ensure_ascii=True)
