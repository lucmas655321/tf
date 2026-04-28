#!/usr/bin/env bash
# test.sh — riproduce golden_sample.txt da zero usando solo CLI tf
# Risultato atteso: diff 0 tra il file prodotto e golden_sample.txt
set -euo pipefail

# Vai sempre nella directory dello script — funziona ovunque venga chiamato
cd "$(dirname "$0")"

GOLDEN="golden_sample.txt"
WORK="/tmp/tf_test_work.txt"
TF="tf"

pass() { echo "  OK  $1"; }
fail() { echo "FAIL  $1"; exit 1; }

tf_cmd() { printf '%s' "$1" | $TF; }
tf_ok()  {
    local out
    out=$(tf_cmd "$1")
    echo "$out" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('ok') else 1)" \
        || { echo "  cmd: $1"; echo "  out: $out"; fail "$2"; }
}

echo "=== tf idempotency test ==="
echo ""

# ── pulizia ─────────────────────────────────────────────────────────────────
rm -f "$WORK"
touch "$WORK"

# ── T1: scan rileva golden_sample.txt come strutturato ───────────────────────
echo "T1  scan — golden_sample strutturato"
out=$(tf_cmd '{"cmd":"scan","path":"."}')
echo "$out" | python3 -c "
import sys, json
d = json.load(sys.stdin)
files = {f['file']: f for f in d['files']}
assert 'golden_sample.txt' in files, 'golden_sample.txt non trovato in scan'
assert files['golden_sample.txt']['structured'], 'golden_sample.txt non strutturato'
" || fail "T1"
pass "T1"

# ── T2: tree root depth=1 ─────────────────────────────────────────────────────
echo "T2  tree root depth=1 — 3 blocchi top-level"
out=$(tf_cmd '{"cmd":"tree","path":"golden_sample.txt@root","depth":1}')
echo "$out" | python3 -c "
import sys, json
d = json.load(sys.stdin)
items = d['tree']['items']
labels = [i['label'] for i in items if i['type'] == 'block']
assert labels == ['intro','sezione_a','sezione_b'], f'atteso [intro,sezione_a,sezione_b] trovato {labels}'
" || fail "T2"
pass "T2"

# ── T3: getBlock roundtrip ────────────────────────────────────────────────────
echo "T3  getBlock — intro"
out=$(tf_cmd '{"cmd":"getBlock","path":"golden_sample.txt@root/intro"}')
echo "$out" | python3 -c "
import sys, json
text = json.load(sys.stdin)['content']
assert 'TextFolding struttura documenti' in text, f'testo intro non trovato: {text!r}'
" || fail "T3"
pass "T3"

# ── T4: search ────────────────────────────────────────────────────────────────
echo "T4  search pattern 'idempotenza'"
out=$(tf_cmd '{"cmd":"search","path":"golden_sample.txt@root","pattern":"idempotenza"}')
echo "$out" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['ok'], 'search fallita'
assert len(d['results']) > 0, 'nessun risultato per idempotenza'
" || fail "T4"
pass "T4"

# ── T5: costruzione da zero → diff 0 ─────────────────────────────────────────
echo "T5  costruzione da zero → diff con golden = 0"

# step 5.0 — init: crea struttura root nel file vuoto
tf_ok '{"cmd":"init","path":"'"$WORK"'","write":true}' "T5 init"

# step 5.1 — struttura completa in un colpo
tf_ok '{
  "cmd": "editText",
  "path": "'"$WORK"'@root",
  "text": "Riga fuori da tutto — livello root.\n[intro]\n[sezione_a]\n[sezione_b]\nAltra riga root fuori da blocchi.",
  "newBlocks": {
    "intro":       "TextFolding struttura documenti in blocchi navigabili.\nOgni blocco ha un path univoco e può contenere sotto-blocchi.",
    "sezione_a":   "[sotto_a1]\n[sotto_a2]",
    "sotto_a1":    "Primo sotto-blocco di sezione_a.\nContenuto riga 1.\nContenuto riga 2.",
    "sotto_a2":    "Secondo sotto-blocco di sezione_a.\nUna sola riga di testo.",
    "sezione_b":   "[sotto_b1]\n[conclusione]",
    "sotto_b1":    "Unico sotto-blocco di sezione_b.\nTre righe.\nFine.",
    "conclusione": "Fine del documento golden sample.\nUsato come riferimento per i test di idempotenza."
  },
  "write": true
}' "T5 editText root"

