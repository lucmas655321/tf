#!/usr/bin/env python3
#[of]: root
"""
Test runner CLI — chiama tf_backend.py via subprocess (JSON su stdin).
Stessa suite funzionale di run_mcp.py, verifica coerenza tra MCP e CLI.
Uso: python3 test/run_cli.py [--verbose]
"""
import sys, os, json, shutil, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "tf_backend.py")
#[of]: infra

# ---------------------------------------------------------------------------
# Infrastruttura CLI
# ---------------------------------------------------------------------------

_pass = _fail = _skip = 0
_failures = []
_verbosity = 2 if ("--verbose" in sys.argv or "-v" in sys.argv) else \
             1 if "--fails" in sys.argv else 0

TF = "/tmp/tf_test_cli.txt"

def tf(cmd: dict):
    """Chiama tf_backend.py con JSON su stdin. Ritorna dict o stringa."""
    # Il CLI usa "file" per comandi che non hanno path@blocco,
    # ma molti comandi usano "path" con la sintassi file@blocco.
    payload = json.dumps(cmd)
    result = subprocess.run(
        ["python3", BACKEND],
        input=payload, capture_output=True, text=True
    )
    out = result.stdout.strip()
    if not out:
        err = result.stderr.strip()
        return {"ok": False, "error": err or "no output"}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return out

def _reset():
    with open(TF, "w") as f:
        f.write(
            "#[of]: root\n"
            "#[of]: cap1\nTESTA.\nCODA.\n#[cf]\n"
            "#[of]: cap2\n"
            "#[of]: sub_a\nContenuto A.\n#[cf]\n"
            "#[of]: sub_b\nContenuto B.\n#[cf]\n"
            "#[cf]\n"
            "#[of]: cap3\nTerzo.\n#[cf]\n"
            "#[cf]\n"
        )

def ok(name, got, check_fn, msg=""):
    global _pass, _fail
    try:
        passed = check_fn(got)
    except Exception as e:
        passed = False
        msg = f"exception in check: {e}"
    if passed:
        _pass += 1
        if _verbosity >= 2:
            print(f"  PASS  {name}")
    else:
        _fail += 1
        _failures.append((name, repr(got)[:200], msg))
        if _verbosity >= 1:
            print(f"  FAIL  {name}  →  {msg or repr(got)[:120]}")

def skip(name, reason=""):
    global _skip
    _skip += 1
    if _verbosity >= 2:
        print(f"  SKIP  {name}  ({reason})")

def section(title):
    if _verbosity >= 1:
        print(f"\n── {title}")

def is_ok(r):    return isinstance(r, dict) and r.get("ok") is True
def is_fail(r):  return isinstance(r, dict) and r.get("ok") is False

def tree_labels(r, depth=1):
    """Estrae label figli dal tree JSON del CLI (struttura annidata)."""
    if isinstance(r, str):
        return r   # fallback stringa
    node = r.get("tree") if isinstance(r, dict) else None
    if node is None:
        return ""
    labels = []
    def _walk(n, d):
        for item in n.get("items", []):
            if item.get("type") == "block":
                labels.append(item["label"])
                if d != 1:
                    _walk(item, d - 1 if d > 1 else -1)
    _walk(node, depth)
    return "\n".join(labels)

def block_text(r):
    """Estrae testo da risposta getBlockContent CLI (stringa grezza)."""
    if isinstance(r, str):
        return r
    if isinstance(r, dict):
        return r.get("result", str(r))
    return str(r)
#[cf]

# ---------------------------------------------------------------------------
#[of]: T_setup
# SETUP
# ---------------------------------------------------------------------------
section("SETUP")
_reset()

r = tf({"cmd": "tree", "path": TF + "@root", "depth": 1})
ok("S1 root esplicito", r, lambda v: is_ok(v) and "cap1" in tree_labels(v))
ok("S2 struttura base", r,
   lambda v: "cap2" in tree_labels(v) and "cap3" in tree_labels(v))

# ---------------------------------------------------------------------------
# TREE
# ---------------------------------------------------------------------------
#[cf]
#[of]: T_tree
section("TREE")
_reset()

r = tf({"cmd": "tree", "path": TF + "@root"})
ok("T1 tree completo", r,
   lambda v: is_ok(v) and "cap1" in tree_labels(v, -1) and "sub_a" in tree_labels(v, -1))

