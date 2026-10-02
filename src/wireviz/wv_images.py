# -*- coding: utf-8 -*-
"""Image sources that Graphviz cannot read directly.

Graphviz needs an image file in a format its build supports. Two kinds
of ``image.src`` are turned into a PNG file in a per-harness temporary
directory first:

- ``data:image/...;base64,...`` URIs embedded in the YAML (upstream #188,
  #322). They need no file system access, so they also work for
  ``parse(..., untrusted=True)`` callers.
- ``.webp`` files, which many Graphviz builds cannot load (upstream #202).

The directory lives as long as the ``Harness`` (``Harness.temp_dir()``).
"""

import base64
import binascii
import hashlib
import io
import re
from pathlib import Path

from wireviz.wv_safety import UNTRUSTED_MAX_IMAGE_PIXELS

# Largest decoded data URI image. Real connector photos are well below it.
MAX_DATA_URI_BYTES = 10 * 1024 * 1024

_DATA_URI = re.compile(
    r"^data:image/(?P<type>png|jpeg|jpg|gif|webp);base64,(?P<data>[A-Za-z0-9+/=\s]+)$",
    re.IGNORECASE,
)


def is_data_uri(src) -> bool:
    return isinstance(src, str) and src[:5].lower() == "data:"


def _to_png(data: bytes, name: str, temp_dir: Path) -> Path:
    """Write ``data`` (any image format Pillow reads) as a PNG file in
    ``temp_dir`` and return its path. The pixel count is checked from the
    header before anything is decoded."""
    from PIL import Image as PILImage

    try:
        with PILImage.open(io.BytesIO(data)) as im:
            if im.width * im.height > UNTRUSTED_MAX_IMAGE_PIXELS:
                raise ValueError(
                    f"Image {name} has {im.width * im.height} pixels; "
                    f"the limit is {UNTRUSTED_MAX_IMAGE_PIXELS}"
                )
            out = temp_dir / f"img-{hashlib.sha256(data).hexdigest()[:16]}.png"
            if not out.exists():
                im.save(out, format="PNG")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Image {name} is not a readable image: {exc}") from exc
    return out


def materialize_data_uri(src: str, temp_dir: Path) -> Path:
    """Decode a ``data:image/...;base64,`` URI into a PNG file."""
    m = _DATA_URI.match(src.strip())
    if not m:
        raise ValueError(
            "Image data URIs must look like data:image/png;base64,... "
            "(png, jpeg, gif or webp)"
        )
    if len(m["data"]) * 3 // 4 > MAX_DATA_URI_BYTES:
        raise ValueError(f"Embedded image is larger than {MAX_DATA_URI_BYTES} bytes")
    try:
        data = base64.b64decode(re.sub(r"\s", "", m["data"]), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"Embedded image is not valid base64: {exc}") from exc
    return _to_png(data, "data URI", temp_dir)


def materialize_webp(path: Path, temp_dir: Path) -> Path:
    """Convert a ``.webp`` file into a PNG file Graphviz can load."""
    return _to_png(Path(path).read_bytes(), str(path), temp_dir)
