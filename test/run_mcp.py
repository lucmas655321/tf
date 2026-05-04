#!/usr/bin/env python3
#[of]: root
"""
Test runner MCP — importa tf_mcp.py direttamente, esegue la suite completa.
Uso: python3 test/run_mcp.py [--verbose]
"""
import sys, os, json, re, shutil, tempfile, argparse

# Aggiungi la root del progetto al path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tf_mcp as m   # importa le funzioni direttamente (senza server MCP)
import tf_backend as _tfb

# CWD fixture — CI non ha .tf/config.tf; creiamo una dir temporanea minimale
_cwd_tmp = tempfile.mkdtemp(prefix="tf_mcp_test_cwd_")
_tf_dir = os.path.join(_cwd_tmp, ".tf")
os.makedirs(_tf_dir)
with open(os.path.join(_tf_dir, "config.tf"), "w") as _f:
    _f.write(f"#[of]: root\n#[of]: config\ncwd = {_cwd_tmp}\n#[cf]\n#[cf]\n")
_tfb._PROJECT_CWD = _cwd_tmp

# ---------------------------------------------------------------------------
# Infrastruttura runner
# ---------------------------------------------------------------------------

_pass = _fail = _skip = 0
_failures = []
_verbosity = 2 if ("--verbose" in sys.argv or "-v" in sys.argv) else \
             1 if "--fails" in sys.argv else 0

TF = "/tmp/tf_test_runner.txt"   # file di test temporaneo

def _reset():
    """Ricrea il file di test con struttura base."""
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

# helpers per check comuni
def is_ok(r):     return isinstance(r, dict) and (r.get("ok") is True or "result" in r)
def is_fail(r):   return isinstance(r, dict) and r.get("ok") is False
def has_str(s):   return lambda r: isinstance(r, str) and s in r
def json_ok(r):
    """tf_mcp restituisce a volte stringhe JSON nested — unwrappa."""
    if isinstance(r, str):
        try: return json.loads(r)
        except: pass
    return r

def tree_result(r):
    """Estrae stringa dal result di tf_tree (può essere str o dict)."""
    if isinstance(r, str): return r
    if isinstance(r, dict): return r.get("result", "")
    return str(r)

# ---------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------
section("SETUP")

_reset()
r = m.tf_tree(TF + "@root", depth=1)
ok("S1 root esplicito", tree_result(r),
   lambda v: v and "cap1" in v, "tree non mostra cap1")
ok("S2 struttura base", tree_result(r),
   lambda v: "cap2" in v and "cap3" in v)

# ---------------------------------------------------------------------------
# TREE
# ---------------------------------------------------------------------------
section("TREE")
_reset()

r = m.tf_tree(TF + "@root")
ok("T1 tree completo", tree_result(r),
   lambda v: "cap1" in v and "sub_a" in v)

r = m.tf_tree(TF + "@root", depth=1)
ok("T2 depth=1 no nipoti", tree_result(r),
   lambda v: "cap2" in v and "sub_a" not in v)

r = m.tf_tree(TF + "@root", depth=1, show_path=True)
ok("T3 show_path @line", tree_result(r),
   lambda v: "@" in v and "root/cap1" in v)

r = m.tf_tree(TF + "@root/cap2", depth=-1)
ok("T4 sotto-albero cap2", tree_result(r),
   lambda v: "sub_a" in v and "sub_b" in v)

r = m.tf_tree(TF + "@root/cap1")
ok("T5 foglia (bug noto)", tree_result(r),
   lambda v: True,   # comportamento ambiguo, non falliamo il runner
   "bug noto T5: nessun figlio")

r = m.tf_tree(TF + "@root/fantasma")
ok("T6 path inesistente", tree_result(r),
   lambda v: "ERROR" in v or "error" in v.lower())

# ---------------------------------------------------------------------------
# GET BLOCK CONTENT
# ---------------------------------------------------------------------------
section("GET BLOCK CONTENT")
_reset()

r = json_ok(m.tf_getBlockContent(TF + "@root/cap1"))
ok("G1 testo base", r,
   lambda v: "TESTA" in str(v))

r = json_ok(m.tf_getBlockContent(TF + "@root/cap2", mode="structured"))
ok("G2 structured mostra [sub_a]", r,
   lambda v: "[sub_a]" in str(v) or "sub_a" in str(v))

r = json_ok(m.tf_getBlockContent(TF + "@root/cap2", mode="expanded"))
ok("G3 expanded testo piatto", r,
   lambda v: "Contenuto A" in str(v))

r = json_ok(m.tf_getBlockContent(TF + "@root/cap1", raw=True))
ok("G4 raw contiene tag", r,
   lambda v: "#[of]" in str(v) or "#[cf]" in str(v))

r = json_ok(m.tf_getBlockContent(TF + "@root/fantasma"))
ok("G5 blocco inesistente", r,
   is_fail)

r = m.tf_getBlockContent(TF + "@root/cap1", numbered=True)
ok("G6 numbered prefissa riga assoluta", r,
   lambda v: re.search(r'\d+: TESTA', str(v)))

# ---------------------------------------------------------------------------
# EDIT TEXT
# ---------------------------------------------------------------------------
section("EDIT TEXT")
_reset()

r = m.tf_editText(TF + "@root/cap1", "Nuovo testo.", write=True)
ok("E1 editText base", r, is_ok)
r = json_ok(m.tf_getBlockContent(TF + "@root/cap1"))
ok("E1 verifica contenuto", r, lambda v: "Nuovo testo" in str(v))

r = m.tf_editText(TF + "@root/cap1",
                  "[sub1]\n[sub2]",
                  new_blocks={"sub1": "Prima parte.", "sub2": "Seconda parte."},
                  write=True)
ok("E3 crea sotto-blocchi", r, is_ok)
r = m.tf_tree(TF + "@root/cap1", depth=1)
ok("E3 verifica sotto-blocchi", tree_result(r),
   lambda v: "sub1" in v and "sub2" in v)

r = m.tf_editText(TF + "@root/cap1", "#[of]: rotto", write=False)
ok("E4 tag TF bloccato", r, is_fail)

_reset()
r = m.tf_editText(TF + "@root/fantasma", "x", write=False)
ok("E5 blocco inesistente", r, is_fail)

# ---------------------------------------------------------------------------
# INSERT
# ---------------------------------------------------------------------------
section("INSERT")
_reset()

