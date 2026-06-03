"""Document parser supporting PDF, CSV, MD, DOCX, and TXT files."""

import csv
import io
from pathlib import Path


async def parse_document(file_path: str, file_type: str) -> tuple[str, dict]:
    """Parse a document and return (extracted_text, metadata)."""
    ext = file_type.lower()
    if ext == "pdf":
        return _parse_pdf(file_path)
    elif ext == "csv":
        return _parse_csv(file_path)
    elif ext == "md":
        return _parse_md(file_path)
    elif ext == "docx":
        return _parse_docx(file_path)
    elif ext == "txt":
        return _parse_txt(file_path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def _parse_pdf(file_path: str) -> tuple[str, dict]:
    text_parts = []
    page_count = 0
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t.strip())
    except ImportError:
        raise ImportError("pdfplumber is required for PDF parsing")
    return "\n\n".join(text_parts), {"page_count": page_count, "parser": "pdfplumber"}


def _parse_csv(file_path: str) -> tuple[str, dict]:
    text_parts = []
    row_count = 0
    with open(file_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_text = " | ".join(f"{k}: {v}" for k, v in row.items())
            text_parts.append(row_text)
            row_count += 1
    return "\n".join(text_parts), {"row_count": row_count, "parser": "csv"}


def _parse_md(file_path: str) -> tuple[str, dict]:
    with open(file_path, encoding="utf-8") as f:
        text = f.read()
    return text, {"parser": "md"}


def _parse_docx(file_path: str) -> tuple[str, dict]:
    try:
        from markitdown import MarkItDown
        md = MarkItDown()
        result = md.convert(file_path)
        return result.text_content, {"parser": "markitdown"}
    except ImportError:
        # Fallback: try python-docx
        try:
            from docx import Document
            doc = Document(file_path)
            text = "\n".join(p.text for p in doc.paragraphs)
            return text, {"parser": "python-docx"}
        except ImportError:
            raise ImportError("markitdown or python-docx is required for DOCX parsing")


def _parse_txt(file_path: str) -> tuple[str, dict]:
    for encoding in ("utf-8", "gbk", "gb2312", "latin-1"):
        try:
            with open(file_path, encoding=encoding) as f:
                text = f.read()
            return text, {"parser": "txt", "encoding": encoding}
        except UnicodeDecodeError:
            continue
    raise ValueError("Unable to decode TXT file with common encodings")


def detect_file_type(filename: str) -> str:
    """Detect file type from extension."""
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext in ("pdf", "csv", "md", "docx", "txt"):
        return ext
    raise ValueError(f"Unsupported file extension: .{ext}. Supported: pdf, csv, md, docx, txt")
