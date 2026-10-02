# -*- coding: utf-8 -*-

import re
from html import escape
from html.entities import name2codepoint
from typing import List, Optional, Union

from wireviz.DataClasses import Color
from wireviz.wv_colors import translate_color
from wireviz.wv_helper import remove_links


def nested_html_table(
    rows: List[Union[str, List[Optional[str]], None]], table_attrs: str = ""
) -> str:
    # input: list, each item may be scalar or list
    # output: a parent table with one child table per parent item that is list, and one cell per parent item that is scalar
    # purpose: create the appearance of one table, where cell widths are independent between rows
    # attributes in any leading <tdX> inside a list are injected into to the preceeding <td> tag
    html = []
    html.append(
        f'<table border="0" cellspacing="0" cellpadding="0"{table_attrs or ""}>'
    )

    num_rows = 0
    for row in rows:
        if isinstance(row, List):
            if len(row) > 0 and any(row):
                html.append(" <tr><td>")
                # fmt: off
                html.append('  <table border="0" cellspacing="0" cellpadding="3" cellborder="1"><tr>')
                # fmt: on
                for cell in row:
                    if cell is not None:
                        # Inject attributes to the preceeding <td> tag where needed
                        # fmt: off
                        html.append(f'   <td balign="left">{cell}</td>'.replace("><tdX", ""))
                        # fmt: on
                html.append("  </tr></table>")
                html.append(" </td></tr>")
                num_rows = num_rows + 1
        elif row is not None:
            html.append(" <tr><td>")
            html.append(f"  {row}")
            html.append(" </td></tr>")
            num_rows = num_rows + 1
    if num_rows == 0:  # empty table
        # generate empty cell to avoid GraphViz errors
        html.append("<tr><td></td></tr>")
    html.append("</table>")
    return html


def html_bgcolor_attr(color: Color) -> str:
    """Return attributes for bgcolor or '' if no color."""
    return f' bgcolor="{translate_color(color, "HEX")}"' if color else ""


def html_bgcolor(color: Color, _extra_attr: str = "") -> str:
    """Return <td> attributes prefix for bgcolor or '' if no color."""
    return f"<tdX{html_bgcolor_attr(color)}{_extra_attr}>" if color else ""


def html_colorbar(color: Color) -> str:
    """Return <tdX> attributes prefix for bgcolor and minimum width or None if no color."""
    return html_bgcolor(color, ' width="4"') if color else None


def html_img_tag(image) -> str:
    """Return the exact ``<img>`` tag WireViz emits for ``image``.
    wv_safety.check_dot_images allows only these strings in untrusted mode."""
    src = escape(str(image.src), quote=True)  # paths may contain & < > "
    scale = escape(str(image.scale), quote=True)
    return f'<img scale="{scale}" src="{src}"/>'


def html_image(image):
    from wireviz.DataClasses import Image

    if not image:
        return None
    # The leading attributes belong to the preceeding tag. See where used below.
    html = f"{html_size_attr(image)}>{html_img_tag(image)}"
    if image.fixedsize:
        # Close the preceeding tag and enclose the image cell in a table without
        # borders to avoid narrow borders when the fixed width < the node width.
        html = f""">
    <table border="0" cellspacing="0" cellborder="0"><tr>
     <td{html}</td>
    </tr></table>
   """
    return f"""<tdX{' sides="TLR"' if image.caption else ''}{html_bgcolor_attr(image.bgcolor)}{html}"""


def html_caption(image):
    from wireviz.DataClasses import Image

    return (
        f'<tdX sides="BLR"{html_bgcolor_attr(image.bgcolor)}>{html_line_breaks(image.caption)}'
        if image and image.caption
        else None
    )


def html_size_attr(image):
    from wireviz.DataClasses import Image

    # Return Graphviz HTML attributes to specify minimum or fixed size of a TABLE or TD object
    return (
        (
            (f' width="{image.width}"' if image.width else "")
            + (f' height="{image.height}"' if image.height else "")
            + (' fixedsize="true"' if image.fixedsize else "")
        )
        if image
        else ""
    )


# A bare &, < or > breaks the Graphviz HTML-like label (upstream #230):
# XML rejects a bare & or <, and the DOT parser counts angle brackets to
# find the end of the label. Text between tags is escaped; tags (<b>,
# <br/>, <font ...>) and entities (&amp;, &#176;) are kept, so intended
# markup still works.
# Only the elements Graphviz HTML-like labels know, and only HTML entity
# names or numeric entities: "<VBAT>" or "a&b;c" is user text.
_TAG = re.compile(
    r"(</?(?:b|br|font|i|img|o|s|sub|sup|u|hr|vr|table|tr|td)\b[^<>]*>)",
    re.IGNORECASE,
)
_BARE_AMP = re.compile(
    r"&(?!(?:#[0-9]+|#[xX][0-9a-fA-F]+|(?:"
    + "|".join(sorted(name2codepoint, key=len, reverse=True))
    + r"));)"
)


def escape_bare(inp):
    """Escape &, < and > that are not part of an entity or a tag."""
    if not isinstance(inp, str):
        return inp
    parts = _TAG.split(inp)
    for i in range(0, len(parts), 2):  # even indexes are text between tags
        text = _BARE_AMP.sub("&amp;", parts[i])
        parts[i] = text.replace("<", "&lt;").replace(">", "&gt;")
    return "".join(parts)


def html_text(inp):
    """Return a single-line value ready for a Graphviz HTML-like label."""
    return escape_bare(remove_links(inp)) if isinstance(inp, str) else inp


def html_line_breaks(inp):
    return (
        escape_bare(remove_links(inp)).replace("\n", "<br />")
        if isinstance(inp, str)
        else inp
    )
