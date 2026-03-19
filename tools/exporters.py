from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from docx import Document
from fpdf import FPDF

# PDF layout constants. Units are in points (1/72 inch). These can be adjusted as needed for different formatting preferences.
PDF_MARGIN = 72
PDF_TEXT_SIZE = 11
PDF_TITLE_SIZE = 16
PDF_SECTION_SIZE = 13
PDF_LINE_HEIGHT = 15

# Text replacements for handling Unicode punctuation in PDF generation. This mapping replaces common Unicode punctuation characters with their ASCII equivalents to ensure better compatibility and appearance in the generated PDF files.
PDF_TEXT_REPLACEMENTS = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
        "\u2022": "-",
        "\u00a0": " ",
    }
)


# This function takes the cleaned transcript, summary, and metadata, and writes them to JSON, DOCX, and PDF files in the specified output directory. It returns a dictionary with the paths to each of the generated files.
def write_outputs(
    *,
    output_dir: Path,
    stem: str,
    cleaned_transcript: str | None,
    summary: list[str],
    metadata: dict[str, Any],
    audio_filename: str | None = None,
    raw_transcript: str | None = None,
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
    )
    json_path.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_docx(docx_path, content)
    _write_pdf(pdf_path, content)

    return {
        "json": json_path,
        "docx": docx_path,
        "pdf": pdf_path,
    }


# This helper function constructs a structured content dictionary that includes the audio filename, cleaned transcript (or raw transcript if cleaned is unavailable), summary, and metadata. This structured content is then used by the DOCX and PDF writing functions to generate the respective files with consistent formatting and information.
def _build_export_content(
    *,
    audio_filename: str | None,
    cleaned_transcript: str | None,
    raw_transcript: str | None,
    summary: list[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    transcript = (cleaned_transcript or raw_transcript or "").strip() or "[Transcript unavailable]"
    generated_at = datetime.now().astimezone().strftime("%m-%d-%Y %H:%M:%S %Z")
    return {
        "title": "Audio Transcription Output",
        "generated_at": generated_at,
        "audio_filename": audio_filename,
        "metadata": dict(metadata),
        "summary": list(summary),
        "transcript_lines": transcript.splitlines() or [transcript],
    }


# The following two functions, _write_docx and _write_pdf, are responsible for generating the DOCX and PDF files respectively. They take the structured content dictionary and format it appropriately for each file type, including headings, paragraphs, and metadata sections. The DOCX file is created using the python-docx library, while the PDF file is created using the FPDF library with specific layout settings for margins, font sizes, and line heights to ensure a clean and readable output.
def _write_docx(path: Path, content: dict[str, Any]) -> None:
    document = Document()
    document.add_heading(content["title"], level=1)

    if content["audio_filename"]:
        document.add_paragraph(f"Source Audio: {content['audio_filename']}")
    document.add_paragraph(f"Generated: {content['generated_at']}")

    metadata: dict[str, Any] = content["metadata"]
    if metadata:
        document.add_heading("Metadata", level=2)
        for key, value in sorted(metadata.items()):
            document.add_paragraph(f"{key}: {value}")

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


# The _write_pdf function creates a PDF file with a structured layout that includes the title, metadata, summary, and transcript. It uses the FPDF library to set up the document with specific margins and font sizes, and it formats the content with headings and line spacing for readability. The function handles cases where certain pieces of information may be unavailable, ensuring that the PDF still provides a clear and organized presentation of the available data.
def _write_pdf(path: Path, content: dict[str, Any]) -> None:
    pdf = FPDF(format="letter", unit="pt")
    pdf.set_title(content["title"])
    pdf.set_author("ai-audio-transcriber")
    pdf.set_creator("ai-audio-transcriber")
    pdf.set_margins(PDF_MARGIN, PDF_MARGIN, PDF_MARGIN)
    pdf.set_auto_page_break(auto=True, margin=PDF_MARGIN)
    pdf.set_compression(False)
    pdf.add_page()

    _pdf_heading(pdf, content["title"], PDF_TITLE_SIZE)

    if content["audio_filename"]:
        _pdf_line(pdf, f"Source Audio: {content['audio_filename']}")
    _pdf_line(pdf, f"Generated: {content['generated_at']}")

    metadata: dict[str, Any] = content["metadata"]
    if metadata:
        _pdf_heading(pdf, "Metadata", PDF_SECTION_SIZE)
        for key, value in sorted(metadata.items()):
            _pdf_line(pdf, f"{key}: {value}")

    _pdf_heading(pdf, "Summary", PDF_SECTION_SIZE)
    summary: list[str] = content["summary"]
    if summary:
        for bullet in summary:
            _pdf_line(pdf, f"- {bullet}")
    else:
        _pdf_line(pdf, "[No summary available]")

    _pdf_heading(pdf, "Transcript", PDF_SECTION_SIZE)
    transcript_lines: list[str] = content["transcript_lines"]
    for line in transcript_lines:
        _pdf_line(pdf, line)

    pdf.output(str(path))


# The following two helper functions, _pdf_heading and _pdf_line, are used to format the headings and lines of text in the PDF document. The _pdf_heading function sets the font to bold and adjusts the size for section headings, while the _pdf_line function sets the font for regular text lines. Both functions handle line spacing and ensure that the text is properly aligned within the PDF layout.
def _pdf_heading(pdf: FPDF, text: str, size: int) -> None:
    pdf.ln(PDF_LINE_HEIGHT / 2)
    pdf.set_font("Helvetica", style="B", size=size)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(w=pdf.epw, h=PDF_LINE_HEIGHT, text=_pdf_safe_text(text))


# The _pdf_line function is responsible for writing a line of text to the PDF document. It sets the font to a regular style and the specified text size, then uses the multi_cell method to write the text with proper line spacing and alignment within the PDF's margins.
def _pdf_line(pdf: FPDF, text: str) -> None:
    pdf.set_font("Helvetica", size=PDF_TEXT_SIZE)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(w=pdf.epw, h=PDF_LINE_HEIGHT, text=_pdf_safe_text(text))

# This function takes a string of text and applies Unicode normalization and character replacements to ensure that the text is compatible with the PDF generation process.
def _pdf_safe_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).translate(PDF_TEXT_REPLACEMENTS)
    return normalized.encode("latin-1", errors="replace").decode("latin-1")

