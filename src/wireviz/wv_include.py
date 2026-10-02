# -*- coding: utf-8 -*-
"""Top-level ``include:`` of shared connector/cable libraries (upstream #220).

Each included file is parsed on its own and merged into the including
file at dict level:

- ``connectors`` and ``cables`` are merged by key. The including file
  wins over its includes; the same key in two included files is an
  error that names both files.
- ``additional_bom_items`` are appended.
- ``metadata``, ``options``, ``tweak`` and ``connections`` belong to the
  main file only; in an included file they are an error.
- A relative ``image.src`` in an included file is made absolute against
  that file's directory.
- Includes nest. A cycle, or nesting deeper than ``MAX_INCLUDE_DEPTH``,
  is an error.

YAML anchors and ``<<:`` do not cross files.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

from wireviz.wv_helper import file_read_text, yaml_load

MAX_INCLUDE_DEPTH = 16
MERGED_SECTIONS = ("connectors", "cables")
MAIN_ONLY_SECTIONS = ("metadata", "options", "tweak", "connections")


def resolve_includes(
    yaml_data: Dict,
    base_dir: Path,
    include_paths: Sequence[Union[str, Path]] = (),
    _stack: Optional[List[Path]] = None,
) -> Dict[tuple, Path]:
    """Merge the files named in ``yaml_data["include"]`` into ``yaml_data``
    (in place). Return {(section, key): file that defines it} for every
    merged entry, so the caller can tell a real conflict from the same
    file reached twice (a "diamond": a.yml and b.yml both include
    common.yml)."""
    stack = _stack or []
    includes = yaml_data.pop("include", None)
    if includes is None:
        return {}
    if isinstance(includes, str):
        includes = [includes]
    if not isinstance(includes, list) or not all(isinstance(i, str) for i in includes):
        raise TypeError("include must be a file name or a list of file names")
    if len(stack) >= MAX_INCLUDE_DEPTH:
        raise ValueError(
            f"include: nesting is deeper than {MAX_INCLUDE_DEPTH} levels ({stack[-1]})"
        )

    seen_files = set()
    main_keys = {
        section: set(yaml_data.get(section) or {}) for section in MERGED_SECTIONS
    }
    origin: Dict[tuple, Path] = {}  # (section, key) -> defining file
    for name in includes:
        path = _find(name, base_dir, include_paths)
        real = path.resolve()
        if real in stack:
            chain = " -> ".join(str(p) for p in [*stack, real])
            raise ValueError(f"include: cycle {chain}")
        try:
            text = file_read_text(path)
        except UnicodeDecodeError as exc:
            raise ValueError(f"include {path}: not a UTF-8 YAML file") from exc
        data = yaml_load(text)
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise TypeError(f"include {path}: expected a mapping at the top level")
        for section in MAIN_ONLY_SECTIONS:
            if section in data:
                raise ValueError(
                    f"include {path}: {section} is allowed only in the main file"
                )
        nested = resolve_includes(data, path.parent, include_paths, [*stack, real])
        _absolute_images(data, path.parent)

        for section in MERGED_SECTIONS:
            entries = data.get(section) or {}
            if not isinstance(entries, dict):
                raise TypeError(f"include {path}: {section} must be a mapping")
            target = yaml_data.get(section)
            if not isinstance(target, dict):
                target = yaml_data[section] = {}
            for key, attribs in entries.items():
                if key in main_keys[section]:
                    continue  # the including file wins
                defined_in = nested.get((section, key), real)
                if (section, key) in origin:
                    if origin[(section, key)] == defined_in:
                        continue  # the same file reached twice
                    raise ValueError(
                        f"include: {section}.{key} is defined in both "
                        f"{origin[(section, key)]} and {defined_in}"
                    )
                origin[(section, key)] = defined_in
                target[key] = attribs
        extra = data.get("additional_bom_items") or []
        if real in seen_files:
            extra = []  # a file reached twice adds its BOM items once
        seen_files.add(real)
        if extra:
            yaml_data["additional_bom_items"] = list(
                yaml_data.get("additional_bom_items") or []
            ) + list(extra)
    return origin


def _find(name: str, base_dir: Path, include_paths) -> Path:
    candidate = Path(name).expanduser()
    if candidate.is_absolute():
        roots = [candidate]
    else:
        roots = [Path(base_dir) / candidate] + [
            Path(p) / candidate for p in include_paths
        ]
    for path in roots:
        if path.is_file():
            # absolute, but not resolved: relative paths inside a symlinked
            # file stay relative to the link's directory
            return Path(os.path.abspath(path))
    searched = "\n".join(str(p) for p in roots)
    raise FileNotFoundError(f"include {name} was not found. Searched:\n{searched}")


def _absolute_images(data: Dict, base_dir: Path) -> None:
    """Make relative image paths of an included file absolute, so they
    resolve against the included file and not the main file."""
    for section in MERGED_SECTIONS:
        for key, attribs in list((data.get(section) or {}).items()):
            if not isinstance(attribs, dict):
                continue
            image = attribs.get("image")
            src = (
                image
                if isinstance(image, str)
                else (image.get("src") if isinstance(image, dict) else None)
            )
            if (
                not isinstance(src, str)
                or src[:5].lower() == "data:"
                or Path(src).is_absolute()
            ):
                continue
            resolved = str((base_dir / src).resolve())
            data[section][key] = {
                **attribs,
                "image": (
                    resolved if isinstance(image, str) else {**image, "src": resolved}
                ),
            }