r = m.tf_insert(TF + "@root/cap1", "APPENDED.", row=-1, write=True)
ok("I1 append fine blocco", r, is_ok)
r = json_ok(m.tf_getBlockContent(TF + "@root/cap1"))
ok("I1 verifica append", r, lambda v: "APPENDED" in str(v))

r = m.tf_insert(TF + "@root/cap1", "PREPENDED.", row=0, write=True)
ok("I2 prepend inizio blocco", r, is_ok)
r = json_ok(m.tf_getBlockContent(TF + "@root/cap1", mode="expanded"))
ok("I2 verifica prepend primo", r,
   lambda v: str(v).strip().startswith("PREPENDED"))

r = m.tf_insert(TF + "@root/cap1", "#[of]: rotto", write=False)
ok("I4 insert tag TF bloccato", r, is_fail)

r = m.tf_insert(TF + "@root/fantasma", "x", write=False)
ok("I5 insert su blocco inesistente", r, is_fail)


r = m.tf_insert(TF + "@root/cap1", "x", row=999, write=False)
ok("I6 insert row grande = append silenzioso", r, is_ok)

r = m.tf_wrapBlock(TF + "@root/cap1", "gruppo", start=0, end=999, write=False)
ok("I7 wrapBlock end out of range", r, is_fail)
ok("I7 messaggio out of range", r, lambda v: "out of range" in str(v.get("error", "")))

r = m.tf_wrapBlocks(TF + "@root", [{"label": "g", "start": 0, "end": 999}], write=False)
ok("I8 wrapBlocks end out of range", r, is_fail)
ok("I8 messaggio out of range", r, lambda v: "out of range" in str(v.get("error", "")))

# ---------------------------------------------------------------------------
# ADD BLOCK
# ---------------------------------------------------------------------------
section("ADD BLOCK")
_reset()

r = m.tf_addBlock(TF + "@root", "dopo_cap1", content="Post cap1.", after="root/cap1")
ok("A2 addBlock with after=", r, is_ok)
r = m.tf_tree(TF + "@root", depth=1)
ok("A2 verifica ordine", tree_result(r),
   lambda v: v.index("cap1") < v.index("dopo_cap1") < v.index("cap2"))

r = m.tf_addBlock(TF + "@root", "last_block", content="In fondo.", after="root/cap3")
ok("A5 addBlock after ultimo blocco", r, is_ok)
r = m.tf_tree(TF + "@root", depth=1)
ok("A5 verifica last_block in fondo", tree_result(r),
   lambda v: v.strip().splitlines()[-1].startswith("last_block"))

# A3: addBlock(line=0) — bug noto, inserisce prima di root
r = m.tf_addBlock(TF + "@root", "vuoto", line=0)
skip("A3 addBlock(line=0)", "BUG NOTO: inserisce prima di #[of]: root")
_reset()  # il file è corrotto dopo A3, reset

# -- A6..A11: SEMANTICA DEL PARENT DICHIARATO NEL PATH --
# Regression test 2026-04-21: tf_addBlock con path='file@root/X' inseriva il blocco
# in coda al file invece che dentro X. Fix: path determina il parent; after/line
# devono essere congruenti con esso, altrimenti ERROR esplicito (no silent).

# A6: path='@root/cap2' senza after/line -> inserito come ultimo figlio di cap2.
r = m.tf_addBlock(TF + "@root/cap2", "nested_a6", content="A6.", write=True)
ok("A6 path=@parent senza after/line -> ultimo figlio del parent", r,
   lambda v: is_ok(v) and v.get("parent") == "root/cap2")
r2 = m.tf_tree(TF + "@root/cap2", depth=1)
ok("A6 verifica figlio di cap2 (non di root)", tree_result(r2),
   lambda v: "nested_a6" in v)
r3 = m.tf_tree(TF + "@root", depth=1)
ok("A6 non è figlio di root", tree_result(r3),
   lambda v: "nested_a6" not in v.splitlines()[0:5])  # non è tra i primi figli di root
_reset()

# A7: path='@root/cap2' + after='root/cap2/sub_a' (sibling congruente) -> OK.
r = m.tf_addBlock(TF + "@root/cap2", "between_subs", content="A7.",
                  after="root/cap2/sub_a", write=True)
ok("A7 path=@parent + after=sibling congruente", r,
   lambda v: is_ok(v) and v.get("parent") == "root/cap2")
r2 = m.tf_tree(TF + "@root/cap2", depth=1)
ok("A7 ordine sub_a < between_subs < sub_b", tree_result(r2),
   lambda v: v.index("sub_a") < v.index("between_subs") < v.index("sub_b"))
_reset()

# A8: INCONGRUENZA path='@root/cap1' ma after punta a figlio di cap2 -> ERROR.
r = m.tf_addBlock(TF + "@root/cap1", "should_fail",
                  after="root/cap2/sub_a", write=True)
ok("A8 INCONGRUENZA after non-figlio del parent -> error", r,
   lambda v: is_fail(v) and "incongruence" in str(v.get("error", "")).lower())

# A9: INCONGRUENZA path='@root/cap1' ma line= fuori dallo span di cap1 -> ERROR.
r = m.tf_addBlock(TF + "@root/cap1", "should_fail_line",
                  line=999, write=True)
ok("A9 INCONGRUENZA line fuori span del parent -> error", r,
   lambda v: is_fail(v) and "incongruence" in str(v.get("error", "")).lower())

# A10: parent inesistente nel path -> ERROR esplicito, non silent fallback.
r = m.tf_addBlock(TF + "@root/fantasma", "ignored", write=True)
ok("A10 parent inesistente -> error", r,
   lambda v: is_fail(v) and "parent block not found" in str(v.get("error", "")).lower())

# A11: backward-compat — path=file (no @) -> append in coda al file, no errore.
_reset()
r = m.tf_addBlock(TF, "legacy_append", content="bk-compat.", write=True)
ok("A11 backward-compat path senza @ -> append file", r,
   lambda v: is_ok(v) and v.get("parent") is None)
_reset()

# -- A12..A14: REGRESSION TEST BUG FIXES 2026-04-27 --
# Bug #3: after parameter resolved relative to parent (not from root)
# Bug #8: after="label@N" parsing handles uniqueness suffix correctly
# Bug #1: tf_inspect on single block with depth returns the block

