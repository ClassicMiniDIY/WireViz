# -*- coding: utf-8 -*-

import base64
import html
import re
import sys
from pathlib import Path
from typing import Collection, Optional, Union

mime_subtype_replacements = {"jpg": "jpeg", "svg": "svg+xml", "tif": "tiff"}


# TODO: Share cache and code between data_URI_base64() and embed_svg_images()
def data_URI_base64(file: Union[str, Path], media: str = "image") -> str:
    """Return Base64-encoded data URI of input file."""
    file = Path(file)
    b64 = base64.b64encode(file.read_bytes()).decode("utf-8")
    uri = f"data:{media}/{get_mime_subtype(file)};base64,{b64}"
    if len(uri) > 65535:
        sys.stderr.write(
            "data_URI_base64(): Warning: Browsers might have different URI length limitations\n"
        )
    return uri


def embed_svg_images(
    svg_in: str,
    base_path: Union[str, Path, None] = None,
    allowed_paths: Optional[Collection[Union[str, Path]]] = None,
) -> str:
    """Replace ``<image xlink:href="file">`` references with data URIs.

    Args:
        svg_in: SVG text produced by Graphviz.
        base_path: Directory that relative references resolve against.
            Defaults to the current working directory.
        allowed_paths: The image files that may be read. A reference
            that resolves to any other file is left unchanged and a
            warning goes to stderr. ``None`` allows every file — only
            for callers that fully trust the SVG. Graphviz copies some
            user input into the SVG without escaping, so text in a YAML
            file can add ``<image>`` elements; ``Harness`` therefore
            always passes the images it resolved from ``image.src``.
    """
    base = Path(base_path) if base_path is not None else Path.cwd()
    allowed = (
        None
        if allowed_paths is None
        else {(base / Path(p)).resolve() for p in allowed_paths}
    )
    images_b64 = {}  # cache of base64-encoded images

    def image_tag(pre: str, url: str, post: str) -> str:
        return f'<image{pre} xlink:href="{url}"{post}>'

    def replace(match: re.Match) -> str:
        imgurl = match["URL"]
        if imgurl.startswith("data:"):
            return match[0]
        if not imgurl in images_b64:  # only encode/cache every unique URL once
            imgurl_abs = (base / html.unescape(imgurl)).resolve()
            if allowed is not None and imgurl_abs not in allowed:
                sys.stderr.write(
                    f"Warning: SVG references {imgurl!r}, which is not an image "
                    "declared in the harness; it is not embedded\n"
                )
                return match[0]
            image = imgurl_abs.read_bytes()
            images_b64[imgurl] = base64.b64encode(image).decode("utf-8")
        return image_tag(
            match["PRE"] or "",
            f"data:image/{get_mime_subtype(html.unescape(imgurl))};base64,{images_b64[imgurl]}",
            match["POST"] or "",
        )

    pattern = re.compile(
        image_tag(r"(?P<PRE> [^>]*?)?", r'(?P<URL>[^"]*?)', r"(?P<POST> [^>]*?)?"),
        re.IGNORECASE,
    )
    return pattern.sub(replace, svg_in)


def get_mime_subtype(filename: Union[str, Path]) -> str:
    mime_subtype = Path(filename).suffix.lstrip(".").lower()
    if mime_subtype in mime_subtype_replacements:
        mime_subtype = mime_subtype_replacements[mime_subtype]
    return mime_subtype
