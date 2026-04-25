from uv_override_prune.analyze import Result
from uv_override_prune.cli import format_per_entry
from uv_override_prune.core import AuditReport, EntryResult


def _entry(
    section: str,
    entry: str,
    status: str,
    value: str = "",
    detail: str = "",
) -> EntryResult:
    return EntryResult(
        section=section,
        entry=entry,
        result=Result(status=status, detail=detail, value=value),
    )


def test_format_per_entry_groups_by_section():
    report = AuditReport(
        entries=(
            _entry("override-dependencies", "foo>=1.0", "prune", "2.0"),
            _entry("override-dependencies", "bar>=2.0", "keep", "1.0"),
            _entry("constraint-dependencies", "x>=1.0", "skip", "-"),
        ),
    )
    output = format_per_entry(report)
    assert "=== override-dependencies (2 entries) ===" in output
    assert "=== constraint-dependencies (1 entries) ===" in output


def test_format_per_entry_renders_status_labels():
    report = AuditReport(
        entries=(
            _entry("override-dependencies", "foo>=1.0", "prune", "2.0"),
            _entry("override-dependencies", "bar>=2.0", "keep", "1.0"),
            _entry("override-dependencies", "qux>=3.0", "skip", "-"),
            _entry("override-dependencies", "err>=4.0", "error", "parse error"),
        ),
    )
    output = format_per_entry(report)
    assert "[PRUNE]" in output
    assert "[KEEP]" in output
    assert "[SKIP]" in output
    assert "[ERROR]" in output


def test_format_per_entry_includes_value_column():
    report = AuditReport(
        entries=(
            _entry("override-dependencies", "foo>=1.0", "prune", "2.0"),
            _entry("override-dependencies", "bar>=2.0", "keep", "1.0"),
        ),
    )
    output = format_per_entry(report)
    assert "foo>=1.0" in output
    assert "2.0" in output
    assert "bar>=2.0" in output
    assert "1.0" in output


def test_format_per_entry_aligns_entry_column_per_section():
    report = AuditReport(
        entries=(
            _entry("override-dependencies", "x", "prune", "1.0"),
            _entry("override-dependencies", "longer-name>=1.0", "keep", "0.5"),
        ),
    )
    output = format_per_entry(report)
    lines = output.splitlines()
    # both entry rows should have value column aligned to the same column
    prune_line = next(line for line in lines if "[PRUNE]" in line)
    keep_line = next(line for line in lines if "[KEEP]" in line)
    assert prune_line.index("1.0") == keep_line.index("0.5")


def test_format_per_entry_empty_when_no_entries():
    report = AuditReport(entries=())
    assert format_per_entry(report) == ""
