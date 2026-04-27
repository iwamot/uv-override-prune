from pathlib import Path

from uv_override_prune.analyze import Result
from uv_override_prune.core import (
    AuditReport,
    AuditTargets,
    EntryResult,
    evaluate_entry,
)


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
    targets = AuditTargets(text="", base_dir=Path(), sections=())
    result = evaluate_entry(targets, "override-dependencies", "foo==1.0")
    assert result.status == "skip"
    assert result.value == "(non-lower-bound)"


def test_evaluate_entry_returns_parse_error_for_invalid_entry():
    targets = AuditTargets(text="", base_dir=Path(), sections=())
    result = evaluate_entry(targets, "override-dependencies", "not a valid req")
    assert result.status == "error"
    assert result.value == "parse error"
