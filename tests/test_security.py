# -*- coding: utf-8 -*-
"""Security regression tests from the October 2026 audit.

Each test names the finding it guards (C1, H2, M1, ...). See
``docs/plans/2026-10-02-october-2026-audit.md`` for the threat model.
The first group applies to every caller; the ``untrusted`` group
applies to ``parse(..., untrusted=True)``.
"""

import base64
import io
import struct
import time
import zlib
from pathlib import Path

import pytest

from wireviz.Harness import _embed_yaml_in_png, read_yaml_from_png
from wireviz.wireviz import parse
from wireviz.wv_helper import expand
from wireviz.wv_safety import MAX_EXPAND

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
SECRET = "wireviz-test-secret-7f3a"


@pytest.fixture
def secret_file(tmp_path: Path) -> Path:
    f = tmp_path / "secret.txt"
    f.write_text(SECRET)
    return f


def _render_svg(yaml_src: str, **kwargs) -> str:
    return parse(yaml_src, return_types="svg", **kwargs)


# ===========================================================================
# Always on
# ===========================================================================


def test_c1_fontname_markup_rejected(secret_file: Path):
    """C1/C2. ``options.fontname`` reaches the SVG unescaped, so markup
    in it must be rejected before Graphviz runs."""
    src = f"""
options:
  fontname: 'arial"/><image xlink:href="{secret_file}" x="0"/><text a="'
connectors: {{X1: {{pincount: 1}}}}
connections: [[X1]]
"""
    with pytest.raises(ValueError, match="fontname"):
        _render_svg(src)


@pytest.mark.parametrize("name", ["arial", "DejaVu Sans Mono", "Arial, Helvetica"])
def test_c1_plain_fontnames_accepted(name: str):
    src = f"""
options: {{fontname: '{name}'}}
connectors: {{X1: {{pincount: 1}}}}
connections: [[X1]]
"""
    assert "<svg" in _render_svg(src)


def test_c1_font_face_injection_does_not_embed_local_file(secret_file: Path, capsys):
    """C1. A ``<font face>`` in any hypertext field reaches the SVG
    unescaped. The injected ``<image>`` must not be inlined."""
    face = (
        f'a&quot;/&gt;&lt;image xlink:href=&quot;{secret_file}&quot; '
        f'x=&quot;0&quot;/&gt;&lt;text b=&quot;'
    )
    src = f"""
connectors:
  X1:
    pincount: 1
    notes: '<font face="{face}">n</font>'
connections: [[X1]]
"""
    svg = _render_svg(src)
    encoded = base64.b64encode(SECRET.encode()).decode()
    assert encoded not in svg
    assert SECRET not in svg
    assert "not embedded" in capsys.readouterr().err


def test_c1_declared_image_is_still_embedded():
    """The allowlist must not break the normal ``image: src:`` case."""
    img = EXAMPLES / "resources" / "stereo-phone-plug-TRS.png"
    src = f"""
connectors:
  X1:
    pincount: 1
    image: {{src: '{img}'}}
connections: [[X1]]
"""
    svg = _render_svg(src)
    assert "data:image/png;base64," in svg
    assert str(img) not in svg


def test_image_src_with_ampersand(tmp_path: Path):
    """Bug 16. ``&`` in an image path is XML-escaped in the Graphviz
    label and unescaped again before the file is embedded."""
    img_dir = tmp_path / "a&b"
    img_dir.mkdir()
    img = img_dir / "pic.png"
    img.write_bytes((EXAMPLES / "resources" / "stereo-phone-plug-TRS.png").read_bytes())
    src = f"""
connectors:
  X1:
    pincount: 1
    image: {{src: '{img}'}}
connections: [[X1]]
"""
    assert "data:image/png;base64," in _render_svg(src)


