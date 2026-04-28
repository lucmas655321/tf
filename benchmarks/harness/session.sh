#!/usr/bin/env bash
# benchmarks/harness/session.sh
#
# Run a single benchmark session.
#
# Protocol (3-step):
#   step 01 — cold   : "READY" with cache DISABLED  → baseline cold overhead
#   step 02 — warmup : cache ON, condition-specific  → populates cache
#   step 03 — task   : prompt(s), stream-json        → measured run
#
# Single-prompt mode (--size):
#   One claude call, one prompt file. Output: 03_task_stream.jsonl + metrics.
#
# Multi-prompt mode (--case):
#   Reads prompts.json from the case dir. Runs N prompts in sequence within
#   the same claude session using --resume <session-id>. Each prompt produces
#   03_prompt_N_stream.jsonl + 03_prompt_N_metrics.json. Files for all named
#   file keys are copied into the workspace at setup time.
#
# Output: runs/<id>/
#   01_clean_metrics.json  02_warmup_metrics.json
#   03_task_stream.jsonl   03_task_metrics.json          (single-prompt mode)
#   03_prompt_N_stream.jsonl  03_prompt_N_metrics.json   (multi-prompt mode)
#   session_summary.json   stderr.log
#
# Usage:
#   session.sh --cond (a|tf) --id <run-id> --size (s|m|l) [--dry-run]
#   session.sh --cond (a|tf) --id <run-id> --case <case-dir> [--dry-run]
#
#   --cond   a  = no MCP (native tools only)
#            tf = textfolding MCP
#   --id     run identifier, e.g. "exp05_a_1" (used as output dir name)
#   --size   s = textwrap_s  m = argparse_m  l = pydecimal_l  (single-prompt)
#   --case   path to case dir containing prompts.json + files/ (multi-prompt)
#   --dry-run  create workspace only, do not invoke claude

set -eu

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HARNESS_DIR/../.." && pwd)"
CASES_DIR="$REPO_ROOT/benchmarks/cases"

# --- parse args ---------------------------------------------------------------
COND="" ID="" SIZE="" CASE_DIR_ARG="" DRY_RUN=0 PROMPTS_LIMIT=0

while [ $# -gt 0 ]; do
  case "$1" in
    --cond)    COND="$2";         shift 2 ;;
    --id)      ID="$2";           shift 2 ;;
    --size)    SIZE="$2";         shift 2 ;;
    --case)    CASE_DIR_ARG="$2"; shift 2 ;;
    --prompts) PROMPTS_LIMIT="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1;         shift   ;;
    -h|--help) sed -n '2,33p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

[ -n "$COND" ] || { echo "error: --cond required (a|tf)" >&2; exit 1; }
[ -n "$ID"   ] || { echo "error: --id required" >&2; exit 1; }
[ -n "$SIZE$CASE_DIR_ARG" ] || { echo "error: --size or --case required" >&2; exit 1; }
[ -z "$SIZE" ] || [ -z "$CASE_DIR_ARG" ] || { echo "error: --size and --case are mutually exclusive" >&2; exit 1; }

# --- resolve mode -------------------------------------------------------------
if [ -n "$SIZE" ]; then
  MODE="single"
  case "$SIZE" in
    s) CASE_DIR="$CASES_DIR/textwrap_s" ;;
    m) CASE_DIR="$CASES_DIR/argparse_m" ;;
    l) CASE_DIR="$CASES_DIR/pydecimal_l" ;;
    *) echo "error: --size must be s, m, or l" >&2; exit 1 ;;
  esac
else
  MODE="multi"
  # accept absolute or relative (relative to cases/)
  if [ -d "$CASE_DIR_ARG" ]; then
    CASE_DIR="$(cd "$CASE_DIR_ARG" && pwd)"
  else
    CASE_DIR="$CASES_DIR/$CASE_DIR_ARG"
  fi
  [ -d "$CASE_DIR" ] || { echo "error: case dir not found: $CASE_DIR" >&2; exit 1; }
  [ -f "$CASE_DIR/prompts.json" ] || { echo "error: prompts.json not found in $CASE_DIR" >&2; exit 1; }
fi

