# -*- coding: utf-8 -*-

import base64
import re
import struct
import subprocess
import sys
import zlib
from collections import Counter
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Set, Tuple, Union

from graphviz import Graph, nohtml
from graphviz.quoting import attr_list, quote

from wireviz import APP_NAME, APP_URL, __version__, wv_colors
from wireviz.DataClasses import (
    Cable,
    Connector,
    MateComponent,
    MatePin,
    Metadata,
    Options,
    Side,
    Tweak,
)
from wireviz.svgembed import embed_svg_images
from wireviz.wv_bom import (
    HEADER_MPN,
    HEADER_PN,
    HEADER_SPN,
    bom_list,
    component_table_entry,
    generate_bom,
    get_additional_component_table,
    make_list,
    pn_info_string,
)
from wireviz.wv_colors import get_color_hex, translate_color
from wireviz.wv_gv_html import (
    html_bgcolor,
    html_bgcolor_attr,
    html_caption,
    html_colorbar,
    html_image,
    html_img_tag,
    html_line_breaks,
    html_text,
    nested_html_table,
    remove_links,
)
from wireviz.wv_helper import (
    awg_equiv,
    file_write_text,
    flatten2d,
    is_arrow,
    mm2_equiv,
    tuplelist2csv,
    tuplelist2tsv,
    upper_first,
)
from wireviz.wv_html import generate_html_output
from wireviz.wv_safety import (
    UNTRUSTED_RENDER_TIMEOUT,
    check_dot_images,
    check_html_label,
    sanitize_svg,
)

OLD_CONNECTOR_ATTR = {
    "pinout": "was renamed to 'pinlabels' in v0.2",
    "pinnumbers": "was renamed to 'pins' in v0.2",
    "autogenerate": "is replaced with new syntax in v0.4",
}

# iTXt chunk key used to embed the source YAML in rendered PNGs for
# round-trip editing. The "wireviz:" prefix avoids collision with PNG
# software-defined keywords or other tools' chunks.
PNG_YAML_CHUNK_KEY = "wireviz:yaml"


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Upper bound for the decompressed YAML read back from a PNG. Real
# harness sources are a few kB; the limit stops a zlib bomb.
_MAX_PNG_YAML_BYTES = 16 * 1024 * 1024


def _png_chunks(png_bytes: bytes):
    """Yield ``(type, data, raw_chunk)`` for each chunk of a PNG file.

    Works on the raw bytes, so no pixel data is decoded. A crafted PNG
    with huge dimensions therefore costs nothing to inspect.
    """
    if not png_bytes.startswith(_PNG_SIGNATURE):
        raise ValueError("Not a PNG file (bad signature)")
    pos = len(_PNG_SIGNATURE)
    while pos < len(png_bytes):
        if pos + 8 > len(png_bytes):
            raise ValueError("Truncated PNG chunk header")
        (length,) = struct.unpack(">I", png_bytes[pos : pos + 4])
        ctype = png_bytes[pos + 4 : pos + 8]
        end = pos + 12 + length
        if end > len(png_bytes):
            raise ValueError("Truncated PNG chunk")
        yield ctype, png_bytes[pos + 8 : pos + 8 + length], png_bytes[pos:end]
        pos = end
        if ctype == b"IEND":
            return


def _itxt_chunk(keyword: str, text: str) -> bytes:
    """Return a complete, compressed iTXt chunk (length, type, data, CRC)."""
    data = (
        keyword.encode("latin-1")
        + b"\x00"  # keyword terminator
        + b"\x01\x00"  # compression flag = on, method = zlib
        + b"\x00"  # empty language tag
        + b"\x00"  # empty translated keyword
        + zlib.compress(text.encode("utf-8"))
    )
    ctype = b"iTXt"
    return (
        struct.pack(">I", len(data))
        + ctype
        + data
        + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
    )


def _parse_itxt(data: bytes) -> Tuple[str, str]:
    """Return ``(keyword, text)`` from the data of an iTXt chunk."""
    try:
        keyword, rest = data.split(b"\x00", 1)
        compressed, method = rest[0], rest[1]
        _language, rest = rest[2:].split(b"\x00", 1)
        _translated, text = rest.split(b"\x00", 1)
    except (ValueError, IndexError) as exc:
        raise ValueError("Malformed iTXt chunk") from exc
    if compressed:
        if method != 0:
            raise ValueError(f"Unknown iTXt compression method {method}")
        inflater = zlib.decompressobj()
        text = inflater.decompress(text, _MAX_PNG_YAML_BYTES)
        if inflater.unconsumed_tail:
            raise ValueError(
                f"Embedded text is larger than {_MAX_PNG_YAML_BYTES} bytes"
            )
    return keyword.decode("latin-1"), text.decode("utf-8")


def _embed_yaml_in_png(png_bytes: bytes, yaml_source: str) -> bytes:
    """Return the PNG with the YAML source stored in an iTXt chunk.

    The chunk is inserted just before ``IEND``; every other chunk is
    copied byte for byte, so DPI, color profile and other text chunks
    stay as they were. An existing ``wireviz:yaml`` chunk is replaced.
    The image is not decoded, so the cost does not depend on its size.
    """
    out = [_PNG_SIGNATURE]
    for ctype, data, raw in _png_chunks(png_bytes):
        if (
            ctype == b"iTXt"
            and data.split(b"\x00", 1)[0] == PNG_YAML_CHUNK_KEY.encode()
        ):
            continue  # we're about to write a fresh one
        if ctype == b"IEND":
            out.append(_itxt_chunk(PNG_YAML_CHUNK_KEY, yaml_source))
        out.append(raw)
    return b"".join(out)


def read_yaml_from_png(png: Union[str, Path, BinaryIO]) -> Optional[str]:
    """Return the YAML source embedded in a PNG by an earlier WireViz
    render, or ``None`` if no ``wireviz:yaml`` chunk is present.

    ``png`` is a path or a binary file-like object. Only the chunk
    structure is read; the image itself is never decoded.
    """
    png_bytes = png.read() if hasattr(png, "read") else Path(png).read_bytes()
    key = PNG_YAML_CHUNK_KEY.encode()
    for ctype, data, _raw in _png_chunks(png_bytes):
        if ctype == b"iTXt" and data.split(b"\x00", 1)[0] == key:
            return _parse_itxt(data)[1]
    return None


