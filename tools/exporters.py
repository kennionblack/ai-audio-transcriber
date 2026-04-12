from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from docx import Document
from fpdf import FPDF

# PDF layout constants. Units are in points (1/72 inch). These can be adjusted as needed
# for different formatting preferences.
PDF_MARGIN = 72
PDF_TEXT_SIZE = 11
PDF_TITLE_SIZE = 16
PDF_SECTION_SIZE = 13
PDF_LINE_HEIGHT = 15


PDF_FONT_FAMILY = "TranscriberSans"
PDF_FONT_FAMILY_CJK = "TranscriberSansCJK"
_FONTS_DIR = Path(__file__).parent.parent / "assets" / "fonts"
PDF_FONT_REGULAR = _FONTS_DIR / "font-regular.ttf"
PDF_FONT_BOLD = _FONTS_DIR / "font-bold.ttf"
PDF_FONT_CJK_REGULAR = _FONTS_DIR / "font-cjk-regular.ttf"
PDF_FONT_CJK_BOLD = _FONTS_DIR / "font-cjk-bold.ttf"
# Bundled CJK font used as the primary candidate, works on all platforms.
# The bundled font is committed to the repo at assets/fonts/ so it is always present.
PDF_CJK_FONT_CANDIDATES = (PDF_FONT_CJK_REGULAR,)



