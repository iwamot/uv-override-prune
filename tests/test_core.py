from pathlib import Path

import pytest
from packaging.version import Version

from uv_override_prune.analyze import Result
from uv_override_prune.core import (
    AuditReport,
    AuditTargets,
    EntryResult,
    audit,
    evaluate_entry,
    evaluate_section,
    load_targets,
)

FIXTURES = Path(__file__).parent / "fixtures"

# The fixture uv.lock was produced with `httpx==0.23.0`; the range here is
# what a project looks like once its pin has been relaxed but not relocked.
LOCK_AWARE_PYPROJECT = """\
[project]
name = "exp"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["httpx>=0.23"]

[tool.uv]
override-dependencies = ["httpcore>=1.0"]
"""


def _entry(section: str, entry: str, status: str) -> EntryResult:
    return EntryResult(
        section=section,
        entry=entry,
        result=Result(status=status, value=""),
    )


def test_entry_result_exposes_status():
    er = EntryResult(
        section="override-dependencies",
        entry="foo>=1.0",
        result=Result(status="prune", value="2.0"),
    )
    assert er.status == "prune"


def test_audit_report_prunable_filters():
    report = AuditReport(
        entries=(
            _entry("override-dependencies", "foo>=1.0", "prune"),
            _entry("override-dependencies", "bar>=2.0", "keep"),
            _entry("constraint-dependencies", "baz>=3.0", "prune"),
            _entry("override-dependencies", "qux>=4.0", "skip"),
        ),
    )
    assert [e.entry for e in report.prunable()] == ["foo>=1.0", "baz>=3.0"]


def test_audit_report_prunable_empty_when_none():
    report = AuditReport(
        entries=(
            _entry("override-dependencies", "bar>=2.0", "keep"),
            _entry("override-dependencies", "qux>=4.0", "skip"),
        ),
    )
    assert report.prunable() == []


def test_audit_report_by_section_groups_by_field():
    report = AuditReport(
        entries=(
            _entry("override-dependencies", "foo>=1.0", "prune"),
            _entry("constraint-dependencies", "baz>=3.0", "prune"),
            _entry("override-dependencies", "qux>=4.0", "prune"),
            _entry("override-dependencies", "bar>=2.0", "keep"),
        ),
    )
    assert report.by_section() == {
        "override-dependencies": ["foo>=1.0", "qux>=4.0"],
        "constraint-dependencies": ["baz>=3.0"],
    }


def test_audit_report_by_section_omits_sections_with_no_prunable():
    report = AuditReport(
        entries=(
            _entry("override-dependencies", "foo>=1.0", "prune"),
            _entry("constraint-dependencies", "baz>=3.0", "keep"),
        ),
    )
    assert report.by_section() == {"override-dependencies": ["foo>=1.0"]}


def test_audit_report_by_section_empty_when_no_prunable():
    report = AuditReport(entries=())
    assert report.by_section() == {}


def test_evaluate_entry_skips_non_lower_bound_with_descriptive_value():
    targets = AuditTargets(text="", base_dir=Path(), lock_text=None, sections=())
    result = evaluate_entry(targets, "override-dependencies", "foo==1.0")
    assert result.status == "skip"
    assert result.value == "(non-lower-bound)"


def test_evaluate_entry_skips_marker_entry_with_descriptive_value():
    targets = AuditTargets(text="", base_dir=Path(), lock_text=None, sections=())
    result = evaluate_entry(
        targets,
        "override-dependencies",
        'foo>=1.0; python_version >= "3.10"',
    )
    assert result.status == "skip"
    assert result.value == "(has-marker)"


def test_evaluate_entry_skips_project_with_dynamic_dependencies():
    targets = AuditTargets(
        text='[project]\nname = "foo"\ndynamic = ["dependencies"]\n',
        base_dir=Path(),
        lock_text=None,
        sections=(),
    )
    result = evaluate_entry(targets, "override-dependencies", "foo>=1.0")
    assert result.status == "skip"
    assert result.value == "(dynamic-metadata)"


