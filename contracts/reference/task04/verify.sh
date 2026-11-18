#!/usr/bin/env bash
# Run the TASK-04 verification suite; exits non-zero on any failure.
set -u
cd "$(dirname "$0")" || exit 2
export PYTHONIOENCODING=utf-8

echo "[1/3] schema + model invariants"
python3 tools/check_model.py || { echo; echo "CHECKS FAILED"; exit 1; }

echo
echo "[2/3] configuration digest"
python3 tools/configuration_digest.py --verify || { echo; echo "CHECKS FAILED"; exit 1; }

echo
echo "[3/3] v1.0.1 limits and accepted-with-warning rules"
python3 tools/test_limits.py || { echo; echo "CHECKS FAILED"; exit 1; }

echo
echo "ALL CHECKS PASSED"
