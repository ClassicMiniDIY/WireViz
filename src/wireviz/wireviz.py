#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import copy
import platform
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))  # add src/wireviz to PATH

from wireviz.DataClasses import Metadata, Options, Tweak
from wireviz.Harness import Harness
from wireviz.wv_helper import (
    expand,
    file_read_text,
    get_single_key_and_value,
    is_arrow,
    smart_file_resolve,
)
from wireviz.wv_safety import UNTRUSTED_MAX_INPUT_BYTES, check_untrusted_image

from . import APP_NAME


def parse(
    inp: Union[Path, str, Dict],
    return_types: Union[None, str, Tuple[str]] = None,
    output_formats: Union[None, str, Tuple[str]] = None,
    output_dir: Union[str, Path] = None,
    output_name: Union[None, str] = None,
    image_paths: Union[Path, str, List, None] = None,
    source_path: Union[Path, str, None] = None,
    template_dir: Union[Path, str, None] = None,
    embed_yaml: bool = True,
    untrusted: bool = False,
) -> Any:
    """
    This function takes an input, parses it as a WireViz Harness file,
    and outputs the result as one or more files and/or as a function return value

    Accepted inputs:
        * A path to a YAML source file to parse
        * A string containing the YAML data to parse
        * A Python Dict containing the pre-parsed YAML data

    Supported return types:
        * "png":     the diagram as raw PNG data
        * "svg":     the diagram as raw SVG data
        * "harness": the diagram as a Harness Python object

    Supported output formats:
        * "csv":  the BOM, as a comma-separated text file
        * "gv":   the diagram, as a GraphViz source file
        * "html": the diagram and (depending on the template) the BOM, as a HTML file
        * "png":  the diagram, as a PNG raster image
        * "pdf":  the diagram, as a PDF document (no BOM — see "html" for that)
        * "svg":  the diagram, as a SVG vector image
        * "tsv":  the BOM, as a tab-separated text file

    Args:
        inp (Path | str | Dict):
            The input to be parsed (see above for accepted inputs).
        return_types (optional):
            One of the supported return types (see above), or a tuple of multiple return types.
            If set to None, no output is returned by the function.
        output_formats (optional):
            One of the supported output types (see above), or a tuple of multiple output formats.
            If set to None, no files are generated.
        output_dir (Path | str, optional):
            The directory to place the generated output files.
            Defaults to inp's parent directory, or cwd if inp is not a path.
        output_name (str, optional):
            The name to use for the generated output files (without extension).
            Defaults to inp's file name (without extension).
            Required parameter if inp is not a path.
        image_paths (Path | str | List, optional):
            Paths to use when resolving any image paths included in the data.
            Note: If inp is a path to a YAML file,
            its parent directory will automatically be included in the list.
        source_path (Path | str, optional):
            Path of the originating YAML file when ``inp`` is a string or dict.
            Used to: (1) resolve a custom ``metadata.template.name`` reference
            against the source's directory, and (2) resolve relative
            ``<image src=...>`` paths embedded in graphviz output.
            When ``inp`` is itself a Path, this is filled in automatically.
        template_dir (Path | str, optional):
            Explicit first-priority directory to search when resolving a
            ``metadata.template.name`` reference. Searched before the YAML
            source directory and the output directory; the built-in
            templates ship as the final fallback.
        embed_yaml (bool, optional):
            When True (default) and PNG output is requested, the YAML
            source is embedded in the PNG as an iTXt chunk under the
            ``wireviz:yaml`` key for round-trip editing. Set to False
            to render plain PNGs without source-bearing metadata.
        untrusted (bool, optional):
            Set to True when the YAML comes from someone other than the
            caller (for example, a web request). Then: a ``str`` input is
            always YAML text, never a path; the input size is capped;
            ``image.src`` must be relative and inside ``image_paths``;
            ``metadata.template.name`` must be a bare name; ``tweak`` is
            rejected; the SVG and the HTML output are sanitized; and each
            Graphviz call has a timeout. See ``wv_safety.py``.

    Returns:
        Depending on the return_types parameter, may return:
        * None
        * one of the following, or a tuple containing two or more of the following:
            * PNG data
            * SVG data
            * a Harness object
    """

    if not output_formats and not return_types:
        raise Exception("No output formats or return types specified")
    # A bare string names one format ("svg"), not a sequence of letters.
    if isinstance(output_formats, str):
        output_formats = (output_formats,)
    if isinstance(return_types, str):
        return_types = (return_types,)
    return_types = tuple(t.lower() for t in return_types or ())

    yaml_data, yaml_file, yaml_str = _get_yaml_data_and_path(inp, untrusted)
    if not isinstance(yaml_data, dict):
        raise TypeError(
            f"Expected a dict as top-level YAML input, but got: {type(yaml_data)}"
        )
    if untrusted:
        _reject_tweaks(yaml_data)
    # When inp was a Path, derive source_path automatically so callers
    # don't have to pass it twice. Matches the docstring contract.
    if source_path is None and yaml_file is not None:
        source_path = yaml_file
    write_to_stdout = (
        output_formats and (str(output_dir) == "-" or str(output_name) == "-")
    )
    if output_formats and not write_to_stdout:
        # need to write data to file, determine output directory and filename
        output_dir = _get_output_dir(yaml_file, output_dir)
        output_name = _get_output_name(yaml_file, output_name)
        output_file = output_dir / output_name
    else:
        output_dir = None
        output_name = None
        output_file = None

    # Work on a private copy: never mutate the caller's list (or a shared
    # default) — a long-running server calls parse() many times.
    if image_paths is None:
        image_paths = []
    elif isinstance(image_paths, (str, Path)):
        image_paths = [image_paths]
    else:
        image_paths = list(image_paths)
    # Relative image paths resolve against the YAML file's directory: the
    # input file itself, or source_path for str/dict input.
    image_source = yaml_file or (
        Path(source_path)
        if source_path is not None and str(source_path) != "-"
        else None
    )
    if image_source is not None and not untrusted:
        default_image_path = image_source.parent.resolve()
        if not default_image_path in [Path(x).resolve() for x in image_paths]:
            image_paths.append(default_image_path)

    # define variables =========================================================
    # containers for parsed component data and connection sets
    template_connectors = {}
    template_cables = {}
    connection_sets = []
    # actual harness
    harness = Harness(
        # `or {}`: an empty section (`metadata:` with no value) is None.
        metadata=Metadata(**(yaml_data.get("metadata") or {})),
        options=Options(**(yaml_data.get("options") or {})),
        tweak=Tweak(**(yaml_data.get("tweak") or {})),
        source_path=source_path,
        untrusted=untrusted,
    )
    # others
    # store mapping of components to their respective template
    designators_and_templates = {}
    # keep track of auto-generated designators to avoid duplicates
    autogenerated_designators = {}

    # When title is not given, either deduce it from filename, or use default text.
    if "title" not in harness.metadata:
        harness.metadata["title"] = output_name or f"{APP_NAME} diagram and BOM"

    # add items
    # parse YAML input file ====================================================

    sections = ["connectors", "cables", "connections"]
    types = [dict, dict, list]
    for sec, ty in zip(sections, types):
        if sec in yaml_data and type(yaml_data[sec]) == ty:  # section exists
            if len(yaml_data[sec]) > 0:  # section has contents
                if ty == dict:
                    for key, attribs in yaml_data[sec].items():
                        # The Image dataclass might need to open an image file with a relative path.
                        image = attribs.get("image")
                        if isinstance(image, dict):
                            # Copy before rewriting src: a YAML alias may
                            # share this mapping with another component.
                            attribs = {**attribs, "image": dict(image)}
                            image = attribs["image"]
                            image_path = image["src"]
                            if untrusted:
                                image["src"] = check_untrusted_image(
                                    image_path, image_paths
                                )
                            elif image_path and not Path(image_path).is_absolute():
                                # resolve relative image path
                                image["src"] = smart_file_resolve(
                                    image_path, image_paths
                                )
                        if sec == "connectors":
                            template_connectors[key] = attribs
                        elif sec == "cables":
                            template_cables[key] = attribs
            else:  # section exists but is empty
                pass
        else:  # section does not exist, create empty section
            if ty == dict:
                yaml_data[sec] = {}
            elif ty == list:
                yaml_data[sec] = []

    connection_sets = yaml_data["connections"]

    # go through connection sets, generate and connect components ==============

    template_separator_char = harness.options.template_separator

    def resolve_designator(inp, separator):
        if separator in inp:  # generate a new instance of an item
            if inp.count(separator) > 1:
                raise Exception(f"{inp} - Found more than one separator ({separator})")
            template, designator = inp.split(separator)
            if designator == "":
                autogenerated_designators[template] = (
                    autogenerated_designators.get(template, 0) + 1
                )
                designator = f"__{template}_{autogenerated_designators[template]}"
            # check if redefining existing component to different template
            if designator in designators_and_templates:
                if designators_and_templates[designator] != template:
                    raise Exception(
                        f"Trying to redefine {designator} from {designators_and_templates[designator]} to {template}"
                    )
            else:
                designators_and_templates[designator] = template
        else:
            template, designator = (inp, inp)
            if designator in designators_and_templates:
                pass  # referencing an exiting connector, no need to add again
            else:
                designators_and_templates[designator] = template
        return (template, designator)

    # utilities to check for alternating connectors and cables/arrows ==========

    alternating_types = ["connector", "cable/arrow"]
    expected_type = None

    def check_type(designator, template, actual_type):
        nonlocal expected_type
        if not expected_type:  # each connection set may start with either section
            expected_type = actual_type

        if actual_type != expected_type:  # did not alternate
            raise Exception(
                f'Expected {expected_type}, but "{designator}" ("{template}") is {actual_type}'
            )

    def alternate_type():  # flip between connector and cable/arrow
        nonlocal expected_type
        expected_type = alternating_types[1 - alternating_types.index(expected_type)]

    for connection_set in connection_sets:
        # The steps below rewrite the set in place. A YAML alias (*name)
        # makes several sets share one list, so work on a private copy.
        connection_set = copy.deepcopy(connection_set)
        # figure out number of parallel connections within this set
        connectioncount = []
        for entry in connection_set:
            if isinstance(entry, list):
                connectioncount.append(len(entry))
            elif isinstance(entry, dict):
                connectioncount.append(len(expand(list(entry.values())[0])))
                # e.g.: - X1: [1-4,6] yields 5
            else:
                pass  # strings do not reveal connectioncount
        if not any(connectioncount):
            # no item in the list revealed connection count;
            # assume connection count is 1
            connectioncount = [1]
            # Example: The following is a valid connection set,
            #          even though no item reveals the connection count;
            #          the count is not needed because only a component-level mate happens.
            # -
            #   - CONNECTOR
            #   - ==>
            #   - CONNECTOR

        # check that all entries are the same length
        if len(set(connectioncount)) > 1:
            raise Exception(
                "All items in connection set must reference the same number of connections"
            )
        # all entries are the same length, connection count is set
        connectioncount = connectioncount[0]

        # expand string entries to list entries of correct length
        for index, entry in enumerate(connection_set):
            if isinstance(entry, str):
                connection_set[index] = [entry] * connectioncount

        # resolve all designators
        for index, entry in enumerate(connection_set):
            if isinstance(entry, list):
                for subindex, item in enumerate(entry):
                    template, designator = resolve_designator(
                        item, template_separator_char
                    )
                    connection_set[index][subindex] = designator
            elif isinstance(entry, dict):
                key = list(entry.keys())[0]
                template, designator = resolve_designator(key, template_separator_char)
                value = entry[key]
                connection_set[index] = {designator: value}
            else:
                pass  # string entries have been expanded in previous step

        # expand all pin lists
        for index, entry in enumerate(connection_set):
            if isinstance(entry, list):
                connection_set[index] = [{designator: 1} for designator in entry]
            elif isinstance(entry, dict):
                designator = list(entry.keys())[0]
                pinlist = expand(entry[designator])
                connection_set[index] = [{designator: pin} for pin in pinlist]
            else:
                pass  # string entries have been expanded in previous step

        # Populate wiring harness ==============================================

        expected_type = None  # reset check for alternating types
        # at the beginning of every connection set
        # since each set may begin with either type

        # generate components
        for entry in connection_set:
            for item in entry:
                designator = list(item.keys())[0]
                template = designators_and_templates[designator]

                if designator in harness.connectors:  # existing connector instance
                    check_type(designator, template, "connector")
                elif template in template_connectors.keys():
                    # generate new connector instance from template
                    check_type(designator, template, "connector")
                    harness.add_connector(
                        name=designator, **template_connectors[template]
                    )

                elif designator in harness.cables:  # existing cable instance
                    check_type(designator, template, "cable/arrow")
                elif template in template_cables.keys():
                    # generate new cable instance from template
                    check_type(designator, template, "cable/arrow")
                    harness.add_cable(name=designator, **template_cables[template])

                elif is_arrow(designator):
                    check_type(designator, template, "cable/arrow")
                    # arrows do not need to be generated here
                else:
                    raise Exception(
                        f"{template} is an unknown template/designator/arrow."
                    )

            alternate_type()  # entries in connection set must alternate between connectors and cables/arrows

        # transpose connection set list
        # before: one item per component, one subitem per connection in set
        # after:  one item per connection in set, one subitem per component
        connection_set = list(map(list, zip(*connection_set)))

        # connect components
        for index_entry, entry in enumerate(connection_set):
            for index_item, item in enumerate(entry):
                designator = list(item.keys())[0]

                if designator in harness.cables:
                    if index_item == 0:
                        # list started with a cable, no connector to join on left side
                        from_name, from_pin = (None, None)
                    else:
                        from_name, from_pin = get_single_key_and_value(
                            entry[index_item - 1]
                        )
                    via_name, via_pin = (designator, item[designator])
                    if index_item == len(entry) - 1:
                        # list ends with a cable, no connector to join on right side
                        to_name, to_pin = (None, None)
                    else:
                        to_name, to_pin = get_single_key_and_value(
                            entry[index_item + 1]
                        )
                    harness.connect(
                        from_name, from_pin, via_name, via_pin, to_name, to_pin
                    )

                elif is_arrow(designator):
                    if index_item == 0:  # list starts with an arrow
                        raise Exception(
                            "An arrow cannot be at the start of a connection set"
                        )
                    elif index_item == len(entry) - 1:  # list ends with an arrow
                        raise Exception(
                            "An arrow cannot be at the end of a connection set"
                        )

                    from_name, from_pin = get_single_key_and_value(
                        entry[index_item - 1]
                    )
                    via_name, via_pin = (designator, None)
                    to_name, to_pin = get_single_key_and_value(entry[index_item + 1])
                    if "-" in designator:  # mate pin by pin
                        harness.add_mate_pin(
                            from_name, from_pin, to_name, to_pin, designator
                        )
                    elif "=" in designator and index_entry == 0:
                        # mate two connectors as a whole
                        harness.add_mate_component(from_name, to_name, designator)

    # Auto-instantiate any declared connector that has loops but was not
    # referenced in a connection set. A connector whose only purpose is to
    # carry loopback wires is still a legitimate part of the harness and
    # must not be silently dropped as an "unused template".
    auto_loop_connectors = []
    used_templates = set(designators_and_templates.values())
    for template_name, attribs in template_connectors.items():
        # already instantiated as a literal designator
        if template_name in harness.connectors:
            continue
        # already used as a template via Template.Designator syntax — its
        # loops are already on each instance and we don't want a phantom
        # floating connector named after the template.
        if template_name in used_templates:
            continue
        if attribs.get("loops"):
            harness.add_connector(name=template_name, **attribs)
            designators_and_templates[template_name] = template_name
            auto_loop_connectors.append(template_name)
    if auto_loop_connectors:
        # stderr, not stdout: stdout may carry the rendered output (-O -)
        sys.stderr.write(
            "Info: auto-instantiating loop-only connector(s) not referenced"
            " in any connection set: " + ", ".join(auto_loop_connectors) + "\n"
        )

    # warn about unused templates

    proposed_components = list(template_connectors.keys()) + list(
        template_cables.keys()
    )
    used_components = set(designators_and_templates.values())
    forgotten_components = [c for c in proposed_components if not c in used_components]
    if len(forgotten_components) > 0:
        sys.stderr.write(
            "Warning: The following components are not referenced in any connection set:\n"
        )
        sys.stderr.write(", ".join(forgotten_components) + "\n")

    # harness population completed =============================================

    for line in yaml_data.get("additional_bom_items") or []:
        harness.add_bom_item(line)

    # Only build the YAML text for the PNG chunk when a PNG is produced.
    wants_png = "png" in (output_formats or ()) or "png" in return_types
    yaml_source_for_png = (
        _yaml_source(inp, yaml_str) if embed_yaml and wants_png else None
    )
    if output_formats:
        if write_to_stdout:
            if len(output_formats) != 1:
                raise ValueError(
                    "Exactly one output format must be specified when writing to stdout."
                )
            harness.output(
                filename=None,
                fmt=output_formats,
                view=False,
                template_dir=template_dir,
                yaml_source=yaml_source_for_png,
            )
        else:
            harness.output(
                filename=output_file,
                fmt=output_formats,
                view=False,
                output_dir=output_dir,
                output_name=output_name,
                template_dir=template_dir,
                yaml_source=yaml_source_for_png,
            )

    if return_types:
        returns = []
        for rt in return_types:
            if rt == "png":
                # Same bytes as file/stdout output, YAML chunk included.
                returns.append(
                    harness._render(("png",), yaml_source=yaml_source_for_png)["png"]
                )
            if rt == "svg":
                returns.append(harness.svg)
            if rt == "harness":
                returns.append(harness)

        return tuple(returns) if len(returns) != 1 else returns[0]


