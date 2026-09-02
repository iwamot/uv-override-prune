# uv-override-prune

[![pypi](https://img.shields.io/pypi/v/uv-override-prune.svg)](https://pypi.org/project/uv-override-prune/)
[![python](https://img.shields.io/pypi/pyversions/uv-override-prune.svg)](https://pypi.org/project/uv-override-prune/)

Detect prunable `override-dependencies` / `constraint-dependencies` entries in uv projects.

## Install

```bash
uv tool install uv-override-prune
```

Or run it without installing — useful for one-off checks:

```bash
uvx uv-override-prune
```

## Usage

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
[SKIP]  foo==1.0           (non-lower-bound)

Run with --fix to prune entries marked [PRUNE].
```

Exit codes:

| Code | Meaning |
|------|---------|
| `0`  | No prunable entries (or `--fix` succeeded) |
| `1`  | Prunable entries found (without `--fix`) |
| `2`  | `pyproject.toml` not found or malformed |

## Why

uv lets you pin a transitive dependency version via `[tool.uv] override-dependencies` and `constraint-dependencies`.

A common reason to reach for these is CVE mitigation: a vulnerability is disclosed in a transitive package, and you force the patched minimum version while direct deps catch up.

Once they do, the entry is no longer doing anything — but it's easy to forget which ones are still load-bearing. Stale overrides become a judgment cost at every audit or upgrade ("is this still needed, or just history?").

`uv-override-prune` answers that mechanically: it checks whether each entry's lower bound is already satisfied by what `uv lock` would resolve without the override.

## How it works

For each candidate entry, the tool removes it in a temp copy of `pyproject.toml`, runs `uv lock` there, and checks whether the resulting natural resolution still satisfies the entry's specifier. If yes, the entry is `[PRUNE]`.

## Scope

- Targets entries in `[tool.uv] override-dependencies` and `constraint-dependencies`.
- Only specifiers using `>=` and/or `>` are checked. Entries using `==`, `~=`, `<`, `<=`, `!=` (alone or mixed) are skipped.
- Entries with an environment marker (e.g. `foo>=1.0; python_version >= "3.10"`) are skipped, since the natural `uv lock` resolution doesn't reflect the marker's intent.
- An entry that repeats an earlier entry in the same section (same package and specifier, ignoring spelling) is reported as `[PRUNE]` with `(duplicate)`. The first copy is evaluated with every copy removed, so its verdict reflects the natural resolution and `--fix` leaves exactly one copy.

## Known limitations

- Projects with a `[build-system]` section may fail to lock in the temp dir if they depend on source files (e.g. `setuptools.packages.find`, Hatch dynamic version from source). `[tool.uv.sources]` path deps, workspace members, and `[project] readme` are rewritten automatically; other build-backend-specific references are not.
- One-at-a-time evaluation: if overrides interact (e.g. cascade redundancy, shared transitive deps), individual runs may miss some prunable entries. Re-run after applying removals to surface the next layer.

## License

MIT
