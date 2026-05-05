# -*- coding: utf-8 -*-

import base64
import io
import re
import sys
from collections import Counter
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from graphviz import Graph
from PIL import Image as PILImage
from PIL.PngImagePlugin import PngInfo
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
    html_line_breaks,
    nested_html_table,
    remove_links,
)
from wireviz.wv_helper import (
    awg_equiv,
    file_write_text,
    flatten2d,
    is_arrow,
    mm2_equiv,
    tuplelist2tsv,
)
from wireviz.wv_html import generate_html_output

OLD_CONNECTOR_ATTR = {
    "pinout": "was renamed to 'pinlabels' in v0.2",
    "pinnumbers": "was renamed to 'pins' in v0.2",
    "autogenerate": "is replaced with new syntax in v0.4",
}

# iTXt chunk key used to embed the source YAML in rendered PNGs for
# round-trip editing. The "wireviz:" prefix avoids collision with PNG
# software-defined keywords or other tools' chunks.
PNG_YAML_CHUNK_KEY = "wireviz:yaml"


def _embed_yaml_in_png(png_bytes: bytes, yaml_source: str) -> bytes:
    """Re-encode PNG bytes with the YAML source stored in an iTXt chunk.

    Pillow's PNG write path does not natively support adding a single
    chunk to an existing file, so this decodes and re-encodes. To keep
    the round-trip non-destructive, anything Pillow surfaced via
    ``im.info`` (DPI, color profiles, existing text chunks) is carried
    forward, and existing iTXt entries on the source image are merged
    in alongside the new ``wireviz:yaml`` chunk.
    """
    with PILImage.open(io.BytesIO(png_bytes)) as im:
        im.load()
        chunks = PngInfo()
        # Preserve any existing iTXt chunks (e.g. dpi metadata or
        # downstream-tool annotations) — Pillow surfaces them in im.text.
        existing_text = getattr(im, "text", {}) or {}
        for key, value in existing_text.items():
            if key == PNG_YAML_CHUNK_KEY:
                continue  # we're about to write a fresh one
            chunks.add_itxt(key, value, zip=True)
        chunks.add_itxt(PNG_YAML_CHUNK_KEY, yaml_source, zip=True)
        out = io.BytesIO()
        # ``**im.info`` carries forward DPI, color profile, gamma, etc.
        # Filter the keys Pillow's PNG writer accepts to avoid TypeErrors
        # from unrelated info entries.
        png_save_keys = {"dpi", "gamma", "transparency", "icc_profile"}
        save_kwargs = {k: v for k, v in im.info.items() if k in png_save_keys}
        im.save(out, format="PNG", pnginfo=chunks, **save_kwargs)
        return out.getvalue()