# --- condition config ---------------------------------------------------------
case "$COND" in
  a)
    MCP_CFG_SRC="$HARNESS_DIR/mcp_a.json"
    WARMUP_PROMPT="Reply with exactly: READY"
    TARGET_SUFFIX="plain.py"
    PROMPT_KEY="prompt_a"
    DISALLOWED_TOOLS=""
    ;;
  tf)
    MCP_CFG_SRC="$HARNESS_DIR/mcp_tf.template.json"
    WARMUP_PROMPT="Call tf('') to read the TF manual, then reply with exactly: READY"
    TARGET_SUFFIX="tf.py"
    PROMPT_KEY="prompt_tf"
    DISALLOWED_TOOLS="--disallowedTools Bash,Read,Write,Edit,NotebookRead,NotebookEdit,WebSearch,WebFetch"
    ;;
  *) echo "error: --cond must be a or tf" >&2; exit 1 ;;
esac

[ -f "$MCP_CFG_SRC" ] || { echo "error: mcp config not found: $MCP_CFG_SRC" >&2; exit 1; }

WS_ROOT="$REPO_ROOT/runs/$ID"

# --- materialise workspace ----------------------------------------------------
if [ -d "$WS_ROOT" ]; then
  echo "[session] workspace exists — wiping: $WS_ROOT"
  rm -rf "$WS_ROOT"
fi
mkdir -p "$WS_ROOT"

if [ "$MODE" = "single" ]; then
  PLAIN_FILE="$CASE_DIR/$TARGET_SUFFIX"
  PROMPT_FILE="$CASE_DIR/prompt_${COND}.md"
  [ -f "$PLAIN_FILE"  ] || { echo "error: source file not found: $PLAIN_FILE" >&2; exit 1; }
  [ -f "$PROMPT_FILE" ] || { echo "error: prompt not found: $PROMPT_FILE" >&2; exit 1; }
  cp "$PLAIN_FILE"  "$WS_ROOT/$TARGET_SUFFIX"
  cp "$PLAIN_FILE"  "$WS_ROOT/${TARGET_SUFFIX}.bak"
  cp "$PROMPT_FILE" "$WS_ROOT/PROMPT.md"
  echo "[session] mode: single  file: $TARGET_SUFFIX  prompt: $(basename "$PROMPT_FILE")"
else
  # copy files as plain.py / tf.py (same names as single-step)
  FILE_KEYS=$(python3 -c "
import json
prompts = json.load(open('$CASE_DIR/prompts.json'))
keys = sorted({p['file'] for p in prompts})
print('\n'.join(keys))
")
  for KEY in $FILE_KEYS; do
    SRC="$CASE_DIR/files/$KEY/$TARGET_SUFFIX"
    [ -f "$SRC" ] || { echo "error: file not found: $SRC" >&2; exit 1; }
    cp "$SRC" "$WS_ROOT/$TARGET_SUFFIX"
    cp "$SRC" "$WS_ROOT/${TARGET_SUFFIX}.bak"
  done
  N_PROMPTS=$(python3 -c "import json; n=len(json.load(open('$CASE_DIR/prompts.json'))); lim=$PROMPTS_LIMIT; print(min(n,lim) if lim>0 else n)")
  echo "[session] mode: multi  prompts: $N_PROMPTS  files: $(echo $FILE_KEYS | tr '\n' ' ')"
fi

if [ "$COND" = "tf" ]; then
  tf-ai tf_initProject "{\"cwd\":\"$WS_ROOT\"}" > /dev/null 2>&1 || true
fi

MCP_CFG="$WS_ROOT/.mcp.json"
if grep -q "__WORKSPACE_CWD__" "$MCP_CFG_SRC" 2>/dev/null; then
  sed "s|__WORKSPACE_CWD__|$WS_ROOT|g" "$MCP_CFG_SRC" > "$MCP_CFG"
else
  cp "$MCP_CFG_SRC" "$MCP_CFG"
fi

echo "[session] workspace ready: $WS_ROOT  cond: $COND"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[session] --dry-run: stopping here"
  exit 0
fi

cd "$WS_ROOT"

# --- helpers ------------------------------------------------------------------
run_json() {
  local prompt_text="$1" out="$2" extra="${3:-}"
  claude -p "$prompt_text" \
    --output-format json \
    --mcp-config "$MCP_CFG" \
    --strict-mcp-config \
    --permission-mode bypassPermissions \
    --bare \
    $DISALLOWED_TOOLS \
    $extra \
    > "$out" 2>> "$WS_ROOT/stderr.log"
}

run_stream() {
  local prompt_text="$1" out="$2" extra="${3:-}"
  claude -p "$prompt_text" \
    --output-format stream-json \
    --verbose \
    --mcp-config "$MCP_CFG" \
    --strict-mcp-config \
    --permission-mode bypassPermissions \
    --bare \
    $DISALLOWED_TOOLS \
    $extra \
    > "$out" 2>> "$WS_ROOT/stderr.log"
}

metrics_from_json() {
  jq '{
    cost_usd:     .total_cost_usd,
    duration_ms:  .duration_ms,
    num_turns:    .num_turns,
    input_tokens: .usage.input_tokens,
    output_tokens:.usage.output_tokens,
    cache_create: .usage.cache_creation_input_tokens,
    cache_read:   .usage.cache_read_input_tokens
  }' "$1"
}