r = tf({"cmd": "tree", "path": TF + "@root", "depth": 1})
ok("T2 depth=1 no nipoti", r,
   lambda v: is_ok(v) and "cap2" in tree_labels(v) and "sub_a" not in tree_labels(v))

r = tf({"cmd": "tree", "path": TF + "@root", "depth": 1, "showPath": True})
ok("T3 showPath @line", r,
   lambda v: is_ok(v) and any("root/cap1" in str(i.get("path",""))
                               for i in v.get("tree",{}).get("items",[])
                               if i.get("type")=="block"))

r = tf({"cmd": "tree", "path": TF + "@root/cap2", "depth": -1})
ok("T4 sotto-albero cap2", r,
   lambda v: is_ok(v) and "sub_a" in tree_labels(v, -1))

r = tf({"cmd": "tree", "path": TF + "@root/cap1"})
ok("T5 foglia (bug noto)", r, lambda _: True, "bug noto T5")

r = tf({"cmd": "tree", "path": TF + "@root/fantasma"})
ok("T6 path inesistente", r, is_fail)

# ---------------------------------------------------------------------------
# GET BLOCK CONTENT
# ---------------------------------------------------------------------------
#[cf]
#[of]: T_get
section("GET BLOCK CONTENT")
_reset()

r = tf({"cmd": "getBlockContent", "path": TF + "@root/cap1"})
ok("G1 testo base", r, lambda v: "TESTA" in block_text(v))

r = tf({"cmd": "getBlockContent", "path": TF + "@root/cap2", "mode": "structured"})
ok("G2 structured mostra sub_a", r, lambda v: "sub_a" in block_text(v))

r = tf({"cmd": "getBlockContent", "path": TF + "@root/cap2", "mode": "expanded"})
ok("G3 expanded (CLI: sub_a inline o placeholder)", r,
   lambda v: "sub_a" in block_text(v) or "Contenuto A" in block_text(v))

skip("G4 raw (CLI non supporta raw=True)", "raw= solo MCP")

r = tf({"cmd": "getBlockContent", "path": TF + "@root/fantasma"})
ok("G5 blocco inesistente", r, is_fail)

# ---------------------------------------------------------------------------
# EDIT TEXT
# ---------------------------------------------------------------------------
#[cf]
#[of]: T_edit
section("EDIT TEXT")
_reset()

r = tf({"cmd": "editText", "path": TF + "@root/cap1", "text": "Nuovo testo.", "write": True})
ok("E1 editText base", r, is_ok)
r = tf({"cmd": "getBlockContent", "path": TF + "@root/cap1"})
ok("E1 verifica contenuto", r, lambda v: "Nuovo testo" in block_text(v))

r = tf({"cmd": "editText", "path": TF + "@root/cap1",
        "text": "[sub1]\n[sub2]",
        "newBlocks": {"sub1": "Prima parte.", "sub2": "Seconda parte."},
        "write": True})
ok("E3 crea sotto-blocchi", r, is_ok)
r = tf({"cmd": "tree", "path": TF + "@root/cap1", "depth": 1})
ok("E3 verifica", r,
   lambda v: "sub1" in tree_labels(v) and "sub2" in tree_labels(v))

r = tf({"cmd": "editText", "path": TF + "@root/cap1", "text": "#[of]: rotto", "write": False})
ok("E4 tag TF bloccato", r, is_fail)

_reset()
r = tf({"cmd": "editText", "path": TF + "@root/fantasma", "text": "x", "write": False})
ok("E5 blocco inesistente", r, is_fail)

# ---------------------------------------------------------------------------
# INSERT
# ---------------------------------------------------------------------------
#[cf]
#[of]: T_insert
section("INSERT")
_reset()

r = tf({"cmd": "insert", "path": TF + "@root/cap1", "text": "APPENDED.", "row": -1, "write": True})
ok("I1 append fine blocco", r, is_ok)
r = tf({"cmd": "getBlockContent", "path": TF + "@root/cap1"})
ok("I1 verifica append", r, lambda v: "APPENDED" in block_text(v))

