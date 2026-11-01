"""Bounded decoding. Never persist original images or metadata."""
import io
import warnings
from dataclasses import dataclass
from pathlib import PurePath
from PIL import Image, UnidentifiedImageError, ImageOps

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 16_000_000

class ImageError(Exception):
    def __init__(self, code, message, http_status=422):
        self.code, self.message, self.http_status = code, message, http_status

@dataclass
class SafeImage:
    content: bytes
    mime: str
    width: int
    height: int

def sanitize_image(content: bytes, filename: str) -> SafeImage:
    if len(content) > MAX_BYTES:
        raise ImageError('file_too_large', '图片不能超过 5 MiB', 413)
    suffix = PurePath(filename or '').suffix.lower()
    expected = {'.png':'PNG', '.jpg':'JPEG', '.jpeg':'JPEG'}.get(suffix)
    if not expected:
        raise ImageError('unsupported_type', '仅支持 PNG/JPEG', 415)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in ('PNG', 'JPEG'):
                    raise ImageError('unsupported_type', '实际格式必须为 PNG/JPEG', 415)
                if image.format != expected:
                    raise ImageError('format_mismatch', '扩展名与实际图片格式不一致', 415)
                if image.width * image.height > MAX_PIXELS:
                    raise ImageError('pixel_limit', '图片像素总量超过 1600 万', 413)
                if getattr(image, 'n_frames', 1) != 1:
                    raise ImageError('animated_image', '不支持动画图片')
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                image.load()
                oriented = ImageOps.exif_transpose(image)
                clean = Image.new('RGB', oriented.size, 'white')
                rgba = oriented.convert('RGBA')
                clean.paste(rgba, mask=rgba.getchannel('A'))
                out = io.BytesIO()
                clean.save(out, format='PNG')
                if out.tell() > MAX_BYTES:
                    raise ImageError('sanitized_too_large', '处理后图片过大，请缩小图片', 413)
                return SafeImage(out.getvalue(), 'image/png', clean.width, clean.height)
    except ImageError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageError('pixel_limit', '图片像素超限', 413) from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise ImageError('decode_failed', '图片损坏或无法解码') from None
