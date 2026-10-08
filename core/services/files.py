"""Safe file uploads: PDF, JPG and PNG only, checked by their first bytes, at most 4 MB."""
from django import forms
from django.contrib.contenttypes.models import ContentType

from core.models import ALLOWED_MIME_TYPES, MAX_UPLOAD_BYTES, Attachment

SIGNATURES = (
    (b"%PDF-", "application/pdf", (".pdf",)),
    (b"\x89PNG\r\n\x1a\n", "image/png", (".png",)),
    (b"\xff\xd8\xff", "image/jpeg", (".jpg", ".jpeg")),
)


def detect_type(upload):
    """Return the real MIME type of an upload, or raise ValidationError with a plain message."""
    if upload.size > MAX_UPLOAD_BYTES:
        raise forms.ValidationError("That file is too big. Files can be up to 4 MB.")
    name = (upload.name or "").lower()
    upload.seek(0)
    head = upload.read(16)
    upload.seek(0)
    for magic, mime, exts in SIGNATURES:
        if head.startswith(magic):
            if not name.endswith(exts):
                break
            return mime
    raise forms.ValidationError("Only PDF, JPG and PNG files can be attached.")


class AttachmentField(forms.FileField):
    """An optional file field that only accepts safe file types."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("label", "Attach a file (optional)")
        kwargs.setdefault("help_text", "PDF, JPG or PNG, up to 4 MB.")
        super().__init__(**kwargs)

    def clean(self, data, initial=None):
        f = super().clean(data, initial)
        if f:
            f.detected_type = detect_type(f)
        return f


def save_attachment(parent, upload, user):
    mime = getattr(upload, "detected_type", None) or detect_type(upload)
    assert mime in ALLOWED_MIME_TYPES
    att = Attachment(
        content_type=ContentType.objects.get_for_model(parent),
        object_id=parent.pk,
        original_name=(upload.name or "file")[:200],
        mime_type=mime,
        size_bytes=upload.size,
        uploaded_by=user,
    )
    att.file.save(upload.name, upload, save=False)
    att.save()
    return att


def attachments_for(obj):
    return Attachment.objects.filter(
        content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk
    ).select_related("uploaded_by")
