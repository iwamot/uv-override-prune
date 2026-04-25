# uv-override-prune

[![CI](https://github.com/iwamot/uv-override-prune/actions/workflows/validate.yml/badge.svg)](https://github.com/iwamot/uv-override-prune/actions/workflows/validate.yml)
[![codecov](https://codecov.io/gh/iwamot/uv-override-prune/graph/badge.svg)](https://codecov.io/gh/iwamot/uv-override-prune)
[![PyPI](https://img.shields.io/pypi/v/uv-override-prune.svg)](https://pypi.org/project/uv-override-prune/)
[![Python](https://img.shields.io/pypi/pyversions/uv-override-prune.svg)](https://pypi.org/project/uv-override-prune/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Detect prunable `override-dependencies` / `constraint-dependencies` entries in uv projects.

## What it does

uv lets you patch transitive dependency versions via `[tool.uv] override-dependencies` and `constraint-dependencies`. These are commonly added to work around issues in upstream packages (e.g. to force a CVE-patched minimum version that transitive deps don't yet require). As direct dependencies get updated over time, these entries can become unnecessary — but they tend to accumulate silently.

`uv-override-prune` detects entries whose lower-bound constraint is already satisfied by natural resolution, so you can safely remove them.

## Install

```bash
uv tool install uv-override-prune
```

Or run it without installing — useful for one-off checks:

```bash
uvx uv-override-prune
```

## CLI usage

```bash
# Detect prunable entries (default)
uv-override-prune                          # checks ./pyproject.toml
uv-override-prune path/to/pyproject.toml   # checks given file

# Remove prunable entries in place
uv-override-prune --fix
```

Example output:

```
=== override-dependencies (3 entries) ===
[KEEP]  aiohttp>=3.13.5    3.13.3
[PRUNE] httpx>=0.1.0       0.28.1
[SKIP]  foo==1.0           -

Run with --fix to prune them from pyproject.toml.
```

Exit codes:

| Code | Meaning |
|------|---------|
| `0`  | No prunable entries (or `--fix` succeeded) |
| `1`  | Prunable entries found (without `--fix`) |
| `2`  | `pyproject.toml` not found |

## Scope

- Targets entries in `[tool.uv]` `override-dependencies` and `constraint-dependencies`.
- Only entries whose specifier uses `>=` and/or `>` are checked. Entries using `==`, `~=`, `<`, `<=`, `!=` (alone or mixed) are skipped.
- One-at-a-time detection: removes each entry in a temp copy of `pyproject.toml`, runs `uv lock`, and checks whether the natural resolution still satisfies the entry's specifier.

## Known limitations

- Projects with a `[build-system]` section may fail to lock in the temp dir if they depend on source files (e.g. `setuptools.packages.find`, Hatch dynamic version from source). `[tool.uv.sources]` path deps, workspace members, and `[project] readme` are rewritten automatically; other build-backend-specific references are not.
- One-at-a-time evaluation: if overrides interact (e.g. cascade redundancy, shared transitive deps), individual runs may miss some prunable entries. Re-run after applying removals to surface the next layer.

## License

MIT