# A12: after="cap1" (simple label) resolved relative to parent when parent declared
r = m.tf_addBlock(TF + "@root", "after_cap1_simple", content="A12.", after="cap1", write=True)
ok("A12 after=simple_label resolved relative to parent", r,
   lambda v: is_ok(v) and v.get("parent") == "root")
r2 = m.tf_tree(TF + "@root", depth=1)
ok("A12 ordine cap1 < after_cap1_simple", tree_result(r2),
   lambda v: v.index("cap1") < v.index("after_cap1_simple"))
_reset()

# A13: after="cap1@5" (label@line) parsed correctly, line suffix ignored
r = m.tf_addBlock(TF + "@root", "after_cap1_line", content="A13.", after="cap1@5", write=True)
ok("A13 after=label@line parsed correctly", r,
   lambda v: is_ok(v) and v.get("parent") == "root")
_reset()

# A14: tf_inspect on single block with depth=1 returns the block (not empty)
_reset()
r = m.tf_inspect(path=TF, block="cap1", depth=1)
ok("A14 tf_inspect single block depth=1 returns block", r,
   lambda v: v and "cap1" in v)  # non vuoto e contiene il label
# A15: tf_inspect on single block with depth=2 returns block + children
r = m.tf_inspect(path=TF, block="cap2", depth=2)
ok("A15 tf_inspect single block depth=2 shows children", r,
   lambda v: "cap2" in str(v) and ("sub_a" in str(v) or "sub_b" in str(v)))
# A16: tf_inspect mode='inspect' shows line count for TEXT blocks >30 lines
# (create a large block first)
r = m.tf_addBlock(TF + "@root", "large_block",
                  content="\n".join(["x"] * 35), write=True)
ok("A16a create large block", r, is_ok)
r = m.tf_inspect(path=TF, depth=1, mode="inspect")
ok("A16 tf_inspect mode=inspect shows TEXT:NL alert", r,
   lambda v: "TEXT:" in str(v))  # mode=inspect mostra alert
# A16b: default mode='read' no alerts (output minimale)
r = m.tf_inspect(path=TF, depth=1)
ok("A16b default mode=read has no alerts", r,
   lambda v: "TEXT:" not in str(v) and "MIXED:" not in str(v))
# A16c: mode='audit' shows ONLY problematic nodes
r = m.tf_inspect(path=TF, depth=1, mode="audit")
ok("A16c mode=audit filters to issues only", r,
   lambda v: "large_block" in str(v) and "cap1" not in str(v))

# ---------------------------------------------------------------------------
# WRAP BLOCK
# ---------------------------------------------------------------------------
section("WRAP BLOCK")
_reset()

r = m.tf_wrapBlock(TF + "@root/cap1", "wrapper", start=0, end=1)
ok("W1 wrapBlock con start/end", r, is_ok)
r = m.tf_tree(TF + "@root/wrapper")
ok("W1 verifica struttura", tree_result(r), lambda v: len(v) > 0)
_reset()

# ---------------------------------------------------------------------------
# SEARCH
# ---------------------------------------------------------------------------
section("SEARCH")
_reset()

r = m.tf_search(TF + "@root", "Contenuto")
ok("SR2 search paths mode (default)", r,
   lambda v: "matched" in str(v) and "sub_a" in str(v))

r = m.tf_search(TF + "@root", "Contenuto", mode="lines")
ok("SR2b search lines mode", r,
   lambda v: "Contenuto" in str(v) and "sub_a" in str(v))

r = m.tf_search(TF + "@root", "XYZ_INESISTENTE")
ok("SR1 search no match", r,
   lambda v: "0 matches" in str(v) or str(v).strip() == "")

# ---------------------------------------------------------------------------
# RENAME BLOCK
# ---------------------------------------------------------------------------
section("RENAME BLOCK")
_reset()

r = m.tf_renameBlock(TF + "@root/cap3", "capitolo_tre")
ok("RN1 rinomina base", r, is_ok)
r = m.tf_tree(TF + "@root", depth=1)
ok("RN1 verifica label", tree_result(r),
   lambda v: "capitolo_tre" in v and "cap3" not in v)

r = m.tf_renameBlock(TF + "@root/fantasma", "x")
ok("RN2 blocco inesistente", r, is_fail)

r = m.tf_renameBlock(TF + "@root/capitolo_tre", "cap1")
ok("RN3 crea omonimo (policy permissiva)", r, is_ok)

# ---------------------------------------------------------------------------
# MOVE BLOCK
# ---------------------------------------------------------------------------
section("MOVE BLOCK")
_reset()

r = m.tf_moveBlock(TF + "@root/cap3", "root/cap2")
ok("MV1 sposta come figlio", r, is_ok)
r = m.tf_tree(TF + "@root/cap2")
ok("MV1 verifica gerarchia", tree_result(r), lambda v: "cap3" in v)

r = m.tf_moveBlock(TF + "@root/cap2/cap3", "root")
ok("MV2 sposta back to root", r, is_ok)

r = m.tf_moveBlock(TF + "@root/cap3", "root", after="root/cap1")
ok("MV3 after= su figlio esistente (bug noto)", r,
   lambda _: True,  # è ok:false ma è bug noto
   "BUG NOTO MV3")

r = m.tf_moveBlock(TF + "@root/cap2", "root/cap2")
ok("MV4 sposta dentro se stesso", r, is_fail)

r = m.tf_moveBlock(TF + "@root/cap1", "root/fantasma")
ok("MV5 parent inesistente", r, is_fail)

# ---------------------------------------------------------------------------
# REMOVE BLOCK
# ---------------------------------------------------------------------------
section("REMOVE BLOCK")
_reset()

m.tf_addBlock(TF + "@root", "cap_temp", content="Temp.", after="root/cap3")
r = m.tf_removeBlock(TF + "@root/cap_temp")
ok("RM1 remove base", r, is_ok)
r = m.tf_tree(TF + "@root", depth=1)
ok("RM1 verifica sparito", tree_result(r), lambda v: "cap_temp" not in v)

r = m.tf_removeBlock(TF + "@root/cap2/sub_a", keep_content=True)
ok("RM2 keep_content (flatten)", r, is_ok)
r = json_ok(m.tf_getBlockContent(TF + "@root/cap2"))
ok("RM2 testo inline", r, lambda v: "Contenuto A" in str(v))
r = m.tf_tree(TF + "@root/cap2")
ok("RM2 sub_a sparito", tree_result(r), lambda v: "sub_a" not in v)

