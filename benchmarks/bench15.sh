#!/usr/bin/env bash
# benchmarks/bench15.sh
#
# Thin wrapper for bench.sh that runs the FIRST 15 prompts of pydecimal_multi
# in both conditions, n=1 by default.
#
# Usage:
#   bench15.sh <prefix> [--n N] [--case <case-dir>]
#
# Defaults:
#   --case   pydecimal_multi
#   --n      1
#
# Examples:
#   bench15.sh exp21
#   bench15.sh exp22 --n 3
#   bench15.sh exp23 --case argparse_multi    (must have >=15 prompts)

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCH="$SCRIPT_DIR/bench.sh"

PREFIX=""
CASE="pydecimal_multi"
N=1

while [ $# -gt 0 ]; do
  case "$1" in
    --n)    N="$2";    shift 2 ;;
    --case) CASE="$2"; shift 2 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *)
      if [ -z "$PREFIX" ]; then PREFIX="$1"; shift
      else echo "unknown arg: $1" >&2; exit 1
      fi
      ;;
  esac
done

[ -n "$PREFIX" ] || { echo "error: <prefix> required (e.g. exp21)" >&2; exit 1; }

bash "$BENCH" both "$PREFIX" --case "$CASE" --prompts 15 --n "$N" 2>&1 | tee "/tmp/${PREFIX}.log"
