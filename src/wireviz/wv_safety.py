# -*- coding: utf-8 -*-
"""Input limits and output sanitizers.

WireViz has two kinds of callers. The CLI and scripts render YAML that
the person running them wrote (trusted). A server such as the
wireviz-gui sidecar renders YAML that anyone can send (untrusted).

The limits in the first block apply to every caller: no real harness
gets near them, and without them a few bytes of YAML can allocate
gigabytes. Everything else in this module applies only when
``parse(..., untrusted=True)`` is used. See
``docs/plans/2026-10-02-october-2026-audit.md``.
"""

import html
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, List, Sequence, Set, Union

# Upper bound for one pin/wire range (``[1-10000]``) and for
# ``pincount`` / ``wirecount``. Applies to all callers.
MAX_EXPAND = 10_000

# ``options.fontname`` is written into Graphviz attributes and the HTML
# template, and Graphviz does not escape it in SVG output. Font family
# names never need markup characters (fontconfig styles use : and +).
FONTNAME_PATTERN = re.compile(r"^[\w][\w ,.:+\-]*$")


def check_fontname(fontname: str) -> str:
    """Return ``fontname`` unchanged, or raise ValueError if it holds
    characters that could break out of an SVG or HTML attribute."""
    if not isinstance(fontname, str) or not FONTNAME_PATTERN.fullmatch(fontname):
        raise ValueError(
            f"options.fontname {fontname!r} is not a valid font name "
            "(allowed: letters, digits, space and , . : + - _)"
        )
    return fontname


def check_count(name: str, value: int) -> None:
    """Raise ValueError when a pin/wire count is above ``MAX_EXPAND``."""
    if value > MAX_EXPAND:
        raise ValueError(f"{name} {value} is larger than the limit of {MAX_EXPAND}")


# ===========================================================================
# Untrusted mode — parse(..., untrusted=True)
# ===========================================================================

# Largest YAML source accepted. Real harness files are a few kB.
UNTRUSTED_MAX_INPUT_BYTES = 1_000_000

# Seconds one Graphviz call may run before it is stopped.
UNTRUSTED_RENDER_TIMEOUT = 30

# Largest image (width x height) a harness may reference. Graphviz
# decodes images for raster output, so a small file with huge
# dimensions can allocate gigabytes.
UNTRUSTED_MAX_IMAGE_PIXELS = 50_000_000

# metadata.template.name must be a bare name, never a path.
TEMPLATE_NAME_PATTERN = re.compile(r"^[\w-]+$")

SAFE_LINK_SCHEMES = ("http:", "https:", "mailto:")

# Image files allowed in untrusted mode, by extension -> Pillow format.
_IMAGE_FORMATS = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".gif": "GIF",
    ".webp": "WEBP",
}


def check_untrusted_image(
    src: Union[str, Path], roots: Sequence[Union[str, Path]]
) -> Path:
    """Return the resolved image path, or raise ValueError when ``src``
    is absolute, escapes every root in ``roots``, or is too large."""
    if Path(src).is_absolute():
        raise ValueError(f"Image path {src} must be relative")
    for root in roots:
        root = Path(root).resolve()
        candidate = (root / src).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            break
    else:
        raise ValueError(f"Image {src} was not found among the supplied images")

    from PIL import Image as PILImage

    fmt = _IMAGE_FORMATS.get(candidate.suffix.lower())
    if fmt is None:
        raise ValueError(
            f"Image {src}: only {', '.join(sorted(_IMAGE_FORMATS))} files are allowed"
        )
    try:
        # formats=[...]: Pillow must not probe other decoders (EPS would
        # run Ghostscript on the file).
        with PILImage.open(candidate, formats=[fmt]) as im:  # header only
            if im.format != fmt:
                raise ValueError(f"Image {src} is not a {fmt} file")
            pixels = im.width * im.height
    except Exception as exc:
        raise ValueError(f"Image {src} is not a readable image: {exc}") from exc
    if pixels > UNTRUSTED_MAX_IMAGE_PIXELS:
        raise ValueError(
            f"Image {src} has {pixels} pixels; the limit is {UNTRUSTED_MAX_IMAGE_PIXELS}"
        )
    return candidate


# Start of an <img> tag in a Graphviz HTML-like label. Graphviz loads
# the file for every output format (PNG and PDF rasterize it).
_DOT_IMG_START = re.compile(r"<\s*img\b", re.IGNORECASE)


def check_dot_images(dot_source: str, generated_tags: Set[str]) -> None:
    """Raise ValueError if the DOT source holds any ``<img>`` tag other
    than the exact tags WireViz generated for declared images
    (``wv_gv_html.html_img_tag``).

    Parsing user-written tags is not safe: Graphviz reads attribute
    names case-insensitively and uses the last ``src``, so a tag that
    looks allowed to a regex can load another file. Removing the known
    generated tags and refusing any ``<img`` that remains avoids that.
    """
    remaining = dot_source
    for tag in generated_tags:
        remaining = remaining.replace(tag, "")
    if _DOT_IMG_START.search(remaining):
        raise ValueError(
            "Images may only be added with image: src:, not with <img> in text"
        )