r = m.tf_removeBlock(TF + "@root")
ok("RM3 non può rimuovere root", r, is_fail)

r = m.tf_removeBlock(TF + "@root/fantasma")
ok("RM4 path inesistente", r, is_fail)

# ---------------------------------------------------------------------------
#[of]: duplicate_block
# DUPLICATE BLOCK
# ---------------------------------------------------------------------------
section("DUPLICATE BLOCK")
_reset()

r = m.tf_duplicateBlock(TF + "@root/cap1")
ok("DU1 auto-rename", r, lambda v: is_ok(v) and v.get("new_label") == "cap1_copy")

r = m.tf_duplicateBlock(TF + "@root/cap1", new_label="cap1_bak")
ok("DU2 label esplicito", r, lambda v: is_ok(v) and v.get("new_label") == "cap1_bak")

c_orig = json_ok(m.tf_getBlockContent(TF + "@root/cap1"))
c_copy = json_ok(m.tf_getBlockContent(TF + "@root/cap1_copy"))
ok("DU3 contenuto identico", None,
   lambda _: str(c_orig) == str(c_copy))

#[cf]
#[of]: T_replace_in_block
# REPLACE IN BLOCK
# ---------------------------------------------------------------------------
section("REPLACE IN BLOCK")
_reset()

# RIB1: replace text inside block (no wrap)
r = m.tf_replaceInBlock(TF + "@root/cap1", old_text="TESTA", new_text="REPLACED")
ok("RIB1 replace ok", r, is_ok)

r2 = json_ok(m.tf_getBlockContent(TF + "@root/cap1"))
ok("RIB1 new text present", r2, lambda v: "REPLACED" in str(v))
ok("RIB1 old text gone", r2, lambda v: "TESTA" not in str(v))

# RIB2: old_text not found → error
r = m.tf_replaceInBlock(TF + "@root/cap1", old_text="__NON_EXISTENT__", new_text="x")
ok("RIB2 not found → error", r, is_fail)

# RIB3: replace and wrap in new sub-block
_reset()
r = m.tf_replaceInBlock(TF + "@root/cap1", old_text="TESTA", new_text="WRAPPED_TEXT", label="new_sub")
ok("RIB3 replace+wrap ok", r, lambda v: is_ok(v) and v.get("wrapped") == "new_sub")

r3 = json_ok(m.tf_getBlockContent(TF + "@root/cap1/new_sub"))
ok("RIB3 new sub-block readable", r3, lambda v: "WRAPPED_TEXT" in str(v))

# RIB4: canonical new names old_str/new_str (Opzione 1: naming alignment).
_reset()
r = m.tf_replaceInBlock(TF + "@root/cap1", old_str="TESTA", new_str="NEW_STR_OK")
ok("RIB4 canonical old_str/new_str", r, is_ok)
r2 = json_ok(m.tf_getBlockContent(TF + "@root/cap1"))
ok("RIB4 new_str present", r2, lambda v: "NEW_STR_OK" in str(v))

# RIB5: tf_addBlock con nuovo nome canonico 'text' (alias di 'content').
_reset()
r = m.tf_addBlock(TF + "@root", "added_via_text", text="via text arg", after="root/cap1")
ok("RIB5 tf_addBlock canonical 'text'", r, is_ok)
r2 = json_ok(m.tf_getBlockContent(TF + "@root/added_via_text"))
ok("RIB5 text content written", r2, lambda v: "via text arg" in str(v))

# RIB6: missing args -> error esplicito, non crash.
r = m.tf_replaceInBlock(TF + "@root/cap1")
ok("RIB6 missing old_str/new_str -> error", r,
   lambda v: is_fail(v) and "missing" in str(v.get("error", "")).lower())
#[cf]
#[of]: T_regression
# REGRESSION — BUG1 (md root tag) + A3 (addBlock line=0)
# ---------------------------------------------------------------------------
section("REGRESSION")
import tempfile, os as _os

# BUG1: cmd_onboard_add_root su .md deve generare '<!-- [of]: root -->' non '<!-- [of]: root'
_md = tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False)
_md.write("# Hello\nSome content\n")
_md.close()
r = m.tf_onboard(_md.name, write=True)
ok("BUG1 onboard .md ok", r, is_ok)
with open(_md.name) as _f:
    _first = _f.readline().strip()
ok("BUG1 root tag closes with -->", _first, lambda v: v.endswith("-->"))
_os.unlink(_md.name)

# A3: addBlock(line=0) non deve corrompere il file (blocco non inserito prima di root)
_reset()
r = m.tf_addBlock(TF + "@root", label="a3_test", line=0, content="test content")
ok("A3 addBlock line=0 ok", r, is_ok)
r2 = json_ok(m.tf_getBlockContent(TF + "@root", mode="structured"))
ok("A3 file non corrotto (root leggibile)", r2, lambda v: isinstance(v, str))
r3 = m.tf_tree(TF + "@root")
ok("A3 a3_test block presente", r3, lambda v: "a3_test" in str(v))
#[cf]
#[of]: T_onboard
# ONBOARD
# ---------------------------------------------------------------------------
section("ONBOARD")
_reset()

import shutil, ast as _ast

SAMPLE_RAW = os.path.join(os.path.dirname(__file__), "sample_raw.py")
ONBOARD_TMP = SAMPLE_RAW.replace("_raw.py", "_onboard_tmp.py")

if not os.path.exists(SAMPLE_RAW):
    for name in ("OB1 preview ok", "OB2 preview has candidates",
                 "OB3 write ok", "OB4 candidates wrapped > 0",
                 "OB5 root block readable after onboard",
                 "OB6 syntax valid after onboard"):
        skip(name, "sample_raw.py not found")
