# -*- coding: utf-8 -*-
"""One test per upstream wireviz/WireViz issue fixed in this fork.

Each test names the upstream issue it pins down. The triage of all open
upstream issues is in ``docs/plans/2026-10-02-upstream-issue-triage.md``.
"""

import os
from pathlib import Path

import pytest

from wireviz.wireviz import parse
from wireviz.wv_bom import bom_list

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
TRS = EXAMPLES / "resources" / "stereo-phone-plug-TRS.png"


def _svg(src: str, **kwargs) -> str:
    return parse(src, return_types="svg", **kwargs)


# ===========================================================================
# Batch A — bugs
# ===========================================================================


def test_issue208_wire_index_beyond_wirecount():
    src = """
connectors: {X1: {pincount: 3}}
cables: {W1: {wirecount: 2}}
connections:
  - - X1: [1, 3]
    - W1: [1, 3]
"""
    with pytest.raises(ValueError, match=r"W1:3 is out of range; W1 has 2 wire"):
        parse(src, return_types="harness")


def test_issue208_unknown_wire_label_is_not_drawn_as_shield():
    src = """
connectors: {X1: {pincount: 1}}
cables: {W1: {wirecount: 1, wirelabels: [SIG]}}
connections:
  - - X1: [1]
    - W1: [SIGG]
"""
    with pytest.raises(ValueError, match="W1:SIGG not found"):
        parse(src, return_types="harness")


def test_issue305_yaml11_words_stay_text_in_labels():
    """NO / NC / ON / Yes were read as booleans and crashed the render."""
    src = """
connectors:
  K1: {pinlabels: [NO, NC, COM, ON]}
cables:
  W1: {wirecount: 2, wirelabels: [Yes, off]}
connections:
  - - K1: [1, 2]
    - W1: [1, 2]
"""
    h = parse(src, return_types="harness")
    assert h.connectors["K1"].pinlabels == ["NO", "NC", "COM", "ON"]
    assert h.cables["W1"].wirelabels == ["Yes", "off"]
    assert ">NO<" in h.svg


@pytest.mark.parametrize(
    "word, expected", [("no", False), ("Yes", True), ("off", False), ("true", True)]
)
def test_issue305_boolean_fields_still_accept_yaml11_words(word, expected):
    src = f"""
options: {{mini_bom_mode: {word}}}
connectors: {{X1: {{pincount: 1, show_name: {word}, ignore_in_bom: {word}}}}}
cables: {{W1: {{wirecount: 1, shield: {word}}}}}
connections: [[X1], [W1]]
"""
    h = parse(src, return_types="harness")
    assert h.options.mini_bom_mode is expected
    assert h.connectors["X1"].show_name is expected
    assert h.connectors["X1"].ignore_in_bom is expected
    assert h.cables["W1"].shield is expected


def test_issue305_metadata_keeps_the_word():
    h = parse("metadata: {approved: yes}\nconnectors: {}\n", return_types="harness")
    assert h.metadata["approved"] == "yes"


def test_issue426_component_without_attributes_names_it():
    src = """
connectors:
  BoardMains2:
connections: [[BoardMains2]]
"""
    with pytest.raises(Exception, match="Connector BoardMains2: specify at least one"):
        parse(src, return_types="harness")


def test_issue426_component_with_scalar_value():
    src = "connectors:\n  X1: oops\nconnections: [[X1]]\n"
    with pytest.raises(TypeError, match="connectors.X1 must be a mapping"):
        parse(src, return_types="harness")


@pytest.mark.parametrize("text", ["", "   \n", "# only a comment\n"])
def test_issue342_empty_input(text: str):
    with pytest.raises(ValueError, match="input is empty"):
        parse(text, return_types="harness")


def test_issue342_empty_file_via_cli(tmp_path: Path, runner):
    from wireviz.wv_cli import wireviz as cli

    f = tmp_path / "empty.yml"
    f.write_text("")
    result = runner.invoke(cli, ["-f", "s", str(f)])
    assert result.exit_code == 1
    assert "IsADirectoryError" not in result.stderr
    assert "input is empty" in result.stderr
    assert "Traceback" not in result.stderr


def test_issue487_colon_in_designators():
    src = """
connectors:
  "J1:A": {pincount: 2}
  "J2:B": {pincount: 2}
cables:
  "W:1": {wirecount: 2}
connections:
  - - "J1:A": [1, 2]
    - "W:1": [1, 2]
    - "J2:B": [1, 2]
  - - "J1:A": [1]
    - -->
    - "J2:B": [1]
"""
    h = parse(src, return_types="harness")
    assert '"J1:A":p1r:e -- "W:1":w1:w' in h.graph.source
    svg = h.svg
    assert "J1:A" in svg and "W:1" in svg


@pytest.mark.parametrize(
    "notes, shown",
    [
        ("a&b", "a&amp;b"),
        ("x < 5 V", "x &lt; 5 V"),
        ("<5V", "&lt;5V"),
        ("a -> b", "a -&gt; b"),
        ("R&amp;D", "R&amp;D"),  # an entity stays as it is
        ("25&#176;C", "25&#176;C"),
        ("<b>bold</b>", "<b>bold</b>"),  # intended markup still works
    ],
)
def test_issue230_bare_ampersand_and_lt_are_escaped(notes: str, shown: str):
    src = f"""
connectors:
  "X&1":
    pinlabels: ["A&B", "<1>"]
    notes: '{notes}'
connections: [["X&1"]]
"""
    h = parse(src, return_types="harness")
    assert shown in h.graph.source
    assert "<svg" in h.svg  # Graphviz accepts the label