def test_evaluate_entry_returns_parse_error_for_invalid_entry():
    targets = AuditTargets(text="", base_dir=Path(), lock_text=None, sections=())
    result = evaluate_entry(targets, "override-dependencies", "not a valid req")
    assert result.status == "error"
    assert result.value == "parse error"


def test_evaluate_section_prunes_later_duplicate_without_evaluating_it():
    targets = AuditTargets(text="", base_dir=Path(), lock_text=None, sections=())
    items = ["foo==1.0", "foo==1.0", "bar==1.0"]
    results = list(evaluate_section(targets, "override-dependencies", items))
    assert [r.status for r in results] == ["skip", "prune", "skip"]
    assert [r.value for r in results] == [
        "(non-lower-bound)",
        "(duplicate)",
        "(non-lower-bound)",
    ]


def test_audit_report_errors():
    report = AuditReport(
        entries=(
            _entry("override-dependencies", "foo>=1.0", "prune"),
            _entry("override-dependencies", "bar>=2.0", "error"),
            _entry("constraint-dependencies", "baz>=3.0", "error"),
        )
    )
    assert [e.entry for e in report.errors()] == ["bar>=2.0", "baz>=3.0"]


@pytest.mark.parametrize(
    "statuses, fixed, expected",
    [
        ([], False, 0),
        (["keep", "skip"], False, 0),
        (["prune"], False, 1),
        (["prune"], True, 0),
        (["error"], False, 2),
        (["prune", "error"], False, 2),
        (["prune", "error"], True, 2),
    ],
)
def test_audit_report_exit_code(statuses, fixed, expected):
    report = AuditReport(
        entries=tuple(
            _entry("override-dependencies", f"pkg{i}>=1.0", s)
            for i, s in enumerate(statuses)
        )
    )
    assert report.exit_code(fixed=fixed) == expected


def test_load_targets_reads_lockfile_next_to_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(LOCK_AWARE_PYPROJECT)
    (tmp_path / "uv.lock").write_text("version = 1\n")
    assert load_targets(tmp_path / "pyproject.toml").lock_text == "version = 1\n"


def test_load_targets_has_no_lock_text_without_lockfile(tmp_path):
    (tmp_path / "pyproject.toml").write_text(LOCK_AWARE_PYPROJECT)
    assert load_targets(tmp_path / "pyproject.toml").lock_text is None


def test_audit_keeps_override_the_locked_versions_still_need(tmp_path):
    """Runs the real `uv lock` against PyPI.

    httpx 0.23.0 is locked and requires httpcore<0.16, so without the
    override `uv lock` downgrades httpcore. A from-scratch resolution
    would upgrade httpx instead and report the override as prunable.
    """
    (tmp_path / "pyproject.toml").write_text(LOCK_AWARE_PYPROJECT)
    lock = (FIXTURES / "lock_aware" / "uv.lock").read_text()
    (tmp_path / "uv.lock").write_text(lock)

    report = audit(tmp_path / "pyproject.toml")

    assert [e.status for e in report.entries] == ["keep"]
    assert Version(report.entries[0].result.value) < Version("1.0")
    assert (tmp_path / "uv.lock").read_text() == lock


def test_audit_locks_a_project_with_a_dynamic_version(tmp_path):
    """Runs the real `uv lock` against PyPI.

    hatch-vcs would need the sources and the git history to compute the
    version, neither of which exists in the temp dir the audit locks in.
    """
    (tmp_path / "pyproject.toml").write_text(
        """\
[project]
name = "exp"
dynamic = ["version"]
requires-python = ">=3.12"
dependencies = ["idna>=2"]

[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[tool.hatch.version]
source = "vcs"

[tool.uv]
override-dependencies = ["idna>=3.0"]
"""
    )

    report = audit(tmp_path / "pyproject.toml")

    assert [e.status for e in report.entries] == ["prune"]