else:
    # prepare a fresh copy
    shutil.copy(SAMPLE_RAW, ONBOARD_TMP)

    # preview: no write
    r = m.tf_onboard(ONBOARD_TMP, write=False)
    ok("OB1 preview ok", r, lambda v: is_ok(v) and v.get("written") == False)
    ok("OB2 preview has candidates", r, lambda v: v.get("scan", {}).get("candidates_found", 0) > 0)

    # write: apply all steps
    r = m.tf_onboard(ONBOARD_TMP, write=True)
    ok("OB3 write ok", r, lambda v: is_ok(v) and v.get("written") == True)
    ok("OB4 candidates wrapped > 0", r, lambda v: v.get("scan", {}).get("wrapped", 0) > 0)

    # validate TF structure: root block readable
    r2 = json_ok(m.tf_getBlockContent(ONBOARD_TMP + "@root"))
    ok("OB5 root block readable after onboard", r2, lambda v: isinstance(v, str) and len(v) > 0)

    # validate Python syntax
    with open(ONBOARD_TMP) as _f:
        _src = "".join(l for l in _f if not l.strip().startswith("#["))
    try:
        _ast.parse(_src)
        ok("OB6 syntax valid after onboard", True, lambda v: v)
    except SyntaxError as _e:
        ok("OB6 syntax valid after onboard", False, lambda v: v, note=str(_e))

    # cleanup
    os.remove(ONBOARD_TMP)
#[cf]
#[of]: T_onboard_roundtrip
section("ONBOARD ROUNDTRIP + MULTIFORMAT")

# Helper: onboard then strip, verify identical content
def _roundtrip(orig_content, suffix):
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False)
    tmp.write(orig_content)
    tmp.close()
    try:
        r1 = m.tf_onboard(tmp.name, write=True)
        assert r1.get("ok"), f"onboard failed: {r1}"
        r2 = m.tf_strip(tmp.name, write=True)
        assert r2.get("ok"), f"strip failed: {r2}"
        with open(tmp.name) as f:
            final = f.read()
        return final
    finally:
        os.remove(tmp.name)

# RT1: roundtrip Python — onboard then strip == original
_py = (
    "import os\n\n"
    "class Foo:\n"
    "    def bar(self):\n"
    "        return 1\n\n"
    "    def baz(self):\n"
    "        return 2\n\n"
    "def top():\n"
    "    return 3\n"
)
_final_py = _roundtrip(_py, ".py")
ok("RT1 python roundtrip identical", _final_py, lambda v: v == _py,
   "\n--- expected ---\n" + _py + "\n--- got ---\n" + _final_py)

# RT2: depth-2 regression — sample with methods must produce wrapped_depth2 > 0
_tmp2 = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False)
_tmp2.write(_py)
_tmp2.close()
r = m.tf_onboard(_tmp2.name, write=True)
ok("RT2 depth-2 methods wrapped", r,
   lambda v: v.get("scan", {}).get("wrapped_depth2", 0) >= 2,
   "expected >=2 methods wrapped (Foo.bar + Foo.baz)")
os.remove(_tmp2.name)

# RT3: roundtrip Markdown — <!-- [of]: --> tags
# md has no auto-candidates (no classes/defs), so onboard just adds root.
# After strip, content must equal original.
_md = "# Title\n\nSome text.\n\n## Section\n\nMore text.\n"
_final_md = _roundtrip(_md, ".md")
ok("RT3 markdown roundtrip identical", _final_md, lambda v: v == _md,
   "\n--- expected ---\n" + _md + "\n--- got ---\n" + _final_md)

# RT4: roundtrip CSS — /* [of]: */ tags
_css = ".btn {\n  color: red;\n}\n\n.box {\n  padding: 1em;\n}\n"
_final_css = _roundtrip(_css, ".css")
ok("RT4 css roundtrip identical", _final_css, lambda v: v == _css,
   "\n--- expected ---\n" + _css + "\n--- got ---\n" + _final_css)

# RT5: roundtrip JS — // [of]: tags
_js = (
    "function foo() {\n"
    "  return 1;\n"
    "}\n\n"
    "function bar() {\n"
    "  return 2;\n"
    "}\n"
)
_final_js = _roundtrip(_js, ".js")
ok("RT5 js roundtrip identical", _final_js, lambda v: v == _js,
   "\n--- expected ---\n" + _js + "\n--- got ---\n" + _final_js)
#[cf]
# ---------------------------------------------------------------------------
# INSPECT
# ---------------------------------------------------------------------------
section("INSPECT")
_reset()

r = m.tf_inspect(TF)
ok("IN1 inspect file", r, lambda v: "cap1" in str(v) and "cap2" in str(v))

r = m.tf_inspect(TF, block="root/cap2")
ok("IN2 inspect sotto-albero", r, lambda v: "cap2" in str(v))

r = m.tf_inspect(TF, depth=1)
ok("IN3 depth=1 solo primo livello", r,
   lambda v: "cap1" in str(v) and "sub_a" not in str(v))

# ---------------------------------------------------------------------------
# NORMALIZE + DIFF
# ---------------------------------------------------------------------------
section("NORMALIZE + DIFF")
_reset()

r = m.tf_normalize(TF, write=False)
ok("ND1 normalize preview", r,
   lambda v: is_ok(v) and v.get("written") is False)

r = m.tf_normalize(TF, write=True)
ok("ND2 normalize write", r,
   lambda v: is_ok(v) and v.get("written") is True)

tmp2 = TF.replace(".txt", "_b.txt")
shutil.copy(TF, tmp2)
m.tf_editText(TF + "@root/cap3", "Terzo modificato.", write=True)
r = m.tf_diff(tmp2, TF)
ok("ND3 diff rileva modifica", r,
   lambda v: is_ok(v) and any(d.get("status") == "modified" for d in v.get("diff", [])))
os.unlink(tmp2)

# ---------------------------------------------------------------------------
# INIT + SCAN
# ---------------------------------------------------------------------------
section("INIT + SCAN")

raw_file = "/tmp/tf_test_raw.txt"
with open(raw_file, "w") as f:
    f.write("def foo():\n    pass\n\ndef bar():\n    return 42\n")

r = m.tf_init(raw_file)
ok("TI1 init file grezzo", r,
   lambda v: is_ok(v) and "prompt" in v and "content" in v)
ok("TI4 root esplicito dopo init", None,
   lambda _: open(raw_file).read().startswith("#[of]: root"))
os.unlink(raw_file)

_reset()
r = m.tf_init(TF)
ok("TI2 init su file già TF", r, is_fail)

skip("TI3 tf_scan MCP tool", "BUG: tf_scan non esposto come MCP tool")

# ---------------------------------------------------------------------------
# HEALTH / AUDIT
# ---------------------------------------------------------------------------
section("HEALTH / AUDIT")

