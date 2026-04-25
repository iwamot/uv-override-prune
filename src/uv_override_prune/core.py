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


def _evaluate_entry(
    original_text: str,
    section_key: str,
    entry: str,
    original_dir: Path,
) -> Result:
    try:
        req = Requirement(entry)
    except Exception:  # noqa: BLE001
        return Result(status="error", value="parse error")

    if not is_pure_lower_bound(req):
        return Result(status="skip", value="-")

    modified_text = prepare_modified_text(
        original_text,
        section_key,
        entry,
        original_dir,
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

    Reads the file, iterates over `>=` / `>` entries in
    `[tool.uv].override-dependencies` and `constraint-dependencies`,
    and runs `uv lock` once per entry to check whether the natural
    resolution still satisfies the bound.
    """
    path = Path(pyproject_path).resolve()
    text = path.read_text()
    doc = tomlkit.parse(text)
    base_dir = path.parent

    entries: list[EntryResult] = []
    for section in FIELDS:
        try:
            arr = get_uv_array(doc, section)
        except (KeyError, TypeError):
            continue
        for raw in [str(e) for e in arr]:
            result = _evaluate_entry(text, section, raw, base_dir)
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