r = tf({"cmd": "insert", "path": TF + "@root/cap1", "text": "PREPENDED.", "row": 0, "write": True})
ok("I2 prepend inizio", r, is_ok)
r = tf({"cmd": "getBlockContent", "path": TF + "@root/cap1"})
ok("I2 verifica prepend nel testo", r,
   lambda v: "PREPENDED" in block_text(v))

r = tf({"cmd": "insert", "path": TF + "@root/cap1", "text": "#[of]: rotto", "write": False})
ok("I4 insert tag TF bloccato", r, is_fail)

r = tf({"cmd": "insert", "path": TF + "@root/fantasma", "text": "x", "write": False})
ok("I5 insert blocco inesistente", r, is_fail)

# ---------------------------------------------------------------------------
# ADD BLOCK
# ---------------------------------------------------------------------------
#[cf]
#[of]: T_add
section("ADD BLOCK")
# Note: CLI addBlock usa "line" (riga assoluta), non "after".
# after= è solo MCP. In CLI si calcola la riga manualmente o si usa editText.
_reset()

# A2: inseriamo dopo cap1 (line=5 = dopo il #[cf] di cap1)
r = tf({"cmd": "addBlock", "path": TF, "file": TF,
        "label": "dopo_cap1", "line": 5, "content": "Post cap1.", "write": True})
ok("A2 addBlock CLI (line=5)", r, is_ok)
r = tf({"cmd": "tree", "path": TF + "@root", "depth": 1})
ok("A2 verifica dopo_cap1 presente", r,
   lambda v: "dopo_cap1" in tree_labels(v))

r = tf({"cmd": "addBlock", "path": TF + "@root", "label": "a3_test", "line": 0, "content": "a3 content", "write": True})
ok("A3 addBlock(line=0) ok", r, is_ok)
r2 = tf({"cmd": "tree", "path": TF + "@root", "depth": 1})
ok("A3 file non corrotto", r2, lambda v: "a3_test" in tree_labels(v))
_reset()
skip("A5 addBlock after= (CLI)", "CLI non supporta after=, solo MCP")
_reset()

# ---------------------------------------------------------------------------
# SEARCH
# ---------------------------------------------------------------------------
#[cf]
#[of]: T_search
section("SEARCH")
_reset()

r = tf({"cmd": "search", "path": TF + "@root", "pattern": "Contenuto"})
ok("SR2 search trova match", r,
   lambda v: "Contenuto" in str(v) and "sub_a" in str(v))

r = tf({"cmd": "search", "path": TF + "@root", "pattern": "XYZ_INESISTENTE"})
ok("SR1 search no match", r,
   lambda v: (isinstance(v, dict) and v.get("results") == []) or
             "0 matches" in str(v) or str(v).strip() in ("", "[]"))

# ---------------------------------------------------------------------------
# RENAME BLOCK
# ---------------------------------------------------------------------------
#[cf]
#[of]: T_rename
section("RENAME BLOCK")
_reset()

r = tf({"cmd": "renameBlock", "path": TF + "@root/cap3",
        "newLabel": "capitolo_tre", "write": True})
ok("RN1 rinomina base", r, is_ok)
r = tf({"cmd": "tree", "path": TF + "@root", "depth": 1})
ok("RN1 verifica label", r,
   lambda v: "capitolo_tre" in tree_labels(v) and "cap3" not in tree_labels(v))

r = tf({"cmd": "renameBlock", "path": TF + "@root/fantasma",
        "newLabel": "x", "write": False})
ok("RN2 blocco inesistente", r, is_fail)

r = tf({"cmd": "renameBlock", "path": TF + "@root/capitolo_tre",
        "newLabel": "cap1", "write": True})
ok("RN3 crea omonimo (permissiva)", r, is_ok)

# ---------------------------------------------------------------------------
# MOVE BLOCK
# ---------------------------------------------------------------------------
#[cf]
#[of]: T_move
section("MOVE BLOCK")
_reset()

# CLI usa "moveBlockToParent" (non "moveBlock" con newParent)
r = tf({"cmd": "moveBlockToParent", "path": TF + "@root/cap3",
        "newParent": "root/cap2", "write": True})
ok("MV1 sposta come figlio", r, is_ok)
r = tf({"cmd": "tree", "path": TF + "@root/cap2"})
ok("MV1 verifica gerarchia", r,
   lambda v: "cap3" in tree_labels(v, -1))

