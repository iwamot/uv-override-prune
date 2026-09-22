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


def classify(req: Requirement, resolved: Sequence[Version]) -> Result:
    """Decide redundant/needed status given a Requirement and resolved Versions.

    `resolved` is empty when the package is not present in the resolution
    (i.e. nothing depends on it, so the override was vacuous). It holds
    several versions when uv forked the resolution on environment markers
    and locked a different version per fork; the entry is redundant only
    if every fork satisfies it, and the value lists the versions that
    decided the verdict.
    """
    if not resolved:
        return Result(status="prune", value="(unused)")
    unsatisfied = [
        v for v in resolved if not req.specifier.contains(str(v), prereleases=True)
    ]
    if unsatisfied:
        return Result(status="keep", value=_join_versions(unsatisfied))
    return Result(status="prune", value=_join_versions(resolved))


def _join_versions(versions: Sequence[Version]) -> str:
    return ", ".join(str(v) for v in sorted(set(versions)))


def find_resolved_versions(
    lock_doc: Mapping[str, object],
    pkg: str,
) -> list[Version]:
    """Find every resolved version of `pkg` in a parsed uv.lock document.

    A package appears once per fork it was resolved differently in, so
    the list has one entry per `[[package]]` table with that name, in
    lock order. `lock_doc` may be a plain dict or a tomlkit TOMLDocument;
    only the Mapping protocol is used. Package names are normalised per
    PEP 503.
    """
    target = canonicalize_name(pkg)
    packages = lock_doc.get("package")
    if not isinstance(packages, list):
        return []
    found: list[Version] = []
    for raw_entry in packages:
        if not isinstance(raw_entry, Mapping):
            continue
        entry = cast(Mapping[str, object], raw_entry)
        if canonicalize_name(str(entry.get("name", ""))) == target:
            found.append(Version(str(entry.get("version", ""))))
    return found
