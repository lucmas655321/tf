#!/usr/bin/env bash
# run_all.sh — esegui tutti i test in ordine.
# Miller deve essere aperto in VSCode (pannello visibile) — verificato per primo.
# Fermati al primo errore.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# ── 1. Miller (richiede VSCode aperto) ──────────────────────────────────────
echo "=== run_miller.py ==="
python3 test/run_miller.py || { echo "STOP: run_miller.py fallito"; exit 1; }
echo ""

# ── 2. MCP ───────────────────────────────────────────────────────────────────
echo "=== run_mcp.py ==="
python3 test/run_mcp.py || { echo "STOP: run_mcp.py fallito"; exit 1; }
echo ""

# ── 3. CLI ───────────────────────────────────────────────────────────────────
echo "=== run_cli.py ==="
python3 test/run_cli.py || { echo "STOP: run_cli.py fallito"; exit 1; }
echo ""

# ── 4. Trees (albero continuo) ───────────────────────────────────────────────
echo "=== run_trees.py ==="
python3 test/run_trees.py || { echo "STOP: run_trees.py fallito"; exit 1; }
echo ""

# ── 5. Shell (CLI idempotency) ────────────────────────────────────────────────
echo "=== test.sh ==="
(cd "$ROOT/test" && bash test.sh) || { echo "STOP: test.sh fallito"; exit 1; }
echo ""

echo "=== tutti i test passati ==="
