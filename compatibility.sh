#!/bin/bash
set -euo pipefail

mise install uv
eval "$(mise activate bash)"

uv build --wheel --out-dir dist
uv run --isolated --no-project --with ./dist/*.whl uv-override-prune --fix