def _reject_tweaks(yaml_data: Dict) -> None:
    """Raise ValueError if untrusted input uses ``tweak``. Tweaks inject
    raw GraphViz source, which cannot be made safe."""
    if yaml_data.get("tweak"):
        raise ValueError("tweak is not allowed for untrusted input")
    for section in ("connectors", "cables"):
        for name, attribs in (yaml_data.get(section) or {}).items():
            if isinstance(attribs, dict) and attribs.get("tweak"):
                raise ValueError(
                    f"{section}.{name}.tweak is not allowed for untrusted input"
                )


def _get_yaml_data_and_path(
    inp: Union[str, Path, Dict],
    untrusted: bool = False,
) -> Tuple[Dict, Optional[Path], Optional[str]]:
    # determine whether inp is a file path, a YAML string, or a Dict
    if untrusted and isinstance(inp, str):
        # Never read a server-side file because the request text happens
        # to name one.
        if len(inp.encode("utf-8")) > UNTRUSTED_MAX_INPUT_BYTES:
            raise ValueError(
                f"Input is larger than the limit of {UNTRUSTED_MAX_INPUT_BYTES} bytes"
            )
        return yaml.safe_load(inp), None, inp
    if isinstance(inp, Path):  # always a file; never fall back to YAML text
        yaml_path = inp.expanduser().resolve(strict=True)
        yaml_str = _read_source(yaml_path)
        return yaml.safe_load(yaml_str), yaml_path, yaml_str
    if not isinstance(inp, Dict):  # received a str
        try:
            yaml_path = Path(inp).expanduser().resolve(strict=True)
        except (FileNotFoundError, OSError, ValueError) as e:
            # if inp is a long YAML string, Pathlib will normally raise
            # FileNotFoundError or OSError(errno = ENAMETOOLONG) when
            # trying to expand and resolve it as a path, but in Windows
            # might ValueError or OSError(errno = EINVAL or None) be raised
            # instead in some cases (depending on the Python version).
            # Catch these specific errors, but raise any others.

            from errno import EINVAL, ENAMETOOLONG

            if type(e) is OSError and e.errno not in (EINVAL, ENAMETOOLONG, None):
                sys.stderr.write(
                    f"OSError(errno={e.errno}) in Python {sys.version} at {platform.platform()}\n"
                )
                raise e
            # file does not exist; assume inp is a YAML string
            yaml_str = inp
            yaml_path = None
        else:
            # The path exists, so it is a file: read errors (not UTF-8,
            # a PNG without WireViz YAML, a directory) are real errors.
            yaml_str = _read_source(yaml_path)
        yaml_data = yaml.safe_load(yaml_str)
    else:
        # received a Dict — deep-copy so the parsing pipeline's in-place
        # changes don't leak back to the caller. The YAML text for PNG
        # embedding is built later, only if a PNG is produced.
        yaml_data = copy.deepcopy(inp)
        yaml_path = None
        yaml_str = None
    return yaml_data, yaml_path, yaml_str


