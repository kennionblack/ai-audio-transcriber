import json
from tools.context import get_context


def get_raw_transcript() -> str:
    """Return the raw transcript from the shared context. Blocks until available."""
    return get_context().get_raw_transcript()


def set_cleaned_transcript(text: str) -> str:
    """Store the cleaned transcript in the shared context.

    Validation runs automatically — the transcript must be a non-empty string.
    Returns 'ok' on success or a list of validation errors on failure.
    """
    errors = get_context().set_cleaned_transcript(text)
    if errors:
        return f"[validation_error] {'; '.join(errors)}"
    return "ok"


def set_summary(bullets_json: str, n_bullets: int) -> str:
    """Store summary bullet points in the shared context.

    *bullets_json* must be a JSON array of strings, e.g.:
      ["First point.", "Second point.", "Third point."]

    Validation ensures every element is a non-empty string and the total count
    falls within the configured min/max range. Returns 'ok' on success.
    """
    # Agents can't write lists directly, so we take the summary as a JSON string and convert it to a list
    try:
        bullets = json.loads(bullets_json)
    except json.JSONDecodeError as exc:
        return f"[validation_error] invalid JSON: {exc}"

    if not isinstance(bullets, list):
        return "[validation_error] expected a JSON array of strings"
    
    if len(bullets) > n_bullets:
        return "[validation_error] invalid number of bullet points"

    errors = get_context().set_summary(bullets)
    if errors:
        return f"[validation_error] {'; '.join(errors)}"
    return "ok"


def get_context_snapshot() -> str:
    """Return the full shared context (raw transcript, cleaned transcript, summary, metadata) as JSON."""
    return get_context().snapshot_json()


