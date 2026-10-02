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
        f"a&quot;/&gt;&lt;image xlink:href=&quot;{secret_file}&quot; "
        f"x=&quot;0&quot;/&gt;&lt;text b=&quot;"
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
    src = "bomb:\n" + "\n".join("  " + line for line in levels) + """
connectors: {X1: {pincount: 2}}
cables: {W1: {wirecount: 1}}
connections:
  - - X1: [*j]
    - W1: [1]
"""
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
    data = b"wireviz:yaml\x00\x01\x00\x00\x00" + zlib.compress(
        b"a" * (17 * 1024 * 1024)
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


# ===========================================================================
# parse(..., untrusted=True)
# ===========================================================================

TRS = EXAMPLES / "resources" / "stereo-phone-plug-TRS.png"


def test_l1_image_paths_not_mutated(tmp_path: Path, minimal_yaml: Path):
    """L1. parse() must not mutate the caller's list or a shared default."""
    defaults_before = repr(parse.__defaults__)
    mine = [tmp_path]
    parse(minimal_yaml, return_types="harness", image_paths=mine)
    parse(minimal_yaml, return_types="harness")
    assert mine == [tmp_path]
    assert repr(parse.__defaults__) == defaults_before


def test_h3_untrusted_str_is_never_a_path(tmp_path: Path):
    """H3. A request body that names a server file must not read it."""
    f = tmp_path / "server-only.yml"
    f.write_text(
        f"connectors: {{X1: {{pincount: 1, notes: {SECRET}}}}}\n"
        "connections: [[X1]]\n"
    )
    with pytest.raises(TypeError) as exc:
        parse(str(f), return_types="harness", untrusted=True)
    assert SECRET not in str(exc.value)
    # Trusted callers keep the old behavior.
    assert parse(str(f), return_types="harness").connectors["X1"].notes == SECRET


def test_untrusted_input_size_cap():
    from wireviz.wv_safety import UNTRUSTED_MAX_INPUT_BYTES

    big = "# " + "x" * UNTRUSTED_MAX_INPUT_BYTES + "\nconnectors: {}\n"
    with pytest.raises(ValueError, match="larger than"):
        parse(big, return_types="harness", untrusted=True)


def _image_yaml(src) -> str:
    return f"""
connectors:
  X1:
    pincount: 1
    image: {{src: '{src}'}}
connections: [[X1]]
"""


def test_h2_untrusted_absolute_image_rejected():
    with pytest.raises(ValueError, match="relative"):
        parse(_image_yaml(TRS), return_types="svg", untrusted=True)


def test_h2_untrusted_image_traversal_rejected(tmp_path: Path):
    root = tmp_path / "uploads"
    root.mkdir()
    (tmp_path / "outside.png").write_bytes(TRS.read_bytes())
    with pytest.raises(ValueError, match="not found"):
        parse(
            _image_yaml("../outside.png"),
            return_types="svg",
            image_paths=[root],
            untrusted=True,
        )


def test_h2_untrusted_image_inside_root_is_embedded(tmp_path: Path):
    (tmp_path / "pic.png").write_bytes(TRS.read_bytes())
    svg = parse(
        _image_yaml("pic.png"),
        return_types="svg",
        image_paths=[tmp_path],
        untrusted=True,
    )
    assert "data:image/png;base64," in svg


def test_untrusted_image_pixel_cap(tmp_path: Path):
    (tmp_path / "huge.png").write_bytes(_png(20000, 20000))
    with pytest.raises(ValueError, match="pixels"):
        parse(
            _image_yaml("huge.png"),
            return_types="svg",
            image_paths=[tmp_path],
            untrusted=True,
        )


@pytest.mark.parametrize("name", ["../../etc/passwd", "/tmp/private", "a.b"])
def test_m3_untrusted_template_name_must_be_bare(name: str):
    src = f"""
metadata: {{template: {{name: '{name}'}}}}
connectors: {{X1: {{pincount: 1}}}}
connections: [[X1]]
"""
    harness = parse(src, return_types="harness", untrusted=True)
    with pytest.raises(ValueError, match="bare name"):
        harness._render(("html",))


@pytest.mark.parametrize(
    "src",
    [
        "tweak: {append: ['stylesheet=\"x\"']}\nconnectors: {X1: {pincount: 1}}\n",
        "connectors: {X1: {pincount: 1, tweak: {append: ['a=b']}}}\n",
    ],
)
def test_c2_untrusted_tweak_rejected(src: str):
    with pytest.raises(ValueError, match="tweak"):
        parse(src + "connections: [[X1]]\n", return_types="harness", untrusted=True)


def test_c2_untrusted_svg_has_no_script():
    """C2. Hypertext can make Graphviz emit javascript: links and event
    handlers; the untrusted SVG must not contain them."""
    src = """
connectors:
  X1:
    pincount: 1
    notes: '<table><tr><td href="javascript:alert(1)">click</td></tr></table>'
  X2:
    pincount: 1
    notes: '<font face="x&quot; onload=&quot;alert(2)">n</font>'
connections: [[X1], [X2]]
"""
    try:
        svg = parse(src, return_types="svg", untrusted=True)
    except ValueError as exc:  # markup that breaks XML is refused outright
        assert "not well-formed" in str(exc)
        return
    lowered = svg.lower()
    assert "javascript:" not in lowered
    assert "onload" not in lowered and "alert(2)" not in lowered


def test_c2_sanitize_svg_allowlist():
    from wireviz.wv_safety import sanitize_svg

    dirty = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<g onclick="x()"><script>alert(1)</script>'
        '<a xlink:href="javascript:alert(1)"><text>t</text></a>'
        '<a xlink:href="https://example.com"><text>ok</text></a>'
        '<image xlink:href="/etc/passwd"/>'
        '<image xlink:href="data:image/png;base64,AAAA"/>'
        "<foreignObject><div/></foreignObject>"
        '<animate attributeName="href" to="javascript:alert(1)"/>'
        "</g></svg>"
    )
    clean = sanitize_svg(dirty)
    assert "script" not in clean
    assert "onclick" not in clean
    assert "javascript" not in clean
    assert "/etc/passwd" not in clean
    assert "foreignObject" not in clean
    assert "https://example.com" in clean
    assert "data:image/png;base64,AAAA" in clean