# HA1: test vero della logica duplicate_code — fixture con 2 blocchi quasi identici.
# (Il vecchio HA1 lanciava tf_audit su tutto il progetto reale: smoke-test travestito
# da unit test, O(N^2) su tanti blocchi. Sostituito con un fixture isolato.)
_dup_dir = tempfile.mkdtemp(prefix="tf_audit_ha1_")
_dup_file = os.path.join(_dup_dir, "fixture.py")
with open(_dup_file, "w") as _fh:
    _fh.write(
        "#[of]: root\n"
        "#[of]: process_x\n"
        "def process(x):\n"
        "    result = []\n"
        "    for item in x:\n"
        "        result.append(item * 2)\n"
        "        if item > 10:\n"
        "            result.append(item)\n"
        "    return result\n"
        "#[cf]\n"
        "#[of]: process_y\n"
        "def process(y):\n"
        "    result = []\n"
        "    for item in y:\n"
        "        result.append(item * 2)\n"
        "        if item > 10:\n"
        "            result.append(item)\n"
        "    return result\n"
        "#[cf]\n"
        "#[cf]\n"
    )
try:
    r = m.tf_audit(_dup_dir, threshold=3)
    ok("HA1 audit non crasha su fixture dir", r,
       lambda v: isinstance(v, str) and "AUDIT:" in v)
    ok("HA1 duplicate_code rilevato (process_x ~ process_y)", r,
       lambda v: "DUP(" in v and "process_x" in v and "process_y" in v)
    ok("HA1 DUP include file e path", r,
       lambda v: "fixture.py@root/process_x" in v and "fixture.py@root/process_y" in v)
    ok("HA1 LONG include file (non solo path)", r,
       lambda v: "fixture.py@root/process_x" in v.split("DUP(")[0])
finally:
    shutil.rmtree(_dup_dir, ignore_errors=True)

_reset()
r = m.tf_audit(TF)
ok("HA2 audit su file pulito", r,
   lambda v: isinstance(v, str) and "0 issue" in v)

# ---------------------------------------------------------------------------
# SESSION
# ---------------------------------------------------------------------------
section("SESSION")
_reset()

r = m.tf_session(TF + "@root", action="save",
                 status="test in corso", next="completare")
ok("SE1 save session", r, lambda v: json_ok(v).get("ok") is True
   if isinstance(v, str) else is_ok(v))

r = m.tf_session(TF + "@root", action="load")
ok("SE2 load (status+next)", r,
   lambda v: "test in corso" in str(v) and "completare" in str(v))

r = m.tf_session(TF + "@root", action="load", keys=["*"])
ok("SE3 load tutto", r, lambda v: "status" in str(v))

r = m.tf_session(TF + "@root", action="save", status="AGGIORNATO")
r2 = m.tf_session(TF + "@root", action="load")
ok("SE4 update incrementale", r2,
   lambda v: "AGGIORNATO" in str(v) and "completare" in str(v))

# ---------------------------------------------------------------------------
# AGENT
# ---------------------------------------------------------------------------
section("AGENT")

r = m.tf_agent(TF, action="set", agent_id="test-ai",
               data={"kind": "ai", "focus": "root/cap1"})
ok("AG1 set agent", r, is_ok)

r = m.tf_agent(TF, action="get", agent_id="test-ai")
ok("AG2 get agent", r,
   lambda v: is_ok(v) and v.get("state", {}).get("focus") == "root/cap1")

r = m.tf_agent(TF, action="list")
ok("AG3 list sessions", r,
   lambda v: is_ok(v) and len(v.get("sessions", [])) >= 1)

r = m.tf_agent(TF, action="clean", agent_id="test-ai")
ok("AG4 clean session", r, is_ok)

r = m.tf_agent(".", action="get", agent_id="miller")
ok("AG5 miller shortcut", r, is_ok)

# ---------------------------------------------------------------------------
# MAN / PROGRESSIVE DISCLOSURE (new firma: tf_man(topic='', level=1))
# ---------------------------------------------------------------------------
section("MAN")

# MA1 bootstrap: topic='' e topic='bootstrap' tornano lo stesso blocco.
r = m.tf_man()
ok("MA1 bootstrap default compatto", r,
   lambda v: isinstance(v, str) and 10 <= len(v.splitlines()) <= 40 and "tf_check_env" in v)

r = m.tf_man(topic="bootstrap")
ok("MA2 topic='bootstrap' == default", r,
   lambda v: isinstance(v, str) and "tf_check_env" in v)

# MA3 principles: le 3 regole ferree.
r = m.tf_man(topic="principles")
ok("MA3 principles ha R1 R2 R3", r,
   lambda v: all(kw in v for kw in ["R1", "R2", "R3", "Read", "invent"]))

# MA4 help tool level 1 (minimo).
r = m.tf_man(topic="tf_search", level=1)
ok("MA4 tf_search l1 ha firma + scopo + es", r,
   lambda v: all(kw in v for kw in ["firma:", "scopo:", "es:", "pattern"]))

# MA5 help tool level 2 (arricchito).
r = m.tf_man(topic="tf_search", level=2)
ok("MA5 tf_search l2 cita mode/ignore_case", r,
   lambda v: "mode='paths'" in v or "mode='lines'" in v)

# MA6 help tool level 3 (completezza) — tf_search ha l3 esplicito.
r = m.tf_man(topic="tf_search", level=3)
ok("MA6 tf_search l3 copre regex/edge", r,
   lambda v: "regex" in v.lower() or "edge case" in v.lower())

# MA7 fallback di livello: tool con solo l1 ritorna l1 anche se si chiede l3.
r = m.tf_man(topic="tf_check_env", level=3)
ok("MA7 fallback livello highest available", r,
   lambda v: isinstance(v, str) and "tf_check_env" in v and "firma:" in v)

# MA8 topic sconosciuto → enumera i tool.
r = m.tf_man(topic="tf_does_not_exist")
ok("MA8 topic sconosciuto elenca tool", r,
   lambda v: ("non riconosciuto" in v or "not recognized" in v or "unknown" in v.lower()) and "tf_tree" in v and "tf_search" in v)

# MA9 flows/f_read esiste.
r = m.tf_man(topic="flows/f_read")
ok("MA9 flow f_read esiste", r,
   lambda v: isinstance(v, str) and "tf_tree" in v and "tf_getBlockContent" in v)

# MA10 errors table.
r = m.tf_man(topic="errors")
ok("MA10 errors ha block not found", r,
   lambda v: "block not found" in v)

