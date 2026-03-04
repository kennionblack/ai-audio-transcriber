import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools import print_verbose

# This allows us to set our own output directory in an env var if desired
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))

def _validate_transcript(value: str) -> list[str] | None:
    # only checking if string is empty here, we can extend this later if we define a more specific transcript format
    errors = []
    if not value.strip():
        errors.append("transcript must not be empty")
    return errors or None


def _validate_summary(bullets: list[str], min_bullets: int, max_bullets: int) -> list[str] | None:
    """Return a list of error strings if *bullets* violates constraints, or None if valid."""
    errors = []
    if not isinstance(bullets, list):
        return ["summary must be a list of strings"]
    for i, item in enumerate(bullets):
        if not isinstance(item, str):
            errors.append(f"summary[{i}] must be a string, got {type(item).__name__}")
        elif not item.strip():
            errors.append(f"summary[{i}] is empty")
    if len(bullets) < min_bullets:
        errors.append(f"summary has {len(bullets)} bullet(s), minimum is {min_bullets}")
    if len(bullets) > max_bullets:
        errors.append(f"summary has {len(bullets)} bullet(s), maximum is {max_bullets}")
    return errors or None

@dataclass
class TranscriptContext:
    raw_transcript: str | None = None
    cleaned_transcript: str | None = None
    # This field syntax makes the summary list mutable in a dataclass
    summary: list[str] = field(default_factory=list)
    # If we want to add metadata like audio duration, speaker names, or other relevant details we can store it here and have tools to set/get specific metadata keys as needed
    metadata: dict[str, Any] = field(default_factory=dict)
    audio_filename: str | None = None

    # These values are arbitrary, we can discuss what amount of bullet points should be generated 
    # If we want the user to choose their own amount of bullet points, we can write a tool to store that amount in this context and have the validation read from that instead of hardcoded values
    # Another alternative is to pass the desired number of bullet points as a command line arg, which might be nice for the gui as we can just modify the command that's run when the user kicks off the pipeline
    min_bullets: int = 3
    max_bullets: int = 15

    def set_raw_transcript(self, text: str) -> list[str] | None:
        errors = _validate_transcript(text)
        if errors:
            return errors
        self.raw_transcript = text
        print_verbose("[context] raw_transcript stored")
        return None

    def get_raw_transcript(self) -> str:
        if self.raw_transcript is None:
            return "[context] raw transcript not yet available"
        return self.raw_transcript

    def set_cleaned_transcript(self, text: str) -> list[str] | None:
        errors = _validate_transcript(text)
        if errors:
            return errors
        self.cleaned_transcript = text
        print_verbose("[context] cleaned_transcript stored")
        return None

    def get_cleaned_transcript(self) -> str:
        if self.cleaned_transcript is None:
            return "[context] cleaned transcript not yet available"
        return self.cleaned_transcript

    def set_summary(self, bullets: list[str]) -> list[str] | None:
        errors = _validate_summary(bullets, self.min_bullets, self.max_bullets)
        if errors:
            return errors
        self.summary = list(bullets)
        print_verbose(f"[context] summary stored ({len(bullets)} bullets)")
        self._on_complete()
        return None

    def get_summary(self) -> list[str]:
        return list(self.summary)

    def _on_complete(self) -> None:
        # Write JSON output to output_directory/file_name.json
        # Name conflicts write to file_name_1.json, file_name_2.json, etc. to avoid overwriting previous runs
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            base = Path(self.audio_filename).stem if self.audio_filename else "summary"
            filename = self._next_filename(base)
            payload = {
                "cleaned_transcript": self.cleaned_transcript,
                "summary": list(self.summary),
                "metadata": dict(self.metadata),
            }
            out_path = OUTPUT_DIR / filename
            out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
            print_verbose(f"[context] output written to {out_path}")
        except Exception as exc:
            print_verbose(f"[context] output write failed: {exc}")

    @staticmethod
    def _next_filename(base: str) -> str:
        first = f"{base}.json"
        if not (OUTPUT_DIR / first).exists():
            return first

        pattern = re.compile(rf"^{re.escape(base)}_(\d+)\.json$")
        highest = 0
        for entry in OUTPUT_DIR.iterdir():
            m = pattern.match(entry.name)
            if m:
                highest = max(highest, int(m.group(1)))
        return f"{base}_{highest + 1}.json"

    def set_metadata(self, key: str, value: Any) -> str:
        self.metadata[key] = value
        print_verbose(f"[context] metadata[{key!r}] set")
        return "ok"

    def snapshot(self) -> dict[str, Any]:
        """Return the full context as a JSON-serialisable dict."""
        return {
            "raw_transcript": self.raw_transcript,
            "cleaned_transcript": self.cleaned_transcript,
            "summary": list(self.summary),
            "metadata": dict(self.metadata),
        }

    def snapshot_json(self) -> str:
        return json.dumps(self.snapshot(), ensure_ascii=False)

_instance: TranscriptContext = TranscriptContext()

def get_context() -> TranscriptContext:
    return _instance

def _reset_context(**kwargs) -> TranscriptContext:
    """Reset singleton with an empty context for testing"""
    global _instance
    _instance = TranscriptContext(**kwargs)
    return _instance
