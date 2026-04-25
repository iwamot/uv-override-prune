"""Pure analysis: requirement parsing, classification, version lookup.

These functions operate on in-memory data structures (Requirement, Version,
parsed TOML documents) and have no dependency on file I/O or subprocesses.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


@dataclass(frozen=True)
class Result:
    """The classification verdict for a single override/constraint entry."""

    status: str  # "prune" | "keep" | "skip" | "error"
    detail: str  # long-form explanation
    value: str  # short value: resolved version, "(unused)", "-", or error tag


def is_pure_lower_bound(req: Requirement) -> bool:
    """True if the specifier uses only '>=' and/or '>' operators."""
    ops = {spec.operator for spec in req.specifier}
    return bool(ops) and ops <= {">=", ">"}


def classify(req: Requirement, resolved: Version | None) -> Result:
    """Decide redundant/needed status given a Requirement and resolved Version.

    `resolved` is None when the package is not present in the resolution
    (i.e. nothing depends on it, so the override was vacuous).
    """
    if resolved is None:
        return Result(
            status="prune",
            detail=f"{req.name} not required by any dep (constraint was vacuous)",
            value="(unused)",
        )
    if req.specifier.contains(str(resolved), prereleases=True):
        return Result(
            status="prune",
            detail=f"natural resolution {resolved} satisfies {req.specifier}",
            value=str(resolved),
        )
    return Result(
        status="keep",
        detail=f"natural resolution would be {resolved} (violates {req.specifier})",
        value=str(resolved),
    )


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