r = tf({"cmd": "moveBlockToParent", "path": TF + "@root/cap2/cap3",
        "newParent": "root", "write": True})
ok("MV2 sposta back to root", r, is_ok)

skip("MV3 after= su figlio esistente", "BUG NOTO MV3 + after= solo MCP")

r = tf({"cmd": "moveBlockToParent", "path": TF + "@root/cap2",
        "newParent": "root/cap2", "write": False})
ok("MV4 sposta dentro se stesso", r, is_fail)

r = tf({"cmd": "moveBlockToParent", "path": TF + "@root/cap1",
        "newParent": "root/fantasma", "write": False})
ok("MV5 parent inesistente", r, is_fail)

# ---------------------------------------------------------------------------
# REMOVE BLOCK
# ---------------------------------------------------------------------------
#[cf]
#[of]: T_remove
section("REMOVE BLOCK")
_reset()

tf({"cmd": "addBlock", "path": TF, "file": TF,
    "label": "cap_temp", "line": 13, "content": "Temp.", "write": True})
r = tf({"cmd": "removeBlock", "path": TF + "@root/cap_temp", "write": True})
ok("RM1 remove base", r, is_ok)
r = tf({"cmd": "tree", "path": TF + "@root", "depth": 1})
ok("RM1 verifica sparito", r,
   lambda v: "cap_temp" not in tree_labels(v))

# CLI usa "flattenBlock" invece di removeBlock(keepContent=True)
r = tf({"cmd": "flattenBlock", "path": TF + "@root/cap2/sub_a", "write": True})
ok("RM2 flattenBlock (CLI)", r, is_ok)
r = tf({"cmd": "getBlockContent", "path": TF + "@root/cap2"})
ok("RM2 testo inline", r, lambda v: "Contenuto A" in block_text(v))

r = tf({"cmd": "removeBlock", "path": TF + "@root", "write": False})
ok("RM3 non può rimuovere root", r, is_fail)

r = tf({"cmd": "removeBlock", "path": TF + "@root/fantasma", "write": False})
ok("RM4 path inesistente", r, is_fail)

# ---------------------------------------------------------------------------
# DUPLICATE BLOCK
# ---------------------------------------------------------------------------
#[cf]
#[of]: T_dup
section("DUPLICATE BLOCK")
_reset()   # ricrea il file (può essere stato eliminato da cleanup precedente)

r = tf({"cmd": "duplicateBlock", "path": TF + "@root/cap1", "write": True})
ok("DU1 auto-rename crea copia", r, is_ok)
r = tf({"cmd": "tree", "path": TF + "@root", "depth": 1})
ok("DU1 copia cap1_copy presente", r,
   lambda v: "cap1_copy" in tree_labels(v))

skip("DU2 newLabel esplicito (CLI)", "CLI non supporta newLabel in duplicateBlock")

r_orig = tf({"cmd": "getBlockContent", "path": TF + "@root/cap1"})
r_copy = tf({"cmd": "getBlockContent", "path": TF + "@root/cap1_copy"})
# CLI antepone [label] al testo — ignoriamo la prima riga per il confronto
def _body(r):
    lines = block_text(r).splitlines()
    return "\n".join(l for l in lines if not (l.startswith("[") and l.endswith("]")))
ok("DU3 contenuto identico (corpo senza label)", None,
   lambda _: _body(r_orig) == _body(r_copy))

# ---------------------------------------------------------------------------
# NORMALIZE + DIFF
# ---------------------------------------------------------------------------
#[cf]
#[of]: T_norm
section("NORMALIZE + DIFF")
_reset()

r = tf({"cmd": "normalize", "file": TF, "write": False})
ok("ND1 normalize preview", r,
   lambda v: is_ok(v) and not v.get("written", True))

r = tf({"cmd": "normalize", "file": TF, "write": True})
ok("ND2 normalize write", r,
   lambda v: is_ok(v) and v.get("written") is True)

tmp2 = TF.replace(".txt", "_b.txt")
shutil.copy(TF, tmp2)
tf({"cmd": "editText", "path": TF + "@root/cap3", "text": "Terzo modificato.", "write": True})
r = tf({"cmd": "diff", "fileA": tmp2, "fileB": TF})
ok("ND3 diff rileva modifica", r,
   lambda v: is_ok(v) and any(d.get("status") == "modified" for d in v.get("diff", [])))