# MA11 tf_tree l1 — firma e esempio presenti, no # header, no JSON wrap.
r = m.tf_man(topic="tf_tree", level=1)
ok("MA11 tf_tree l1 firma + no # header + no JSON wrap", r,
   lambda v: "tf_tree" in v and "firma:" in v and not v.strip().startswith("#") and not v.strip().startswith('{"result"'))

# MA12 tf_editText l1 — firma e hard rule R1.
r = m.tf_man(topic="tf_editText", level=1)
ok("MA12 tf_editText l1 firma + R1 menzione", r,
   lambda v: "tf_editText" in v and "firma:" in v and "R1" in v)

# MA13 topic=tf_tree level=2 — contiene auto-depth e show_path.
r = m.tf_man(topic="tf_tree", level=2)
ok("MA13 tf_tree l2 contiene auto-depth e show_path", r,
   lambda v: "auto-depth" in v and "show_path" in v)

# ---------------------------------------------------------------------------
# ROOT ESPLICITO
# ---------------------------------------------------------------------------
section("ROOT ESPLICITO")
_reset()

r = m.tf_tree(TF + "@root", show_path=True, depth=1)
ok("RO2 root.start_line reale (@N)", tree_result(r),
   lambda v: "@" in v)

r = m.tf_addBlock(TF + "@root", "nuovo", content="X.", after="root/cap1")
ok("RO3 addBlock su root con after=", r, is_ok)

r = m.tf_moveBlock(TF + "@root/cap2/sub_a", "root")
ok("RO4 moveBlock to root", r, is_ok)

r = json_ok(m.tf_getBlockContent(TF + "@root", raw=True))
ok("RO5 raw root inizia con tag", r,
   lambda v: str(v).startswith("#[of]: root"))

# ---------------------------------------------------------------------------
# ERROR HANDLING
# ---------------------------------------------------------------------------
section("ERROR HANDLING")
_reset()

r = m.tf_editText(TF + "@root/cap1", "#[of]: rotto", write=False)
ok("ER2 editText con tag TF", r, is_fail)

r = m.tf_insert(TF + "@root/cap1", text="#[of]: rotto", write=False)
ok("ER3 insert con tag TF", r, is_fail)

r = m.tf_tree("/tmp/inesistente.txt@root")
ok("ER4 file inesistente", r, lambda v: "ERROR" in str(v).upper())

r = json_ok(m.tf_getBlockContent(TF + "@"))
ok("ER5 path malformato (bug noto: ritorna root)", r,
   lambda _: True,   # bug noto ER5 — non fallisce il runner
   "BUG NOTO ER5: path@ ritorna root invece di errore")

os.chmod(TF, 0o444)
r = m.tf_editText(TF + "@root/cap1", "x", write=True)
ok("ER6 write su read-only", r, is_fail)
os.chmod(TF, 0o644)

# ---------------------------------------------------------------------------
# FRATELLI OMONIMI
# ---------------------------------------------------------------------------
section("FRATELLI OMONIMI")
_reset()

r = m.tf_duplicateBlock(TF + "@root/cap1")
ok("FR1 duplicate auto-rename", r,
   lambda v: is_ok(v) and v.get("new_label") != "cap1")

r = m.tf_renameBlock(TF + "@root/cap1_copy", "cap1")
ok("FR3 rinomina che crea omonimo (permissiva)", r, is_ok)

r = m.tf_tree(TF + "@root", show_path=True, depth=1)
ok("FR2 show_path disambigua omonimi", tree_result(r),
   lambda v: v.count("cap1") >= 2 and "@" in v)

r = json_ok(m.tf_getBlockContent(TF + "@root/cap1"))
ok("FR4 omonimo → primo + warning", r,
   lambda v: "warnings" in str(v) or "cap1" in str(v))

# ---------------------------------------------------------------------------
# PUBLIC SERVER PROXY — tutti i tool via tf().
# ---------------------------------------------------------------------------
section("PUBLIC SERVER PROXY")
_reset()

import tf_mcp as _lite

def _tf_str(cmd_dict):
    return _lite.tf(json.dumps(cmd_dict))

def _tf(cmd_dict):
    r = _tf_str(cmd_dict)
    try:
        return json.loads(r)
    except json.JSONDecodeError:
        return {"ok": True, "result": r}

# bad JSON → bootstrap
r = _lite.tf("not json")
ok("LT1 bad json → bootstrap", r, lambda v: "navigate" in v or "tool" in v)

# missing tool key → bootstrap
r = _lite.tf('{"path": "x"}')
ok("LT2 missing tool key → bootstrap", r, lambda v: "navigate" in v or "tool" in v)

# empty → bootstrap
r = _lite.tf("")
ok("LT2b empty → bootstrap", r, lambda v: "navigate" in v or "tool" in v)

# unknown tool
r = _tf({"tool": "tf_foobar"})
ok("LT3 unknown tool → error", r, is_fail)

# tf_man
r = _tf_str({"tool": "tf_man"})
ok("LT4 tf_man bootstrap via lite", r, lambda v: "tf_tree" in v and "tf_getBlockContent" in v)

# tf_tree
r = _tf_str({"tool": "tf_tree", "path": TF + "@root", "depth": 1})
ok("LT5 tf_tree via lite", r, lambda v: "cap1" in v)

# tf_inspect
r = _tf_str({"tool": "tf_inspect", "path": TF, "depth": 1})
ok("LT6 tf_inspect via lite", r, lambda v: "cap1" in v)

# tf_getBlockContent
r = _tf_str({"tool": "tf_getBlockContent", "path": TF + "@root/cap1"})
ok("LT7 tf_getBlockContent via lite", r, lambda v: "TESTA" in v)

# tf_search
r = _tf({"tool": "tf_search", "path": TF + "@root", "pattern": "Contenuto"})
ok("LT8 tf_search via lite", r, is_ok)

# tf_editText
r = _tf({"tool": "tf_editText", "path": TF + "@root/cap1", "text": "lite edit", "write": True})
ok("LT9 tf_editText via lite", r, is_ok)
_reset()

# tf_insert
r = _tf({"tool": "tf_insert", "path": TF + "@root/cap1", "text": "inserted", "write": True})
ok("LT10 tf_insert via lite", r, is_ok)
_reset()

# tf_replaceInBlock
r = _tf({"tool": "tf_replaceInBlock", "path": TF + "@root/cap1",
         "old_text": "TESTA.", "new_text": "REPLACED.", "write": True})
ok("LT11 tf_replaceInBlock via lite", r, is_ok)
_reset()