def test_issue300_ignored_component_hides_its_additional_components():
    src = """
connectors:
  X1:
    pincount: 1
    ignore_in_bom: true
    additional_components:
      - {type: Crimp, qty_multiplier: pincount}
  X2:
    pincount: 1
    additional_components:
      - {type: Seal}
cables:
  W1:
    wirecount: 1
    ignore_in_bom: true
    additional_components:
      - {type: Sleeve}
connections:
  - - X1: [1]
    - W1: [1]
    - X2: [1]
"""
    h = parse(src, return_types="harness")
    descriptions = [row[1] for row in bom_list(h.bom())[1:]]
    assert "Seal" in descriptions
    assert "Crimp" not in descriptions
    assert "Sleeve" not in descriptions
    # No BOM number exists for the hidden parts: the diagram shows them in full.
    source = h.graph.source
    assert "Crimp" in source and "Sleeve" in source


def test_issue265_colors_given_as_string():
    src = "cables: {W1: {wirecount: 2, colors: DIN}}\nconnections: [[W1]]\n"
    with pytest.raises(TypeError, match="use color_code"):
        parse(src, return_types="harness")


def test_issue265_pinlabels_given_as_string():
    src = "connectors: {X1: {pinlabels: GND}}\nconnections: [[X1]]\n"
    with pytest.raises(TypeError, match="pinlabels must be a list"):
        parse(src, return_types="harness")


def test_issue292_image_as_plain_string(tmp_path: Path):
    (tmp_path / "pic.png").write_bytes(TRS.read_bytes())
    src = """
connectors:
  X1: {pincount: 1, image: pic.png}
cables:
  W1: {wirecount: 1, image: pic.png}
connections: [[X1], [W1]]
"""
    svg = _svg(src, image_paths=[tmp_path])
    assert svg.count("data:image/png;base64,") == 2


def test_issue292_image_string_is_checked_in_untrusted_mode():
    """A plain-string image must go through the same path checks."""
    src = f"connectors:\n  X1: {{pincount: 1, image: '{TRS}'}}\nconnections: [[X1]]\n"
    with pytest.raises(ValueError, match="relative"):
        parse(src, return_types="svg", untrusted=True)


def test_issue432_loops_by_pin_label():
    src = """
connectors:
  X1:
    pinlabels: [GND, SIG, VCC, SENSE]
    loops:
      - [VCC, SENSE]
      - [1, SIG]
"""
    h = parse(src, return_types="harness")
    assert h.connectors["X1"].loops == [[3, 4], [1, 2]]
    assert "<svg" in h.svg


def test_issue432_unknown_loop_pin():
    src = "connectors:\n  X1: {pinlabels: [GND], loops: [[GND, NOPE]]}\n"
    with pytest.raises(Exception, match="X1:NOPE not found"):
        parse(src, return_types="harness")


def test_issue465_loops_use_pin_positions_not_numbers():
    """Pins 0-5, 8, 9: loop [5, 8] must use table rows 6 and 7."""
    src = """
connectors:
  X1:
    pins: [0, 1, 2, 3, 4, 5, 8, 9]
    loops: [[5, 8]]
"""
    source = parse(src, return_types="harness").graph.source
    assert "X1:p6" in source and "X1:p7" in source
    assert "X1:p9" not in source


# ===========================================================================
# Batch B — small features
# ===========================================================================

MINIMAL = """
connectors:
  X1: {pinlabels: [A, B]}
  X2: {pinlabels: [A, B]}
cables:
  W1: {wirecount: 2, colors: [RD, BU]}
connections:
  - - X1: [1, 2]
    - W1: [1, 2]
    - X2: [1, 2]
"""


def test_issue98_csv_bom(tmp_path: Path):
    src = (
        MINIMAL
        + "additional_bom_items:\n  - {description: 'Label, \"quoted\"', qty: 2}\n"
    )
    parse(src, output_formats=("csv",), output_dir=tmp_path, output_name="h")
    import csv

    rows = list(csv.reader((tmp_path / "h.bom.csv").read_text().splitlines()))
    assert rows[0][0] == "Id"
    assert ['Label, "quoted"' in row for row in rows].count(True) == 1


def test_issue98_csv_cli(runner, tmp_path: Path):
    from wireviz.wv_cli import wireviz as cli

    f = tmp_path / "h.yml"
    f.write_text(MINIMAL)
    result = runner.invoke(cli, ["-f", "c", str(f)])
    assert result.exit_code == 0, result.stderr
    assert (tmp_path / "h.bom.csv").exists()


def test_issue457_loop_color():
    src = """
connectors:
  X1:
    pinlabels: [A, B, C, D]
    loops:
      - {RD: [A, B]}
      - [C, D]
"""
    h = parse(src, return_types="harness")
    assert h.connectors["X1"].loops == [[1, 2], [3, 4]]
    assert h.connectors["X1"].loop_colors == ["RD", None]
    source = h.graph.source
    assert "#000000:#ff0000:#000000" in source  # red loop, as thick as a wire
    assert "#000000:#ffffff:#000000" in source  # default loop look kept


def test_issue460_title_in_diagram():
    src = (
        "metadata: {title: 'Mini 1275 GT loom'}\noptions: {show_title: true}\n"
        + MINIMAL
    )
    h = parse(src, return_types="harness")
    assert 'label="Mini 1275 GT loom"' in h.graph.source
    assert "Mini 1275 GT loom" in h.svg
    # off by default
    assert "labelloc" not in parse(MINIMAL, return_types="harness").graph.source


def test_issue460_title_is_escaped_in_untrusted_mode():
    src = (
        "metadata: {title: '<b onload=x>T</b>'}\noptions: {show_title: true}\n"
        + MINIMAL
    )
    svg = parse(src, return_types="svg", untrusted=True)
    assert "onload" not in svg.replace("&lt;b onload", "")


