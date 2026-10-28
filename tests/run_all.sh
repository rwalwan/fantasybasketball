#!/usr/bin/env bash
# Runs every tests/test_*.mjs (node) and tests/test_*.py (python); exits non-zero on the first failure.
set -euo pipefail
cd "$(dirname "$0")/.."
for f in tests/test_*.mjs; do [ -e "$f" ] && node "$f"; done
for f in tests/test_*.py; do [ -e "$f" ] && python3 "$f"; done
echo "all tests passed"
