from pathlib import Path

from hypothesis import example, given, settings
from hypothesis import strategies as st
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


REPORT_ROWS = st.lists(
    st.tuples(
        st.integers(0, 20),
        st.sampled_from(["override-dependencies", "constraint-dependencies"]),
        st.sampled_from(["foo>=1.0", "bar>=2.0", "baz>=3.0"]),
        st.text(max_size=20),
    ),
    max_size=8,
)


@settings(max_examples=200, derandomize=True, database=None, deadline=None)
@example(prunable=[], kept=[], skipped=[], errors=[])
@example(
    prunable=[
        (3, "override-dependencies", "foo>=1.0", "2.0"),
        (1, "constraint-dependencies", "bar>=2.0", "3.0"),
        (2, "override-dependencies", "foo>=1.0", "(duplicate)"),
    ],
    kept=[(0, "constraint-dependencies", "foo>=1.0", "1.0")],
    skipped=[(4, "override-dependencies", "baz>=3.0", "(has-marker)")],
    errors=[(5, "constraint-dependencies", "baz>=3.0", "lock failed")],
)
@example(
    prunable=[(0, "override-dependencies", "foo>=1.0", "2.0")],
    kept=[],
    skipped=[],
    errors=[],
)
@given(prunable=REPORT_ROWS, kept=REPORT_ROWS, skipped=REPORT_ROWS, errors=REPORT_ROWS)
def test_audit_report_preserves_outcomes_and_failure_priority(
    prunable, kept, skipped, errors
):
    def ordered(status, rows):
        return sorted(
            [
                (rank, EntryResult(section, raw, Result(status=status, value=value)))
                for rank, section, raw, value in rows
            ],
            key=lambda row: row[0],
        )

    prune_rows = ordered("prune", prunable)
    error_rows = ordered("error", errors)
    entries = tuple(
        entry
        for _, entry in sorted(
            prune_rows + ordered("keep", kept) + ordered("skip", skipped) + error_rows,
            key=lambda row: row[0],
        )
    )
    expected_prunable = [entry for _, entry in prune_rows]
    expected_errors = [entry for _, entry in error_rows]
    expected_sections: dict[str, list[str]] = {}
    for entry in expected_prunable:
        expected_sections.setdefault(entry.section, []).append(entry.entry)

    report = AuditReport(entries=entries)
    assert report.prunable() == expected_prunable
    assert report.errors() == expected_errors
    assert report.by_section() == expected_sections
    assert report.exit_code(fixed=False) == (2 if errors else int(bool(prunable)))
    assert report.exit_code(fixed=True) == (2 if errors else 0)
    assert report.entries == entries


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