diff "$GOLDEN" "$WORK" || fail "T5 diff non zero"
pass "T5"

# ── T6: editText modifica + ripristino ────────────────────────────────────────
echo "T6  editText modifica → ripristino → diff 0"

tf_ok '{
  "cmd": "editText",
  "path": "'"$WORK"'@root/intro",
  "text": "RIGA MODIFICATA.",
  "write": true
}' "T6 modifica intro"

# verifica che sia cambiato
out=$(tf_cmd '{"cmd":"getBlock","path":"'"$WORK"'@root/intro"}')
echo "$out" | python3 -c "
import sys,json; t=json.load(sys.stdin)['content']
assert 'RIGA MODIFICATA' in t, 'modifica non applicata'
" || fail "T6 verifica modifica"

# ripristina
tf_ok '{
  "cmd": "editText",
  "path": "'"$WORK"'@root/intro",
  "text": "TextFolding struttura documenti in blocchi navigabili.\nOgni blocco ha un path univoco e può contenere sotto-blocchi.",
  "write": true
}' "T6 ripristino intro"

diff "$GOLDEN" "$WORK" || fail "T6 diff non zero dopo ripristino"
pass "T6"

# ── T7: removeBlock + ricostruzione ───────────────────────────────────────────
echo "T7  removeBlock sotto_a2 → ricostruzione → diff 0"

tf_ok '{
  "cmd": "removeBlock",
  "path": "'"$WORK"'@root/sezione_a/sotto_a2",
  "write": true
}' "T7 removeBlock"

# verifica che non ci sia più
out=$(tf_cmd '{"cmd":"tree","path":"'"$WORK"'@root/sezione_a","depth":1}')
echo "$out" | python3 -c "
import sys,json
items=[i['label'] for i in json.load(sys.stdin)['tree']['items']]
assert 'sotto_a2' not in items, f'sotto_a2 ancora presente: {items}'
" || fail "T7 verifica rimozione"

# ricostruisce sotto_a2
tf_ok '{
  "cmd": "editText",
  "path": "'"$WORK"'@root/sezione_a",
  "text": "[sotto_a1]\n[sotto_a2]",
  "newBlocks": {
    "sotto_a2": "Secondo sotto-blocco di sezione_a.\nUna sola riga di testo."
  },
  "write": true
}' "T7 ricostruzione sotto_a2"

diff "$GOLDEN" "$WORK" || fail "T7 diff non zero dopo ricostruzione"
pass "T7"

# ── T8: renameBlock + rename inverso ──────────────────────────────────────────
echo "T8  renameBlock sotto_b1 → tmp → sotto_b1 → diff 0"

tf_ok '{
  "cmd": "renameBlock",
  "path": "'"$WORK"'@root/sezione_b/sotto_b1",
  "newLabel": "tmp_block",
  "write": true
}' "T8 rename a tmp"

tf_ok '{
  "cmd": "renameBlock",
  "path": "'"$WORK"'@root/sezione_b/tmp_block",
  "newLabel": "sotto_b1",
  "write": true
}' "T8 rename a sotto_b1"

diff "$GOLDEN" "$WORK" || fail "T8 diff non zero dopo rename inverso"
pass "T8"

# ── T9: session channel ───────────────────────────────────────────────────────
echo "T9  setSession focus_ai → state.json aggiornato → cleanSession → rimosso"
AGENT_ID="test-agent-t9"
SESSION_JSON="/tmp/.tf/sessions/$AGENT_ID/state.json"

tf_ok '{
  "cmd": "setSession",
  "file": "'"$WORK"'",
  "agentId": "'"$AGENT_ID"'",
  "data": {"focus_ai": "root/intro", "kind": "ai"}
}' "T9 setSession"

# verifica che state.json esista e contenga focus_ai
python3 -c "
import json
d = json.load(open('$SESSION_JSON'))
assert d.get('focus_ai') == 'root/intro', f'focus_ai non trovato in {d}'
assert d.get('kind') == 'ai', f'kind errato: {d}'
" || fail "T9 focus_ai non in state.json"

# file sorgente NON deve essere toccato
diff "$GOLDEN" "$WORK" || fail "T9 setSession ha modificato il file sorgente"

