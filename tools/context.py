import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.exporters import write_outputs
from tools import print_verbose
from runtime_events import emit_event

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
    # Translations keyed by language code (e.g. {"zh": "...", "fr": "..."})
    translations: dict[str, str] = field(default_factory=dict)
    # Translated summaries keyed by language code (e.g. {"zh": ["...", "..."], "fr": ["...", "..."]})
    translated_summaries: dict[str, list[str]] = field(default_factory=dict)
    # Callback invoked when transcription completed, currently used to trigger translation when language specified
    on_translation_ready: Any = None

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
        emit_event("transcript_ready", transcript=text)
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
        emit_event("summary_ready", summary=list(bullets))
        self._on_complete()
        return None

    def get_summary(self) -> list[str]:
        return list(self.summary)

    def _on_complete(self) -> None:
        # Write aligned output artifacts with a shared stem.
        try:
            base = Path(self.audio_filename).stem if self.audio_filename else "summary"
            stem = self._next_output_stem(base)
            artifact_paths = write_outputs(
                output_dir=OUTPUT_DIR,
                stem=stem,
                cleaned_transcript=self.cleaned_transcript,
                summary=list(self.summary),
                metadata=dict(self.metadata),
                audio_filename=self.audio_filename,
                raw_transcript=self.raw_transcript,
            )
            for format_name, out_path in artifact_paths.items():
                print_verbose(f"[context] {format_name} output written to {out_path}")
            emit_event(
                "export_files_ready",
                export_files={format_name: str(out_path) for format_name, out_path in artifact_paths.items()},
            )
        except Exception as exc:
            print_verbose(f"[context] output write failed: {exc}")
            print(f"[context] output write failed: {exc}")

        if self.on_translation_ready is not None:
            self.on_translation_ready(stem)

    @staticmethod
    def _next_output_stem(base: str) -> str:
        extensions = {".json", ".docx", ".pdf"}
        if not OUTPUT_DIR.exists():
            return base

        if not any((OUTPUT_DIR / f"{base}{extension}").exists() for extension in extensions):
            return base

        pattern = re.compile(rf"^{re.escape(base)}(?:_(\d+))?$")
        highest = 0
        for entry in OUTPUT_DIR.iterdir():
            if entry.suffix.lower() not in extensions:
                continue
            m = pattern.match(entry.stem)
            if m:
                suffix = m.group(1)
                highest = max(highest, int(suffix) if suffix else 0)
        return f"{base}_{highest + 1}"

    def set_translation(self, language_code: str, text: str) -> list[str] | None:
        # Reusing _validate_transcript here might be risky with different languages
        # For the moment it just checks for an empty string but that could be tightened later
        errors = _validate_transcript(text)
        if errors:
            return errors
        self.translations[language_code] = text
        print_verbose(f"[context] translation[{language_code!r}] stored")
        emit_event("translation_ready", language=language_code, transcript=text)
        return

    def get_translation(self, language_code: str) -> str | None:
        return self.translations.get(language_code)

    def set_translated_summary(self, language_code: str, bullets: list[str]) -> None:
        self.translated_summaries[language_code] = list(bullets)
        print_verbose(f"[context] translated_summary[{language_code!r}] stored ({len(bullets)} bullets)")
        emit_event("translated_summary_ready", language=language_code, summary=list(bullets))

    def get_translated_summary(self, language_code: str) -> list[str] | None:
        return self.translated_summaries.get(language_code)

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
            "translations": dict(self.translations),
            "translated_summaries": {k: list(v) for k, v in self.translated_summaries.items()},
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