# A DOT ID that needs no quotes: an identifier or a numeral.
_DOT_PLAIN_ID = re.compile(
    r"^([A-Za-z_\x80-\uffff][\w\x80-\uffff]*|-?(\.\d+|\d+(\.\d*)?))$"
)


# One complete DOT double-quoted string (inner quotes escaped).
_DOT_QUOTED = re.compile(r'^"(?:[^"\\]|\\.)*"$', re.S)


def _dot_attr_value(value: str) -> str:
    """Return ``value`` ready for a DOT attribute: as-is when it is a
    plain ID, a numeral, an already-quoted string or an HTML label;
    otherwise quoted, with inner double quotes escaped."""
    if _DOT_PLAIN_ID.match(value):
        return value
    if _DOT_QUOTED.match(value) or (
        len(value) >= 2 and value[0] == "<" and value[-1] == ">"
    ):
        return value
    # Keep backslash escapes (\N, \l) but never end on a lone backslash,
    # which would escape the closing quote.
    if (len(value) - len(value.rstrip("\\"))) % 2:
        value += "\\"
    return '"' + re.sub(r'(?<!\\)"', r'\\"', value) + '"'


def short_cells(connector: Connector, pinindex: int) -> List[str]:
    """Return one table cell per short (upstream #350) for the pin row at
    ``pinindex``: a solid bar from the first to the last shorted pin, with
    a dot at each shorted pin."""
    cells = []
    for pins, color in connector.short_groups:
        rows = [connector.pins.index(pin) for pin in pins]
        hex_color = get_color_hex(color)[0] if color else "#000000"
        if pinindex in rows:
            r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
            dot = "#000000" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#ffffff"
            cells.append(
                f'    <td border="0" bgcolor="{hex_color}"><font color="{dot}">&#9679;</font></td>'
            )
        elif min(rows) < pinindex < max(rows):
            cells.append(f'    <td border="0" bgcolor="{hex_color}"></td>')
        else:
            cells.append('    <td border="0"></td>')
    return cells


def _edge(dot: Graph, tail: tuple, head: tuple, **attrs) -> None:
    """Add an edge between two ``(node, port, compass)`` endpoints.

    graphviz's ``Graph.edge()`` takes "node:port:compass" strings and
    splits them on ":", so a designator that contains a colon broke the
    DOT source (upstream #487). Each part is quoted on its own here.
    The line has the same format ``Graph.edge()`` writes.
    """

    def endpoint(node, port, compass) -> str:
        # nohtml: a name like "<X1>" is a plain string, not an HTML label
        parts = [quote(nohtml(str(node)))]
        if port:
            parts.append(quote(port))
        if compass:
            parts.append(compass)
        return ":".join(parts)

    dot.body.append(
        f"\t{endpoint(*tail)} -- {endpoint(*head)}{attr_list(kwargs=attrs)}\n"
    )


def check_old(node: str, old_attr: dict, args: dict) -> None:
    """Raise exception for any outdated attributes in args."""
    for attr, descr in old_attr.items():
        if attr in args:
            raise ValueError(f"'{attr}' in {node}: '{attr}' {descr}")


