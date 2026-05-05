# Change Log

## [0.5.0] (2026-05-05)

First release of the [ClassicMiniDIY/WireViz](https://github.com/ClassicMiniDIY/WireViz) fork. Pulls in seven open upstream PRs that had been sitting unmerged for years, lays an automated test suite, and fixes a handful of bugs surfaced along the way.

### New features

- **stdin/stdout streaming** ([upstream #321](https://github.com/wireviz/WireViz/pull/321)). Pass `-` as the input filename to read YAML from stdin, and pass `-` to either `--output-dir` or `--output-name` to write a single rendered format to stdout. Enables `cat harness.yml | wireviz -f s -O - - > harness.svg`-style pipelines.
- **YAML embedded in PNG** ([upstream #234](https://github.com/wireviz/WireViz/pull/234)). PNG outputs now carry the source YAML in a `wireviz:yaml` iTXt chunk by default. The CLI auto-detects `.png` inputs and pulls the YAML back out — a single PNG is enough to re-render or edit a harness. Opt out with `--no-embed-yaml`.
- **PDF output** ([upstream #367](https://github.com/wireviz/WireViz/pull/367)). The previously-stubbed `pdf` format is now wired to graphviz's PDF renderer. Use `-f P`.
- **Custom template directory** ([upstream #444](https://github.com/wireviz/WireViz/pull/444)). New `-t` / `--template-dir` flag and `parse(template_dir=...)` parameter point at an explicit directory of HTML templates. Search order: `template_dir` → YAML source dir → output dir → built-in templates.
- **`output_dpi` option** ([upstream #379](https://github.com/wireviz/WireViz/pull/379)). YAML `options.output_dpi` controls the graphviz `dpi` graph attribute. Default 96.0 (matches graphviz's own default for non-PostScript renderers); `null` omits the attribute entirely.
- **Per-connector / per-cable tweak with placeholder** ([upstream #357](https://github.com/wireviz/WireViz/pull/357)). Connectors and cables can now carry their own `tweak:` block with the same `override` / `append` shape as the global one, and a placeholder substring rewritten to the node's actual designator at instantiation. Lets users author one tweak template and apply it to many components.
- **`<!-- %revision% -->` HTML template placeholder** ([upstream #492](https://github.com/wireviz/WireViz/pull/492)). Resolves to the most recently declared entry in `metadata.revisions`.

### Bug fixes (upstream PRs incorporated)

- Loopback rendering: loop-only connectors silently dropped, all loops forced onto a single side, loop edge ports referenced pin numbers instead of pin positions ([upstream #496](https://github.com/wireviz/WireViz/pull/496)).
- Hex RGB color codes mis-detected as multi-color stripes, padding single-color wires to 3× thickness ([upstream #495](https://github.com/wireviz/WireViz/pull/495)).
- Custom HTML templates not resolvable against the YAML source directory ([upstream #473](https://github.com/wireviz/WireViz/pull/473)).
- SVG images embedded as base64 data URIs used the wrong MIME type (`image/svg` instead of `image/svg+xml`) ([upstream #443](https://github.com/wireviz/WireViz/pull/443)).

### Bug fixes (additional, surfaced by code review or the new test suite)

- Loop-only connector templates used via `Template.Designator` syntax (`DSub.X1`) no longer get an additional phantom floating instance.
- `parse()` no longer mutates dict inputs in place during connection-set expansion (load-bearing for programmatic callers).
- `re.sub(..., 1)` migrated to `re.sub(..., count=1)` for Python 3.13+ compatibility.
- CLI errors (missing input file, missing prepend file, unknown `-f` code, multi-format-to-stdout, corrupt PNG input) now raise `click.UsageError` instead of generic `Exception`, so users see clean error messages instead of Python tracebacks.
- Data URIs no longer have a leading space after `;base64,` (RFC 2397 compliance).
- `_latest_revision` handles scalar `revisions:` values (string/int/float) without truncation; previously `revisions: v1.0` returned `'0'`.
- Per-connector `tweak.override` with a `null` value no longer crashes the placeholder-substitution lambda.
- `_extend_tweak` keeps empty override dicts rather than collapsing to `None`, which previously caused `Harness.create_graph()` to choke.
- `output_dpi: null` correctly omits the dpi graph attribute (instead of emitting the literal string `"None"`).
- The `wireviz:yaml` chunk embedding preserves existing PNG metadata (DPI, color profile, prior text chunks) instead of stripping them on re-encode.
- Tweak override conflict errors now include both the existing and new value.
- `parse()` `source_path` auto-fills from a `Path` input as the docstring promised.

### Internal

- New `wireviz.parse()` signature additions: `source_path`, `template_dir`, `embed_yaml`. Existing callers are backward-compatible.
- New `Harness._render(fmt, ...)` method returning an in-memory `{format: bytes|str}` dict, used by both `Harness.output()` (file mode) and the stdin/stdout dispatch path.
- New module-level helpers: `Harness.PNG_YAML_CHUNK_KEY`, `Harness.read_yaml_from_png()`.
- New `Harness.output()` and `Harness._render()` accept `fmt` as `Union[str, Tuple[str, ...], List[str]]`; bare strings are normalized to one-tuples.

### Testing

- New automated pytest suite (134 tests across nine files): smoke, parse, CLI, harness, dataclasses, colors, BOM, regressions, round-trip. Runs in ~5 seconds.
- New `Tests` GitHub Actions workflow runs pytest across Python 3.7–3.12 in parallel with the existing `Create Examples` workflow.

### Notes for upstream divergence

Adapted to current upstream `master` even when source PRs targeted `dev` (which carries an unreleased "big refactor" we deliberately did not pull). All commits cite their upstream origin in the body, so a future merge back upstream is feasible.


## [0.4.1] (2024-07-13)

### Improvements to help reported issues

- Print Python & OS versions when raising unexpected OSError related to #346 & #392 (bugfixes below)
- Explain unexpeced top-level type ([#342](https://github.com/wireviz/WireViz/issues/342), [#383](https://github.com/wireviz/WireViz/pull/383))
- Add non-empty label to reduce over-sized loops ([#286](https://github.com/wireviz/WireViz/issues/286), [#381](https://github.com/wireviz/WireViz/pull/381))
- Improve placeholder name consistency ([#377](https://github.com/wireviz/WireViz/issues/377), [#380](https://github.com/wireviz/WireViz/pull/380))
- Add work-around for Graphviz SVG bug ([#175](https://github.com/wireviz/WireViz/issues/175), [#371](https://github.com/wireviz/WireViz/pull/371))

### Bugfixes

- Avoid ResourceWarning: unclosed file ([#309 (comment)](https://github.com/wireviz/WireViz/pull/309#issuecomment-2170988381), [#395](https://github.com/wireviz/WireViz/pull/395))
- Catch ValueError and OSError(errno=None) ([#318 (review)](https://github.com/wireviz/WireViz/pull/318#pullrequestreview-1457016602), [#391](https://github.com/wireviz/WireViz/issues/391), [#392](https://github.com/wireviz/WireViz/pull/392))
- Add minor missing doc entry ([#186 (comment)](https://github.com/wireviz/WireViz/pull/186#issuecomment-2139037434), [#186 (comment)](https://github.com/wireviz/WireViz/pull/186#issuecomment-2155032522))
- Avoid Graphviz error when hiding all pins ([#257](https://github.com/wireviz/WireViz/issues/257), [#375](https://github.com/wireviz/WireViz/pull/375))
- Avoid decimal point and trailing zero for integer BOM quantities ([#340](https://github.com/wireviz/WireViz/issues/340), [#374](https://github.com/wireviz/WireViz/pull/374))
- Update project URL references ([#316 (comment)](https://github.com/wireviz/WireViz/issues/316#issuecomment-1568748914), [#364](https://github.com/wireviz/WireViz/pull/364))
- Add missing import of embed_svg_images ([#363](https://github.com/wireviz/WireViz/pull/363))
- Use correct default title ([#360](https://github.com/wireviz/WireViz/issues/360), [#361](https://github.com/wireviz/WireViz/pull/361))
- Fix bugs in mate processing ([#355](https://github.com/wireviz/WireViz/issues/355), [#358](https://github.com/wireviz/WireViz/pull/358))
- Include missing files in published package ([#345](https://github.com/wireviz/WireViz/issues/345), [#347](https://github.com/wireviz/WireViz/pull/347)) 
- Catch OSError(errno=EINVAL) ([#344](https://github.com/wireviz/WireViz/issues/344), [#346](https://github.com/wireviz/WireViz/pull/346))


## [0.4](https://github.com/wireviz/WireViz/tree/v0.4) (2024-05-12)

### Backward-incompatible changes
- New syntax for autogenerated components ([#184](https://github.com/wireviz/WireViz/issues/184), [#186](https://github.com/wireviz/WireViz/pull/186))
  - Components that are not referenced in any connection set will not be rendered. Instead, a warning will be output in the console. ([#328](https://github.com/wireviz/WireViz/issues/328), [#332](https://github.com/wireviz/WireViz/pull/332))
- New command line interface ([#244](https://github.com/wireviz/WireViz/pull/244)). Run `wireviz --help` for details 
  - The path specified with the `-o`/`--output-dir` option no longer includes the filename (without extension) of the generated files. Use the `-O`/`--output-name` option to specify a different filename for the generated files.
- The `.gv` file is no longer included as a default output format (only as an intermediate file during processing) unless specified with the new `-f` option described below.

### New features

- Allow mates between connectors ([#134](https://github.com/wireviz/WireViz/issues/134), [#186](https://github.com/wireviz/WireViz/pull/186))
- Improve technical drawing output ([#74](https://github.com/wireviz/WireViz/pull/74), [#32](https://github.com/wireviz/WireViz/issues/32), [#239](https://github.com/wireviz/WireViz/pull/239))
- Embed images in SVG output ([#189](https://github.com/wireviz/WireViz/pull/189))
- Add ability to choose output formats using the `-f`/`--format` command line option ([#60](https://github.com/wireviz/WireViz/issues/60))
- Add option to multiply additional component quantity by number of unpopulated positions on connector ([#298](https://github.com/wireviz/WireViz/pull/298))

### Misc. fixes
- Use `isort` and `black` for cleaner code and easier merging ([#248](https://github.com/wireviz/WireViz/pull/248))
- Code improvements ([#246](https://github.com/wireviz/WireViz/pull/246), [#250](https://github.com/wireviz/WireViz/pull/250))
- Bug fixes ([#264](https://github.com/wireviz/WireViz/pull/264), [#318](https://github.com/wireviz/WireViz/pull/318))
- Minor adjustments ([#256](https://github.com/wireviz/WireViz/pull/256))


## [0.3.2](https://github.com/wireviz/WireViz/tree/v0.3.2) (2021-11-27)

### Hotfix

- Adjust GraphViz generation code for compatibility with v0.18 of the `graphviz` Python package ([#258](https://github.com/wireviz/WireViz/issues/258), [#261](https://github.com/wireviz/WireViz/pull/261))


## [0.3.1](https://github.com/wireviz/WireViz/tree/v0.3.1) (2021-10-25)

### Hotfix

- Assign generic harness title when using WireViz as a module and not specifying an output file name ([#253](https://github.com/wireviz/WireViz/issues/253), [#254](https://github.com/wireviz/WireViz/pull/254))


## [0.3](https://github.com/wireviz/WireViz/tree/v0.3) (2021-10-11)

### New features

- Allow referencing a cable's/bundle's wires by color or by label ([#70](https://github.com/wireviz/WireViz/issues/70), [#169](https://github.com/wireviz/WireViz/issues/169), [#193](https://github.com/wireviz/WireViz/issues/193), [#194](https://github.com/wireviz/WireViz/pull/194))
- Allow additional BOM items within components ([#50](https://github.com/wireviz/WireViz/issues/50), [#115](https://github.com/wireviz/WireViz/pull/115))
- Add support for length units in cables and wires ([#7](https://github.com/wireviz/WireViz/issues/7), [#196](https://github.com/wireviz/WireViz/pull/196) (with work from [#161](https://github.com/wireviz/WireViz/pull/161), [#162](https://github.com/wireviz/WireViz/pull/162), [#171](https://github.com/wireviz/WireViz/pull/171)), [#198](https://github.com/wireviz/WireViz/pull/198), [#205](https://github.com/wireviz/WireViz/issues/205). [#206](https://github.com/wireviz/WireViz/pull/206))
- Add option to define connector pin colors ([#53](https://github.com/wireviz/WireViz/issues/53), [#141](https://github.com/wireviz/WireViz/pull/141))
- Remove HTML links from the input attributes ([#164](https://github.com/wireviz/WireViz/pull/164))
- Add harness metadata section ([#158](https://github.com/wireviz/WireViz/issues/158), [#214](https://github.com/wireviz/WireViz/pull/214))
- Add support for supplier and supplier part number information ([#240](https://github.com/wireviz/WireViz/issues/240), [#241](https://github.com/wireviz/WireViz/pull/241/))
- Add graph rendering options (background colors, fontname, color name display style, ...) ([#158](https://github.com/wireviz/WireViz/issues/158), [#214](https://github.com/wireviz/WireViz/pull/214))
- Add support for background colors for cables and connectors, as well as for some individual cells ([#210](https://github.com/wireviz/WireViz/issues/210), [#219](https://github.com/wireviz/WireViz/pull/219))
- Add optional tweaking of the .gv output ([#215](https://github.com/wireviz/WireViz/pull/215)) (experimental)

### Misc. fixes

- Remove case-sensitivity issues with pin names and labels ([#160](https://github.com/wireviz/WireViz/issues/160), [#229](https://github.com/wireviz/WireViz/pull/229))
- Improve type hinting ([#156](https://github.com/wireviz/WireViz/issues/156), [#163](https://github.com/wireviz/WireViz/pull/163))
- Move BOM management and HTML functions to separate modules ([#151](https://github.com/wireviz/WireViz/issues/151), [#192](https://github.com/wireviz/WireViz/pull/192))
- Simplify BOM code ([#197](https://github.com/wireviz/WireViz/pull/197))
- Bug fixes ([#218](https://github.com/wireviz/WireViz/pull/218), [#221](https://github.com/wireviz/WireViz/pull/221))

### Known issues

- Including images in the harness may lead to issues in the following cases: ([#189](https://github.com/wireviz/WireViz/pull/189), [#220](https://github.com/wireviz/WireViz/issues/220))
  - When using the `-o`/`--output_file` CLI option, specifying an output path in a different directory from the input file
  - When using the `--prepend-file` CLI option, specifying a prepend file in a different directory from the mail input file


## [0.2](https://github.com/wireviz/WireViz/tree/v0.2) (2020-10-17)

### Backward incompatible changes

- Change names of connector attributes ([#77](https://github.com/wireviz/WireViz/issues/77), [#105](https://github.com/wireviz/WireViz/pull/105))
  - `pinnumbers` is now `pins`
  - `pinout` is now `pinlabels`
- Remove ferrules as a separate connector type ([#78](https://github.com/wireviz/WireViz/issues/78), [#102](https://github.com/wireviz/WireViz/pull/102))
  - Simple connectors like ferrules are now defined using the `style: simple` attribute
- Change the way loops are defined ([#79](https://github.com/wireviz/WireViz/issues/79), [#75](https://github.com/wireviz/WireViz/pull/75))
  - Wires looping between two pins of the same connector are now handled via the connector's `loops` attribute.

See the [syntax description](syntax.md) for details.

### New features

- Add bidirectional AWG/mm2 conversion ([#40](https://github.com/wireviz/WireViz/issues/40), [#41](https://github.com/wireviz/WireViz/pull/41))
- Add support for part numbers ([#11](https://github.com/wireviz/WireViz/pull/11), [#114](https://github.com/wireviz/WireViz/issues/114), [#121](https://github.com/wireviz/WireViz/pull/121))
- Add support for multicolored wires ([#12](https://github.com/wireviz/WireViz/issues/12), [#17](https://github.com/wireviz/WireViz/pull/17), [#96](https://github.com/wireviz/WireViz/pull/96), [#131](https://github.com/wireviz/WireViz/issues/131), [#132](https://github.com/wireviz/WireViz/pull/132))
- Add support for images ([#27](https://github.com/wireviz/WireViz/issues/27), [#153](https://github.com/wireviz/WireViz/pull/153))
- Add ability to export data directly to other programs ([#55](https://github.com/wireviz/WireViz/pull/55))
- Add support for line breaks in various fields ([#49](https://github.com/wireviz/WireViz/issues/49), [#64](https://github.com/wireviz/WireViz/pull/64))
- Allow using connector pin names to define connections ([#72](https://github.com/wireviz/WireViz/issues/72), [#139](https://github.com/wireviz/WireViz/issues/139), [#140](https://github.com/wireviz/WireViz/pull/140))
- Make defining connection sets easier and more flexible ([#67](https://github.com/wireviz/WireViz/issues/67), [#75](https://github.com/wireviz/WireViz/pull/75))
- Add new command line options ([#167](https://github.com/wireviz/WireViz/issues/167), [#173](https://github.com/wireviz/WireViz/pull/173))
- Add new features to `build_examples.py` ([#118](https://github.com/wireviz/WireViz/pull/118))
- Add new colors ([#103](https://github.com/wireviz/WireViz/pull/103), [#113](https://github.com/wireviz/WireViz/pull/113), [#144](https://github.com/wireviz/WireViz/issues/144), [#145](https://github.com/wireviz/WireViz/pull/145))
- Improve documentation ([#107](https://github.com/wireviz/WireViz/issues/107), [#111](https://github.com/wireviz/WireViz/pull/111))

### Misc. fixes

- Improve BOM generation
- Add various input sanity checks
- Improve HTML output ([#66](https://github.com/wireviz/WireViz/issues/66), [#136](https://github.com/wireviz/WireViz/pull/136), [#95](https://github.com/wireviz/WireViz/pull/95), [#177](https://github.com/wireviz/WireViz/pull/177))
- Fix node rendering bug ([#69](https://github.com/wireviz/WireViz/issues/69), [#104](https://github.com/wireviz/WireViz/pull/104))
- Improve shield rendering ([#125](https://github.com/wireviz/WireViz/issues/125), [#126](https://github.com/wireviz/WireViz/pull/126))
- Add GitHub Linguist overrides ([#146](https://github.com/wireviz/WireViz/issues/146), [#154](https://github.com/wireviz/WireViz/pull/154))


## [0.1](https://github.com/wireviz/WireViz/tree/v0.1) (2020-06-29)

- Initial release
