from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from openai import AsyncOpenAI

from runtime_events import emit_event
from tools.context import get_context
from tools.exporters import write_outputs
from tools import print_verbose

# Supported translation languages, we can change this if we want
SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "zh": "Chinese (Simplified)",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "ja": "Japanese",
    "ko": "Korean",
    "pt": "Portuguese",
    "ar": "Arabic",
    "ru": "Russian",
}


def parse_language(raw: str) -> str:
    code = raw.strip().lower()
    if not code:
        print("Error: a language code is required.")
        sys.exit(1)

    if code not in SUPPORTED_LANGUAGES:
        supported = ", ".join(f"{k} ({v})" for k, v in SUPPORTED_LANGUAGES.items())
        print(
            f"Error: unsupported language '{code}'\n"
            f"Supported: {supported}",
        )
        sys.exit(1)

    return code


async def translate_text(
    text: str,
    target_language: str,
) -> str:
    if not text.strip():
        raise ValueError("Cannot translate empty text.")

    lang_name = SUPPORTED_LANGUAGES[target_language]

    system_prompt = (
        f"You are a professional translator. Translate the following text "
        f"into {lang_name}. Preserve the original paragraph "
        f"structure, formatting, and tone. Return only the translated text "
        f"with no commentary or explanation."
    )

    client = AsyncOpenAI()

    response = await client.chat.completions.create(
        # This model seems to do better with translation than gpt-5-mini, which is the default elsewhere
        model="gpt-5.4-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
    )

    return response.choices[0].message.content.strip()


async def _translate_to_language(
    transcript: str,
    summary: list[str],
    lang: str,
    stem: str,
    output_dir: Path,
    metadata: dict,
    audio_filename: str | None,
) -> None:
    lang_name = SUPPORTED_LANGUAGES[lang]
    print_verbose(f"[translate] translating to {lang_name} ({lang}) ...")

    translated = await translate_text(transcript, lang)

    # Concurrently translate each bullet point to avoid api call bottleneck when lots of bullet points are present
    translated_summary = await asyncio.gather(
        *(translate_text(bullet, lang) for bullet in summary)
    )

    ctx = get_context()
    ctx.set_translation(lang, translated)
    ctx.set_translated_summary(lang, translated_summary)

    paths = write_outputs(
        output_dir=output_dir,
        stem=f"{stem}_{lang}",
        cleaned_transcript=translated,
        summary=translated_summary,
        metadata={**metadata, "language": lang, "language_name": lang_name},
        audio_filename=audio_filename,
        # We can decide a better title string if we care about this
        title=f"Translation \u2014 {lang_name} ({lang})",
    )
    for fmt, p in paths.items():
        print_verbose(f"[translate] {fmt} -> {p}")


async def run_translation(
    language: str,
    output_dir: Path,
    stem: str,
) -> None:
    ctx = get_context()

    transcript = ctx.cleaned_transcript or ""
    if not transcript.strip():
        print("Error: no cleaned transcript available for translation.")
        return

    summary = ctx.get_summary()
    metadata = dict(ctx.metadata)
    audio_filename = ctx.audio_filename

    await _translate_to_language(
        transcript,
        summary,
        language,
        stem=stem,
        output_dir=output_dir,
        metadata=metadata,
        audio_filename=audio_filename,
    )

    emit_event("translation_complete", text=language)
    print_verbose(f"[translate] translation to {language} complete")