@dataclass
class Harness:
    metadata: Metadata
    options: Options
    tweak: Tweak
    source_path: Path = None
    # True when the YAML came from an untrusted source; see
    # parse(untrusted=...). _render then sanitizes SVG and HTML output
    # and runs Graphviz with a timeout.
    untrusted: bool = False

    def __post_init__(self):
        self.connectors = {}
        self.cables = {}
        self.mates = []
        self._bom = []  # Internal Cache for generated bom
        self.additional_bom_items = []
        self._temp_dir: Optional[Path] = None

    def temp_dir(self) -> Path:
        """A private directory for files this harness generates (images
        decoded from data URIs, converted .webp). It is removed when the
        Harness object is garbage-collected."""
        if self._temp_dir is None:
            import shutil
            import tempfile
            import weakref

            self._temp_dir = Path(tempfile.mkdtemp(prefix="wireviz-")).resolve()
            weakref.finalize(self, shutil.rmtree, str(self._temp_dir), True)
        return self._temp_dir

    def add_connector(self, name: str, *args, **kwargs) -> None:
        check_old(f"Connector '{name}'", OLD_CONNECTOR_ATTR, kwargs)
        self.connectors[name] = Connector(name, *args, **kwargs)
        self._extend_tweak(self.connectors[name])

    def add_cable(self, name: str, *args, **kwargs) -> None:
        self.cables[name] = Cable(name, *args, **kwargs)
        self._extend_tweak(self.cables[name])

    def _extend_tweak(self, node: Union[Connector, Cable]) -> None:
        """Fold ``node.tweak`` into ``self.tweak`` after substituting the
        node's name for the placeholder string.

        Per-connector / per-cable ``tweak:`` entries let users author a
        single template and have its ``override`` keys / ``append`` lines
        rewritten with the actual designator at instantiation time. This
        is the only place the placeholder substitution happens — the
        global tweak is applied unchanged at graph emission time.
        """
        if not node.tweak:
            return
        ph = node.tweak.placeholder
        # An empty string is a legal value to opt out of the global
        # placeholder; only None falls back.
        if ph is None:
            ph = self.tweak.placeholder
        # The replacement target may be None when an override deletes a
        # key (``key: null`` in YAML), so guard the str.replace call.
        if ph:
            rph = lambda s: s.replace(ph, node.name) if isinstance(s, str) else s
        else:
            rph = lambda s: s

        n_override = node.tweak.override or {}
        s_override = self.tweak.override or {}
        for ident, n_dict in n_override.items():
            ident = rph(ident)
            s_dict = s_override.get(ident, {})
            for k, v in n_dict.items():
                k, v = rph(k), rph(v)
                if k in s_dict and v != s_dict[k]:
                    raise ValueError(
                        f"{node.name}.tweak.override.{ident}.{k}: new value "
                        f"{v!r} conflicts with existing {s_dict[k]!r}"
                    )
                s_dict[k] = v
            # Keep the empty dict rather than collapsing to None — the
            # graph-emission code (Harness.create_graph) expects values
            # in self.tweak.override to be dicts, not None.
            s_override[ident] = s_dict
        self.tweak.override = s_override or None
        self.tweak.append = (
            make_list(self.tweak.append)
            + [rph(v) for v in make_list(node.tweak.append)]
        ) or None

    def add_mate_pin(self, from_name, from_pin, to_name, to_pin, arrow_type) -> None:
        # Pins may be given by label, as in cable connections (upstream #510).
        from_pin = self._resolve_pin(from_name, from_pin)
        to_pin = self._resolve_pin(to_name, to_pin)
        self.mates.append(MatePin(from_name, from_pin, to_name, to_pin, arrow_type))
        self.connectors[from_name].activate_pin(from_pin, Side.RIGHT)
        self.connectors[to_name].activate_pin(to_pin, Side.LEFT)

    def _pin_endpoint(self, name: str, pin, side: str, compass: str) -> tuple:
        """Return the ``(node, port, compass)`` of a connector pin; the port
        is None for simple connectors, which have no pin table."""
        connector = self.connectors[name]
        if connector.style == "simple":
            return (name, None, compass)
        return (name, f"p{connector.pins.index(pin) + 1}{side}", compass)

    def _resolve_pin(self, name: str, pin):
        """Return the pin number for ``pin`` on connector ``name``, where
        ``pin`` is a pin number or a pin label."""
        return self.connectors[name].resolve_pin(pin)

    def add_mate_component(self, from_name, to_name, arrow_type) -> None:
        self.mates.append(MateComponent(from_name, to_name, arrow_type))

    def add_bom_item(self, item: dict) -> None:
        self.additional_bom_items.append(item)

    def connect(
        self,
        from_name: str,
        from_pin: (int, str),
        via_name: str,
        via_wire: (int, str),
        to_name: str,
        to_pin: (int, str),
    ) -> None:
        # check from and to connectors
        if from_name is not None and from_name in self.connectors:
            from_pin = self._resolve_pin(from_name, from_pin)
        if to_name is not None and to_name in self.connectors:
            to_pin = self._resolve_pin(to_name, to_pin)

        # check via cable
        if via_name in self.cables:
            cable = self.cables[via_name]
            # check if provided name is ambiguous
            if via_wire in cable.colors and via_wire in cable.wirelabels:
                if cable.colors.index(via_wire) != cable.wirelabels.index(via_wire):
                    raise Exception(
                        f"{via_name}:{via_wire} is defined both in colors and wirelabels, for different wires."
                    )
                # TODO: Maybe issue a warning if present in both lists but referencing the same wire?
            if via_wire in cable.colors:
                if cable.colors.count(via_wire) > 1:
                    raise Exception(
                        f"{via_name}:{via_wire} is used for more than one wire."
                    )
                # list index starts at 0, wire IDs start at 1
                via_wire = cable.colors.index(via_wire) + 1
            elif (
                isinstance(via_wire, int)
                and not 1 <= via_wire <= cable.wirecount
                and [str(label) for label in cable.wirelabels].count(str(via_wire)) == 1
            ):
                # A quoted numeric label ('10') arrives as the number 10.
                via_wire = [str(label) for label in cable.wirelabels].index(
                    str(via_wire)
                ) + 1
            elif via_wire in cable.wirelabels:
                if cable.wirelabels.count(via_wire) > 1:
                    raise Exception(
                        f"{via_name}:{via_wire} is used for more than one wire."
                    )
                via_wire = (
                    cable.wirelabels.index(via_wire) + 1
                )  # list index starts at 0, wire IDs start at 1
            # Validate here: an out-of-range wire used to fail deep inside
            # create_graph with an IndexError (upstream #208), and an
            # unknown label was silently drawn as the shield.
            if isinstance(via_wire, int) and not isinstance(via_wire, bool):
                if not 1 <= via_wire <= cable.wirecount:
                    raise ValueError(
                        f"{via_name}:{via_wire} is out of range; "
                        f"{via_name} has {cable.wirecount} wire(s)"
                    )
            elif via_wire != "s":
                raise ValueError(f"{via_name}:{via_wire} not found.")
            elif not cable.shield:
                raise ValueError(f"{via_name}:s is used, but {via_name} has no shield.")

        # perform the actual connection
        self.cables[via_name].connect(from_name, from_pin, via_wire, to_name, to_pin)
        if from_name in self.connectors:
            self.connectors[from_name].activate_pin(from_pin, Side.RIGHT)
        if to_name in self.connectors:
            self.connectors[to_name].activate_pin(to_pin, Side.LEFT)

    def create_graph(self) -> Graph:
        dot = Graph()
        dot.body.append(f"// Graph generated by {APP_NAME} {__version__}\n")
        dot.body.append(f"// {APP_URL}\n")
        graph_attrs = dict(
            rankdir="LR",
            ranksep="2",
            bgcolor=wv_colors.translate_color(self.options.bgcolor, "HEX"),
            nodesep="0.33",
            fontname=self.options.fontname,
        )
        # Pass dpi only when set; output_dpi: null in YAML means "let
        # Graphviz pick its default" (96 for non-PostScript renderers).
        # Stringified because the graphviz Python lib doesn't coerce
        # numerics for us.
        if self.options.output_dpi is not None:
            graph_attrs["dpi"] = str(self.options.output_dpi)
        if self.options.show_title and self.metadata.get("title"):
            # A plain-text graph label: graphviz quotes it (#460).
            graph_attrs.update(
                # Backslashes doubled: DOT reads \N, \G and a trailing \
                # in a label as escapes.
                label=nohtml(str(self.metadata["title"]).replace("\\", "\\\\")),
                labelloc="t",
                fontsize="20",
            )
        dot.attr("graph", **graph_attrs)  # TODO: Add graph attribute: charset="utf-8",
        dot.attr(
            "node",
            shape="none",
            width="0",
            height="0",
            margin="0",  # Actual size of the node is entirely determined by the label.
            style="filled",
            fillcolor=wv_colors.translate_color(self.options.bgcolor_node, "HEX"),
            fontname=self.options.fontname,
        )
        dot.attr("edge", style="bold", fontname=self.options.fontname)

        # determine if there are double- or triple-colored wires in the harness;
        # if so, pad single-color wires and loops to make all wires of equal thickness
        pad = any(
            len(get_color_hex(colorstr)) > 1
            for cable in self.cables.values()
            for colorstr in cable.colors
        )

        for connector in self.connectors.values():
            # If no wires connected (except maybe loop wires)?
            if not (connector.ports_left or connector.ports_right):
                connector.ports_left = True  # Use left side pins.

            # Resolve per-loop sides *before* the pin table is built so
            # loop pins are guaranteed to activate the correct port column.
            loop_sides = connector.resolve_loops()

            html = []
            # fmt: off
            rows = [[f'{html_bgcolor(connector.bgcolor_title)}{html_text(connector.name)}'
                        if connector.show_name else None],
                    [pn_info_string(HEADER_PN, None, html_text(connector.pn)),
                     html_line_breaks(pn_info_string(HEADER_MPN, connector.manufacturer, connector.mpn)),
                     html_line_breaks(pn_info_string(HEADER_SPN, connector.supplier, connector.spn))],
                    [html_line_breaks(connector.type),
                     html_line_breaks(connector.subtype),
                     f'{connector.pincount}-{html_text(self.options.terminology.pin)}' if connector.show_pincount else None,
                     html_text(translate_color(connector.color, self.options.color_mode)) if connector.color else None,
                     html_colorbar(connector.color)],
                    '<!-- connector table -->' if connector.style != 'simple' else None,
                    [html_image(connector.image)],
                    [html_caption(connector.image)]]
            # fmt: on

            rows.extend(get_additional_component_table(self, connector))
            if connector.strip and connector.strip.description():
                rows.append([html_text(connector.strip.description())])
            rows.append([html_line_breaks(connector.notes)])
            html.extend(nested_html_table(rows, html_bgcolor_attr(connector.bgcolor)))

            if connector.style != "simple":
                pinhtml = []
                pinhtml.append(
                    '<table border="0" cellspacing="0" cellpadding="3" cellborder="1">'
                )

                for pinindex, (pinname, pinlabel, pincolor) in enumerate(
                    zip_longest(
                        connector.pins, connector.pinlabels, connector.pincolors
                    )
                ):
                    if (
                        connector.hide_disconnected_pins
                        and not connector.visible_pins.get(pinname, False)
                    ):
                        continue

                    pinhtml.append("   <tr>")
                    if connector.ports_left:
                        pinhtml.append(
                            f'    <td port="p{pinindex+1}l">{html_text(pinname)}</td>'
                        )
                    # Shorts sit next to the left ports (or first): every row
                    # has those cells, so the short columns line up.
                    pinhtml.extend(short_cells(connector, pinindex))
                    if pinlabel:
                        pinhtml.append(f"    <td>{html_text(pinlabel)}</td>")
                    if connector.pincolors:
                        if pincolor in wv_colors._color_hex or wv_colors.css_color_hex(
                            pincolor
                        ):
                            # fmt: off
                            pinhtml.append(f'    <td sides="tbl">{html_text(translate_color(pincolor, self.options.color_mode))}</td>')
                            pinhtml.append( '    <td sides="tbr">')
                            pinhtml.append( '     <table border="0" cellborder="1"><tr>')
                            pinhtml.append(f'      <td bgcolor="{wv_colors.translate_color(pincolor, "HEX")}" width="8" height="8" fixedsize="true"></td>')
                            pinhtml.append( '     </tr></table>')
                            pinhtml.append( '    </td>')
                            # fmt: on
                        else:
                            pinhtml.append('    <td colspan="2"></td>')

                    if connector.ports_right:
                        pinhtml.append(
                            f'    <td port="p{pinindex+1}r">{html_text(pinname)}</td>'
                        )
                    pinhtml.append("   </tr>")

                pinhtml.append("  </table>")

                if len(pinhtml) == 2:  # Table start and end with no rows between?
                    pinhtml = ["<!-- all pins hidden -->"]  # Avoid Graphviz error

                html = [
                    row.replace("<!-- connector table -->", "\n".join(pinhtml))
                    for row in html
                ]

            html = "\n".join(html)
            if self.untrusted:
                check_html_label(html, f"Connector {connector.name}")
            dot.node(
                nohtml(connector.name),
                label=f"<\n{html}\n>",
                shape="box",
                style="filled",
                fillcolor=translate_color(self.options.bgcolor_connector, "HEX"),
            )

            if len(connector.loops) > 0:
                for loop, (side_a, side_b), loop_color in zip(
                    connector.loops, loop_sides, connector.loop_colors
                ):
                    dot.attr(
                        "edge",
                        color=":".join(
                            ["#000000"]
                            + (
                                get_color_hex(loop_color, pad=pad)
                                if loop_color
                                else ["#ffffff"]
                            )
                            + ["#000000"]
                        ),
                    )
                    # Pin port IDs are 1-based positions in the pin table,
                    # NOT pin numbers (see the pin HTML emission above,
                    # `port="p{pinindex+1}..."`). Translate pin numbers to
                    # positions the same way cable and mate edges do
                    # (self.connectors[...].pins.index(pin) + 1).
                    pos_a = connector.pins.index(loop[0]) + 1
                    pos_b = connector.pins.index(loop[1]) + 1
                    s_a = "l" if side_a == Side.LEFT else "r"
                    s_b = "l" if side_b == Side.LEFT else "r"
                    d_a = "w" if side_a == Side.LEFT else "e"
                    d_b = "w" if side_b == Side.LEFT else "e"
                    _edge(
                        dot,
                        (connector.name, f"p{pos_a}{s_a}", d_a),
                        (connector.name, f"p{pos_b}{s_b}", d_b),
                        label=" ",  # Work-around to avoid over-sized loops.
                    )

        for cable in self.cables.values():
            html = []

            awg_fmt = ""
            # gauge_unit is None when no gauge is given (upstream #497/#498).
            if cable.show_equiv and isinstance(cable.gauge_unit, str):
                # Only convert units we actually know about, i.e. currently
                # mm2 and awg --- other units _are_ technically allowed,
                # and passed through as-is.
                if cable.gauge_unit == "mm\u00B2":
                    awg_fmt = f" ({awg_equiv(cable.gauge)} AWG)"
                elif cable.gauge_unit.upper() == "AWG":
                    awg_fmt = f" ({mm2_equiv(cable.gauge)} mm\u00B2)"

            # fmt: off
            rows = [[f'{html_bgcolor(cable.bgcolor_title)}{html_text(cable.name)}'
                        if cable.show_name else None],
                    [pn_info_string(HEADER_PN, None,
                        html_text(cable.pn)) if not isinstance(cable.pn, list) else None,
                     html_line_breaks(pn_info_string(HEADER_MPN,
                        cable.manufacturer if not isinstance(cable.manufacturer, list) else None,
                        cable.mpn if not isinstance(cable.mpn, list) else None)),
                     html_line_breaks(pn_info_string(HEADER_SPN,
                        cable.supplier if not isinstance(cable.supplier, list) else None,
                        cable.spn if not isinstance(cable.spn, list) else None))],
                    [html_line_breaks(cable.type),
                     f'{cable.wirecount}x' if cable.show_wirecount else None,
                     f'{html_text(str(cable.gauge))} {html_text(cable.gauge_unit)}{awg_fmt}' if cable.gauge else None,
                     '+ S' if cable.shield else None,
                     f'{cable.length} {html_text(cable.length_unit)}' if cable.length > 0 else None,
                     html_text(translate_color(cable.color, self.options.color_mode)) if cable.color else None,
                     html_colorbar(cable.color)],
                    '<!-- wire table -->',
                    [html_image(cable.image)],
                    [html_caption(cable.image)]]
            # fmt: on

            rows.extend(get_additional_component_table(self, cable))
            rows.append([html_line_breaks(cable.notes)])
            html.extend(nested_html_table(rows, html_bgcolor_attr(cable.bgcolor)))

            wirehtml = []
            # conductor table
            wirehtml.append('<table border="0" cellspacing="0" cellborder="0">')
            wirehtml.append("   <tr><td>&nbsp;</td></tr>")

            wires = list(zip_longest(cable.colors, cable.wirelabels))
            order, group_of = cable.wire_display_order()
            for i in order:
                connection_color, wirelabel = wires[i - 1]
                group = group_of.get(i)
                if group is not None and i == cable.twisted_groups[group][0][0]:
                    # Twisted group (upstream #3, #353): a thin solid frame
                    # with a caption. Solid, because dashed means a shield.
                    numbers, rate = cable.twisted_groups[group]
                    kind = {2: "pair", 3: "triad", 4: "quad"}.get(len(numbers), "group")
                    caption = f"Twisted {kind}" + (f": {rate}" if rate else "")
                    wirehtml.append(
                        '   <tr><td colspan="3" border="1" cellpadding="2">'
                    )
                    wirehtml.append(
                        '    <table border="0" cellspacing="0" cellborder="0">'
                    )
                    wirehtml.append(
                        f'     <tr><td colspan="3">{html_text(caption)}</td></tr>'
                    )
                wirehtml.append("   <tr>")
                wirehtml.append(f"    <td><!-- {i}_in --></td>")
                wirehtml.append(f"    <td>")

                wireinfo = []
                if cable.show_wirenumbers:
                    wireinfo.append(str(i))
                colorstr = wv_colors.translate_color(
                    connection_color, self.options.color_mode
                )
                if colorstr:
                    wireinfo.append(colorstr)
                if cable.wirelabels:
                    wireinfo.append(wirelabel if wirelabel is not None else "")
                wirehtml.append(f'     {html_text(":".join(wireinfo))}')

                wirehtml.append(f"    </td>")
                wirehtml.append(f"    <td><!-- {i}_out --></td>")
                wirehtml.append("   </tr>")

                # fmt: off
                bgcolors = ['#000000'] + get_color_hex(connection_color, pad=pad) + ['#000000']
                wirehtml.append(f"   <tr>")
                wirehtml.append(f'    <td colspan="3" border="0" cellspacing="0" cellpadding="0" port="w{i}" height="{(2 * len(bgcolors))}">')
                wirehtml.append('     <table cellspacing="0" cellborder="0" border="0">')
                for j, bgcolor in enumerate(bgcolors[::-1]):  # Reverse to match the curved wires when more than 2 colors
                    wirehtml.append(f'      <tr><td colspan="3" cellpadding="0" height="2" bgcolor="{bgcolor if bgcolor != "" else wv_colors.default_color}" border="0"></td></tr>')
                wirehtml.append("     </table>")
                wirehtml.append("    </td>")
                wirehtml.append("   </tr>")
                # fmt: on

                # for bundles, individual wires can have part information
                if cable.category == "bundle":
                    # create a list of wire parameters
                    wireidentification = []
                    if isinstance(cable.pn, list):
                        wireidentification.append(
                            pn_info_string(HEADER_PN, None, html_text(cable.pn[i - 1]))
                        )
                    manufacturer_info = pn_info_string(
                        HEADER_MPN,
                        (
                            cable.manufacturer[i - 1]
                            if isinstance(cable.manufacturer, list)
                            else None
                        ),
                        cable.mpn[i - 1] if isinstance(cable.mpn, list) else None,
                    )
                    supplier_info = pn_info_string(
                        HEADER_SPN,
                        (
                            cable.supplier[i - 1]
                            if isinstance(cable.supplier, list)
                            else None
                        ),
                        cable.spn[i - 1] if isinstance(cable.spn, list) else None,
                    )
                    if manufacturer_info:
                        wireidentification.append(html_line_breaks(manufacturer_info))
                    if supplier_info:
                        wireidentification.append(html_line_breaks(supplier_info))
                    # print parameters into a table row under the wire
                    if len(wireidentification) > 0:
                        # fmt: off
                        wirehtml.append('   <tr><td colspan="3">')
                        wirehtml.append('    <table border="0" cellspacing="0" cellborder="0"><tr>')
                        for attrib in wireidentification:
                            wirehtml.append(f"     <td>{attrib}</td>")
                        wirehtml.append("    </tr></table>")
                        wirehtml.append("   </td></tr>")
                        # fmt: on

                if group is not None and i == cable.twisted_groups[group][0][-1]:
                    wirehtml.append("    </table>")
                    wirehtml.append("   </td></tr>")

            if cable.shield:
                wirehtml.append("   <tr><td>&nbsp;</td></tr>")  # spacer
                wirehtml.append("   <tr>")
                wirehtml.append("    <td><!-- s_in --></td>")
                wirehtml.append(
                    f"    <td>{html_text(upper_first(self.options.terminology.shield))}</td>"
                )
                wirehtml.append("    <td><!-- s_out --></td>")
                wirehtml.append("   </tr>")
                if isinstance(cable.shield, str):
                    # shield is shown with specified color and black borders
                    shield_color_hex = wv_colors.get_color_hex(cable.shield)[0]
                    attributes = (
                        f'height="6" bgcolor="{shield_color_hex}" border="2" sides="tb"'
                    )
                else:
                    # shield is shown as a thin black wire
                    attributes = f'height="2" bgcolor="#000000" border="0"'
                # fmt: off
                wirehtml.append(f'   <tr><td colspan="3" cellpadding="0" {attributes} port="ws"></td></tr>')
                # fmt: on

            wirehtml.append("   <tr><td>&nbsp;</td></tr>")
            wirehtml.append("  </table>")

            html = [
                row.replace("<!-- wire table -->", "\n".join(wirehtml)) for row in html
            ]

            # connections
            for connection in cable.connections:
                if isinstance(connection.via_port, int):
                    # check if it's an actual wire and not a shield
                    dot.attr(
                        "edge",
                        color=":".join(
                            ["#000000"]
                            + wv_colors.get_color_hex(
                                cable.colors[connection.via_port - 1], pad=pad
                            )
                            + ["#000000"]
                        ),
                    )
                else:  # it's a shield connection
                    # shield is shown with specified color and black borders, or as a thin black wire otherwise
                    dot.attr(
                        "edge",
                        color=(
                            ":".join(["#000000", shield_color_hex, "#000000"])
                            if isinstance(cable.shield, str)
                            else "#000000"
                        ),
                    )
                if not cable.show_box:
                    # show_box: false (upstream #212): no cable node; each wire
                    # is one edge straight from connector to connector.
                    if connection.from_pin is None or connection.to_pin is None:
                        raise ValueError(
                            f"Cable {cable.name}: show_box: false needs a "
                            "connector at both ends of every wire"
                        )
                    _edge(
                        dot,
                        self._pin_endpoint(
                            connection.from_name, connection.from_pin, "r", "e"
                        ),
                        self._pin_endpoint(
                            connection.to_name, connection.to_pin, "l", "w"
                        ),
                    )
                    continue
                if connection.from_pin is not None:  # connect to left
                    from_connector = self.connectors[connection.from_name]
                    from_pin_index = from_connector.pins.index(connection.from_pin)
                    from_port = (
                        f"p{from_pin_index+1}r"
                        if from_connector.style != "simple"
                        else None
                    )
                    _edge(
                        dot,
                        (connection.from_name, from_port, "e"),
                        (cable.name, f"w{connection.via_port}", "w"),
                    )
                    if from_connector.show_name:
                        from_info = [
                            str(connection.from_name),
                            str(connection.from_pin),
                        ]
                        if from_connector.pinlabels:
                            pinlabel = from_connector.pinlabels[from_pin_index]
                            if pinlabel != "":
                                from_info.append(pinlabel)
                        from_string = html_text(":".join(map(str, from_info)))
                    else:
                        from_string = ""
                    html = [
                        row.replace(f"<!-- {connection.via_port}_in -->", from_string)
                        for row in html
                    ]
                if connection.to_pin is not None:  # connect to right
                    to_connector = self.connectors[connection.to_name]
                    to_pin_index = to_connector.pins.index(connection.to_pin)
                    to_port = (
                        f"p{to_pin_index+1}l"
                        if to_connector.style != "simple"
                        else None
                    )
                    _edge(
                        dot,
                        (cable.name, f"w{connection.via_port}", "e"),
                        (connection.to_name, to_port, "w"),
                    )
                    if to_connector.show_name:
                        to_info = [str(connection.to_name), str(connection.to_pin)]
                        if to_connector.pinlabels:
                            pinlabel = to_connector.pinlabels[to_pin_index]
                            if pinlabel != "":
                                to_info.append(pinlabel)
                        to_string = html_text(":".join(map(str, to_info)))
                    else:
                        to_string = ""
                    html = [
                        row.replace(f"<!-- {connection.via_port}_out -->", to_string)
                        for row in html
                    ]

            style, bgcolor = (
                ("filled,dashed", self.options.bgcolor_bundle)
                if cable.category == "bundle"
                else ("filled", self.options.bgcolor_cable)
            )
            html = "\n".join(html)
            if self.untrusted and cable.show_box:
                check_html_label(html, f"Cable {cable.name}")
            if cable.show_box:
                dot.node(
                    nohtml(cable.name),
                    label=f"<\n{html}\n>",
                    shape="box",
                    style=style,
                    fillcolor=translate_color(bgcolor, "HEX"),
                )

        # mates
        for mate in self.mates:
            if mate.shape[-1] == ">":
                dir = "both" if mate.shape[0] == "<" else "forward"
            else:
                dir = "back" if mate.shape[0] == "<" else "none"

            if isinstance(mate, MatePin):
                color = "#000000"
            elif isinstance(mate, MateComponent):
                color = "#000000:#000000"
            else:
                raise Exception(f"{mate} is an unknown mate")

            from_connector = self.connectors[mate.from_name]
            to_connector = self.connectors[mate.to_name]
            if isinstance(mate, MatePin) and from_connector.style != "simple":
                from_pin_index = from_connector.pins.index(mate.from_pin)
                from_port = f"p{from_pin_index+1}r"
            else:  # MateComponent or style == 'simple'
                from_port = None
            if isinstance(mate, MatePin) and to_connector.style != "simple":
                to_pin_index = to_connector.pins.index(mate.to_pin)
                to_port = f"p{to_pin_index+1}l"
            else:  # MateComponent or style == 'simple'
                to_port = None

            dot.attr("edge", color=color, style="dashed", dir=dir)
            _edge(dot, (mate.from_name, from_port, "e"), (mate.to_name, to_port, "w"))

        def typecheck(name: str, value: Any, expect: type) -> None:
            if not isinstance(value, expect):
                raise Exception(
                    f"Unexpected value type of {name}: Expected {expect}, got {type(value)}\n{value}"
                )

        # TODO?: Differ between override attributes and HTML?
        if self.tweak.override is not None:
            typecheck("tweak.override", self.tweak.override, dict)
            for k, d in self.tweak.override.items():
                typecheck(f"tweak.override.{k} key", k, str)
                typecheck(f"tweak.override.{k} value", d, dict)
                for a, v in d.items():
                    typecheck(f"tweak.override.{k}.{a} key", a, str)
                    typecheck(f"tweak.override.{k}.{a} value", v, (str, type(None)))

            # Override generated attributes of selected entries matching tweak.override.
            for i, entry in enumerate(dot.body):
                if isinstance(entry, str):
                    # Find a possibly quoted keyword after leading TAB(s) and followed by [ ].
                    match = re.match(
                        r'^\t*(")?((?(1)[^"]|[^ "])+)(?(1)") \[.*\]$', entry, re.S
                    )
                    keyword = match and match[2]
                    if keyword in self.tweak.override.keys():
                        for attr, value in self.tweak.override[keyword].items():
                            if value is None:
                                entry, n_subs = re.subn(
                                    f'( +)?{re.escape(attr)}=("[^"]*"|[^] ]*)(?(1)| *)',
                                    "",
                                    entry,
                                )
                                if n_subs < 1:
                                    sys.stderr.write(
                                        f"Harness.create_graph() warning: {attr} not found in {keyword}!\n"
                                    )
                                elif n_subs > 1:
                                    sys.stderr.write(
                                        f"Harness.create_graph() warning: {attr} removed {n_subs} times in {keyword}!\n"
                                    )
                                continue

                            value = _dot_attr_value(value)
                            # Replacement functions, not strings: the value
                            # is literal text (it may hold \N, \l, ...).
                            entry, n_subs = re.subn(
                                f'{re.escape(attr)}=("[^"]*"|[^] ]*)',
                                lambda _m: f"{attr}={value}",
                                entry,
                            )
                            if n_subs < 1:
                                # If attr not found, then append it
                                entry = re.sub(
                                    r"\]$", lambda _m: f" {attr}={value}]", entry
                                )
                            elif n_subs > 1:
                                sys.stderr.write(
                                    f"Harness.create_graph() warning: {attr} overridden {n_subs} times in {keyword}!\n"
                                )

                        dot.body[i] = entry

        if self.tweak.append is not None:
            if isinstance(self.tweak.append, list):
                for i, element in enumerate(self.tweak.append, 1):
                    typecheck(f"tweak.append[{i}]", element, str)
                dot.body.extend(self.tweak.append)
            else:
                typecheck("tweak.append", self.tweak.append, str)
                dot.body.append(self.tweak.append)

        # Tweak processing above must be the last before returning dot.
        # Please don't insert any code that might change the dot contents
        # after tweak processing.

        return dot

    # cache for the GraphViz Graph object
    # do not access directly, use self.graph instead
    _graph = None

    @property
    def graph(self):
        if not self._graph:  # no cached graph exists, generate one
            self._graph = self.create_graph()
        return self._graph  # return cached graph

    def _pipe(self, fmt: str) -> bytes:
        """Run Graphviz on the harness graph and return the output.

        In untrusted mode Graphviz runs as a subprocess with a timeout,
        because the graphviz package's ``pipe()`` cannot stop it.
        """
        if not self.untrusted:
            return self.graph.pipe(format=fmt)
        check_dot_images(
            self.graph.source,
            {
                html_img_tag(node.image)
                for node in [*self.connectors.values(), *self.cables.values()]
                if node.image is not None
            },
        )
        try:
            result = subprocess.run(
                ["dot", "-Kdot", f"-T{fmt}"],
                input=self.graph.source.encode("utf-8"),
                capture_output=True,
                timeout=UNTRUSTED_RENDER_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Graphviz did not finish within {UNTRUSTED_RENDER_TIMEOUT} s"
            ) from exc
        if result.returncode != 0:
            raise RuntimeError(
                "Graphviz failed: " + result.stderr.decode("utf-8", "replace").strip()
            )
        return result.stdout

    @property
    def png(self):
        return self._render(("png",))["png"]

    @property
    def svg(self):  # TODO?: Verify xml encoding="utf-8" in SVG?
        return self._render(("svg",))["svg"]

    def _image_base_path(self) -> Path:
        """Directory that relative image references resolve against: the
        YAML source's directory when known, else the working directory."""
        if self.source_path is not None and str(self.source_path) != "-":
            return Path(self.source_path).parent
        return Path.cwd()

    def _declared_images(self) -> Set[Path]:
        """Resolved paths of every ``image.src`` in the harness — the only
        files ``embed_svg_images`` may read."""
        base = self._image_base_path()
        return {
            (base / Path(node.image.src)).resolve()
            for node in [*self.connectors.values(), *self.cables.values()]
            if node.image is not None
        }

    def output(
        self,
        filename: Optional[Union[str, Path]],
        fmt: Union[str, Tuple[str, ...], List[str]] = ("html", "png", "svg", "tsv"),
        view: bool = False,
        cleanup: bool = True,
        output_dir: Optional[Union[str, Path]] = None,
        output_name: Optional[str] = None,
        template_dir: Optional[Union[str, Path]] = None,
        yaml_source: Optional[str] = None,
    ) -> None:
        """Render the harness in the requested formats.

        When ``filename`` is a path, each requested format is written to
        ``{filename}.{ext}`` (with ``.bom.tsv`` for the BOM). When
        ``filename`` is None, exactly one format must be requested and
        its bytes/text are written to stdout — supports piping the CLI
        into other tools.

        If ``yaml_source`` is provided and PNG output is requested, the
        YAML source string is embedded in the PNG as an iTXt chunk under
        the key ``wireviz:yaml`` for round-trip editing. Recovery via
        ``Harness.read_yaml_from_png()`` or ``wireviz.parse()`` with a
        .png input file.

        Args:
            filename: Output base path (without extension). ``None``
                routes a single format to stdout instead of writing files.
            fmt: One or more formats from ``html``, ``png``, ``svg``,
                ``gv``, ``tsv``, ``csv``, ``pdf``. A bare string is
                normalized to a one-tuple.
            view: Reserved (unused — kept for API compatibility with the
                pre-refactor signature).
            cleanup: Reserved (unused — kept for API compatibility).
            output_dir: Output directory. Used only to populate the
                ``<!-- %filename% -->`` HTML template placeholder and to
                resolve a custom ``metadata.template.name`` reference.
            output_name: Output base name (without extension). Used only
                to populate the ``<!-- %filename_stem% -->`` HTML
                template placeholder.
            template_dir: Explicit directory to search first when
                resolving a ``metadata.template.name`` reference. Falls
                through to the YAML source directory, then ``output_dir``,
                then the built-in templates shipped with WireViz.
            yaml_source: Source YAML string. When non-None and PNG is in
                ``fmt``, embedded as an iTXt chunk in the PNG output for
                round-trip editing.
        """
        if isinstance(fmt, str):
            fmt = (fmt,)
        outputs: Dict[str, Union[str, bytes]] = self._render(
            fmt,
            output_dir=output_dir,
            output_name=output_name,
            template_dir=template_dir,
            yaml_source=yaml_source,
        )

        if filename is None:
            # stdout mode — emit each rendered format in the user-requested
            # order. Text is written as UTF-8 bytes: text-mode stdout uses
            # the locale encoding and, on Windows, rewrites \n as \r\n.
            sys.stdout.flush()
            out = getattr(sys.stdout, "buffer", None)
            for f in fmt:
                content = outputs.get(f)
                if content is None:
                    continue
                if out is None:  # stdout replaced by a text-only stream
                    if isinstance(content, (bytes, bytearray)):
                        raise RuntimeError(f"Cannot write binary {f} to text stdout")
                    sys.stdout.write(content)
                    continue
                if not isinstance(content, (bytes, bytearray)):
                    content = content.encode("utf-8")
                out.write(content)
            if out is not None:
                out.flush()
            return

        suffix_map = {"tsv": "bom.tsv", "csv": "bom.csv"}
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        for f, content in outputs.items():
            ext = suffix_map.get(f, f)
            out_path = f"{filename}.{ext}"
            if isinstance(content, (bytes, bytearray)):
                Path(out_path).write_bytes(content)
            else:
                file_write_text(out_path, content)

    def _render(
        self,
        fmt: Union[str, Tuple[str, ...], List[str]],
        output_dir: Optional[Union[str, Path]] = None,
        output_name: Optional[str] = None,
        template_dir: Optional[Union[str, Path]] = None,
        yaml_source: Optional[str] = None,
    ) -> Dict[str, Union[str, bytes]]:
        """Produce in-memory representations of each requested format.

        Pipes graphviz once per binary output rather than via ``render()``
        + temporary files so the caller can write files OR pipe to stdout
        without the SVG-file roundtrip the previous implementation used.

        Args:
            fmt: One or more formats from ``html``, ``png``, ``svg``,
                ``gv``, ``tsv``. ``csv`` and ``pdf`` are recognized at
                the dispatch layer but not produced here. A bare string
                is normalized to a one-tuple.
            output_dir: Forwarded to ``generate_html_output`` for
                ``<!-- %filename% -->`` and ``<!-- %diagram_png_b64% -->``
                template-placeholder resolution, and as the third-priority
                directory in the custom-template search path.
            output_name: Forwarded to ``generate_html_output`` for
                ``<!-- %filename_stem% -->`` resolution.
            template_dir: Forwarded to ``generate_html_output`` as the
                first-priority directory in the custom-template search
                path.

        Returns:
            ``{format: bytes|str}``. Binary formats (``png``) yield
            bytes; text formats (``svg``, ``html``, ``gv``, ``tsv``)
            yield str.
        """
        if isinstance(fmt, str):
            fmt = (fmt,)
        graph = self.graph
        outputs: Dict[str, Union[str, bytes]] = {}

        svg_str: Optional[str] = None
        if "svg" in fmt or "html" in fmt:
            # Resolve relative <image src=...> references against the YAML
            # source's directory when known; fall back to cwd. (In practice
            # wireviz.parse() rewrites relative image paths to absolute
            # during YAML parse, so this base path only matters for SVG
            # produced from already-rendered Harness objects.) Only the
            # images declared in the harness are embedded: Graphviz copies
            # some user text into the SVG unescaped, so any other <image>
            # reference may point at an arbitrary local file.
            svg_str = embed_svg_images(
                self._pipe("svg").decode("utf-8"),
                self._image_base_path(),
                allowed_paths=self._declared_images(),
            )
            if self.untrusted:
                svg_str = sanitize_svg(svg_str)
            if "svg" in fmt:
                outputs["svg"] = svg_str

        png_bytes: Optional[bytes] = None
        if "png" in fmt:
            png_bytes = self._pipe("png")
            if yaml_source is not None:
                png_bytes = _embed_yaml_in_png(png_bytes, yaml_source)
            outputs["png"] = png_bytes

        if "pdf" in fmt:
            outputs["pdf"] = self._pipe("pdf")

        if "gv" in fmt:
            outputs["gv"] = graph.source

        if "tsv" in fmt or "csv" in fmt or "html" in fmt:
            bomlist = bom_list(self.bom())
            if "tsv" in fmt:
                outputs["tsv"] = tuplelist2tsv(bomlist)
            if "csv" in fmt:
                outputs["csv"] = tuplelist2csv(bomlist)
            if "html" in fmt:
                # Inline PNG as base64 in the HTML only when the PNG was
                # rendered in this same call; otherwise let the template
                # fall back to reading {output_dir}/{output_name}.png.
                png_b64 = (
                    f"data:image/png;base64,{base64.b64encode(png_bytes).decode('utf-8')}"
                    if png_bytes is not None
                    else None
                )
                outputs["html"] = generate_html_output(
                    svg_str,
                    bomlist,
                    self.metadata,
                    self.options,
                    output_dir=output_dir,
                    output_name=output_name,
                    png_b64=png_b64,
                    source_path=self.source_path,
                    template_dir=template_dir,
                    untrusted=self.untrusted,
                )

        return outputs

    def bom(self):
        if not self._bom:
            self._bom = generate_bom(self)
        return self._bom
