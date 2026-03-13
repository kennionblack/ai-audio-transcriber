from __future__ import annotations

import json
import textwrap
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


PDF_PAGE_WIDTH = 612
PDF_PAGE_HEIGHT = 792
PDF_MARGIN = 72
PDF_FONT_SIZE = 11
PDF_LEADING = 14
PDF_WRAP_WIDTH = 92


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

    payload = {
        "cleaned_transcript": cleaned_transcript,
        "summary": list(summary),
        "metadata": dict(metadata),
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    paragraphs = _build_document_paragraphs(
        audio_filename=audio_filename,
        cleaned_transcript=cleaned_transcript,
        raw_transcript=raw_transcript,
        summary=summary,
        metadata=metadata,
    )
    _write_docx(docx_path, paragraphs)
    _write_pdf(pdf_path, paragraphs)

    return {
        "json": json_path,
        "docx": docx_path,
        "pdf": pdf_path,
    }


def _build_document_paragraphs(
    *,
    audio_filename: str | None,
    cleaned_transcript: str | None,
    raw_transcript: str | None,
    summary: list[str],
    metadata: dict[str, Any],
) -> list[str]:
    transcript = (cleaned_transcript or raw_transcript or "").strip() or "[Transcript unavailable]"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

    paragraphs = [
        "Audio Transcription Output",
        f"Generated: {generated_at}",
    ]

    if audio_filename:
        paragraphs.insert(1, f"Source Audio: {audio_filename}")

    if metadata:
        paragraphs.extend(["", "METADATA"])
        for key, value in sorted(metadata.items()):
            paragraphs.append(f"{key}: {value}")

    paragraphs.extend(["", "SUMMARY"])
    if summary:
        paragraphs.extend(f"- {bullet}" for bullet in summary)
    else:
        paragraphs.append("[No summary available]")

    paragraphs.extend(["", "TRANSCRIPT"])
    transcript_lines = transcript.splitlines() or [transcript]
    paragraphs.extend(transcript_lines)

    return paragraphs


def _write_docx(path: Path, paragraphs: list[str]) -> None:
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    document_body = "".join(_docx_paragraph_xml(paragraph) for paragraph in paragraphs)

    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"
 xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"
 xmlns:v="urn:schemas-microsoft-com:vml"
 xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:w10="urn:schemas-microsoft-com:office:word"
 xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"
 xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"
 xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk"
 xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml"
 xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
 mc:Ignorable="w14 wp14">
  <w:body>
    {document_body}
    <w:sectPr>
      <w:pgSz w:w="12240" w:h="15840"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>
"""

    content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""

    package_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""

    document_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>
"""

    core_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:dcmitype="http://purl.org/dc/dcmitype/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Audio Transcription Output</dc:title>
  <dc:creator>ai-audio-transcriber</dc:creator>
  <cp:lastModifiedBy>ai-audio-transcriber</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{created_at}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{created_at}</dcterms:modified>
</cp:coreProperties>
"""

    app_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
 xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>ai-audio-transcriber</Application>
</Properties>
"""

    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", package_rels_xml)
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/_rels/document.xml.rels", document_rels_xml)
        archive.writestr("docProps/core.xml", core_xml)
        archive.writestr("docProps/app.xml", app_xml)


def _docx_paragraph_xml(text: str) -> str:
    if text == "":
        return "<w:p/>"

    escaped = escape(text)
    return (
        "<w:p>"
        "<w:r>"
        f'<w:t xml:space="preserve">{escaped}</w:t>'
        "</w:r>"
        "</w:p>"
    )


def _write_pdf(path: Path, paragraphs: list[str]) -> None:
    wrapped_lines = _wrap_pdf_lines(paragraphs)
    lines_per_page = max(1, int((PDF_PAGE_HEIGHT - (PDF_MARGIN * 2)) / PDF_LEADING))
    pages = [
        wrapped_lines[i : i + lines_per_page]
        for i in range(0, len(wrapped_lines), lines_per_page)
    ] or [["[No content available]"]]

    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    }

    kids: list[str] = []
    next_object_id = 4

    for page_lines in pages:
        page_object_id = next_object_id
        content_object_id = next_object_id + 1
        next_object_id += 2

        kids.append(f"{page_object_id} 0 R")
        stream = _pdf_stream(page_lines)

        objects[page_object_id] = (
            "<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 {PDF_PAGE_WIDTH} {PDF_PAGE_HEIGHT}] "
            "/Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {content_object_id} 0 R >>"
        ).encode("ascii")
        objects[content_object_id] = (
            f"<< /Length {len(stream)} >>\n".encode("ascii")
            + b"stream\n"
            + stream
            + b"\nendstream"
        )

    objects[2] = (
        f"<< /Type /Pages /Count {len(pages)} /Kids [{' '.join(kids)}] >>"
    ).encode("ascii")

    max_object_id = max(objects)
    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (max_object_id + 1)

    for object_id in range(1, max_object_id + 1):
        offsets[object_id] = len(pdf)
        pdf.extend(f"{object_id} 0 obj\n".encode("ascii"))
        pdf.extend(objects[object_id])
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {max_object_id + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")

    for object_id in range(1, max_object_id + 1):
        pdf.extend(f"{offsets[object_id]:010d} 00000 n \n".encode("ascii"))

    pdf.extend(
        (
            f"trailer\n<< /Size {max_object_id + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(pdf)


def _wrap_pdf_lines(paragraphs: list[str]) -> list[str]:
    wrapped: list[str] = []

    for paragraph in paragraphs:
        if paragraph == "":
            wrapped.append("")
            continue

        continuation = "  " if paragraph.startswith("- ") else ""
        lines = textwrap.wrap(
            paragraph,
            width=PDF_WRAP_WIDTH,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
            drop_whitespace=False,
            subsequent_indent=continuation,
        )
        wrapped.extend(lines or [""])

    return wrapped


def _pdf_stream(lines: list[str]) -> bytes:
    start_y = PDF_PAGE_HEIGHT - PDF_MARGIN
    commands = [
        b"BT",
        f"/F1 {PDF_FONT_SIZE} Tf".encode("ascii"),
        f"{PDF_LEADING} TL".encode("ascii"),
        f"{PDF_MARGIN} {start_y} Td".encode("ascii"),
    ]

    for index, line in enumerate(lines):
        if index > 0:
            commands.append(b"T*")
        commands.append(b"(" + _pdf_escape_text(line) + b") Tj")

    commands.append(b"ET")
    return b"\n".join(commands)


def _pdf_escape_text(text: str) -> bytes:
    normalized = unicodedata.normalize("NFKC", text)
    encoded = normalized.encode("cp1252", errors="replace")
    encoded = encoded.replace(b"\\", b"\\\\")
    encoded = encoded.replace(b"(", b"\\(")
    encoded = encoded.replace(b")", b"\\)")
    return encoded
