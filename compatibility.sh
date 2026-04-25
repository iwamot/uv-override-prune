#!/bin/bash
set -euo pipefail

eval "$(mise activate bash)"
mise install aqua:astral-sh/uv

uv build --wheel --out-dir dist
uv run --isolated --no-project --with ./dist/*.whl uv-override-prune --fix
