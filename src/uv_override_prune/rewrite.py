"""Pure TOML document manipulation using tomlkit.

These helpers mutate or transform tomlkit documents in memory.
They do not perform file I/O or run any subprocesses.
"""

from collections.abc import MutableMapping
from pathlib import Path
from typing import cast

import tomlkit
from packaging.requirements import Requirement
from tomlkit import TOMLDocument
from tomlkit.items import Array, Table

from .analyze import is_same_requirement


def get_uv_array(doc: TOMLDocument, section_key: str) -> Array:
    """Return the `[tool.uv].<section_key>` array from `doc`."""
    tool = cast(Table, doc["tool"])
    uv = cast(Table, tool["uv"])
    return cast(Array, uv[section_key])


def rewrite_paths(doc: TOMLDocument, original_dir: Path) -> None:
    """Rewrite relative paths to absolutes anchored at `original_dir`.

    Covers: [tool.uv.sources] path deps, [tool.uv.workspace] members,
    [project] readme. Build-backend-specific references (setuptools
    packages.find, hatch build config, etc.) are not rewritten and may
    still cause `uv lock` to fail for projects with [build-system].

    Mutates `doc` in place.
    """
    uv_cfg = _get_table(doc, "tool", "uv")
    if uv_cfg is not None:
        sources = _get_table(uv_cfg, "sources")
        if sources is not None:
            for val in sources.values():
                if isinstance(val, MutableMapping) and "path" in val:
                    _absolutize(val, "path", original_dir)

        workspace = _get_table(uv_cfg, "workspace")
        if workspace is not None and "members" in workspace:
            members = cast(Array, workspace["members"])
            for i, m in enumerate(list(members)):
                p = Path(str(m))
                if not p.is_absolute():
                    members[i] = str((original_dir / p).resolve())

    project = _get_table(doc, "project")
    if project is not None:
        readme = project.get("readme")
        if isinstance(readme, str):
            _absolutize(project, "readme", original_dir)
        elif isinstance(readme, MutableMapping) and "file" in readme:
            _absolutize(readme, "file", original_dir)


def _get_table(
    parent: MutableMapping[str, object],
    *keys: str,
) -> Table | None:
    """Walk into nested tomlkit tables; return None if any key is missing."""
    current: MutableMapping[str, object] = parent
    for key in keys:
        if key not in current:
            return None
        next_val = current[key]
        if not isinstance(next_val, MutableMapping):
            return None
        current = cast(MutableMapping[str, object], next_val)
    return cast(Table, current)


def _absolutize(
    container: MutableMapping[str, object],
    key: str,
    original_dir: Path,
) -> None:
    """Replace `container[key]` with its absolute form, if it's a relative path."""
    value = container[key]
    if not isinstance(value, str):
        return
    p = Path(value)
    if p.is_absolute():
        return
    container[key] = str((original_dir / p).resolve())


def remove_entries(
    doc: TOMLDocument,
    by_section: dict[str, list[str]],
) -> None:
    """Remove the given entries from `doc`'s override/constraint arrays.

    Mutates `doc` in place. Comments and formatting on untouched lines
    are preserved by tomlkit.
    """
    for section_key, entries in by_section.items():
        arr = get_uv_array(doc, section_key)
        for entry in entries:
            arr.remove(entry)


def prepare_modified_text(
    original_text: str,
    section_key: str,
    entry: str,
    original_dir: Path,
) -> str:
    """Produce pyproject.toml text with `entry` removed and paths absolutised.

    Every element equal to `entry` as a Requirement is removed, not just
    the first: a duplicated entry must leave no copy behind, or the
    remaining copy would keep the bound in force and the natural
    resolution would look as if the entry were redundant.

    Pure transformation: parse, mutate in memory, serialise back.
    """
    doc = tomlkit.parse(original_text)
    arr = get_uv_array(doc, section_key)
    req = Requirement(entry)
    for item in list(arr):
        if is_same_requirement(str(item), req):
            arr.remove(item)
    rewrite_paths(doc, original_dir)
    return tomlkit.dumps(doc)
