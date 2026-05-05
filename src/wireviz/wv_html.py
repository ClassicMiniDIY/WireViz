# -*- coding: utf-8 -*-

import re
from pathlib import Path
from typing import Callable, Dict, List, Union

from wireviz import APP_NAME, APP_URL, __version__, wv_colors
from wireviz.DataClasses import Metadata, Options
from wireviz.svgembed import data_URI_base64
from wireviz.wv_gv_html import html_line_breaks
from wireviz.wv_helper import (
    file_read_text,
    flatten2d,
    smart_file_resolve,
)


def _latest_revision(metadata: Metadata) -> str:
    """Return the key of the most recently added entry in
    ``metadata.revisions`` when revisions is a dict or list, or the
    value itself when it is a scalar (string/int/float).

    Dict/list relies on Python's insertion-order preservation; YAML
    parsers preserve document order. Returns "" for missing, empty,
    or None values.
    """
    revisions = metadata.get("revisions") if metadata else None
    if isinstance(revisions, (dict, list)):
        return str(list(revisions)[-1]) if revisions else ""
    return str(revisions) if revisions is not None else ""


def generate_html_output(
    svg_input: Union[str, None],
    bom_list: List[List[str]],
    metadata: Metadata,
    options: Options,
    output_dir: Union[str, Path, None] = None,
    output_name: Union[str, None] = None,
    png_b64: Union[str, None] = None,
    source_path: Union[str, Path, None] = None,
    template_dir: Union[str, Path, None] = None,
) -> str:
    # load HTML template
    templatename = metadata.get("template", {}).get("name")
    builtin_template_dir = Path(__file__).parent / "templates"
    if templatename:
        # custom template lookup order, highest priority first:
        #   1. explicit template_dir (CLI -t / parse template_dir)
        #   2. YAML source directory (source_path.parent)
        #   3. output directory
        #   4. built-in templates shipped with WireViz
        search_paths = [builtin_template_dir]
        if output_dir is not None:
            search_paths.insert(0, Path(output_dir))
        if source_path is not None:
            search_paths.insert(0, Path(source_path).parent)
        if template_dir is not None:
            search_paths.insert(0, Path(template_dir))
        templatefile = smart_file_resolve(
            f"{templatename}.html",
            search_paths,
        )
    else:
        # fall back to built-in simple template if no template was provided
        templatefile = builtin_template_dir / "simple.html"

    html = file_read_text(templatefile)  # TODO?: Warn if unexpected meta charset?

    # embed SVG diagram (only if used)
    def svgdata() -> str:
        return re.sub(  # TODO?: Verify xml encoding="utf-8" in SVG?
            "^<[?]xml [^?>]*[?]>[^<]*<!DOCTYPE [^>]*>",
            "<!-- XML and DOCTYPE declarations from SVG file removed -->",
            svg_input or "",
            count=1,
        )

    # generate BOM table
    bom = flatten2d(bom_list)

    # generate BOM header (may be at the top or bottom of the table)
    bom_header_html = "  <tr>\n"
    for item in bom[0]:
        th_class = f"bom_col_{item.lower()}"
        bom_header_html = f'{bom_header_html}    <th class="{th_class}">{item}</th>\n'
    bom_header_html = f"{bom_header_html}  </tr>\n"

    # generate BOM contents
    bom_contents = []
    for row in bom[1:]:
        row_html = "  <tr>\n"
        for i, item in enumerate(row):
            td_class = f"bom_col_{bom[0][i].lower()}"
            row_html = f'{row_html}    <td class="{td_class}">{item}</td>\n'
        row_html = f"{row_html}  </tr>\n"
        bom_contents.append(row_html)

    bom_html = (
        '<table class="bom">\n' + bom_header_html + "".join(bom_contents) + "</table>\n"
    )
    bom_html_reversed = (
        '<table class="bom">\n'
        + "".join(list(reversed(bom_contents)))
        + bom_header_html
        + "</table>\n"
    )

    if output_dir is not None and output_name is not None:
        full_filename = str(Path(output_dir) / output_name)
        filename_stem = output_name
    else:
        full_filename = ""
        filename_stem = ""

    # prepare simple replacements
    replacements = {
        "<!-- %generator% -->": f"{APP_NAME} {__version__} - {APP_URL}",
        "<!-- %fontname% -->": options.fontname,
        "<!-- %bgcolor% -->": wv_colors.translate_color(options.bgcolor, "hex"),
        "<!-- %filename% -->": full_filename,
        "<!-- %filename_stem% -->": filename_stem,
        "<!-- %bom% -->": bom_html,
        "<!-- %bom_reversed% -->": bom_html_reversed,
        "<!-- %sheet_current% -->": "1",  # TODO: handle multi-page documents
        "<!-- %sheet_total% -->": "1",  # TODO: handle multi-page documents
        "<!-- %template_sheetsize% -->": metadata.get("template", {}).get(
            "sheetsize", ""
        ),
        "<!-- %revision% -->": _latest_revision(metadata),
    }

    def replacement_if_used(key: str, func: Callable[[], str]) -> None:
        """Append replacement only if used in html."""
        if key in html:
            replacements[key] = func()

    replacement_if_used("<!-- %diagram% -->", svgdata)
    if png_b64 is not None:
        replacement_if_used("<!-- %diagram_png_b64% -->", lambda: png_b64)
    elif full_filename:
        replacement_if_used(
            "<!-- %diagram_png_b64% -->",
            lambda: data_URI_base64(f"{full_filename}.png"),
        )

    # prepare metadata replacements
    if metadata:
        for item, contents in metadata.items():
            if isinstance(contents, (str, int, float)):
                replacements[f"<!-- %{item}% -->"] = html_line_breaks(str(contents))
            elif isinstance(contents, Dict):  # useful for authors, revisions
                for index, (category, entry) in enumerate(contents.items()):
                    if isinstance(entry, Dict):
                        replacements[f"<!-- %{item}_{index+1}% -->"] = str(category)
                        for entry_key, entry_value in entry.items():
                            replacements[
                                f"<!-- %{item}_{index+1}_{entry_key}% -->"
                            ] = html_line_breaks(str(entry_value))
                    elif isinstance(entry, (str, int, float)):
                        pass  # TODO?: replacements[f"<!-- %{item}_{category}% -->"] = html_line_breaks(str(entry))

    # perform replacements
    # regex replacement adapted from:
    # https://gist.github.com/bgusach/a967e0587d6e01e889fd1d776c5f3729

    # longer replacements first, just in case
    replacements_sorted = sorted(replacements, key=len, reverse=True)
    replacements_escaped = map(re.escape, replacements_sorted)
    pattern = re.compile("|".join(replacements_escaped))
    return pattern.sub(lambda match: replacements[match.group(0)], html)
