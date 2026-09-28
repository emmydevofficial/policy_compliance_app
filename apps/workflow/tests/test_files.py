"""SPEC 7 and 14: file type by content, private storage, safe serving."""

import io

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from apps.core.pdfgen import simple_pdf
from apps.workflow import services as wf
from apps.workflow.files import REQUEST_TYPES, SUBMISSION_TYPES, sanitise_filename, validate_upload


def up(name, data, ctype="application/pdf"):
    return SimpleUploadedFile(name, data, content_type=ctype)


def test_php_script_renamed_to_pdf_is_rejected():
    with pytest.raises(ValidationError):
        validate_upload(up("report.pdf", b"<?php system($_GET['c']); ?>"), SUBMISSION_TYPES)


def test_plain_text_renamed_to_pdf_is_rejected():
    with pytest.raises(ValidationError):
        validate_upload(up("report.pdf", b"just some text, not a pdf"), SUBMISSION_TYPES)


def test_genuine_pdf_is_accepted_and_hashed():
    data = simple_pdf(["hello"])
    clean = validate_upload(up("report.pdf", data), SUBMISSION_TYPES)
    import hashlib

    assert clean.content_type == "application/pdf"
    assert clean.sha256 == hashlib.sha256(data).hexdigest()


def test_svg_is_rejected_even_when_named_png():
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    for name in ("image.svg", "image.png"):
        with pytest.raises(ValidationError):
            validate_upload(up(name, svg, "image/svg+xml"), SUBMISSION_TYPES)


def test_html_is_rejected():
    with pytest.raises(ValidationError):
        validate_upload(up("page.pdf", b"<!DOCTYPE html><html></html>"), SUBMISSION_TYPES)


def test_executable_is_rejected():
    with pytest.raises(ValidationError):
        validate_upload(up("tool.pdf", b"MZ\x90\x00" + b"\x00" * 200), SUBMISSION_TYPES)


def test_extension_that_disagrees_with_content_is_rejected():
    with pytest.raises(ValidationError, match="content is PDF"):
        validate_upload(up("sheet.xlsx", simple_pdf(["x"])), SUBMISSION_TYPES)


def test_images_allowed_for_submissions_but_not_requests():
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, "PNG")
    assert validate_upload(up("photo.png", buf.getvalue(), "image/png"), SUBMISSION_TYPES)
    with pytest.raises(ValidationError):
        validate_upload(up("photo.png", buf.getvalue(), "image/png"), REQUEST_TYPES)


def test_png_text_metadata_is_stripped():
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text("GPS", "6.45,3.39")
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(buf, "PNG", pnginfo=info)
    clean = validate_upload(up("site.png", buf.getvalue(), "image/png"), SUBMISSION_TYPES)
    clean.content.seek(0)
    assert b"6.45,3.39" not in clean.content.read()


def test_jpeg_exif_is_stripped():
    img = Image.new("RGB", (8, 8), "blue")
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # Make
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    assert b"PhoneMaker" in buf.getvalue()
    clean = validate_upload(up("site.jpg", buf.getvalue(), "image/jpeg"), SUBMISSION_TYPES)
    clean.content.seek(0)
    assert b"PhoneMaker" not in clean.content.read()


@override_settings(MAX_UPLOAD_BYTES=1000, MAX_UPLOAD_MB=0.001)
def test_oversized_file_is_rejected():
    with pytest.raises(ValidationError, match="larger than"):
        validate_upload(up("big.pdf", simple_pdf(["x" * 2000])), SUBMISSION_TYPES)


def test_filename_is_sanitised():
    assert sanitise_filename('../../etc/pa"ss\r\nwd.pdf') == "passwd.pdf"


def test_stored_name_is_uuid_outside_web_root(req_a, admin):
    att = wf.add_request_attachment(req_a, up("My Circular.pdf", simple_pdf(["c"])), admin)
    stored = att.file.name
    assert "My Circular" not in stored
    assert stored.endswith(".pdf") and f"request-{req_a.pk}" in stored
    path = settings.PRIVATE_MEDIA_ROOT / stored
    assert path.exists()
    assert not str(path).startswith(str(settings.STATIC_ROOT))


def test_download_headers(client, req_a, admin):
    att = wf.add_request_attachment(req_a, up('Circ"ular.pdf', simple_pdf(["c"])), admin)
    client.force_login(admin)
    r = client.get(reverse("requests:attachment_download", args=[att.pk]))
    assert r.status_code == 200
    assert r["Content-Type"] == "application/pdf"
    assert r["Content-Disposition"].startswith("attachment;")
    assert r["X-Content-Type-Options"] == "nosniff"


@override_settings(USE_X_ACCEL_REDIRECT=True, X_ACCEL_PREFIX="/protected/")
def test_x_accel_redirect_in_production_mode(client, req_a, admin):
    att = wf.add_request_attachment(req_a, up("c.pdf", simple_pdf(["c"])), admin)
    client.force_login(admin)
    r = client.get(reverse("requests:attachment_download", args=[att.pk]))
    assert r["X-Accel-Redirect"] == "/protected/" + att.file.name
    assert r.content == b""


def test_rejected_upload_through_the_view_is_reported(client, officer_a, req_a):
    client.force_login(officer_a)
    r = client.post(
        reverse("my:submit", args=[req_a.pk]),
        {
            "compliance_status": "COMPLIANT",
            "evidence_available": "YES",
            "evidence_description": "x",
            "files": up("evil.pdf", b"<?php echo 1; ?>"),
        },
    )
    assert r.status_code == 200
    assert b"markup or script" in r.content
    req_a.refresh_from_db()
    assert req_a.status == "AWAITING"