# This function takes the cleaned transcript, summary, and metadata, and writes them to JSON,
# DOCX, and PDF files in the specified output directory. It returns a dictionary with the paths
# to each of the generated files.
def write_outputs(
    *,
    output_dir: Path,
    stem: str,
    cleaned_transcript: str | None,
    summary: list[str],
    metadata: dict[str, Any],
    audio_filename: str | None = None,
    raw_transcript: str | None = None,
    title: str = "Audio Transcription Output",
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / f"{stem}.json"
    docx_path = output_dir / f"{stem}.docx"
    pdf_path = output_dir / f"{stem}.pdf"
    content = _build_export_content(
        audio_filename,
        cleaned_transcript,
        raw_transcript,
        summary,
        metadata,
        title,
    )
    json_path.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_docx(docx_path, content)
    _write_pdf(pdf_path, content)

    return {
        "json": json_path,
        "docx": docx_path,
        "pdf": pdf_path,
    }


# This helper function constructs a structured content dictionary that includes the audio filename,
# cleaned transcript (or raw transcript if cleaned is unavailable),
# summary, and
# metadata.
def _build_export_content(
    audio_filename: str | None,
    cleaned_transcript: str | None,
    raw_transcript: str | None,
    summary: list[str],
    metadata: dict[str, Any],
    title: str = "Audio Transcription Output",
) -> dict[str, Any]:
    transcript = (cleaned_transcript or raw_transcript or "").strip() or "[Transcript unavailable]"
    generated_at = datetime.now().astimezone().strftime("%m-%d-%Y %H:%M:%S %Z")
    return {
        "title": title,
        "generated_at": generated_at,
        "audio_filename": audio_filename,
        "metadata": dict(metadata),
        "summary": list(summary),
        "transcript_lines": transcript.splitlines() or [transcript],
    }


# The following two functions, _write_docx and _write_pdf,
# are responsible for generating the DOCX and PDF files respectively.
# They take the structured content dictionary and format it appropriately for each file type, including headings,
# paragraphs, and
# metadata sections.
def _write_docx(path: Path, content: dict[str, Any]) -> None:
    document = Document()
    document.add_heading(content["title"], level=1)

    if content["audio_filename"]:
        document.add_paragraph(f"Source Audio: {content['audio_filename']}")
    document.add_paragraph(f"Generated: {content['generated_at']}")


    document.add_heading("Summary", level=2)
    summary: list[str] = content["summary"]
    if summary:
        for bullet in summary:
            document.add_paragraph(f"- {bullet}")
    else:
        document.add_paragraph("[No summary available]")

    document.add_heading("Transcript", level=2)
    transcript_lines: list[str] = content["transcript_lines"]
    for line in transcript_lines:
        document.add_paragraph(line)

    document.save(str(path))


# The _write_pdf function creates a PDF file with a structured layout that includes the title,
# metadata,
# summary, and
# transcript.

def _write_pdf(path: Path, content: dict[str, Any]) -> None:
    pdf = FPDF(format="letter", unit="pt")
    pdf.set_title(content["title"])
    pdf.set_author("ai-audio-transcriber")
    pdf.set_creator("ai-audio-transcriber")
    pdf.set_margins(PDF_MARGIN, PDF_MARGIN, PDF_MARGIN)
    pdf.set_auto_page_break(auto=True, margin=PDF_MARGIN)
    pdf.set_compression(False)

    font_family = "Helvetica"
    cjk_registered = False
    try:
        if PDF_FONT_REGULAR.exists() and PDF_FONT_BOLD.exists():
            pdf.add_font(PDF_FONT_FAMILY, style="", fname=str(PDF_FONT_REGULAR))
            pdf.add_font(PDF_FONT_FAMILY, style="B", fname=str(PDF_FONT_BOLD))
            font_family = PDF_FONT_FAMILY

        fallback_family: str | None = None
        for candidate in PDF_CJK_FONT_CANDIDATES:
            if not candidate.exists():
                continue
            kwargs: dict[str, Any] = {}
            if candidate.suffix.lower() == ".ttc":
                kwargs["collection_font_number"] = 0
            pdf.add_font(PDF_FONT_FAMILY_CJK, style="", fname=str(candidate), **kwargs)
            fallback_family = PDF_FONT_FAMILY_CJK
            cjk_registered = True
            break

        if fallback_family is None and PDF_FONT_CJK_REGULAR.exists() and PDF_FONT_CJK_BOLD.exists():
            pdf.add_font(PDF_FONT_FAMILY_CJK, style="", fname=str(PDF_FONT_CJK_REGULAR))
            pdf.add_font(PDF_FONT_FAMILY_CJK, style="B", fname=str(PDF_FONT_CJK_BOLD))
            fallback_family = PDF_FONT_FAMILY_CJK
            cjk_registered = True

        if fallback_family is not None:
            # Use non-exact matching so CJK fallback still applies when style differs (e.g. bold headings).
            try:
                pdf.set_fallback_fonts([fallback_family], exact_match=False)
            except TypeError:
                pdf.set_fallback_fonts([fallback_family])

        if font_family == "Helvetica" and cjk_registered:
            font_family = fallback_family or PDF_FONT_FAMILY_CJK
    except Exception:
        # If custom font registration fails, fall back to a core PDF font.
        font_family = "Helvetica"

    pdf.add_page()

    _pdf_heading(pdf, content["title"], PDF_TITLE_SIZE, font_family)

    if content["audio_filename"]:
        _pdf_line(pdf, f"Source Audio: {content['audio_filename']}", font_family)
    _pdf_line(pdf, f"Generated: {content['generated_at']}", font_family)

    _pdf_heading(pdf, "Summary", PDF_SECTION_SIZE, font_family)
    summary: list[str] = content["summary"]
    if summary:
        for bullet in summary:
            _pdf_line(pdf, f"- {bullet}", font_family)
    else:
        _pdf_line(pdf, "[No summary available]", font_family)

    _pdf_heading(pdf, "Transcript", PDF_SECTION_SIZE, font_family)
    transcript_lines: list[str] = content["transcript_lines"]
    for line in transcript_lines:
        _pdf_line(pdf, line, font_family)

    pdf.output(str(path))


# The following two helper functions, _pdf_heading and _pdf_line,
# are used to format the headings and lines of text in the PDF document.
# The _pdf_heading function sets the font to bold and adjusts the size for section headings,
# while the _pdf_line function sets the font for regular text lines.
# Both functions handle line spacing and ensure that the text is properly aligned within the PDF layout.
def _pdf_heading(pdf: FPDF, text: str, size: int, font_family: str = PDF_FONT_FAMILY) -> None:
    pdf.ln(PDF_LINE_HEIGHT / 2)
    try:
        pdf.set_font(font_family, style="B", size=size)
    except Exception:
        # Some fallback font registrations may not have a bold variant.
        pdf.set_font(font_family, size=size)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(w=pdf.epw, h=PDF_LINE_HEIGHT, text=text)


# The _pdf_line function is responsible for writing a line of text to the PDF document.
# It sets the font to a regular style and the specified text size,
# then uses the multi_cell method to write the text with proper line
# spacing and alignment within the PDF's margins.
def _pdf_line(pdf: FPDF, text: str, font_family: str = PDF_FONT_FAMILY) -> None:
    pdf.set_font(font_family, size=PDF_TEXT_SIZE)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(w=pdf.epw, h=PDF_LINE_HEIGHT, text=text)