tf_ok '{
  "cmd": "cleanSession",
  "file": "'"$WORK"'",
  "agentId": "'"$AGENT_ID"'"
}' "T9 cleanSession"

python3 -c "
import os
assert not os.path.exists('$SESSION_JSON'), 'state.json ancora presente dopo cleanSession'
" || fail "T9 state.json ancora presente dopo cleanSession"

diff "$GOLDEN" "$WORK" || fail "T9 diff non zero dopo cleanSession"
pass "T9"

# ── T11: tf_get_miller_state legge focus_user da sessions/miller/state.json ───
echo "T11 get_miller_state — focus_user da sessions/miller/state.json"
MILLER_SESSION_DIR="/tmp/.tf/sessions/miller"
MILLER_SESSION_JSON="$MILLER_SESSION_DIR/state.json"
mkdir -p "$MILLER_SESSION_DIR"
python3 -c "
import json, time
state = {
    'agent_id': 'miller',
    'kind': 'user',
    'file': '/tmp/tf_test_work.txt',
    'focus_user': 'root/sezione_b',
    'started': int(time.time()),
    'last_active': int(time.time()),
}
with open('$MILLER_SESSION_JSON', 'w') as f:
    json.dump(state, f)
"

out=$(tf_cmd '{"cmd":"getSession","file":"'"$WORK"'","agentId":"miller"}')
echo "$out" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('ok'), f'getSession fallita: {d}'
s = d.get('state', {})
assert s.get('focus_user') == 'root/sezione_b', f'focus_user errato: {s}'
assert s.get('kind') == 'user', f'kind errato: {s}'
" || fail "T11 focus_user non corretto in sessions/miller/state.json"

rm -f "$MILLER_SESSION_JSON"
pass "T11"

# ── T12: canale bidirezionale AI↔Miller ───────────────────────────────────────
echo "T12 canale AI<->Miller — focus_ai scritto da AI, focus_user scritto da Miller"
MILLER_SESSION_DIR="/tmp/.tf/sessions/miller"
MILLER_SESSION_JSON="$MILLER_SESSION_DIR/state.json"

# AI scrive focus_ai
tf_ok '{
  "cmd": "setSession",
  "file": "'"$WORK"'",
  "agentId": "miller",
  "data": {"focus_ai": "root/intro", "kind": "ai"}
}' "T12 AI scrive focus_ai"

# Miller scrive focus_user (merge sullo stesso file)
tf_ok '{
  "cmd": "setSession",
  "file": "'"$WORK"'",
  "agentId": "miller",
  "data": {"focus_user": "root/sezione_a", "kind": "user"}
}' "T12 Miller scrive focus_user"

# verifica che entrambi i campi coesistano nello stesso state.json
python3 -c "
import json
d = json.load(open('$MILLER_SESSION_JSON'))
assert d.get('focus_ai') == 'root/intro', f'focus_ai perso dopo scrittura Miller: {d}'
assert d.get('focus_user') == 'root/sezione_a', f'focus_user non scritto: {d}'
" || fail "T12 canale bidirezionale: campi mancanti in state.json"

# file sorgente NON deve essere toccato
diff "$GOLDEN" "$WORK" || fail "T12 setSession ha modificato il file sorgente"

tf_ok '{
  "cmd": "cleanSession",
  "file": "'"$WORK"'",
  "agentId": "miller"
}' "T12 cleanSession miller"

python3 -c "
import os
assert not os.path.exists('$MILLER_SESSION_JSON'), 'state.json miller ancora presente dopo cleanSession'
" || fail "T12 state.json miller non rimosso"

pass "T12"

# ── T10: health ───────────────────────────────────────────────────────────────
echo "T10 health — nessun blocco long su golden_sample"

out=$(tf_cmd '{"cmd":"health","path":"golden_sample.txt","threshold":50}')
echo "$out" | python3 -c "
import sys,json
d=json.load(sys.stdin)
assert d['ok'], 'health fallita'
assert d['long_blocks'] == [], f'long_blocks inattesi: {d[\"long_blocks\"]}'
" || fail "T10"
pass "T10"

# ── cleanup ───────────────────────────────────────────────────────────────────
rm -f "$WORK"

echo ""
echo "=== tutti i test passati ==="
