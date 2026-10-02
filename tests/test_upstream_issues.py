# -*- coding: utf-8 -*-
"""One test per upstream wireviz/WireViz issue fixed in this fork.

Each test names the upstream issue it pins down. The triage of all open
upstream issues is in ``docs/plans/2026-10-02-upstream-issue-triage.md``.
"""

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
    assert result.exit_code != 0
    assert "IsADirectoryError" not in repr(result.exception)
    assert "input is empty" in str(result.exception)


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
    assert "#000000:#ff0000:#ff0000:#ff0000:#000000" in source  # red loop
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
        ("data:image/png;base64,AAAA", "not a readable image"),
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