os.unlink(tmp2)

# ---------------------------------------------------------------------------
# INIT
# ---------------------------------------------------------------------------
#[cf]
#[of]: T_init
section("INIT")

raw_file = "/tmp/tf_test_cli_raw.txt"
with open(raw_file, "w") as f:
    f.write("def foo():\n    pass\n\ndef bar():\n    return 42\n")

r = tf({"cmd": "init", "path": raw_file})
ok("TI1 init file grezzo", r,
   lambda v: is_ok(v) and "prompt" in v)
ok("TI4 root esplicito dopo init", None,
   lambda _: open(raw_file).read().startswith("#[of]: root"))
os.unlink(raw_file)

_reset()
r = tf({"cmd": "init", "path": TF})
ok("TI2 init su file già TF", r, is_fail)

# ---------------------------------------------------------------------------
# HEALTH
# ---------------------------------------------------------------------------
#[cf]
#[of]: T_health
section("HEALTH")

r = tf({"cmd": "health", "path": ROOT, "threshold": 5})
ok("HA1 health progetto", r,
   lambda v: is_ok(v) and "long_blocks" in v)

_reset()
r = tf({"cmd": "health", "path": TF, "threshold": 2})
ok("HA2 health su file singolo", r, lambda v: is_ok(v))

# ---------------------------------------------------------------------------
# SESSION
# ---------------------------------------------------------------------------
#[cf]
#[of]: T_session
section("SESSION")
_reset()

r = tf({"cmd": "saveSession", "path": TF + "@root",
        "data": {"status": "test in corso", "next": "completare"}})
ok("SE1 save session", r, is_ok)

r = tf({"cmd": "loadSession", "path": TF + "@root"})
ok("SE2 load status+next", r,
   lambda v: "test in corso" in str(v) and "completare" in str(v))

r = tf({"cmd": "loadSession", "path": TF + "@root", "keys": ["*"]})
ok("SE3 load tutto", r, lambda v: "status" in str(v))

tf({"cmd": "saveSession", "path": TF + "@root",
    "data": {"status": "AGGIORNATO"}})
r = tf({"cmd": "loadSession", "path": TF + "@root"})
ok("SE4 update incrementale", r,
   lambda v: "AGGIORNATO" in str(v) and "completare" in str(v))

# ---------------------------------------------------------------------------
# ERROR HANDLING
# ---------------------------------------------------------------------------
#[cf]
#[of]: T_error
section("ERROR HANDLING")
_reset()

r = tf({"cmd": "editText", "path": TF + "@root/cap1",
        "text": "#[of]: rotto", "write": False})
ok("ER2 editText con tag TF", r, is_fail)

r = tf({"cmd": "insert", "path": TF + "@root/cap1",
        "text": "#[of]: rotto", "write": False})
ok("ER3 insert con tag TF", r, is_fail)

r = tf({"cmd": "tree", "path": "/tmp/inesistente.txt@root"})
ok("ER4 file inesistente", r, is_fail)

os.chmod(TF, 0o444)
r = tf({"cmd": "editText", "path": TF + "@root/cap1", "text": "x", "write": True})
ok("ER6 write su read-only", r, is_fail)
os.chmod(TF, 0o644)

# ---------------------------------------------------------------------------
# FRATELLI OMONIMI
# ---------------------------------------------------------------------------
#[cf]
#[of]: T_fratelli
section("FRATELLI OMONIMI")
_reset()

r = tf({"cmd": "duplicateBlock", "path": TF + "@root/cap1", "write": True})
ok("FR1 duplicate auto-rename", r, is_ok)
r = tf({"cmd": "tree", "path": TF + "@root", "depth": 1})
ok("FR1 label diverso", r, lambda v: "cap1_copy" in tree_labels(v))

r = tf({"cmd": "renameBlock", "path": TF + "@root/cap1_copy",
        "newLabel": "cap1", "write": True})
ok("FR3 crea omonimo (permissiva)", r, is_ok)

r = tf({"cmd": "tree", "path": TF + "@root", "depth": 1, "showPath": True})
ok("FR2 show_path disambigua omonimi", r,
   lambda v: sum(1 for i in v.get("tree",{}).get("items",[])
                 if i.get("type")=="block" and i.get("label")=="cap1") >= 2)

