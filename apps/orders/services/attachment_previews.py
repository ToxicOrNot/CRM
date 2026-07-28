from __future__ import annotations

from io import BytesIO

from django.core.files.base import ContentFile


ORDER_ATTACHMENT_THUMBNAIL_SIZE = (360, 360)
ORDER_ATTACHMENT_THUMBNAIL_QUALITY = 76


class AttachmentPreviewError(Exception):
    pass


def get_order_attachment_thumbnail_name(attachment: object) -> str:
    return f"orders/{attachment.order_id}/thumbnails/{attachment.pk}.jpg"


def get_existing_thumbnail_url(attachment: object) -> str:
    if not getattr(attachment, "pk", None) or not getattr(attachment, "is_image", False):
        return ""

    storage = attachment.file.storage
    thumbnail_name = get_order_attachment_thumbnail_name(attachment)
    if not storage.exists(thumbnail_name):
        return ""
    return storage.url(thumbnail_name)


def get_or_create_order_attachment_thumbnail(attachment: object) -> str:
    if not getattr(attachment, "pk", None) or not getattr(attachment, "file", None):
        raise AttachmentPreviewError("Attachment has no saved file.")

    storage = attachment.file.storage
    thumbnail_name = get_order_attachment_thumbnail_name(attachment)
    if storage.exists(thumbnail_name):
        return thumbnail_name

    thumbnail_content = build_order_attachment_thumbnail(attachment)
    return storage.save(thumbnail_name, ContentFile(thumbnail_content))


def delete_order_attachment_thumbnail(attachment: object) -> None:
    if not getattr(attachment, "pk", None) or not getattr(attachment, "file", None):
        return

    storage = attachment.file.storage
    thumbnail_name = get_order_attachment_thumbnail_name(attachment)
    if storage.exists(thumbnail_name):
        storage.delete(thumbnail_name)


def build_order_attachment_thumbnail(attachment: object) -> bytes:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise AttachmentPreviewError("Pillow is not installed.") from exc

    if getattr(attachment, "is_heic_image", False):
        try:
            from pillow_heif import register_heif_opener
        except ImportError as exc:
            raise AttachmentPreviewError("pillow-heif is not installed.") from exc
        register_heif_opener()

    output = BytesIO()
    try:
        with attachment.file.open("rb") as source:
            with Image.open(source) as image:
                image = ImageOps.exif_transpose(image)
                image.thumbnail(ORDER_ATTACHMENT_THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                image = convert_to_jpeg_image(image, Image)
                image.save(
                    output,
                    format="JPEG",
                    quality=ORDER_ATTACHMENT_THUMBNAIL_QUALITY,
                    optimize=True,
                    progressive=True,
                )
    except Exception as exc:
        raise AttachmentPreviewError("Could not create attachment thumbnail.") from exc

    return output.getvalue()


def convert_to_jpeg_image(image: object, image_module: object) -> object:
    if image.mode == "RGB":
        return image
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba_image = image.convert("RGBA")
        background = image_module.new("RGB", rgba_image.size, "white")
        background.paste(rgba_image, mask=rgba_image.getchannel("A"))
        return background
    return image.convert("RGB")