def test_m1_long_range_rejected():
    with pytest.raises(ValueError, match="limit"):
        expand(f"1-{MAX_EXPAND + 1}")
    assert len(expand(f"1-{MAX_EXPAND}")) == MAX_EXPAND
    assert expand("5-3") == [5, 4, 3]
    assert expand("a-b") == ["a-b"]


def test_m1_range_in_connection_set_rejected():
    src = """
connectors: {X1: {pincount: 2}}
cables: {W1: {wirecount: 2}}
connections:
  - - X1: [1-10000000]
    - W1: [1-10000000]
"""
    with pytest.raises(ValueError, match="limit"):
        parse(src, return_types="harness")


def test_m1_pincount_cap():
    src = """
connectors: {X1: {pincount: 10000000}}
connections: [[X1]]
"""
    with pytest.raises(ValueError, match="pincount"):
        parse(src, return_types="harness")


def test_m1_wirecount_cap():
    src = """
cables: {W1: {wirecount: 10000000}}
connections: [[W1]]
"""
    with pytest.raises(ValueError, match="wirecount"):
        parse(src, return_types="harness")


def test_m1_alias_bomb_fails_fast():
    """M1. Nested YAML aliases used as a pin list must fail at once,
    not be stringified into a multi-gigabyte value."""
    levels = ["a: &a [1,1,1,1,1,1,1,1,1]"]
    for i, name in enumerate("bcdefghij"):
        prev = levels[-1].split("&")[1].split(" ")[0]
        levels.append(f"{name}: &{name} [{', '.join(['*' + prev] * 9)}]")
    src = (
        "bomb:\n"
        + "\n".join("  " + line for line in levels)
        + """
connectors: {X1: {pincount: 2}}
cables: {W1: {wirecount: 1}}
connections:
  - - X1: [*j]
    - W1: [1]
"""
    )
    start = time.monotonic()
    with pytest.raises(Exception):
        parse(src, return_types="harness")
    assert time.monotonic() - start < 5


def _png(width: int, height: int, extra_chunks=()) -> bytes:
    """A syntactically valid PNG header claiming ``width`` x ``height``,
    with one tiny IDAT. Decoding it would need width*height pixels."""

    def chunk(ctype: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + ctype
            + data
            + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + b"".join(chunk(t, d) for t, d in extra_chunks)
        + chunk(b"IDAT", zlib.compress(b"\x00"))
        + chunk(b"IEND", b"")
    )


def test_m2_png_yaml_read_does_not_decode_pixels():
    """M2. A 50000 x 50000 header (10 GB of RGBA) is inspected without
    decoding the image."""
    bomb = _embed_yaml_in_png(_png(50000, 50000), "connectors: {}")
    start = time.monotonic()
    assert read_yaml_from_png(io.BytesIO(bomb)) == "connectors: {}"
    assert time.monotonic() - start < 1


def test_m2_png_yaml_zlib_bomb_rejected():
    """M2. A compressed iTXt that inflates past the limit is refused."""
    data = (
        b"wireviz:yaml\x00\x01\x00\x00\x00"
        + zlib.compress(b"a" * (17 * 1024 * 1024))
    )
    png = _png(1, 1, [(b"iTXt", data)])
    with pytest.raises(ValueError, match="larger than"):
        read_yaml_from_png(io.BytesIO(png))


def test_png_embed_replaces_existing_chunk_and_keeps_others():
    png = _png(1, 1, [(b"tEXt", b"Comment\x00hello")])
    once = _embed_yaml_in_png(png, "first")
    twice = _embed_yaml_in_png(once, "second")
    assert read_yaml_from_png(io.BytesIO(twice)) == "second"
    assert twice.count(b"wireviz:yaml") == 1
    assert b"Comment\x00hello" in twice


def test_read_yaml_from_non_png_raises(tmp_path: Path):
    f = tmp_path / "x.png"
    f.write_bytes(b"not a png")
    with pytest.raises(ValueError, match="Not a PNG"):
        read_yaml_from_png(f)