metrics_from_stream() {
  jq -s 'map(select(.type == "result")) | last | {
    cost_usd:     .total_cost_usd,
    duration_ms:  .duration_ms,
    num_turns:    .num_turns,
    input_tokens: .usage.input_tokens,
    output_tokens:.usage.output_tokens,
    cache_create: .usage.cache_creation_input_tokens,
    cache_read:   .usage.cache_read_input_tokens
  }' "$1"
}

session_id_from_stream() {
  # extract session_id from the result event in a stream-json file
  jq -rs 'map(select(.type == "result")) | last | .session_id // empty' "$1"
}

# =============================================================================
# STEP 01 — cold baseline (cache OFF)
# =============================================================================
echo "[session $ID] step 01 — cold (cache OFF)"
run_stream "Reply with exactly: READY" \
  "$WS_ROOT/01_clean.jsonl" \
  "--settings $HARNESS_DIR/settings_nocache.json"
metrics_from_stream "$WS_ROOT/01_clean.jsonl" > "$WS_ROOT/01_clean_metrics.json"
cat "$WS_ROOT/01_clean_metrics.json"
SESSION_ID="$(session_id_from_stream "$WS_ROOT/01_clean.jsonl")"
echo "[session $ID] step 01 session_id: $SESSION_ID"

# =============================================================================
# STEP 02 — warmup (cache ON, same session)
# =============================================================================
echo "[session $ID] step 02 — warmup (cache ON, resume step 01)"
run_stream "$WARMUP_PROMPT" "$WS_ROOT/02_warmup.jsonl" "--resume $SESSION_ID"
metrics_from_stream "$WS_ROOT/02_warmup.jsonl" > "$WS_ROOT/02_warmup_metrics.json"
cat "$WS_ROOT/02_warmup_metrics.json"
SESSION_ID="$(session_id_from_stream "$WS_ROOT/02_warmup.jsonl")"
echo "[session $ID] step 02 session_id: $SESSION_ID"

# =============================================================================
# STEP 03 — task (resume from warmup)
# =============================================================================
if [ "$MODE" = "single" ]; then
  echo "[session $ID] step 03 — task (single prompt, resume step 02)"
  run_stream "$(cat "$WS_ROOT/PROMPT.md")" "$WS_ROOT/03_task_stream.jsonl" "--resume $SESSION_ID"
  metrics_from_stream "$WS_ROOT/03_task_stream.jsonl" > "$WS_ROOT/03_task_metrics.json"
  cat "$WS_ROOT/03_task_metrics.json"

  jq -s '{
    id:      "'"$ID"'",
    cond:    "'"$COND"'",
    mode:    "single",
    steps:   {clean: .[0], warmup: .[1], task: .[2]},
    totals:  {
      cost_usd:       (.[0].cost_usd + .[1].cost_usd + .[2].cost_usd),
      duration_ms:    (.[0].duration_ms + .[1].duration_ms + .[2].duration_ms),
      task_only_cost: .[2].cost_usd
    }
  }' \
    "$WS_ROOT/01_clean_metrics.json" \
    "$WS_ROOT/02_warmup_metrics.json" \
    "$WS_ROOT/03_task_metrics.json" \
    > "$WS_ROOT/session_summary.json"
  echo "=== SESSION SUMMARY ==="
  cat "$WS_ROOT/session_summary.json"

