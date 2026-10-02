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
