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

import re

# Upper bound for one pin/wire range (``[1-10000]``) and for
# ``pincount`` / ``wirecount``. Applies to all callers.
MAX_EXPAND = 10_000

# ``options.fontname`` is written into Graphviz attributes and the HTML
# template, and Graphviz does not escape it in SVG output. Font family
# names never need markup characters.
FONTNAME_PATTERN = re.compile(r"^[\w][\w ,.\-]*$")


def check_fontname(fontname: str) -> str:
    """Return ``fontname`` unchanged, or raise ValueError if it holds
    characters that could break out of an SVG or HTML attribute."""
    if not isinstance(fontname, str) or not FONTNAME_PATTERN.match(fontname):
        raise ValueError(
            f"options.fontname {fontname!r} is not a valid font name "
            "(allowed: letters, digits, space, comma, period, hyphen, underscore)"
        )
    return fontname


def check_count(name: str, value: int) -> None:
    """Raise ValueError when a pin/wire count is above ``MAX_EXPAND``."""
    if value > MAX_EXPAND:
        raise ValueError(f"{name} {value} is larger than the limit of {MAX_EXPAND}")