else
  # multi-prompt: iterate prompts.json, chain with --resume
  echo "[session $ID] step 03 — task (multi-prompt)"

  # materialise each prompt as a file: _prompt_1.txt, _prompt_2.txt, ...
  # prompts.json values are .md filenames relative to CASE_DIR
  N_PROMPTS=$(python3 - "$CASE_DIR/prompts.json" "$PROMPT_KEY" "$CASE_DIR" "$WS_ROOT" "$PROMPTS_LIMIT" <<'PYEOF'
import json, sys, os
pfile, key, case_dir, ws, lim = sys.argv[1:]
lim = int(lim)
prompts = json.load(open(pfile))
if lim > 0:
    prompts = prompts[:lim]
for i, p in enumerate(prompts):
    md_ref = p[key]
    # support both inline text and .md filename reference
    if md_ref.endswith('.md'):
        text = open(os.path.join(case_dir, md_ref)).read()
    else:
        text = md_ref
    open(os.path.join(ws, f"_prompt_{i+1}.txt"), "w").write(text)
    open(os.path.join(ws, f"_prompt_{i+1}.id"),  "w").write(p["id"])
print(len(prompts))
PYEOF
)

  RESUME_ID="$SESSION_ID"
  for i in $(seq 1 "$N_PROMPTS"); do
    PID="$(cat "$WS_ROOT/_prompt_${i}.id")"
    echo "[session $ID] step 03 — prompt $i/$N_PROMPTS (${PID})"

    STREAM_OUT="$WS_ROOT/03_prompt_${i}_stream.jsonl"
    METRICS_OUT="$WS_ROOT/03_prompt_${i}_metrics.json"

    run_stream "$(cat "$WS_ROOT/_prompt_${i}.txt")" "$STREAM_OUT" "--resume $RESUME_ID"

    metrics_from_stream "$STREAM_OUT" > "$METRICS_OUT"
    cat "$METRICS_OUT"

    RESUME_ID="$(session_id_from_stream "$STREAM_OUT")"
    if [ -z "$RESUME_ID" ]; then
      echo "[session $ID] warning: no session_id in prompt $i — next prompt starts fresh" >&2
    fi
  done

  rm -f "$WS_ROOT"/_prompt_*.txt "$WS_ROOT"/_prompt_*.id

  # aggregate: sum all prompt metrics
  PROMPT_FILES=$(ls "$WS_ROOT"/03_prompt_*_metrics.json | sort -V | tr '\n' ' ')
  python3 - "$WS_ROOT" "$ID" "$COND" $PROMPT_FILES <<'PYEOF'
import json, sys

ws, run_id, cond, *pfiles = sys.argv[1:]
clean   = json.load(open(f"{ws}/01_clean_metrics.json"))
warmup  = json.load(open(f"{ws}/02_warmup_metrics.json"))
prompts = [json.load(open(f)) for f in pfiles]

total_cost = sum(p.get("cost_usd",0) for p in prompts)
total_cc   = sum(p.get("cache_create",0) for p in prompts)
total_cr   = sum(p.get("cache_read",0) for p in prompts)

summary = {
  "id":   run_id,
  "cond": cond,
  "mode": "multi",
  "n_prompts": len(prompts),
  "per_prompt": [
    {
      "n": i+1,
      "cost_usd":     p.get("cost_usd"),
      "cache_create": p.get("cache_create"),
      "cache_read":   p.get("cache_read"),
      "num_turns":    p.get("num_turns"),
    }
    for i, p in enumerate(prompts)
  ],
  "totals": {
    "task_cost_usd":    total_cost,
    "task_cache_create": total_cc,
    "task_cache_read":   total_cr,
    "full_cost_usd":    clean.get("cost_usd",0) + warmup.get("cost_usd",0) + total_cost,
  }
}
print(json.dumps(summary, indent=2))
json.dump(summary, open(f"{ws}/session_summary.json", "w"), indent=2)
PYEOF

fi

echo "=== SESSION SUMMARY ==="
cat "$WS_ROOT/session_summary.json"
