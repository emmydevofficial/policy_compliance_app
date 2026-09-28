import uuid

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.text import slugify


class PrivateStorage(FileSystemStorage):
    """Evidence storage outside every web-served directory. It has no URL on purpose."""

    def __init__(self, **kwargs):
        kwargs.setdefault("location", settings.PRIVATE_MEDIA_ROOT)
        kwargs["base_url"] = None
        super().__init__(**kwargs)

    def url(self, name):  # pragma: no cover - guard
        raise NotImplementedError("Private files are served only through the download view.")


def private_storage() -> PrivateStorage:
    return PrivateStorage()


def _partition(request, bucket: str, filename: str) -> str:
    # The form sets ._detected_ext after content sniffing; the stored name is a UUID plus it.
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    period = slugify(request.period.name) or f"period-{request.period_id}"
    return f"{period}/request-{request.pk}/{bucket}/{uuid.uuid4().hex}.{ext}"


def request_attachment_path(instance, filename: str) -> str:
    return _partition(instance.request, "request", filename)


def submission_attachment_path(instance, filename: str) -> str:
    return _partition(instance.submission.request, f"submission-{instance.submission_id}", filename)
