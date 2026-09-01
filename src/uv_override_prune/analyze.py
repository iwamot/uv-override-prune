"""Pure analysis: requirement parsing, classification, version lookup.

These functions operate on in-memory data structures (Requirement, Version,
parsed TOML documents) and have no dependency on file I/O or subprocesses.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


@dataclass(frozen=True)
class Result:
    """The classification verdict for a single override/constraint entry."""

    status: str  # "prune" | "keep" | "skip" | "error"
    value: str  # resolved version, "(unused)", "(non-lower-bound)", or error tag


def is_pure_lower_bound(req: Requirement) -> bool:
    """True if the specifier uses only '>=' and/or '>' operators."""
    ops = {spec.operator for spec in req.specifier}
    return bool(ops) and ops <= {">=", ">"}


def is_same_requirement(raw: str, req: Requirement) -> bool:
    """True if `raw` parses to a Requirement equal to `req`.

    packaging's equality normalises the name and canonicalises versions,
    so `Click >= 8.0.0` matches `click>=8.0`. Unparsable text matches
    nothing.
    """
    try:
        return Requirement(raw) == req
    except InvalidRequirement:
        return False


def duplicate_indexes(entries: Sequence[str]) -> frozenset[int]:
    """Indexes of entries that restate an earlier entry in the same list.

    A later copy is always prunable: the first occurrence carries the
    bound, and its own verdict is computed with every copy removed, so
    the copies never shadow each other. Unparsable entries never match
    anything.
    """
    seen: set[Requirement] = set()
    out: set[int] = set()
    for i, raw in enumerate(entries):
        try:
            req = Requirement(raw)
        except InvalidRequirement:
            continue
        if req in seen:
            out.add(i)
        seen.add(req)
    return frozenset(out)


def classify(req: Requirement, resolved: Version | None) -> Result:
    """Decide redundant/needed status given a Requirement and resolved Version.

    `resolved` is None when the package is not present in the resolution
    (i.e. nothing depends on it, so the override was vacuous).
    """
    if resolved is None:
        return Result(status="prune", value="(unused)")
    if req.specifier.contains(str(resolved), prereleases=True):
        return Result(status="prune", value=str(resolved))
    return Result(status="keep", value=str(resolved))


def find_resolved_version(
    lock_doc: Mapping[str, object],
    pkg: str,
) -> Version | None:
    """Find the resolved version of `pkg` in a parsed uv.lock document.

    `lock_doc` may be a plain dict or a tomlkit TOMLDocument; only the
    Mapping protocol is used. Package names are normalised per PEP 503.
    """
    target = canonicalize_name(pkg)
    packages = lock_doc.get("package")
    if not isinstance(packages, list):
        return None
    for raw_entry in packages:
        if not isinstance(raw_entry, Mapping):
            continue
        entry = cast(Mapping[str, object], raw_entry)
        if canonicalize_name(str(entry.get("name", ""))) == target:
            return Version(str(entry.get("version", "")))
    return None
