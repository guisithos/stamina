import os
import uuid
from io import BytesIO

from PIL import Image, UnidentifiedImageError

# Habilita leitura de HEIF/HEIC (fotos de iPhone).
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

MAX_PHOTO_DIMENSION = 1920
PHOTO_QUALITY = 75
MAX_PHOTO_BYTES = 20 * 1024 * 1024  # 20 MB max de arquivo original

_db_path = os.getenv("DATABASE_URL", "sqlite:///./app.db").replace("sqlite:///", "")
PHOTOS_DIR = os.path.join(os.path.dirname(_db_path) or ".", "photos")


def ensure_photos_dir():
    os.makedirs(PHOTOS_DIR, exist_ok=True)


def process_photo(raw: bytes) -> bytes:
    """Redimensiona e comprime uma foto (JPEG/PNG/HEIF). Retorna bytes JPEG."""

    try:
        img = Image.open(BytesIO(raw))
    except UnidentifiedImageError:
        raise ValueError("Formato de imagem não suportado")

    # HEIF/PNG podem ter canal alpha — converte pra RGB com fundo branco
    if img.mode in ("RGBA", "P", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    if w > MAX_PHOTO_DIMENSION or h > MAX_PHOTO_DIMENSION:
        ratio = MAX_PHOTO_DIMENSION / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    out = BytesIO()
    img.save(out, "JPEG", quality=PHOTO_QUALITY, optimize=True, progressive=True)
    return out.getvalue()


def save_photo(raw: bytes, activity_id: int) -> str:
    """Salva a foto processada e retorna o nome do arquivo."""
    ensure_photos_dir()
    filename = f"act_{activity_id}_{uuid.uuid4().hex[:8]}.jpg"
    filepath = os.path.join(PHOTOS_DIR, filename)
    processed = process_photo(raw)
    with open(filepath, "wb") as f:
        f.write(processed)
    return filename


def delete_photo(filename: str):
    """Remove o arquivo de foto do disco, se existir."""
    filepath = os.path.join(PHOTOS_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