def test_issue410_disable_key(tmp_path: Path):
    (tmp_path / "pic.png").write_bytes(TRS.read_bytes())
    src = """
connectors:
  X1: {pincount: 1, image: pic.png, notes: n1}
  X2: {pincount: 1, image: pic.png, notes: n2}
connections: [[X1], [X2]]
"""
    svg = _svg(src, image_paths=[tmp_path], disable_keys=["image"])
    assert "data:image" not in svg
    h = parse(
        src, return_types="harness", image_paths=[tmp_path], disable_keys="X1.image"
    )
    assert h.connectors["X1"].image is None and h.connectors["X2"].image is not None
    with pytest.raises(ValueError, match="no connector or cable named X9"):
        parse(
            src, return_types="harness", image_paths=[tmp_path], disable_keys="X9.image"
        )


def test_issue410_disable_key_cli(runner, tmp_path: Path):
    from wireviz.wv_cli import wireviz as cli

    (tmp_path / "pic.png").write_bytes(TRS.read_bytes())
    f = tmp_path / "h.yml"
    f.write_text(
        "connectors:\n  X1: {pincount: 1, image: pic.png}\nconnections: [[X1]]\n"
    )
    result = runner.invoke(cli, ["-f", "s", "--disable-key", "image", str(f)])
    assert result.exit_code == 0, result.stderr
    assert "data:image" not in (tmp_path / "h.svg").read_text()


def test_issue212_show_box_false_draws_wires_between_connectors():
    src = MINIMAL.replace(
        "colors: [RD, BU]}", "colors: [RD, BU], show_box: false, length: 2}"
    )
    h = parse(src, return_types="harness")
    source = h.graph.source
    assert "W1 [label=" not in source  # no cable node
    assert "X1:p1r:e -- X2:p1l:w" in source
    assert "#ff0000" in source
    assert "<svg" in h.svg
    # the BOM still lists the cable
    assert any("Cable" in row[1] for row in bom_list(h.bom())[1:])


def test_issue212_show_box_false_needs_both_ends():
    src = """
connectors: {X1: {pincount: 1}}
cables: {W1: {wirecount: 1, show_box: false}}
connections:
  - - X1: [1]
    - W1: [1]
"""
    with pytest.raises(ValueError, match="show_box: false needs"):
        parse(src, return_types="harness").graph


@pytest.mark.parametrize("name", ["lightgreen", "tomato", "LightGreen", "GOLD"])
def test_issue135_issue271_css_color_names(name: str):
    src = f"""
connectors:
  X1: {{pincount: 2, pincolors: [{name}, RD], color: {name}}}
cables:
  W1: {{wirecount: 2, colors: [{name}, RD]}}
connections:
  - - X1: [1, 2]
    - W1: [1, 2]
"""
    from wireviz.wv_colors import css_color_hex

    h = parse(src, return_types="harness")
    assert css_color_hex(name) in h.graph.source


def test_issue135_codes_win_over_css_names():
    from wireviz.wv_colors import get_color_hex

    assert get_color_hex("RDBU") == ["#ff0000", "#0066ff", "#ff0000"]


def test_issue331_terminology():
    src = (
        "options:\n  terminology: {pin: way, wire: core, shield: screen}\n"
        + MINIMAL.replace("colors: [RD, BU]}", "colors: [RD, BU], shield: true}")
    )
    h = parse(src, return_types="harness")
    source = h.graph.source
    assert "2-way" in source and "Screen" in source and "2-pin" not in source
    descriptions = " ".join(row[1] for row in bom_list(h.bom())[1:])
    assert "2 ways" in descriptions and "screened" in descriptions


def test_issue296_strip_lengths():
    src = MINIMAL.replace(
        "X1: {pinlabels: [A, B]}",
        "X1: {pinlabels: [A, B], strip: {sleeve: 10, insulation: 2.5 mm}}",
    )
    source = parse(src, return_types="harness").graph.source
    assert "Strip sleeve 10 mm, insulation 2.5 mm" in source


def _png_bytes(size=(4, 4), fmt="PNG") -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, format=fmt)
    return buf.getvalue()


@pytest.mark.parametrize("untrusted", [False, True])
def test_issue188_issue322_base64_image(untrusted: bool):
    import base64

    uri = "data:image/png;base64," + base64.b64encode(_png_bytes()).decode()
    src = f"connectors:\n  X1: {{pincount: 1, image: '{uri}'}}\nconnections: [[X1]]\n"
    h = parse(src, return_types="harness", untrusted=untrusted)
    assert Path(h.connectors["X1"].image.src).parent == h.temp_dir()
    assert "data:image/png;base64," in h.svg
    assert h._render(("png",))["png"].startswith(b"\x89PNG")


@pytest.mark.parametrize(
    "uri, message",
    [
        ("data:text/html;base64,PGI+", "must look like"),
        ("data:image/png;base64,!!!!", "must look like"),
        ("data:image/png;base64,AAAA", "not a readable PNG image"),
    ],
)
def test_issue188_bad_data_uri(uri: str, message: str):
    src = f"connectors:\n  X1: {{pincount: 1, image: '{uri}'}}\nconnections: [[X1]]\n"
    with pytest.raises(ValueError, match=message):
        parse(src, return_types="harness")


def test_issue188_data_uri_pixel_cap():
    import base64

    from tests.test_security import _png

    uri = "data:image/png;base64," + base64.b64encode(_png(20000, 20000)).decode()
    src = f"connectors:\n  X1: {{pincount: 1, image: '{uri}'}}\nconnections: [[X1]]\n"
    with pytest.raises(ValueError, match="pixels"):
        parse(src, return_types="harness", untrusted=True)


def test_issue202_webp_is_converted(tmp_path: Path):
    from PIL import features

    if not features.check("webp"):
        pytest.skip("Pillow built without webp")
    (tmp_path / "pic.webp").write_bytes(_png_bytes(fmt="WEBP"))
    src = "connectors:\n  X1: {pincount: 1, image: pic.webp}\nconnections: [[X1]]\n"
    h = parse(src, return_types="harness", image_paths=[tmp_path])
    assert h.connectors["X1"].image.src.suffix == ".png"
    assert "data:image/png;base64," in h.svg