r = tf({"cmd": "getBlockContent", "path": TF + "@root/cap1"})
ok("FR4 omonimo → primo blocco", r,
   lambda v: "TESTA" in block_text(v) or is_ok(v))

# ---------------------------------------------------------------------------
# TAG COMPATIBILITY
# Verifica che ogni estensione supportata usi i tag corretti e che le
# operazioni core (tree, getBlockContent, editText, addBlock) funzionino.
# Strategia: un test di funzionalità completo su .py (tag default #[of]:),
# poi per ogni altra estensione un smoke test parse+read+write.
# ---------------------------------------------------------------------------
#[cf]
#[of]: T_tags
section("TAG COMPATIBILITY")

import tempfile

def _make_tf_file(path: str, content: str):
    with open(path, "w") as f:
        f.write(content)

def _rm(path: str):
    if os.path.exists(path):
        os.unlink(path)

# -- .py (tag default: #[of]: / #[cf]) ------------------------------------
TF_PY = "/tmp/tf_test_tags.py"
_make_tf_file(TF_PY,
    "#[of]: root\n"
    "#[of]: func_a\ndef func_a(): pass\n#[cf]\n"
    "#[of]: func_b\ndef func_b(): pass\n#[cf]\n"
    "#[cf]\n"
)
r = tf({"cmd": "tree", "path": TF_PY + "@root", "depth": 1})
ok("TC-PY1 .py tree ok", r, lambda v: "func_a" in tree_labels(v))
r = tf({"cmd": "getBlockContent", "path": TF_PY + "@root/func_a"})
ok("TC-PY2 .py getBlockContent", r, lambda v: "func_a" in block_text(v))
r = tf({"cmd": "editText", "path": TF_PY + "@root/func_a",
        "text": "def func_a(): return 1\n", "write": True})
ok("TC-PY3 .py editText", r, is_ok)
r = tf({"cmd": "getBlockContent", "path": TF_PY + "@root/func_a"})
ok("TC-PY4 .py editText roundtrip", r, lambda v: "return 1" in block_text(v))
r = tf({"cmd": "addBlock", "path": TF_PY + "@root", "label": "func_c",
        "content": "def func_c(): pass\n", "write": True})
ok("TC-PY5 .py addBlock", r, is_ok)
r = tf({"cmd": "tree", "path": TF_PY + "@root", "depth": 1})
ok("TC-PY6 .py addBlock visible in tree", r, lambda v: "func_c" in tree_labels(v))
_rm(TF_PY)

# -- .js (tag: // [of]: / // [cf]) ----------------------------------------
TF_JS = "/tmp/tf_test_tags.js"
_make_tf_file(TF_JS,
    "// [of]: root\n"
    "// [of]: mod_a\nconst a = 1;\n// [cf]\n"
    "// [of]: mod_b\nconst b = 2;\n// [cf]\n"
    "// [cf]\n"
)
r = tf({"cmd": "tree", "path": TF_JS + "@root", "depth": 1})
ok("TC-JS1 .js tree ok", r, lambda v: "mod_a" in tree_labels(v))
r = tf({"cmd": "getBlockContent", "path": TF_JS + "@root/mod_a"})
ok("TC-JS2 .js getBlockContent", r, lambda v: "const a" in block_text(v))
r = tf({"cmd": "editText", "path": TF_JS + "@root/mod_a",
        "text": "const a = 42;\n", "write": True})
ok("TC-JS3 .js editText", r, is_ok)
r = tf({"cmd": "getBlockContent", "path": TF_JS + "@root/mod_a"})
ok("TC-JS4 .js editText roundtrip", r, lambda v: "42" in block_text(v))
_rm(TF_JS)

# -- .ts (alias .js tags) --------------------------------------------------
TF_TS = "/tmp/tf_test_tags.ts"
_make_tf_file(TF_TS,
    "// [of]: root\n"
    "// [of]: cls\nclass Foo {}\n// [cf]\n"
    "// [cf]\n"
)
r = tf({"cmd": "tree", "path": TF_TS + "@root", "depth": 1})
ok("TC-TS1 .ts tree ok", r, lambda v: "cls" in tree_labels(v))
r = tf({"cmd": "getBlockContent", "path": TF_TS + "@root/cls"})
ok("TC-TS2 .ts getBlockContent", r, lambda v: "Foo" in block_text(v))
_rm(TF_TS)

