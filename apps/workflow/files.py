"""Upload validation and file serving (SPEC section 7).

The type of a file is decided by its content, never by its name or the browser's claim. A
file whose name says one thing and whose bytes say another is refused.
"""

import hashlib
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass

import filetype
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.http import FileResponse, HttpResponse
from django.utils.http import content_disposition_header

logger = logging.getLogger("obligation_desk.security")

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
JPEG = "image/jpeg"
PNG = "image/png"

REQUEST_TYPES = frozenset({PDF, DOCX, XLSX})
SUBMISSION_TYPES = frozenset({PDF, DOCX, XLSX, JPEG, PNG})

EXTENSION_FOR = {PDF: "pdf", DOCX: "docx", XLSX: "xlsx", JPEG: "jpg", PNG: "png"}
ACCEPTED_EXTENSIONS = {
    PDF: {"pdf"},
    DOCX: {"docx"},
    XLSX: {"xlsx"},
    JPEG: {"jpg", "jpeg"},
    PNG: {"png"},
}
LABEL_FOR = {PDF: "PDF", DOCX: "Word (DOCX)", XLSX: "Excel (XLSX)", JPEG: "JPEG", PNG: "PNG"}

_MARKUP = re.compile(rb"^\s*(<\?xml|<svg|<!doctype|<html|<script|<\?php)", re.IGNORECASE)
_EXECUTABLE_MAGIC = (b"MZ", b"\x7fELF", b"#!", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")


@dataclass
class CleanFile:
    content: ContentFile
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str


def sanitise_filename(name: str) -> str:
    name = os.path.basename((name or "").replace("\\", "/"))
    name = unicodedata.normalize("NFKC", name)
    name = "".join(c for c in name if c.isprintable() and c not in '"<>|:*?\r\n\t')
    name = name.strip(" .") or "file"
    if len(name) > 200:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 200 - len(ext) - 1] + "." + ext) if dot else name[:200]
    return name


def accepted_labels(allowed: frozenset[str]) -> str:
    return ", ".join(LABEL_FOR[m] for m in (PDF, DOCX, XLSX, JPEG, PNG) if m in allowed)


def validate_upload(uploaded, allowed: frozenset[str]) -> CleanFile:
    """Check type by content, size, extension agreement; scan; strip image metadata; hash.
    Raises ValidationError with a message fit to show the user."""
    original = sanitise_filename(getattr(uploaded, "name", "file"))
    size = getattr(uploaded, "size", None)
    if size is not None and size > settings.MAX_UPLOAD_BYTES:
        raise ValidationError(f"{original} is larger than the {settings.MAX_UPLOAD_MB} MB limit.")
    uploaded.seek(0)
    data = uploaded.read()
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise ValidationError(f"{original} is larger than the {settings.MAX_UPLOAD_MB} MB limit.")
    if not data:
        raise ValidationError(f"{original} is empty.")

    head = data[:2048]
    if _MARKUP.match(head):
        raise ValidationError(
            f"{original} is a markup or script file (SVG, HTML, XML or PHP). These are not "
            "accepted."
        )
    if head.startswith(_EXECUTABLE_MAGIC):
        raise ValidationError(f"{original} is an executable file. It is not accepted.")

    kind = filetype.guess(data)
    detected = kind.mime if kind else None
    if detected not in allowed:
        raise ValidationError(
            f"{original} is not an accepted file type. Accepted: {accepted_labels(allowed)}."
        )

    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in ACCEPTED_EXTENSIONS[detected]:
        raise ValidationError(
            f"{original} is named .{ext or '(none)'} but its content is "
            f"{LABEL_FOR[detected]}. Rename it correctly or upload the right file."
        )

    _virus_scan(data, original)

    if detected in (JPEG, PNG) and settings.STRIP_IMAGE_EXIF:
        data = _strip_image_metadata(data, detected)

    return CleanFile(
        content=ContentFile(data, name=f"upload.{EXTENSION_FOR[detected]}"),
        original_filename=original,
        content_type=detected,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _strip_image_metadata(data: bytes, mime: str) -> bytes:
    """Phone photographs carry location data. Re-encode without EXIF, keeping orientation."""
    try:
        from PIL import Image, ImageOps
    except ImportError:  # pragma: no cover
        return data
    try:
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)
            out = io.BytesIO()
            if mime == JPEG:
                img.convert("RGB").save(out, format="JPEG", quality=92, optimize=True)
            else:
                img.save(out, format="PNG", optimize=True)  # writes no EXIF or text chunks
            return out.getvalue()
    except Exception as exc:
        raise ValidationError("The image could not be read. Is it damaged?") from exc


def _virus_scan(data: bytes, original: str) -> None:
    """Optional ClamAV hook, on when CLAMAV_ENABLED. A positive result is quarantined, not
    deleted, and the upload refused."""
    if not settings.CLAMAV_ENABLED:
        return
    scanner = shutil.which("clamdscan") or shutil.which("clamscan")
    if not scanner:
        raise ValidationError("The virus scanner is not available. Try again later.")
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    result = subprocess.run(
        [scanner, "--no-summary", path], capture_output=True, text=True, timeout=120
    )
    if result.returncode == 1:
        qdir = settings.PRIVATE_MEDIA_ROOT / "quarantine"
        qdir.mkdir(parents=True, exist_ok=True)
        dest = qdir / os.path.basename(path)
        shutil.move(path, dest)
        logger.warning("Upload quarantined: %s -> %s (%s)", original, dest, result.stdout.strip())
        raise ValidationError(f"{original} failed the virus scan and has been quarantined.")
    os.unlink(path)
    if result.returncode != 0:
        raise ValidationError("The virus scan could not complete. Try again later.")


def file_response(attachment) -> HttpResponse:
    """Serve one stored attachment. The caller has already done the permission check."""
    name = attachment.original_filename
    if settings.USE_X_ACCEL_REDIRECT:
        response = HttpResponse()
        response["X-Accel-Redirect"] = (
            settings.X_ACCEL_PREFIX.rstrip("/") + "/" + attachment.file.name
        )
    else:
        response = FileResponse(attachment.file.open("rb"))
    response["Content-Type"] = attachment.content_type
    response["Content-Disposition"] = content_disposition_header(True, name)
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response