def test_temp_dir_is_removed_with_the_harness():
    import base64
    import gc

    uri = "data:image/png;base64," + base64.b64encode(_png_bytes()).decode()
    h = parse(
        f"connectors:\n  X1: {{pincount: 1, image: '{uri}'}}\nconnections: [[X1]]\n",
        return_types="harness",
    )
    tmp = h.temp_dir()
    assert tmp.exists()
    del h
    gc.collect()
    assert not tmp.exists()


# ---------------------------------------------------------------------------
# Batch A review round 1
# ---------------------------------------------------------------------------


def test_issue300_part_can_override_parent_ignore_in_bom():
    """A hidden device-side connector may still need its terminals."""
    src = """
connectors:
  ECU:
    pincount: 2
    ignore_in_bom: true
    additional_components:
      - {type: Crimp terminal, mpn: T-123, qty_multiplier: populated, ignore_in_bom: false}
      - {type: Seal}
  X2:
    pincount: 2
    additional_components:
      - {type: Boot, ignore_in_bom: yes}
cables: {W1: {wirecount: 2}}
connections:
  - - ECU: [1, 2]
    - W1: [1, 2]
    - X2: [1, 2]
"""
    h = parse(src, return_types="harness")
    descriptions = [row[1] for row in bom_list(h.bom())[1:]]
    assert "Crimp terminal" in descriptions
    assert "Seal" not in descriptions and "Boot" not in descriptions


@pytest.mark.parametrize(
    "label", ["<VBAT>", "x<y and z>w", "a&b;c", "<!-- 1_in -->", "&bogus;"]
)
def test_issue230_tag_like_text_is_escaped(label: str):
    src = f"""
connectors:
  X1: {{pinlabels: ['{label}']}}
cables:
  W1: {{wirecount: 1, wirelabels: ['{label}'], gauge: '1 mm&sup', length: '1 <m'}}
connections:
  - - X1: [1]
    - W1: [1]
"""
    assert "<svg" in parse(src, return_types="svg")


def test_issue208_shield_on_unshielded_cable():
    src = """
connectors: {X1: {pincount: 1}}
cables: {W1: {wirecount: 1}}
connections:
  - - X1: [1]
    - W1: [s]
"""
    with pytest.raises(ValueError, match="W1:s is used, but W1 has no shield"):
        parse(src, return_types="harness")


def test_quoted_numeric_wire_and_pin_labels():
    src = """
connectors: {X1: {pinlabels: ['10', '20']}}
cables: {W1: {wirecount: 2, wirelabels: ['10', '20']}}
connections:
  - - X1: ['20', '10']
    - W1: ['10', '20']
"""
    h = parse(src, return_types="harness")
    assert [(c.from_pin, c.via_port) for c in h.cables["W1"].connections] == [
        (2, 1),
        (1, 2),
    ]


def test_empty_cable_error_names_the_cable():
    # Wires referenced by color cannot imply a wire count (#508).
    src = "connectors: {X1: {pincount: 1}}\ncables:\n  W1:\nconnections:\n  - - X1: [1]\n    - W1: [RD]\n"
    with pytest.raises(Exception, match="Cable W1: unknown number of wires"):
        parse(src, return_types="harness")


# ===========================================================================
# Batch C1 — error context (#505, #207) and wire count inference (#508)
# ===========================================================================


def test_issue505_error_names_the_connection_set():
    src = """
connectors: {X1: {pincount: 2}, X2: {pincount: 2}}
cables: {W1: {wirecount: 2}}
connections:
  - - X1: [1, 2]
    - W1: [1, 2]
    - X2: [1, 2]
  - - X1: [1]
    - W1: [3]
    - X2: [1]
"""
    with pytest.raises(ValueError) as exc:
        parse(src, return_types="harness")
    assert "connection set 2 (X1 → W1 → X2): W1:3 is out of range" in str(exc.value)


def test_issue505_unknown_designator_is_wirevizerror():
    from wireviz.wv_errors import WireVizError

    src = (
        "connectors: {X1: {pincount: 1}}\nconnections:\n  - - X1: [1]\n    - W9: [1]\n"
    )
    with pytest.raises(WireVizError, match="connection set 1 .*W9 is an unknown"):
        parse(src, return_types="harness")


def test_issue505_cli_prints_one_line(runner, tmp_path: Path):
    from wireviz.wv_cli import wireviz as cli

    f = tmp_path / "bad.yml"
    f.write_text(
        "connectors: {X1: {pincount: 1}}\ncables: {W1: {wirecount: 1}}\n"
        "connections:\n  - - X1: [5]\n    - W1: [1]\n"
    )
    result = runner.invoke(cli, ["-f", "s", str(f)])
    assert result.exit_code == 1
    assert "Error:" in result.stderr and "X1:5 not found" in result.stderr
    assert "Traceback" not in result.stderr
    debug = runner.invoke(cli, ["-f", "s", "--debug", str(f)])
    assert debug.exception is not None and "X1:5 not found" in str(debug.exception)


def test_issue508_infer_wire_count_from_wire_numbers():
    src = """
connectors: {X1: {pincount: 4}, X2: {pincount: 4}}
cables: {B1: {}}
connections:
  - - X1: [1-4]
    - B1: [1-4]
    - X2: [1-4]
"""
    h = parse(src, return_types="harness")
    assert h.cables["B1"].wirecount == 4


def test_issue508_bare_named_cable_uses_wires_1_to_n():
    src = """
connectors: {X1: {pincount: 3}, X2: {pincount: 3}}
cables: {B1: {}, B2: {wirecount: 3}}
connections:
  - - X1: [1-3]
    - B1
    - X2: [1-3]
  - - X1: [1-3]
    - B2
    - X2: [1-3]
"""
    h = parse(src, return_types="harness")
    assert h.cables["B1"].wirecount == 3
    for name in ("B1", "B2"):
        assert [c.via_port for c in h.cables[name].connections] == [1, 2, 3]


