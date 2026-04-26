"""High-level orchestration: audit() and apply_fix().

Wires the pure logic in `analyze` and `rewrite` to actual file I/O
and the `uv lock` subprocess for the CLI.
"""

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import tomlkit
from packaging.requirements import Requirement

from .analyze import (
    Result,
    classify,
    find_resolved_version,
    is_pure_lower_bound,
)
from .rewrite import get_uv_array, prepare_modified_text, remove_entries

FIELDS = ("override-dependencies", "constraint-dependencies")


@dataclass(frozen=True)
class EntryResult:
    """The audit outcome for a single override/constraint entry."""

    section: str  # "override-dependencies" | "constraint-dependencies"
    entry: str
    result: Result

    @property
    def status(self) -> str:
        return self.result.status


@dataclass(frozen=True)
class AuditReport:
    """The audit outcome for a whole pyproject.toml.

    Immutable: `entries` is a tuple, and the dataclass is frozen so the
    field cannot be reassigned post-construction.
    """

    entries: tuple[EntryResult, ...]

    def prunable(self) -> list[EntryResult]:
        """Entries that are safe to remove (status == 'prune')."""
        return [e for e in self.entries if e.status == "prune"]

    def by_section(self) -> dict[str, list[str]]:
        """Prunable entries grouped by field name (input shape for apply_fix)."""
        out: dict[str, list[str]] = {}
        for e in self.prunable():
            out.setdefault(e.section, []).append(e.entry)
        return out


def _run_uv_lock(project_dir: Path) -> bool:
    uv_bin = shutil.which("uv")
    if uv_bin is None:
        return False
    completed = subprocess.run(  # noqa: S603
        [uv_bin, "lock", "--project", str(project_dir), "--no-progress"],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    return completed.returncode == 0


@dataclass(frozen=True)
class AuditTargets:
    """The parsed pyproject.toml input for an audit run.

    Holds the original TOML text, its directory (for resolving relative
    paths in the modified copy), and the override/constraint entries
    grouped by section in declaration order.
    """

    text: str
    base_dir: Path
    sections: tuple[tuple[str, tuple[str, ...]], ...]


def load_targets(pyproject_path: Path | str) -> AuditTargets:
    """Read a pyproject.toml and collect the override/constraint targets.

    Cheap: parses TOML but does not invoke `uv lock`. Use this when you
    need to know up front how many entries an audit will process.
    """
    path = Path(pyproject_path).resolve()
    text = path.read_text()
    doc = tomlkit.parse(text)
    base_dir = path.parent

    sections: list[tuple[str, tuple[str, ...]]] = []
    for section in FIELDS:
        try:
            arr = get_uv_array(doc, section)
        except (KeyError, TypeError):
            continue
        sections.append((section, tuple(str(e) for e in arr)))

    return AuditTargets(text=text, base_dir=base_dir, sections=tuple(sections))


def evaluate_entry(
    targets: AuditTargets,
    section_key: str,
    entry: str,
) -> Result:
    """Evaluate one override/constraint entry against `uv lock`.

    Returns a Result with one of the four statuses (prune/keep/skip/error).
    Each call spawns its own tempdir and `uv lock` invocation, so callers
    can interleave evaluation with progress output.
    """
    try:
        req = Requirement(entry)
    except Exception:  # noqa: BLE001
        return Result(status="error", value="parse error")

    if not is_pure_lower_bound(req):
        return Result(status="skip", value="-")

    modified_text = prepare_modified_text(
        targets.text,
        section_key,
        entry,
        targets.base_dir,
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "pyproject.toml").write_text(modified_text)
        if not _run_uv_lock(tmp_path):
            return Result(status="error", value="lock failed")
        lock_doc = tomlkit.parse((tmp_path / "uv.lock").read_text())

    resolved = find_resolved_version(lock_doc, req.name)
    return classify(req, resolved)


def audit(pyproject_path: Path | str) -> AuditReport:
    """Audit a pyproject.toml for redundant override/constraint entries.

    Iterates over `>=` / `>` entries in `[tool.uv].override-dependencies`
    and `constraint-dependencies`, running `uv lock` once per entry to
    check whether the natural resolution still satisfies the bound.
    """
    targets = load_targets(pyproject_path)
    entries: list[EntryResult] = []
    for section, items in targets.sections:
        for raw in items:
            result = evaluate_entry(targets, section, raw)
            entries.append(
                EntryResult(section=section, entry=raw, result=result),
            )
    return AuditReport(entries=tuple(entries))


def apply_fix(
    pyproject_path: Path | str,
    by_section: dict[str, list[str]],
) -> None:
    """Remove the given entries from pyproject.toml in place.

    Comments and formatting on untouched lines are preserved by tomlkit.
    """
    path = Path(pyproject_path).resolve()
    doc = tomlkit.parse(path.read_text())
    remove_entries(doc, by_section)
    path.write_text(tomlkit.dumps(doc))
