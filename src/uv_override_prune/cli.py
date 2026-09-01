"""CLI entry point for uv-override-prune.

A thin wrapper around `core.load_targets`, `core.evaluate_section`, and
`core.apply_fix` that handles argument parsing, streaming output, and
exit codes.
"""

import argparse
import io
import sys
from pathlib import Path

from . import __version__
from .core import (
    AuditReport,
    EntryResult,
    apply_fix,
    evaluate_section,
    load_targets,
)

_LABELS = {
    "prune": "[PRUNE]",
    "keep": "[KEEP] ",
    "skip": "[SKIP] ",
    "error": "[ERROR]",
}


def main() -> int:
    # Equivalent to running under PYTHONUNBUFFERED=1: each evaluation
    # takes seconds, so per-entry progress must reach the terminal as
    # soon as it is printed even when stdout is piped.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(write_through=True)
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(write_through=True)

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
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
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

    targets = load_targets(pyproject_path)
    all_entries: list[EntryResult] = []
    for section, items in targets.sections:
        n = len(items)
        word = "entry" if n == 1 else "entries"
        print(f"=== {section} ({n} {word}) ===")
        if not items:
            print()
            continue
        entry_w = max(len(e) for e in items)
        results = evaluate_section(targets, section, items)
        for raw, result in zip(items, results, strict=True):
            er = EntryResult(section=section, entry=raw, result=result)
            all_entries.append(er)
            print(f"{_LABELS[er.status]} {raw:<{entry_w}}  {result.value}")
        print()

    report = AuditReport(entries=tuple(all_entries))
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