def test_issue508_largest_wire_number_over_all_sets():
    src = """
connectors: {X1: {pincount: 6}}
cables: {B1: {}}
connections:
  - - X1: [1, 2]
    - B1: [1, 2]
  - - X1: [5]
    - B1: [5]
"""
    assert parse(src, return_types="harness").cables["B1"].wirecount == 5


def test_issue508_template_instances_get_their_own_count():
    src = """
connectors: {X1: {pincount: 4}}
cables: {W: {}}
connections:
  - - X1: [1, 2]
    - W.W1: [1, 2]
  - - X1: [1-4]
    - W.W2: [1-4]
"""
    h = parse(src, return_types="harness")
    assert h.cables["W1"].wirecount == 2 and h.cables["W2"].wirecount == 4


def test_issue508_autogenerated_bare_cable_keeps_its_meaning():
    """`- W.` still makes one new single-wire cable per connection."""
    src = """
connectors: {X1: {pincount: 2}, X2: {pincount: 2}}
cables: {W: {wirecount: 1}}
connections:
  - - X1: [1, 2]
    - W.
    - X2: [1, 2]
"""
    h = parse(src, return_types="harness")
    assert len(h.cables) == 2


# ===========================================================================
# Batch C2 — include (#220)
# ===========================================================================


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


MAIN_WITH_INCLUDE = """
include: [lib/parts.yml]
connections:
  - - X1: [1, 2]
    - W1: [1, 2]
    - X2: [1, 2]
"""


def test_issue220_include_merges_library(tmp_path: Path):
    _write(
        tmp_path / "lib/parts.yml",
        "connectors:\n  X1: {pinlabels: [A, B]}\n  X2: {pinlabels: [A, B]}\n"
        "cables:\n  W1: {wirecount: 2}\n",
    )
    main = _write(tmp_path / "main.yml", MAIN_WITH_INCLUDE)
    h = parse(main, return_types="harness")
    assert set(h.connectors) == {"X1", "X2"} and "W1" in h.cables


def test_issue220_main_file_wins_and_includes_conflict(tmp_path: Path):
    _write(
        tmp_path / "a.yml", "connectors:\n  X1: {pincount: 2}\n  X3: {pincount: 1}\n"
    )
    _write(tmp_path / "b.yml", "connectors:\n  X3: {pincount: 5}\n")
    main = _write(
        tmp_path / "main.yml",
        "include: [a.yml]\nconnectors:\n  X1: {pincount: 9}\nconnections: [[X1]]\n",
    )
    assert parse(main, return_types="harness").connectors["X1"].pincount == 9
    clash = _write(tmp_path / "clash.yml", "include: [a.yml, b.yml]\nconnections: []\n")
    with pytest.raises(ValueError, match="connectors.X3 is defined in both"):
        parse(clash, return_types="harness")


def test_issue220_nested_cycle_and_main_only_sections(tmp_path: Path):
    _write(tmp_path / "a.yml", "include: [b.yml]\nconnectors: {XA: {pincount: 1}}\n")
    _write(tmp_path / "b.yml", "connectors: {XB: {pincount: 1}}\n")
    main = _write(tmp_path / "m.yml", "include: [a.yml]\nconnections: [[XA], [XB]]\n")
    assert set(parse(main, return_types="harness").connectors) == {"XA", "XB"}

    _write(tmp_path / "c1.yml", "include: [c2.yml]\n")
    _write(tmp_path / "c2.yml", "include: [c1.yml]\n")
    cyc = _write(tmp_path / "cyc.yml", "include: [c1.yml]\n")
    with pytest.raises(ValueError, match="cycle"):
        parse(cyc, return_types="harness")

    _write(tmp_path / "opt.yml", "options: {fontname: arial}\n")
    bad = _write(tmp_path / "bad.yml", "include: opt.yml\n")
    with pytest.raises(ValueError, match="options is allowed only in the main file"):
        parse(bad, return_types="harness")


def test_issue220_include_paths_and_cli(tmp_path: Path, runner):
    from wireviz.wv_cli import wireviz as cli

    _write(
        tmp_path / "shared/lib/parts.yml",
        "connectors:\n  X1: {pincount: 2}\n  X2: {pincount: 2}\ncables:\n  W1: {wirecount: 2}\n",
    )
    main = _write(tmp_path / "proj/main.yml", MAIN_WITH_INCLUDE)
    with pytest.raises(FileNotFoundError):
        parse(main, return_types="harness")
    assert parse(main, return_types="harness", include_paths=[tmp_path / "shared"])
    result = runner.invoke(cli, ["-f", "s", "-I", str(tmp_path / "shared"), str(main)])
    assert result.exit_code == 0, result.stderr
    assert (tmp_path / "proj/main.svg").exists()


def test_issue220_images_resolve_against_included_file(tmp_path: Path):
    _write(tmp_path / "lib/img/pic.png", "")
    (tmp_path / "lib/img/pic.png").write_bytes(TRS.read_bytes())
    _write(
        tmp_path / "lib/parts.yml",
        "connectors:\n  X1: {pincount: 1, image: img/pic.png}\n",
    )
    main = _write(
        tmp_path / "main.yml", "include: [lib/parts.yml]\nconnections: [[X1]]\n"
    )
    assert "data:image/png;base64," in parse(main, return_types="svg")


def test_issue220_png_embeds_merged_yaml(tmp_path: Path):
    import io

    from wireviz.Harness import read_yaml_from_png

    _write(tmp_path / "lib.yml", "connectors:\n  X1: {pincount: 1}\n")
    main = _write(tmp_path / "main.yml", "include: [lib.yml]\nconnections: [[X1]]\n")
    png = parse(main, return_types="png")
    embedded = read_yaml_from_png(io.BytesIO(png))
    assert "include" not in embedded and "X1" in embedded
    assert parse(embedded, return_types="harness").connectors["X1"]