def _read_source(path: Path) -> str:
    """Return the YAML text of ``path``: the file itself, or the YAML
    embedded in a PNG rendered by WireViz."""
    if path.suffix.lower() == ".png":
        from wireviz.Harness import read_yaml_from_png

        embedded = read_yaml_from_png(path)
        if embedded is None:
            raise ValueError(f"{path} has no embedded WireViz YAML")
        return embedded
    return file_read_text(path)


def _yaml_source(inp: Any, yaml_str: Optional[str]) -> Optional[str]:
    """Return the YAML text to embed in a PNG, or None if a dict input
    cannot be represented as YAML (for example, it holds Path objects)."""
    if yaml_str is not None:
        return yaml_str
    try:
        return yaml.safe_dump(inp, sort_keys=False, allow_unicode=True)
    except yaml.YAMLError as exc:
        sys.stderr.write(
            f"Warning: input cannot be stored as YAML in the PNG ({exc}); "
            "the PNG has no embedded source\n"
        )
        return None


def _get_output_dir(input_file: Path, default_output_dir: Path) -> Path:
    if default_output_dir:  # user-specified output directory
        output_dir = Path(default_output_dir)
    else:  # auto-determine appropriate output directory
        if input_file:  # input comes from a file; place output in same directory
            output_dir = input_file.parent
        else:  # input comes from str or Dict; fall back to cwd
            output_dir = Path.cwd()
    return output_dir.resolve()


def _get_output_name(input_file: Path, default_output_name: Path) -> str:
    if default_output_name:  # user-specified output name
        output_name = default_output_name
    else:  # auto-determine appropriate output name
        if input_file:  # input comes from a file; use same file stem
            output_name = input_file.stem
        else:  # input comes from str or Dict; no fallback available
            raise Exception("No output file name provided")
    return output_name


def main():
    sys.stderr.write("When running from the command line, please use wv_cli.py instead.\n")


if __name__ == "__main__":
    main()