def test_h1_untrusted_html_is_sanitized():
    src = """
metadata:
  title: '<script>alert("title")</script>Harness <b>A</b>'
  description: '<a href="javascript:alert(1)">bad</a> <a href="https://ok.example">good</a>'
connectors: {X1: {pincount: 1}}
connections: [[X1]]
additional_bom_items:
  - {description: '<img src=x onerror=alert("bom")>Spacer', qty: 1}
"""
    harness = parse(src, return_types="harness", untrusted=True)
    page = harness._render(("html",))["html"]
    lowered = page.lower()
    assert "<script>alert" not in lowered
    assert "onerror" not in lowered
    assert "javascript:" not in lowered
    assert "<b>A</b>" in page
    assert "Spacer" in page


def test_h1_trusted_html_keeps_markup():
    """Trusted output is unchanged: hypertext may hold HTML by design."""
    src = """
metadata: {title: 'T <i>x</i>'}
connectors: {X1: {pincount: 1}}
connections: [[X1]]
"""
    page = parse(src, return_types="harness")._render(("html",))["html"]
    assert "T <i>x</i>" in page


def test_sanitize_html_fragment():
    from wireviz.wv_safety import sanitize_html_fragment as s

    assert s("a < b & c") == "a &lt; b &amp; c"
    assert s("x<br />y") == "x<br />y"
    assert s("<b>open") == "<b>open</b>"
    assert s("<style>p{}</style>t") == "t"
    assert s('<font color="red" face="x">r</font>') == '<font color="red">r</font>'
    assert s('<a href=" javascript:x">l</a>') == "<a>l</a>"


def test_m1_untrusted_render_timeout(monkeypatch, minimal_yaml: Path):
    import wireviz.Harness as H

    monkeypatch.setattr(H, "UNTRUSTED_RENDER_TIMEOUT", 0.000001)
    with pytest.raises(RuntimeError, match="did not finish"):
        parse(minimal_yaml.read_text(), return_types="svg", untrusted=True)


def test_untrusted_gallery_example_renders():
    """Untrusted mode must still render ordinary harnesses."""
    f = EXAMPLES / "demo01.yml"
    svg = parse(
        f.read_text(), return_types="svg", image_paths=[f.parent], untrusted=True
    )
    assert svg.startswith("<?xml") and "<svg" in svg


# ===========================================================================
# Code review round 1 (October 2026 audit branch)
# ===========================================================================


def test_review_untrusted_hypertext_img_refused(tmp_path: Path):
    """An <img> typed into a hypertext field makes Graphviz load and
    rasterize that file into PNG/PDF output. Untrusted mode refuses it."""
    src = f"""
connectors:
  X1:
    pincount: 1
    notes: '<table><tr><td><img src="{TRS}"/></td></tr></table>'
connections: [[X1]]
"""
    for fmt in ("png", "svg"):
        with pytest.raises(ValueError, match="image: src"):
            parse(src, return_types=fmt, untrusted=True)


def test_review_untrusted_declared_image_still_renders_png(tmp_path: Path):
    (tmp_path / "pic.png").write_bytes(TRS.read_bytes())
    png = parse(
        _image_yaml("pic.png"),
        return_types="png",
        image_paths=[tmp_path],
        untrusted=True,
    )
    assert png.startswith(b"\x89PNG")


def test_review_html_fragment_escapes_quotes():
    """Values also land inside attributes in the templates."""
    from wireviz.wv_safety import sanitize_html_fragment

    assert '"' not in sanitize_html_fragment('a"b')


@pytest.mark.parametrize("key", ["fontname", "bgcolor"])
def test_review_untrusted_metadata_cannot_replace_builtin_placeholder(key: str):
    src = f"""
metadata:
  {key}: 'x" data-injected="1'
connectors: {{X1: {{pincount: 1}}}}
connections: [[X1]]
"""
    page = parse(src, return_types="harness", untrusted=True)._render(("html",))["html"]
    assert "data-injected" not in page


def test_review_untrusted_sheetsize_must_be_bare():
    src = """
metadata:
  template: {name: din-6771, sheetsize: 'A4" data-injected="1'}
connectors: {X1: {pincount: 1}}
connections: [[X1]]
"""
    harness = parse(src, return_types="harness", untrusted=True)
    with pytest.raises(ValueError, match="sheetsize"):
        harness._render(("html",))


def test_review_sanitize_svg_checks_both_image_hrefs():
    from wireviz.wv_safety import sanitize_svg

    dirty = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<image xlink:href="data:image/png;base64,AAAA" href="https://evil.example/x.png"/>'
        "</svg>"
    )
    assert "evil.example" not in sanitize_svg(dirty)


def test_review_fontname_trailing_newline_rejected():
    from wireviz.wv_safety import check_fontname

    with pytest.raises(ValueError):
        check_fontname("arial\n")


def test_review_malformed_itxt_raises_valueerror():
    from wireviz.Harness import _parse_itxt

    with pytest.raises(ValueError, match="Malformed"):
        _parse_itxt(b"wireviz:yaml")