def check_html_label(label: str, owner: str) -> None:
    """Raise ValueError unless ``label`` (the body of a Graphviz HTML-like
    label) is well-formed and has balanced angle brackets.

    The DOT parser ends an HTML label where its ``<`` and ``>`` count
    balances, so one unescaped ``>`` in a value would end the label early
    and turn the rest into raw DOT (which can load files). This is a
    backstop for untrusted mode behind the escaping of every value.
    """
    if label.count("<") != label.count(">"):
        raise ValueError(f"{owner}: a value contains an unescaped < or >")
    neutral = re.sub(
        r"&(?:#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);", "&amp;", label
    )
    try:
        ET.fromstring(f"<root>{neutral}</root>")
    except ET.ParseError as exc:
        raise ValueError(
            f"{owner}: the generated label is not well-formed ({exc})"
        ) from exc


def check_template_name(name: str, field: str = "metadata.template.name") -> str:
    """Return ``name`` or raise ValueError if it is not a bare name."""
    if not isinstance(name, str) or not TEMPLATE_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            f"{field} {name!r} must be a bare name "
            "(letters, digits, hyphen, underscore)"
        )
    return name


def _safe_link(value: str, allow_fragment: bool = True) -> bool:
    v = "".join(value.split()).lower()  # browsers ignore embedded whitespace
    if allow_fragment and v.startswith("#"):
        return True
    return v.startswith(SAFE_LINK_SCHEMES)


# --- SVG ---------------------------------------------------------------------

_SVG_NS = "http://www.w3.org/2000/svg"
_XLINK_NS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", _SVG_NS)
ET.register_namespace("xlink", _XLINK_NS)

# Every element Graphviz's SVG renderer emits. Anything else
# (script, foreignObject, animate, set, iframe, ...) is removed.
_SVG_ELEMENTS = {
    "svg",
    "g",
    "title",
    "desc",
    "a",
    "text",
    "tspan",
    "polygon",
    "polyline",
    "path",
    "ellipse",
    "circle",
    "rect",
    "line",
    "image",
    "defs",
    "linearGradient",
    "radialGradient",
    "stop",
    "clipPath",
}
_HREF_ATTRS = {"href", f"{{{_XLINK_NS}}}href"}


def sanitize_svg(svg: str) -> str:
    """Return ``svg`` with everything that can run script removed.

    Graphviz copies some user text into its SVG without escaping, so the
    raw output of untrusted YAML can contain arbitrary markup. The SVG is
    parsed as XML and rebuilt from an allowlist: Graphviz's own elements,
    no ``on*`` attributes, links only to http/https/mailto or ``#``, and
    ``<image>`` only as an embedded ``data:image/`` URI. Markup that is
    not well-formed raises ValueError.
    """
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        raise ValueError(
            f"Rendered SVG is not well-formed ({exc}); the input likely "
            "contains markup that Graphviz does not escape"
        ) from exc

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    def clean(elem: ET.Element) -> None:
        for child in list(elem):
            if not isinstance(child.tag, str) or local(child.tag) not in _SVG_ELEMENTS:
                elem.remove(child)
                continue
            if local(child.tag) == "image":
                # Browsers may use either attribute; both must be inline data.
                hrefs = [v for a, v in child.attrib.items() if a in _HREF_ATTRS]
                if not hrefs or not all(h.startswith("data:image/") for h in hrefs):
                    elem.remove(child)
                    continue
            clean(child)
        for attr, value in list(elem.attrib.items()):
            name = local(attr).lower()
            if name.startswith("on"):
                del elem.attrib[attr]
            elif attr in _HREF_ATTRS and local(elem.tag) != "image":
                if not _safe_link(value):
                    del elem.attrib[attr]
            elif "javascript:" in "".join(value.split()).lower():
                del elem.attrib[attr]

    if local(root.tag) != "svg":
        raise ValueError("Rendered output is not an SVG document")
    clean(root)
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n' + body + "\n"


# --- HTML fragments ----------------------------------------------------------

# Tags users put in hypertext fields (see DataClasses.Hypertext) and the
# attributes each may keep.
_HTML_ALLOWED = {
    "a": {"href"},
    "b": set(),
    "i": set(),
    "u": set(),
    "s": set(),
    "em": set(),
    "strong": set(),
    "small": set(),
    "sub": set(),
    "sup": set(),
    "span": set(),
    "font": {"color"},
    "br": set(),
}
_HTML_VOID = {"br"}
_HTML_SKIP_CONTENT = {"script", "style", "template", "textarea", "title"}


class _FragmentSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: List[str] = []
        self.open: List[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _HTML_SKIP_CONTENT:
            self.skip += 1
            return
        if self.skip or tag not in _HTML_ALLOWED:
            return
        kept = []
        for name, value in attrs:
            if name not in _HTML_ALLOWED[tag] or value is None:
                continue
            if name == "href" and not _safe_link(value, allow_fragment=False):
                continue
            kept.append(f' {name}="{html.escape(value, quote=True)}"')
        if tag in _HTML_VOID:
            self.out.append(f"<{tag}{''.join(kept)} />")
        else:
            self.out.append(f"<{tag}{''.join(kept)}>")
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _HTML_VOID and self.open and self.open[-1] == tag:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in _HTML_SKIP_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in self.open:
            return
        while self.open:  # close anything left open inside this tag
            t = self.open.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            # quote=True: templates also put values inside attributes.
            self.out.append(html.escape(data, quote=True))


def sanitize_html_fragment(fragment: Any) -> str:
    """Return ``fragment`` as HTML that keeps simple formatting and safe
    links and drops every other tag, attribute and script."""
    parser = _FragmentSanitizer()
    parser.feed(str(fragment))
    parser.close()
    parser.out.extend(f"</{t}>" for t in reversed(parser.open))
    return "".join(parser.out)