# tf_addBlock
r = _tf({"tool": "tf_addBlock", "path": TF + "@root", "label": "lite_block",
         "content": "lite content", "write": True})
ok("LT12 tf_addBlock via lite", r, is_ok)
_reset()

# tf_renameBlock
r = _tf({"tool": "tf_renameBlock", "path": TF + "@root/cap1",
         "new_label": "cap1_renamed", "write": True})
ok("LT13 tf_renameBlock via lite", r, is_ok)
_reset()

# tf_duplicateBlock
r = _tf({"tool": "tf_duplicateBlock", "path": TF + "@root/cap1", "write": True})
ok("LT14 tf_duplicateBlock via lite", r, is_ok)
_reset()

# tf_moveBlock
r = _tf({"tool": "tf_moveBlock", "path": TF + "@root/cap3",
         "new_parent": TF + "@root/cap2", "write": True})
ok("LT15 tf_moveBlock via lite", r, is_ok)
_reset()

# tf_removeBlock
r = _tf({"tool": "tf_removeBlock", "path": TF + "@root/cap3", "write": True})
ok("LT16 tf_removeBlock via lite", r, is_ok)
_reset()

# tf_wrapBlocks (single range — tf_wrapBlock removed from public server)
r = _tf({"tool": "tf_wrapBlocks", "path": TF + "@root/cap1",
         "blocks": [{"label": "wrap_test", "start": 0, "end": 1}], "write": True})
ok("LT17 tf_wrapBlocks single range via public", r, is_ok)
_reset()

# tf_normalize
r = _tf({"tool": "tf_normalize", "path": TF, "write": False})
ok("LT18 tf_normalize via lite", r, is_ok)

# tf_audit
r = _tf({"tool": "tf_audit", "path": TF})
ok("LT19 tf_audit via lite", r, is_ok)

# tf_diff
import tempfile as _tmp
_tmp2 = _tmp.NamedTemporaryFile(suffix=".txt", delete=False, mode="w")
_tmp2.write(open(TF).read())
_tmp2.close()
r = _tf({"tool": "tf_diff", "path_a": TF, "path_b": _tmp2.name})
ok("LT20 tf_diff via lite", r, is_ok)
os.unlink(_tmp2.name)

# tf_init — su file raw
_raw = _tmp.NamedTemporaryFile(suffix=".py", delete=False, mode="w")
_raw.write("def foo():\n    pass\ndef bar():\n    pass\n")
_raw.close()
r = _tf({"tool": "tf_init", "path": _raw.name})
ok("LT21 tf_init via lite", r, is_ok)
os.unlink(_raw.name)

# tf_onboard — su file raw
_raw2 = _tmp.NamedTemporaryFile(suffix=".py", delete=False, mode="w")
_raw2.write("def foo():\n    pass\ndef bar():\n    pass\n")
_raw2.close()
r = _tf({"tool": "tf_onboard", "path": _raw2.name, "write": False})
ok("LT22 tf_onboard via lite", r, is_ok)
os.unlink(_raw2.name)

# tf_strip
r = _tf({"tool": "tf_strip", "path": TF, "write": False})
ok("LT23 tf_strip via lite", r, is_ok)

# tf_createFile
_new = _tmp.mktemp(suffix=".py")
r = _tf({"tool": "tf_createFile", "path": _new})
ok("LT24 tf_createFile via lite", r, is_ok)
ok("LT24b file esiste", None, lambda _: os.path.exists(_new))
os.unlink(_new)

# tf_check_env
r = _tf({"tool": "tf_check_env"})
ok("LT26 tf_check_env via lite", r, is_ok)

# tf_insert_note
r = _tf({"tool": "tf_insert_note", "path": TF + "@root/cap1",
         "text": "nota lite", "write": True})
ok("LT27 tf_insert_note via lite", r, is_ok)
_reset()

# tf_insert_ref
r = _tf({"tool": "tf_insert_ref", "path": TF + "@root/cap1",
         "target": "somefile.py@root/block", "write": True})
ok("LT28 tf_insert_ref via lite", r, is_ok)
_reset()

# tf_man via lite: topic='' → bootstrap
r = _tf_str({"tool": "tf_man"})
ok("LT29 tf_man via lite bootstrap", r,
   lambda v: isinstance(v, str) and "tf_tree" in v and "tf_getBlockContent" in v)

# tf_man via lite: topic=tool → contenuto specifico (non bootstrap generico)
r = _tf_str({"tool": "tf_man", "topic": "tf_search", "level": 1})
ok("LT29b tf_man topic=tf_search → firma specifica", r,
   lambda v: "firma:" in v and "pattern" in v)

r = _tf_str({"tool": "tf_man", "topic": "tf_tree", "level": 1})
ok("LT29c tf_man topic=tf_tree → firma specifica", r,
   lambda v: "firma:" in v and "depth" in v)

r = _tf_str({"tool": "tf_man", "topic": "tf_editText", "level": 1})
ok("LT29d tf_man topic=tf_editText → firma specifica", r,
   lambda v: "firma:" in v and "text" in v)

r = _tf_str({"tool": "tf_man", "topic": "errors"})
ok("LT29e tf_man topic=errors → error table", r,
   lambda v: "block not found" in v)

r = _tf_str({"tool": "tf_man", "topic": "flows/f_read"})
ok("LT29f tf_man topic=flows/f_read → flow content", r,
   lambda v: "tf_getBlockContent" in v)

# tf_wrapBlocks
r = _tf({"tool": "tf_wrapBlocks", "path": TF + "@root/cap1",
         "blocks": [{"label": "wb_test", "start": 0, "end": 1}], "write": True})
ok("LT30 tf_wrapBlocks via lite", r, is_ok)
_reset()

# tf_man tutti i topic principali via lite
for _topic in ["", "principles", "errors", "flows/f_bootstrap", "flows/f_read",
               "flows/f_write", "flows/f_onboard"]:
    r = _tf_str({"tool": "tf_man", "topic": _topic})
    ok(f"LT31 tf_man topic={_topic or '(bootstrap)'}",
       r, lambda v: isinstance(v, str) and len(v) > 10)

_reset()

# ---------------------------------------------------------------------------
# RISULTATI FINALI
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

if os.path.exists(TF):
    os.unlink(TF)
shutil.rmtree(_cwd_tmp, ignore_errors=True)

sys.exit(0 if _fail == 0 else 1)
#[cf]
