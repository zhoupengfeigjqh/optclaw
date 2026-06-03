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


import json
import re


async def smart_parse_via_ollama(text: str, model: str, prompt_template: str | None = None,
                                  base_url: str | None = None) -> list[dict]:
    """Use Ollama chat to parse raw text into structured LIST[DICT]."""
    import httpx
    from .config import get_ollama_base_url, get_parse_prompt

    if not base_url:
        base_url = get_ollama_base_url()
    if not prompt_template:
        prompt_template = get_parse_prompt()

    prompt = prompt_template.format(text=text) if "{text}" in prompt_template else prompt_template + "\n\n" + text

    url = f"{base_url}/api/chat"
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(url, json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        })
        resp.raise_for_status()
        data = resp.json()

    content = data.get("message", {}).get("content", "")
    return _extract_json_array(content)


def _extract_json_array(text: str) -> list[dict]:
    """Extract JSON array from LLM response, handling markdown code blocks."""
    # Try to extract from ```json ... ``` or ``` ... ``` blocks
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        text = m.group(1).strip()

    # Try to find JSON array directly
    m = re.search(r'\[[\s\S]*\]', text)
    if m:
        text = m.group(0)

    parsed = json.loads(text)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return [parsed]
    raise ValueError(f"Expected JSON array, got: {type(parsed)}")


def detect_file_type(filename: str) -> str:
    """Detect file type from extension."""
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext in ("pdf", "csv", "md", "docx", "txt"):
        return ext
    raise ValueError(f"Unsupported file extension: .{ext}. Supported: pdf, csv, md, docx, txt")
