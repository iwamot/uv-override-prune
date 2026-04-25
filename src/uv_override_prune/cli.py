"""CLI entry point for uv-override-prune.

A thin wrapper around `core.audit` and `core.apply_fix` that handles
argument parsing, output formatting, and exit codes.
"""

import argparse
import sys
from pathlib import Path

from .core import AuditReport, EntryResult, apply_fix, audit

_LABELS = {
    "prune": "[PRUNE]",
    "keep": "[KEEP] ",
    "skip": "[SKIP] ",
    "error": "[ERROR]",
}


def format_per_entry(report: AuditReport) -> str:
    """Render the per-entry section of the report as a string. Pure."""
    by_section: dict[str, list[EntryResult]] = {}
    for e in report.entries:
        by_section.setdefault(e.section, []).append(e)
    lines: list[str] = []
    for section, items in by_section.items():
        n = len(items)
        word = "entry" if n == 1 else "entries"
        lines.append(f"=== {section} ({n} {word}) ===")
        entry_w = max(len(e.entry) for e in items)
        for e in items:
            label = _LABELS[e.status]
            lines.append(f"{label} {e.entry:<{entry_w}}  {e.result.value}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Detect prunable override-dependencies / "
            "constraint-dependencies in uv projects."
        ),
    )
    parser.add_argument(
        "pyproject",
        nargs="?",
        default=None,
        type=Path,
        help="Path to pyproject.toml (default: ./pyproject.toml)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Remove prunable entries from pyproject.toml in place",
    )
    args = parser.parse_args()

    if args.pyproject is None:
        pyproject_path = Path("pyproject.toml")
        display_path = "./pyproject.toml"
    else:
        pyproject_path = args.pyproject
        display_path = str(args.pyproject)

    if not pyproject_path.exists():
        print(f"File not found: {display_path}", file=sys.stderr)
        return 2

    report = audit(pyproject_path)
    print(format_per_entry(report))

    prunable = report.prunable()
    if not prunable:
        print("No prunable entries found.")
        return 0

    if args.fix:
        apply_fix(pyproject_path, report.by_section())
        n = len(prunable)
        word = "entry" if n == 1 else "entries"
        print(f"Pruned {n} {word} from {display_path}.")
        return 0

    print("Run with --fix to prune entries marked [PRUNE].")
    return 1


if __name__ == "__main__":
    sys.exit(main())