def test_issue220_untrusted_refuses_include():
    with pytest.raises(ValueError, match="include is not allowed"):
        parse(
            "include: [/etc/hosts]\nconnectors: {}\n",
            return_types="harness",
            untrusted=True,
        )


# ===========================================================================
# Batch C3 — twisted pairs (#3, #353)
# ===========================================================================

TWISTED = """
connectors:
  X1: {pincount: 4}
  X2: {pincount: 4}
cables:
  W1:
    colors: [RD, BK, WH, BU]
    twisted: [[RD, BK], {wires: [3, 4], rate: 20/m}]
connections:
  - - X1: [1-4]
    - W1: [1-4]
    - X2: [1-4]
"""


@pytest.mark.parametrize("untrusted", [False, True])
def test_issue3_twisted_pairs_render(untrusted: bool):
    h = parse(TWISTED, return_types="harness", untrusted=untrusted)
    assert h.cables["W1"].twisted_groups == [([1, 2], None), ([3, 4], "20/m")]
    source = h.graph.source
    assert "Twisted pair</td>" in source and "Twisted pair: 20/m" in source
    for i in range(1, 5):
        assert f'port="w{i}"' in source
    assert "<svg" in h.svg


def test_issue3_twisted_group_rows_are_contiguous():
    src = TWISTED.replace(
        "twisted: [[RD, BK], {wires: [3, 4], rate: 20/m}]", "twisted: [[1, 3, 4]]"
    )
    h = parse(src, return_types="harness")
    assert h.cables["W1"].wire_display_order()[0] == [1, 3, 4, 2]
    assert "Twisted triad" in h.graph.source


@pytest.mark.parametrize(
    "twisted, message",
    [
        ("[[1]]", "2 or more wires"),
        ("[[1, 2], [2, 3]]", "more than one twisted group"),
        ("[[1, 9]]", "wire 9 not found"),
        ("[[RD, GN]]", "wire GN not found"),
        ("[{wires: [1, 2], twist: left}]", "only wires and rate"),
    ],
)
def test_issue3_twisted_errors(twisted: str, message: str):
    src = TWISTED.replace("[[RD, BK], {wires: [3, 4], rate: 20/m}]", twisted)
    with pytest.raises((ValueError, TypeError), match=message):
        parse(src, return_types="harness")


# ===========================================================================
# Batch C4 — internal shorts / jumpers (#350)
# ===========================================================================

SHORTS = """
connectors:
  TB1:
    pinlabels: [L1, L2, L3, N, PE, AUX]
    hide_disconnected_pins: true
    shorts: [[L1, L2, L3], {YE: [N, AUX]}]
    additional_components:
      - {type: Ferrule, qty_multiplier: populated}
  X2: {pincount: 6}
cables:
  W1: {wirecount: 2}
connections:
  - - TB1: [1, 4]
    - W1: [1, 2]
    - X2: [1, 4]
"""


@pytest.mark.parametrize("untrusted", [False, True])
def test_issue350_shorts_render(untrusted: bool):
    h = parse(SHORTS, return_types="harness", untrusted=untrusted)
    tb1 = h.connectors["TB1"]
    assert tb1.short_groups == [([1, 2, 3], None), ([4, 6], "YE")]
    source = h.graph.source
    assert source.count("&#9679;") == 5  # one dot per shorted pin
    assert 'bgcolor="#ffff00"' in source  # YE bar
    assert "<svg" in h.svg


def test_issue350_shorted_pins_are_populated_and_visible():
    h = parse(SHORTS, return_types="harness")
    tb1 = h.connectors["TB1"]
    assert set(tb1.visible_pins) == {1, 2, 3, 4, 6}  # PE (5) stays hidden
    assert tb1.get_qty_multiplier("populated") == 5


@pytest.mark.parametrize(
    "shorts, message",
    [
        ("[[1]]", "2 or more pins"),
        ("[[1, 2], [2, 3]]", "more than one short"),
        ("[[1, NOPE]]", "TB1:NOPE not found"),
        ("[{5: [1, 2]}]", "short color must be"),
    ],
)
def test_issue350_short_errors(shorts: str, message: str):
    src = SHORTS.replace("[[L1, L2, L3], {YE: [N, AUX]}]", shorts)
    with pytest.raises((ValueError, TypeError), match=message):
        parse(src, return_types="harness")


# ===========================================================================
# Batch C5 — print-ready sheet PDF (#32, #304)
# ===========================================================================


@pytest.fixture
def weasyprint_ok():
    """Skip unless WeasyPrint and Pango load. Imported in the test, not at
    collection, so a broken import cannot affect other tests."""
    try:
        import weasyprint  # noqa: F401
    except Exception as exc:
        if os.environ.get("WIREVIZ_REQUIRE_PDF"):
            pytest.fail(f"WIREVIZ_REQUIRE_PDF is set, but WeasyPrint does not load: {exc}")
        pytest.skip(f"WeasyPrint (wireviz[pdf]) not available: {exc}")


@pytest.mark.parametrize("sheetsize", ["A4", "A3", "A2"])
def test_issue32_sheet_pdf_page_size(tmp_path: Path, sheetsize: str, weasyprint_ok):
    """One page at the template's sheet size (frame + margins)."""
    import weasyprint

    src = (
        f"metadata:\n  title: Sheet\n  template: {{name: din-6771, sheetsize: {sheetsize}}}\n"
        + MINIMAL
    )
    parse(src, output_formats=("sheet",), output_dir=tmp_path, output_name="h")
    assert (tmp_path / "h.sheet.pdf").read_bytes().startswith(b"%PDF")
    html = parse(src, return_types="harness")._render(("html",))["html"]
    pages = weasyprint.HTML(string=html).render().pages
    assert len(pages) == 1
    mm = 25.4 / 96  # CSS px -> mm
    size = (round(pages[0].width * mm), round(pages[0].height * mm))
    assert size == {"A4": (210, 297), "A3": (420, 297), "A2": (594, 420)}[sheetsize]