def read_yaml_from_png(png_path: Union[str, Path]) -> Optional[str]:
    """Return the YAML source embedded in ``png_path`` by an earlier
    WireViz render, or ``None`` if no ``wireviz:yaml`` chunk is present.
    """
    with PILImage.open(png_path) as im:
        im.load()
        return im.text.get(PNG_YAML_CHUNK_KEY) if hasattr(im, "text") else None


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

    def __post_init__(self):
        self.connectors = {}
        self.cables = {}
        self.mates = []
        self._bom = []  # Internal Cache for generated bom
        self.additional_bom_items = []

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
        self.mates.append(MatePin(from_name, from_pin, to_name, to_pin, arrow_type))
        self.connectors[from_name].activate_pin(from_pin, Side.RIGHT)
        self.connectors[to_name].activate_pin(to_pin, Side.LEFT)

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
        for name, pin in zip([from_name, to_name], [from_pin, to_pin]):
            if name is not None and name in self.connectors:
                connector = self.connectors[name]
                # check if provided name is ambiguous
                if pin in connector.pins and pin in connector.pinlabels:
                    if connector.pins.index(pin) != connector.pinlabels.index(pin):
                        raise Exception(
                            f"{name}:{pin} is defined both in pinlabels and pins, for different pins."
                        )
                    # TODO: Maybe issue a warning if present in both lists but referencing the same pin?
                if pin in connector.pinlabels:
                    if connector.pinlabels.count(pin) > 1:
                        raise Exception(f"{name}:{pin} is defined more than once.")
                    index = connector.pinlabels.index(pin)
                    pin = connector.pins[index]  # map pin name to pin number
                    if name == from_name:
                        from_pin = pin
                    if name == to_name:
                        to_pin = pin
                if not pin in connector.pins:
                    raise Exception(f"{name}:{pin} not found.")

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
            elif via_wire in cable.wirelabels:
                if cable.wirelabels.count(via_wire) > 1:
                    raise Exception(
                        f"{via_name}:{via_wire} is used for more than one wire."
                    )
                via_wire = (
                    cable.wirelabels.index(via_wire) + 1
                )  # list index starts at 0, wire IDs start at 1

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

        for connector in self.connectors.values():
            # If no wires connected (except maybe loop wires)?
            if not (connector.ports_left or connector.ports_right):
                connector.ports_left = True  # Use left side pins.

            # Resolve per-loop sides *before* the pin table is built so
            # loop pins are guaranteed to activate the correct port column.
            loop_sides = connector.resolve_loops()

            html = []
            # fmt: off
            rows = [[f'{html_bgcolor(connector.bgcolor_title)}{remove_links(connector.name)}'
                        if connector.show_name else None],
                    [pn_info_string(HEADER_PN, None, remove_links(connector.pn)),
                     html_line_breaks(pn_info_string(HEADER_MPN, connector.manufacturer, connector.mpn)),
                     html_line_breaks(pn_info_string(HEADER_SPN, connector.supplier, connector.spn))],
                    [html_line_breaks(connector.type),
                     html_line_breaks(connector.subtype),
                     f'{connector.pincount}-pin' if connector.show_pincount else None,
                     translate_color(connector.color, self.options.color_mode) if connector.color else None,
                     html_colorbar(connector.color)],
                    '<!-- connector table -->' if connector.style != 'simple' else None,
                    [html_image(connector.image)],
                    [html_caption(connector.image)]]
            # fmt: on

            rows.extend(get_additional_component_table(self, connector))
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
                        pinhtml.append(f'    <td port="p{pinindex+1}l">{pinname}</td>')
                    if pinlabel:
                        pinhtml.append(f"    <td>{pinlabel}</td>")
                    if connector.pincolors:
                        if pincolor in wv_colors._color_hex.keys():
                            # fmt: off
                            pinhtml.append(f'    <td sides="tbl">{translate_color(pincolor, self.options.color_mode)}</td>')
                            pinhtml.append( '    <td sides="tbr">')
                            pinhtml.append( '     <table border="0" cellborder="1"><tr>')
                            pinhtml.append(f'      <td bgcolor="{wv_colors.translate_color(pincolor, "HEX")}" width="8" height="8" fixedsize="true"></td>')
                            pinhtml.append( '     </tr></table>')
                            pinhtml.append( '    </td>')
                            # fmt: on
                        else:
                            pinhtml.append('    <td colspan="2"></td>')

                    if connector.ports_right:
                        pinhtml.append(f'    <td port="p{pinindex+1}r">{pinname}</td>')
                    pinhtml.append("   </tr>")

                pinhtml.append("  </table>")

                if len(pinhtml) == 2:  # Table start and end with no rows between?
                    pinhtml = ["<!-- all pins hidden -->"]  # Avoid Graphviz error

                html = [
                    row.replace("<!-- connector table -->", "\n".join(pinhtml))
                    for row in html
                ]

            html = "\n".join(html)
            dot.node(
                connector.name,
                label=f"<\n{html}\n>",
                shape="box",
                style="filled",
                fillcolor=translate_color(self.options.bgcolor_connector, "HEX"),
            )

            if len(connector.loops) > 0:
                dot.attr("edge", color="#000000:#ffffff:#000000")
                for loop, (side_a, side_b) in zip(connector.loops, loop_sides):
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
                    dot.edge(
                        f"{connector.name}:p{pos_a}{s_a}:{d_a}",
                        f"{connector.name}:p{pos_b}{s_b}:{d_b}",
                        label=" ",  # Work-around to avoid over-sized loops.
                    )

        # determine if there are double- or triple-colored wires in the harness;
        # if so, pad single-color wires to make all wires of equal thickness
        pad = any(
            len(get_color_hex(colorstr)) > 1
            for cable in self.cables.values()
            for colorstr in cable.colors
        )

        for cable in self.cables.values():
            html = []

            awg_fmt = ""
            if cable.show_equiv:
                # Only convert units we actually know about, i.e. currently
                # mm2 and awg --- other units _are_ technically allowed,
                # and passed through as-is.
                if cable.gauge_unit == "mm\u00B2":
                    awg_fmt = f" ({awg_equiv(cable.gauge)} AWG)"
                elif cable.gauge_unit.upper() == "AWG":
                    awg_fmt = f" ({mm2_equiv(cable.gauge)} mm\u00B2)"

            # fmt: off
            rows = [[f'{html_bgcolor(cable.bgcolor_title)}{remove_links(cable.name)}'
                        if cable.show_name else None],
                    [pn_info_string(HEADER_PN, None,
                        remove_links(cable.pn)) if not isinstance(cable.pn, list) else None,
                     html_line_breaks(pn_info_string(HEADER_MPN,
                        cable.manufacturer if not isinstance(cable.manufacturer, list) else None,
                        cable.mpn if not isinstance(cable.mpn, list) else None)),
                     html_line_breaks(pn_info_string(HEADER_SPN,
                        cable.supplier if not isinstance(cable.supplier, list) else None,
                        cable.spn if not isinstance(cable.spn, list) else None))],
                    [html_line_breaks(cable.type),
                     f'{cable.wirecount}x' if cable.show_wirecount else None,
                     f'{cable.gauge} {cable.gauge_unit}{awg_fmt}' if cable.gauge else None,
                     '+ S' if cable.shield else None,
                     f'{cable.length} {cable.length_unit}' if cable.length > 0 else None,
                     translate_color(cable.color, self.options.color_mode) if cable.color else None,
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

            for i, (connection_color, wirelabel) in enumerate(
                zip_longest(cable.colors, cable.wirelabels), 1
            ):
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
                wirehtml.append(f'     {":".join(wireinfo)}')

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
                            pn_info_string(
                                HEADER_PN, None, remove_links(cable.pn[i - 1])
                            )
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

            if cable.shield:
                wirehtml.append("   <tr><td>&nbsp;</td></tr>")  # spacer
                wirehtml.append("   <tr>")
                wirehtml.append("    <td><!-- s_in --></td>")
                wirehtml.append("    <td>Shield</td>")
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
                if connection.from_pin is not None:  # connect to left
                    from_connector = self.connectors[connection.from_name]
                    from_pin_index = from_connector.pins.index(connection.from_pin)
                    from_port_str = (
                        f":p{from_pin_index+1}r"
                        if from_connector.style != "simple"
                        else ""
                    )
                    code_left_1 = f"{connection.from_name}{from_port_str}:e"
                    code_left_2 = f"{cable.name}:w{connection.via_port}:w"
                    dot.edge(code_left_1, code_left_2)
                    if from_connector.show_name:
                        from_info = [
                            str(connection.from_name),
                            str(connection.from_pin),
                        ]
                        if from_connector.pinlabels:
                            pinlabel = from_connector.pinlabels[from_pin_index]
                            if pinlabel != "":
                                from_info.append(pinlabel)
                        from_string = ":".join(from_info)
                    else:
                        from_string = ""
                    html = [
                        row.replace(f"<!-- {connection.via_port}_in -->", from_string)
                        for row in html
                    ]
                if connection.to_pin is not None:  # connect to right
                    to_connector = self.connectors[connection.to_name]
                    to_pin_index = to_connector.pins.index(connection.to_pin)
                    to_port_str = (
                        f":p{to_pin_index+1}l" if to_connector.style != "simple" else ""
                    )
                    code_right_1 = f"{cable.name}:w{connection.via_port}:e"
                    code_right_2 = f"{connection.to_name}{to_port_str}:w"
                    dot.edge(code_right_1, code_right_2)
                    if to_connector.show_name:
                        to_info = [str(connection.to_name), str(connection.to_pin)]
                        if to_connector.pinlabels:
                            pinlabel = to_connector.pinlabels[to_pin_index]
                            if pinlabel != "":
                                to_info.append(pinlabel)
                        to_string = ":".join(to_info)
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
            dot.node(
                cable.name,
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
                from_port_str = f":p{from_pin_index+1}r"
            else:  # MateComponent or style == 'simple'
                from_port_str = ""
            if isinstance(mate, MatePin) and to_connector.style != "simple":
                to_pin_index = to_connector.pins.index(mate.to_pin)
                to_port_str = f":p{to_pin_index+1}l"
            else:  # MateComponent or style == 'simple'
                to_port_str = ""
            code_from = f"{mate.from_name}{from_port_str}:e"
            code_to = f"{mate.to_name}{to_port_str}:w"

            dot.attr("edge", color=color, style="dashed", dir=dir)
            dot.edge(code_from, code_to)

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
                                    f'( +)?{attr}=("[^"]*"|[^] ]*)(?(1)| *)', "", entry
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

                            if len(value) == 0 or " " in value:
                                value = value.replace('"', r"\"")
                                value = f'"{value}"'
                            entry, n_subs = re.subn(
                                f'{attr}=("[^"]*"|[^] ]*)', f"{attr}={value}", entry
                            )
                            if n_subs < 1:
                                # If attr not found, then append it
                                entry = re.sub(r"\]$", f" {attr}={value}]", entry)
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

    @property
    def png(self):
        from io import BytesIO

        graph = self.graph
        data = BytesIO()
        data.write(graph.pipe(format="png"))
        data.seek(0)
        return data.read()

    @property
    def svg(self):  # TODO?: Verify xml encoding="utf-8" in SVG?
        graph = self.graph
        return embed_svg_images(graph.pipe(format="svg").decode("utf-8"), Path.cwd())

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

        if "csv" in fmt:
            # TODO: implement CSV output (preferably using CSV library)
            sys.stderr.write("CSV output is not yet supported\n")

        if filename is None:
            # stdout mode — emit each rendered format in the user-requested order
            for f in fmt:
                content = outputs.get(f)
                if content is None:
                    continue
                if isinstance(content, (bytes, bytearray)):
                    sys.stdout.buffer.write(content)
                else:
                    sys.stdout.write(content)
            return

        suffix_map = {"tsv": "bom.tsv"}
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
            # produced from already-rendered Harness objects or when a
            # tweak injects a post-parse relative path.)
            if self.source_path is not None and str(self.source_path) != "-":
                base_path: Path = Path(self.source_path).parent
            else:
                base_path = Path.cwd()
            svg_str = embed_svg_images(
                graph.pipe(format="svg").decode("utf-8"), base_path
            )
            if "svg" in fmt:
                outputs["svg"] = svg_str

        png_bytes: Optional[bytes] = None
        if "png" in fmt:
            png_bytes = graph.pipe(format="png")
            if yaml_source is not None:
                png_bytes = _embed_yaml_in_png(png_bytes, yaml_source)
            outputs["png"] = png_bytes

        if "pdf" in fmt:
            outputs["pdf"] = graph.pipe(format="pdf")

        if "gv" in fmt:
            outputs["gv"] = graph.source

        if "tsv" in fmt or "html" in fmt:
            bomlist = bom_list(self.bom())
            if "tsv" in fmt:
                outputs["tsv"] = tuplelist2tsv(bomlist)
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
                )

        return outputs

    def bom(self):
        if not self._bom:
            self._bom = generate_bom(self)
        return self._bom
