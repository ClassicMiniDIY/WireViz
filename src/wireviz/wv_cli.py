# -*- coding: utf-8 -*-

import os
import sys
from pathlib import Path

import click

if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wireviz.wireviz as wv
from wireviz import APP_NAME, __version__
from wireviz.Harness import read_yaml_from_png
from wireviz.wv_helper import file_read_text

format_codes = {
    # "c": "csv",
    "g": "gv",
    "h": "html",
    "p": "png",
    "P": "pdf",
    "s": "svg",
    "t": "tsv",
}

epilog = "The -f or --format option accepts a string containing one or more of the "
epilog += "following characters to specify which file types to output:\n"
epilog += ", ".join([f"{key} ({value.upper()})" for key, value in format_codes.items()])


@click.command(
    epilog=epilog,
    no_args_is_help=True,
    context_settings=dict(help_option_names=["-h", "--help"]),
)
@click.argument("file", nargs=-1)
@click.option(
    "-f",
    "--format",
    default="hpst",
    type=str,
    show_default=True,
    help="Output formats (see below).",
)
@click.option(
    "-p",
    "--prepend",
    default=[],
    multiple=True,
    type=Path,
    help="YAML file to prepend to the input file (optional).",
)
@click.option(
    "-o",
    "--output-dir",
    default=None,
    type=Path,
    help="Directory to use for output files, if different from input file directory.",
)
@click.option(
    "-O",
    "--output-name",
    default=None,
    type=str,
    help="File name (without extension) to use for output files, if different from input file name.",
)
@click.option(
    "-t",
    "--template-dir",
    default=None,
    type=Path,
    help="Directory searched first when resolving a metadata.template.name reference.",
)
@click.option(
    "--no-embed-yaml",
    "embed_yaml",
    flag_value=False,
    default=True,
    help="Do not embed the source YAML in PNG output as an iTXt chunk.",
)
@click.option(
    "-V",
    "--version",
    is_flag=True,
    default=False,
    help=f"Output {APP_NAME} version and exit.",
)
def wireviz(
    file, format, prepend, output_dir, output_name, template_dir, embed_yaml, version
):
    """
    Parses the provided FILE and generates the specified outputs.

    Pass FILE as ``-`` to read YAML from stdin, and pass ``-`` to either
    --output-dir or --output-name to write a single rendered format to
    stdout (e.g. ``cat harness.yml | wireviz -f s -O - -``).
    """
    sys.stderr.write(f"\n{APP_NAME} {__version__}\n")
    if version:
        return  # print version number only and exit

    # get list of files
    try:
        _ = iter(file)
    except TypeError:
        filepaths = [file]
    else:
        filepaths = list(file)

    # determine output formats (preserve user-given order, dedup)
    output_formats = []
    for code in format:
        if code in format_codes:
            fmt = format_codes[code]
            if fmt not in output_formats:
                output_formats.append(fmt)
        else:
            raise click.UsageError(f"Unknown output format: {code}")
    output_formats = tuple(output_formats)
    output_formats_str = (
        f'[{"|".join(output_formats)}]'
        if len(output_formats) > 1
        else output_formats[0]
    )

    write_to_stdout = str(output_dir) == "-" or str(output_name) == "-"
    if write_to_stdout and len(output_formats) != 1:
        raise click.UsageError(
            "Exactly one output format (-f) must be specified when writing to stdout."
        )

    # check prepend file
    if len(prepend) > 0:
        prepend_input = ""
        for prepend_file in prepend:
            prepend_file = Path(prepend_file)
            if not prepend_file.exists():
                raise click.UsageError(
                    f"Prepend file does not exist: {prepend_file}"
                )
            sys.stderr.write(f"Prepend file: {prepend_file}\n")

            prepend_input += file_read_text(prepend_file) + "\n"
    else:
        prepend_input = ""

    # run WireViz on each input file (or once on stdin)
    if not filepaths:
        filepaths = ["-"]

    for file in filepaths:
        if str(file) == "-":
            yaml_input = prepend_input + sys.stdin.read()
            # No source-file directory available, so any relative
            # `image: src:` paths in the stdin YAML are resolved against
            # the current working directory (matching how a typical
            # piped invocation would be run from a project root).
            image_paths = {Path.cwd()}
            sys.stderr.write("Input:        <stdin>\n")
            _output_dir = output_dir if output_dir else "-"
            _output_name = output_name if output_name else "stdin"
        else:
            file = Path(file)
            if not file.exists():
                raise click.UsageError(f"Input file does not exist: {file}")

            if file.suffix.lower() == ".png":
                # PNG input: try to recover the YAML embedded by an
                # earlier WireViz render. Catch PIL's UnidentifiedImageError
                # (and anything else PIL throws for corrupt files) so the
                # user sees a clean message instead of a stack trace.
                try:
                    embedded = read_yaml_from_png(file)
                except Exception as exc:
                    raise click.UsageError(
                        f"Could not read PNG {file}: {exc}"
                    ) from exc
                if embedded is None:
                    raise click.UsageError(
                        f"{file} has no embedded WireViz YAML (no "
                        f"'wireviz:yaml' iTXt chunk found)."
                    )
                yaml_input = prepend_input + embedded
                sys.stderr.write(f"Input file:   {file} (extracted YAML)\n")
            else:
                yaml_input = prepend_input + file_read_text(file)
                sys.stderr.write(f"Input file:   {file}\n")
            image_paths = {file.parent}
            _output_dir = output_dir if output_dir else file.parent
            _output_name = output_name if output_name else file.stem

        for p in prepend:
            image_paths.add(Path(p).parent)

        if write_to_stdout:
            sys.stderr.write(f"Output:       <stdout>.{output_formats_str}\n")
        else:
            sys.stderr.write(
                f"Output file:  {Path(_output_dir) / _output_name}.{output_formats_str}\n"
            )

        wv.parse(
            yaml_input,
            output_formats=output_formats,
            output_dir=_output_dir,
            output_name=_output_name,
            image_paths=list(image_paths),
            source_path=file,
            template_dir=template_dir,
            embed_yaml=embed_yaml,
        )

    sys.stderr.write("\n")


if __name__ == "__main__":
    wireviz()
