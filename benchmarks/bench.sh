#!/usr/bin/env bash
# benchmarks/bench.sh
#
# Launch benchmark runs for one or both conditions.
#
# Single-prompt mode (--size):
#   bench.sh (a|tf|both) <prefix> (s|m|l) [--n N] [--dry-run]
#
# Multi-prompt mode (--case):
#   bench.sh (a|tf|both) <prefix> --case <case-dir> [--n N] [--dry-run]
#
# Examples:
#   bench.sh a    exp05_a   s --n 3              # 3 runs condition A, textwrap_s
#   bench.sh both exp05     m --n 3              # 3 runs each, argparse_m
#   bench.sh both exp06     --case textwrap_multi --n 3   # multi-prompt, 3 runs each
#   bench.sh tf   exp06_tf  --case textwrap_multi --dry-run
#
# Output dirs: runs/<prefix>_<cond>_<n>/

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="$SCRIPT_DIR/harness/session.sh"

# --- parse args ---------------------------------------------------------------
COND_ARG="" PREFIX="" SIZE="" CASE_ARG="" N=1 DRY_RUN="" PROMPTS_LIMIT=""

while [ $# -gt 0 ]; do
  case "$1" in
    a|tf|both) COND_ARG="$1"; shift ;;
    s|m|l)     SIZE="$1";      shift ;;
    --n)       N="$2";         shift 2 ;;
    --case)    CASE_ARG="$2";  shift 2 ;;
    --prompts) PROMPTS_LIMIT="--prompts $2"; shift 2 ;;
    --dry-run) DRY_RUN="--dry-run"; shift ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *)
      if [ -z "$PREFIX" ]; then PREFIX="$1"; shift
      else echo "unknown arg: $1" >&2; exit 1
      fi
      ;;
  esac
done

[ -n "$COND_ARG" ] || { echo "error: condition required (a|tf|both)" >&2; exit 1; }
[ -n "$PREFIX"   ] || { echo "error: run-id-prefix required" >&2; exit 1; }
[ -n "$SIZE$CASE_ARG" ] || { echo "error: size (s|m|l) or --case <dir> required" >&2; exit 1; }

case "$COND_ARG" in
  both) CONDITIONS="a tf" ;;
  *)    CONDITIONS="$COND_ARG" ;;
esac

for COND in $CONDITIONS; do
  for i in $(seq 1 "$N"); do
    RUN_ID="${PREFIX}_${COND}_${i}"
    echo "=== [$COND run $i/$N] id=$RUN_ID ==="
    if [ -n "$CASE_ARG" ]; then
      bash "$SESSION" --cond "$COND" --id "$RUN_ID" --case "$CASE_ARG" $PROMPTS_LIMIT $DRY_RUN
    else
      bash "$SESSION" --cond "$COND" --id "$RUN_ID" --size "$SIZE" $DRY_RUN
    fi
  done
done

echo "=== ALL DONE ==="
