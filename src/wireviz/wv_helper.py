# -*- coding: utf-8 -*-

import re
import sys
from pathlib import Path
from typing import Dict, List

import yaml

from wireviz.wv_safety import MAX_EXPAND


class _WireVizLoader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 booleans: only true/false are booleans.

    YAML 1.1 also reads yes/no/on/off as booleans, so pin labels such as
    NO, NC or ON turned into True/False and lost their text (upstream
    #305). Boolean fields convert those words back, see yaml11_bool().
    """


_WireVizLoader.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_WireVizLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)

_YAML11_BOOL_WORDS = {
    **{w: True for w in ("yes", "Yes", "YES", "on", "On", "ON")},
    **{w: False for w in ("no", "No", "NO", "off", "Off", "OFF")},
}


def yaml_load(text: str):
    """Parse WireViz YAML text (safe loader, YAML 1.2 booleans)."""
    return yaml.load(text, Loader=_WireVizLoader)


def yaml11_bool(value):
    """Return True/False for the YAML 1.1 words yes/no/on/off, else value.

    Used for boolean fields, so `show_name: no` keeps working after
    yaml_load() stopped turning those words into booleans.
    """
    if isinstance(value, str) and value in _YAML11_BOOL_WORDS:
        return _YAML11_BOOL_WORDS[value]
    return value


# Conservative equivalents (see upstream #282): each AWG value has no more
# copper than its metric size, and each metric size is the smallest
# standard size with at least as much copper as its AWG value. Common
# charts pair 0.5 mm2 with 20 AWG, but 20 AWG (0.518 mm2) holds more
# copper than 0.5 mm2. Keep this property when editing the table.
awg_equiv_table = {
    "0.09": "28",
    "0.14": "26",
    "0.25": "24",
    "0.34": "22",
    "0.5": "21",
    "0.75": "20",
    "1": "18",
    "1.5": "16",
    "2.5": "14",
    "4": "12",
    "6": "10",
    "10": "8",
    "16": "6",
    "25": "4",
    "35": "2",
    "50": "1",
}

mm2_equiv_table = {v: k for k, v in awg_equiv_table.items()}


def _gauge_key(value) -> str:
    """Table key for a gauge value: 1.0, "1.0" and 1 all become "1"."""
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def awg_equiv(mm2):
    return awg_equiv_table.get(_gauge_key(mm2), "Unknown")


def mm2_equiv(awg):
    return mm2_equiv_table.get(_gauge_key(awg), "Unknown")


def expand(yaml_data):
    # yaml_data can be:
    # - a singleton (normally str or int)
    # - a list of str or int
    # if str is of the format '#-#', it is treated as a range (inclusive) and expanded
    output = []
    if not isinstance(yaml_data, list):
        yaml_data = [yaml_data]
    for e in yaml_data:
        if isinstance(e, (list, dict)):
            # Without this check, str(e) of a YAML alias tree can grow
            # exponentially (a few hundred bytes of YAML -> gigabytes).
            raise ValueError(
                f"Expected a pin/wire number, name or range, but got a {type(e).__name__}"
            )
        e = str(e)
        if "-" in e:
            a, b = e.split("-", 1)
            try:
                a = int(a)
                b = int(b)
            except ValueError:
                # '-' was not a delimiter between two ints, pass e through unchanged
                output.append(e)
                continue
            if abs(a - b) + 1 > MAX_EXPAND:
                raise ValueError(
                    f"Range {e} has more than the limit of {MAX_EXPAND} entries"
                )
            step = 1 if a <= b else -1  # ascending, descending, or length 1
            output.extend(range(a, b + step, step))
        else:
            try:
                x = int(e)  # single int
            except Exception:
                x = e  # string
            output.append(x)
    return output


def get_single_key_and_value(d: dict):
    k = list(d.keys())[0]
    v = d[k]
    return (k, v)


def int2tuple(inp):
    if isinstance(inp, tuple):
        output = inp
    else:
        output = (inp,)
    return output


def flatten2d(inp):
    return [
        [str(item) if not isinstance(item, List) else ", ".join(item) for item in row]
        for row in inp
    ]


def tuplelist2tsv(inp, header=None):
    output = ""
    if header is not None:
        inp.insert(0, header)
    inp = flatten2d(inp)
    for row in inp:
        output = output + "\t".join(str(remove_links(item)) for item in row) + "\n"
    return output


def tuplelist2csv(inp) -> str:
    """Return the BOM rows as CSV text (RFC 4180 quoting, upstream #98)."""
    import csv
    import io

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for row in flatten2d(inp):
        writer.writerow([remove_links(str(item)) for item in row])
    return out.getvalue()


def remove_links(inp):
    return (
        re.sub(r"<[aA] [^>]*>([^<]*)</[aA]>", r"\1", inp)
        if isinstance(inp, str)
        else inp
    )


def clean_whitespace(inp):
    return " ".join(inp.split()).replace(" ,", ",") if isinstance(inp, str) else inp


def open_file_read(filename):
    """Open utf-8 encoded text file for reading - remember closing it when finished"""
    # TODO: Intelligently determine encoding
    return open(filename, "r", encoding="UTF-8")


def open_file_write(filename):
    """Open utf-8 encoded text file for writing - remember closing it when finished"""
    return open(filename, "w", encoding="UTF-8")


def open_file_append(filename):
    """Open utf-8 encoded text file for appending - remember closing it when finished"""
    return open(filename, "a", encoding="UTF-8")


def file_read_text(filename: str) -> str:
    """Read utf-8 encoded text file, close it, and return the text"""
    return Path(filename).read_text(encoding="utf-8")


def file_write_text(filename: str, text: str) -> int:
    """Write utf-8 encoded text file, close it, and return the number of characters written"""
    return Path(filename).write_text(text, encoding="utf-8")


def is_arrow(inp):
    """
    Matches strings of one or multiple `-` or `=` (but not mixed)
    optionally starting with `<` and/or ending with `>`.

    Examples:
      <-, --, ->, <->
      <==, ==, ==>, <=>
    """
    # regex by @shiraneyo
    return bool(
        re.match(r"^\s*(?P<leftHead><?)(?P<body>-+|=+)(?P<rightHead>>?)\s*$", inp)
    )


def aspect_ratio(image_src):
    try:
        from PIL import Image

        with Image.open(image_src) as image:
            if image.width > 0 and image.height > 0:
                return image.width / image.height
            sys.stderr.write(
                f"aspect_ratio(): Invalid image size {image.width} x {image.height}\n"
            )
    # ModuleNotFoundError and FileNotFoundError are the most expected, but all are handled equally.
    except Exception as error:
        sys.stderr.write(f"aspect_ratio(): {type(error).__name__}: {error}\n")
    return 1  # Assume 1:1 when unable to read actual image size


def smart_file_resolve(filename: str, possible_paths: (str, List[str])) -> Path:
    if not isinstance(possible_paths, List):
        possible_paths = [possible_paths]
    filename = Path(filename)
    if filename.is_absolute():
        if filename.exists():
            return filename
        else:
            raise Exception(f"{filename} does not exist.")
    else:  # search all possible paths in decreasing order of precedence
        possible_paths = [
            Path(path).resolve() for path in possible_paths if path is not None
        ]
        for possible_path in possible_paths:
            resolved_path = (possible_path / filename).resolve()
            if resolved_path.exists():
                return resolved_path
        else:
            raise Exception(
                f"{filename} was not found in any of the following locations: \n"
                + "\n".join([str(x) for x in possible_paths])
            )
