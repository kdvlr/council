import io
from pypdf import PdfReader
from .models import AttachmentPayload

MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_EXTRACTED_CHARS = 120_000


def extract_attachment_text(filename: str, mime_type: str, raw_bytes: bytes) -> AttachmentPayload:
    if len(raw_bytes) > MAX_FILE_BYTES:
        raise ValueError(f"File '{filename}' exceeds the 15 MB upload limit.")

    lower_name = filename.lower()
    if lower_name.endswith(".pdf") or mime_type == "application/pdf":
        reader = PdfReader(io.BytesIO(raw_bytes))
        pages: list[str] = []
        for idx, page in enumerate(reader.pages, start=1):
            txt = (page.extract_text() or "").strip()
            if txt:
                pages.append(f"--- Page {idx} ---\n{txt}")
        extracted = "\n\n".join(pages).strip()
        if not extracted:
            raise ValueError(f"No extractable text found in PDF '{filename}'.")
    else:
        try:
            extracted = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                extracted = raw_bytes.decode("latin-1")
            except Exception as exc:
                raise ValueError(f"Unsupported binary file '{filename}'.") from exc

    if len(extracted) > MAX_EXTRACTED_CHARS:
        extracted = (
            extracted[:MAX_EXTRACTED_CHARS]
            + f"\n\n[... truncated to {MAX_EXTRACTED_CHARS:,} characters ...]"
        )

    return AttachmentPayload(
        filename=filename,
        mime_type=mime_type or "text/plain",
        extracted_text=extracted,
        char_count=len(extracted),
    )


def format_attachments_block(attachments: list[dict]) -> str:
    if not attachments:
        return ""
    sections = ["### Reference Context Files"]
    for att in attachments:
        fname = att.get("filename", "attachment")
        text = att.get("extracted_text", "")
        sections.append(f"#### File: `{fname}`\n````text\n{text}\n````")
    return "\n\n".join(sections)