def test_issue32_sheet_pdf_untrusted_and_no_external_fetch(weasyprint_ok):
    src = (
        "metadata:\n  title: '<img src=\"http://example.invalid/x.png\">T'\n" + MINIMAL
    )
    h = parse(src, return_types="harness", untrusted=True)
    assert h._render(("sheet",))["sheet"].startswith(b"%PDF")


def test_issue32_sheet_pdf_without_weasyprint(monkeypatch):
    import builtins

    from wireviz.wv_sheet import SheetPdfUnavailable

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "weasyprint":
            raise ImportError("no weasyprint")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    h = parse(MINIMAL, return_types="harness")
    with pytest.raises(SheetPdfUnavailable, match=r'pip install "wireviz\[pdf\]"'):
        h._render(("sheet",))


def test_issue32_sheet_cli_code():
    from wireviz.wv_cli import format_codes

    assert format_codes["D"] == "sheet" and format_codes["P"] == "pdf"


# ---------------------------------------------------------------------------
# Batch C review round 1
# ---------------------------------------------------------------------------


def test_review_c_sheet_keeps_inline_images(weasyprint_ok, tmp_path: Path):
    """data: images inside the SVG must reach the PDF (the fetcher used to
    refuse them and WeasyPrint dropped the rest of the diagram)."""
    import weasyprint

    from wireviz.wv_sheet import html_to_pdf

    (tmp_path / "pic.png").write_bytes(TRS.read_bytes())
    src = "connectors:\n  X1: {pincount: 1, image: pic.png}\nconnections: [[X1]]\n"
    html = parse(src, return_types="harness", image_paths=[tmp_path])._render(
        ("html",)
    )["html"]
    assert html_to_pdf(html).startswith(b"%PDF")
    images = []
    page = weasyprint.HTML(string=html).render().pages[0]

    def walk(box):
        if type(box).__name__ in ("InlineReplacedBox", "BlockReplacedBox"):
            images.append(box)
        for child in getattr(box, "children", []) or []:
            walk(child)

    walk(page._page_box)
    assert images  # the SVG is laid out as a replaced box
    from weasyprint.urls import URLFetcher

    fetched = []
    original = URLFetcher.fetch

    def spy(self, url, *a, **k):
        fetched.append(url[:10])
        return original(self, url, *a, **k)

    import unittest.mock as mock

    with mock.patch.object(URLFetcher, "fetch", spy):
        html_to_pdf(html)
    assert fetched and all(u.startswith("data:") for u in fetched)


def test_review_c_sheet_never_fetches_files(weasyprint_ok):
    """Only data: URLs may be fetched; file: and http: are refused by the
    fetcher itself (spied, not inferred from the output)."""
    import unittest.mock as mock

    from weasyprint.urls import URLFetcher

    from wireviz.wv_sheet import html_to_pdf

    calls = []
    original = URLFetcher.fetch

    def spy(self, url, *a, **k):
        try:
            result = original(self, url, *a, **k)
        except Exception:
            calls.append((url.split(":")[0], "refused"))
            raise
        calls.append((url.split(":")[0], "fetched"))
        return result

    html = '<html><body><img src="file:///etc/hosts"><img src="http://example.invalid/x.png"></body></html>'
    with mock.patch.object(URLFetcher, "fetch", spy):
        assert html_to_pdf(html).startswith(b"%PDF")
    assert ("file", "fetched") not in calls and ("http", "fetched") not in calls
    assert ("file", "refused") in calls


def test_review_c_untrusted_sheet_runs_with_timeout(weasyprint_ok, monkeypatch):
    import wireviz.Harness as H

    h = parse(MINIMAL, return_types="harness", untrusted=True)
    assert h._render(("sheet",))["sheet"].startswith(b"%PDF")
    monkeypatch.setattr(H, "UNTRUSTED_RENDER_TIMEOUT", 0.000001)
    with pytest.raises(RuntimeError, match="did not finish"):
        parse(MINIMAL, return_types="harness", untrusted=True)._render(("sheet",))


def test_review_c_shorts_cap_and_color():
    many = ", ".join(f"[{2 * i + 1}, {2 * i + 2}]" for i in range(65))
    src = (
        f"connectors:\n  X1: {{pincount: 130, shorts: [{many}]}}\nconnections: [[X1]]\n"
    )
    with pytest.raises(ValueError, match="more than 64 shorts"):
        parse(src, return_types="harness")
    src = "connectors:\n  X1: {pincount: 2, shorts: [{'#abc': [1, 2]}]}\nconnections: [[X1]]\n"
    with pytest.raises(ValueError, match="not a color name or a #rrggbb"):
        parse(src, return_types="harness")


def test_review_c_diamond_include(tmp_path: Path):
    _write(tmp_path / "common.yml", "connectors:\n  TERM: {pincount: 1}\n")
    _write(
        tmp_path / "a.yml", "include: [common.yml]\nconnectors:\n  XA: {pincount: 1}\n"
    )
    _write(
        tmp_path / "b.yml", "include: [common.yml]\nconnectors:\n  XB: {pincount: 1}\n"
    )
    main = _write(
        tmp_path / "m.yml",
        "include: [a.yml, b.yml]\nconnections: [[TERM], [XA], [XB]]\n",
    )
    assert set(parse(main, return_types="harness").connectors) == {"TERM", "XA", "XB"}
    _write(tmp_path / "c.yml", "connectors:\n  TERM: {pincount: 2}\n")
    clash = _write(tmp_path / "n.yml", "include: [a.yml, c.yml]\nconnections: []\n")
    with pytest.raises(ValueError, match=r"defined in both .*common\.yml and .*c\.yml"):
        parse(clash, return_types="harness")