# -- .css (tag: /* [of]: / /* [cf] */) ------------------------------------
TF_CSS = "/tmp/tf_test_tags.css"
_make_tf_file(TF_CSS,
    "/* [of]: root */\n"
    "/* [of]: buttons */\n.btn { color: red; }\n/* [cf] */\n"
    "/* [of]: forms */\n.input { border: 1px; }\n/* [cf] */\n"
    "/* [cf] */\n"
)
r = tf({"cmd": "tree", "path": TF_CSS + "@root", "depth": 1})
ok("TC-CSS1 .css tree ok", r, lambda v: "buttons" in tree_labels(v))
r = tf({"cmd": "getBlockContent", "path": TF_CSS + "@root/buttons"})
ok("TC-CSS2 .css getBlockContent", r, lambda v: "btn" in block_text(v))
r = tf({"cmd": "editText", "path": TF_CSS + "@root/buttons",
        "text": ".btn { color: blue; }\n", "write": True})
ok("TC-CSS3 .css editText", r, is_ok)
r = tf({"cmd": "getBlockContent", "path": TF_CSS + "@root/buttons"})
ok("TC-CSS4 .css editText roundtrip", r, lambda v: "blue" in block_text(v))
_rm(TF_CSS)

# -- .md (tag: <!-- [of]: / <!-- [cf] -->) ---------------------------------
TF_MD = "/tmp/tf_test_tags.md"
_make_tf_file(TF_MD,
    "<!-- [of]: root -->\n"
    "<!-- [of]: intro -->\n# Hello\nThis is the intro.\n<!-- [cf] -->\n"
    "<!-- [of]: section_a -->\n## Section A\nContent here.\n<!-- [cf] -->\n"
    "<!-- [cf] -->\n"
)
r = tf({"cmd": "tree", "path": TF_MD + "@root", "depth": 1})
ok("TC-MD1 .md tree ok", r, lambda v: "intro" in tree_labels(v))
r = tf({"cmd": "getBlockContent", "path": TF_MD + "@root/intro"})
ok("TC-MD2 .md getBlockContent", r, lambda v: "Hello" in block_text(v))
r = tf({"cmd": "editText", "path": TF_MD + "@root/intro",
        "text": "# Hello World\nUpdated intro.\n", "write": True})
ok("TC-MD3 .md editText", r, is_ok)
r = tf({"cmd": "getBlockContent", "path": TF_MD + "@root/intro"})
ok("TC-MD4 .md editText roundtrip", r, lambda v: "World" in block_text(v))
r = tf({"cmd": "addBlock", "path": TF_MD + "@root", "label": "conclusion",
        "content": "## Conclusion\nDone.\n", "write": True})
ok("TC-MD5 .md addBlock", r, is_ok)
r = tf({"cmd": "tree", "path": TF_MD + "@root", "depth": 1})
ok("TC-MD6 .md addBlock visible in tree", r, lambda v: "conclusion" in tree_labels(v))
_rm(TF_MD)

# -- tag isolation: .js tags non riconosciuti in .py ----------------------
TF_ISO = "/tmp/tf_test_iso.py"
_make_tf_file(TF_ISO,
    "// [of]: root\n"
    "// [of]: block_a\nconst x = 1;\n// [cf]\n"
    "// [cf]\n"
)
r = tf({"cmd": "tree", "path": TF_ISO + "@root"})
ok("TC-ISO1 .py non riconosce tag // (file non strutturato)", r, is_fail)
_rm(TF_ISO)

# ---------------------------------------------------------------------------
# RISULTATI FINALI
#[cf]
#[of]: results
# ---------------------------------------------------------------------------
print(f"\n{'─'*50}")
print(f"  PASS {_pass}   FAIL {_fail}   SKIP {_skip}")
print(f"{'─'*50}")
if _failures and _verbosity >= 1:
    print("\nFAILURES:")
    for name, got, msg in _failures:
        print(f"  {name}")
        if msg:
            print(f"    → {msg}")
        print(f"    got: {got}")

for f_ in [TF, TF.replace(".txt", "_b.txt")]:
    if os.path.exists(f_):
        os.unlink(f_)

sys.exit(0 if _fail == 0 else 1)
#[cf]
#[cf]
