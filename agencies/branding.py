"""Traitement des images de marque (photo de connexion, couverture du portail)."""
import io
import uuid

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile

MAX_UPLOAD = 6 * 1024 * 1024
MAX_SIDE = 2000


def process_image(uploaded, *, max_side: int = MAX_SIDE) -> ContentFile:
    """Vérifie que le fichier est une vraie image, la redimensionne et la réencode en JPEG (métadonnées retirées)."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if uploaded.size > MAX_UPLOAD:
        raise ValidationError("Image trop lourde (6 Mo maximum).")
    try:
        img = Image.open(uploaded)
        img.verify()
        uploaded.seek(0)
        img = Image.open(uploaded)
        img = ImageOps.exif_transpose(img)
    except (UnidentifiedImageError, OSError, ValueError):
        raise ValidationError("Ce fichier n'est pas une image valide (JPG, PNG ou WebP).") from None
    if img.width < 600 or img.height < 300:
        raise ValidationError("Image trop petite : 1200 × 600 pixels minimum recommandés.")
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=84, optimize=True, progressive=True)
    return ContentFile(out.getvalue(), name=f"{uuid.uuid4().hex}.jpg")