def test_review_c_include_non_utf8_names_the_file(tmp_path: Path):
    (tmp_path / "lib.yml").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
    main = _write(tmp_path / "m.yml", "include: [lib.yml]\n")
    with pytest.raises(ValueError, match="lib.yml: not a UTF-8"):
        parse(main, return_types="harness")


def test_review_c_bare_reference_to_template_instance():
    src = """
connectors: {X1: {pincount: 5}, X2: {pincount: 5}}
cables: {W: {}}
connections:
  - - X1: [1-2]
    - W.W1
    - X2: [1-2]
  - - X1: [5]
    - W1: [5]
    - X2: [5]
"""
    h = parse(src, return_types="harness")
    assert h.cables["W1"].wirecount == 5


def test_review_c_bare_cable_hint_and_prepass_context():
    src = """
connectors: {X1: {pincount: 3}, X2: {pincount: 3}}
cables: {W1: {colors: [RD, BK]}}
connections:
  - - X1: [1-3]
    - W1
    - X2: [1-3]
"""
    with pytest.raises(ValueError, match="cable named alone uses wires 1..n"):
        parse(src, return_types="harness")
    bad = "connectors: {X1: {pincount: 1}}\ncables: {W1: {}}\nconnections:\n  - - X1: {a: 1}\n    - W1\n"
    with pytest.raises(Exception, match="connection set 1"):
        parse(bad, return_types="harness")


def test_review_c_cli_one_line_for_missing_weasyprint(
    runner, tmp_path: Path, monkeypatch
):
    import wireviz.wv_sheet as ws
    from wireviz.wv_cli import wireviz as cli

    def missing():
        raise ws.SheetPdfUnavailable('needs WeasyPrint: pip install "wireviz[pdf]"')

    monkeypatch.setattr(ws, "_weasyprint", missing)
    f = _write(tmp_path / "h.yml", MINIMAL)
    result = runner.invoke(cli, ["-f", "D", str(f)])
    assert result.exit_code == 1
    assert (
        'pip install "wireviz[pdf]"' in result.stderr
        and "Traceback" not in result.stderr
    )


# ---------------------------------------------------------------------------
# Batch C review round 2
# ---------------------------------------------------------------------------


def test_review_c2_sheet_child_ignores_cwd_package(
    weasyprint_ok, tmp_path: Path, monkeypatch
):
    """The untrusted sheet child must import this wireviz, not a package
    named wireviz in the working directory."""
    fake = tmp_path / "wireviz"
    fake.mkdir()
    (fake / "__init__.py").write_text("")
    (fake / "wv_sheet.py").write_text(
        "import sys\ndef _main():\n    sys.stdout.write('%PDF-fake')\n"
    )
    monkeypatch.chdir(tmp_path)
    h = parse(MINIMAL, return_types="harness", untrusted=True)
    pdf = h._render(("sheet",))["sheet"]
    assert pdf.startswith(b"%PDF-1") and b"fake" not in pdf


@pytest.mark.parametrize(
    "connections, message",
    [
        ("[[X1: [1], {}, X2: [1]]]", "exactly one designator"),
        ("[{X1: [1]}]", "a connection set must be a list"),
        ("[[X1: [1], [], X2: [1]]]", "empty list"),
    ],
)
def test_review_c2_malformed_connection_sets(connections: str, message: str):
    src = f"connectors: {{X1: {{pincount: 1}}, X2: {{pincount: 1}}}}\nconnections: {connections}\n"
    with pytest.raises(ValueError, match=f"connection set 1 .*{message}"):
        parse(src, return_types="harness")


def test_review_c2_shorts_cell_budget():
    shorts = ", ".join(f"[{2 * i + 1}, {2 * i + 2}]" for i in range(64))
    entries = "\n".join(f"  X{i}: *c" for i in range(2, 10))
    src = (
        f"connectors:\n  X1: &c {{pincount: 2000, shorts: [{shorts}]}}\n{entries}\n"
        "connections: [[X1]]\n"
    )
    h = parse(src, return_types="harness")
    with pytest.raises(ValueError, match="pins x shorts"):
        h.graph


def test_review_c2_diamond_include_bom_items_once(tmp_path: Path):
    _write(
        tmp_path / "common.yml",
        "additional_bom_items:\n  - {description: Common item, qty: 1}\n",
    )
    _write(tmp_path / "b.yml", "include: [common.yml]\n")
    _write(tmp_path / "c.yml", "include: [common.yml]\n")
    main = _write(
        tmp_path / "m.yml",
        "include: [b.yml, c.yml]\nconnectors: {X1: {pincount: 1}}\nconnections: [[X1]]\n",
    )
    h = parse(main, return_types="harness")
    assert [i["description"] for i in h.additional_bom_items] == ["Common item"]


def test_review_c2_bare_string_instance_reference():
    src = """
connectors: {X1: {pincount: 3}, X2: {pincount: 3}}
cables: {K: {}}
connections:
  - - X1: [1]
    - K.K1: [1]
    - X2: [1]
  - - X1: [1-3]
    - K1
    - X2: [1-3]
"""
    h = parse(src, return_types="harness")
    assert h.cables["K1"].wirecount == 3
    assert [c.via_port for c in h.cables["K1"].connections] == [1, 1, 2, 3]


@pytest.mark.parametrize(
    "value, shown", [("2024-01-02", "2024-01-02"), ("'v2'", "v2"), ("null", None)]
)
def test_review_c2_date_placeholder(tmp_path: Path, value: str, shown):
    from datetime import date

    (tmp_path / "t.html").write_text("<html><body>[<!-- %date% -->]</body></html>")
    src = f"metadata: {{date: {value}, template: {{name: t}}}}\nconnectors: {{X1: {{pincount: 1}}}}\nconnections: [[X1]]\n"
    page = parse(src, return_types="harness", source_path=tmp_path / "x.yml")._render(
        ("html",), template_dir=tmp_path
    )["html"]
    assert f"[{shown or date.today().isoformat()}]" in page
