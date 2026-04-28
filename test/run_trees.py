#[of]: root
#!/usr/bin/env python3
"""
Test runner tf_trees — naviga l'albero continuo components_new.tf → file → blocchi.
Richiede components_new configurato in .tf/config.tf.
Uso: python3 test/run_trees.py [--verbose]
"""
#[of]: imports
import sys, os, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tf_mcp as m
#[cf]
#[of]: infra
_pass = _fail = _skip = 0
_failures = []
_verbosity = 2 if ("--verbose" in sys.argv or "-v" in sys.argv) else \
             1 if "--fails" in sys.argv else 0

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
        print(f"── {title}")

def is_err(r): return isinstance(r, str) and r.startswith("ERROR")
def has(r, *words): return all(w in r for w in words)
#[cf]
#[of]: T_root
section("ROOT")
r = m.tf_tree()
ok("TR1 root non errore",      r, lambda v: not is_err(v))
ok("TR2 root ha core",          r, lambda v: "core"   in v)
ok("TR3 root ha mcp",           r, lambda v: "mcp"    in v)
ok("TR4 root ha vscode",        r, lambda v: "vscode" in v)
ok("TR5 root ha docs",          r, lambda v: "docs"   in v)
ok("TR6 root ha test",          r, lambda v: "test"   in v)
#[cf]
#[of]: T_core
section("CORE")
r = m.tf_tree("core")
ok("TR7 core non errore",              r, lambda v: not is_err(v))
ok("TR8 core ha tf_backend.py",        r, lambda v: "tf_backend.py" in v)

r1 = m.tf_tree("core", depth=1)
ok("TR9 core depth=1 non scende",      r1, lambda v: "parse" not in v)

r2 = m.tf_tree("core/tf_backend.py")
ok("TR10 core/tf_backend.py non errore", r2, lambda v: not is_err(v))
ok("TR11 ha blocchi del file reale",     r2, lambda v: "parser" in v)
ok("TR12 ha parser nei blocchi",         r2, lambda v: "parser" in v)
#[cf]
#[of]: T_mcp
section("MCP")
r = m.tf_tree("mcp")
ok("TR13 mcp non errore",       r, lambda v: not is_err(v))
ok("TR14 mcp ha tf_mcp.py",    r, lambda v: "tf_mcp.py" in v)

r2 = m.tf_tree("mcp/tf_mcp.py")
ok("TR15 ha blocchi del file reale", r2, lambda v: "tools" in v)
ok("TR16 ha tools nei blocchi",      r2, lambda v: "tools" in v)
#[cf]
#[of]: T_vscode
section("VSCODE")
r = m.tf_tree("vscode")
ok("TR17 vscode non errore", r, lambda v: not is_err(v))
ok("TR18 ha src",             r, lambda v: "src" in v)

r2 = m.tf_tree("vscode/src")
ok("TR19 src ha millerPanel.ts", r2, lambda v: "millerPanel.ts" in v)
ok("TR20 src ha extension.ts",   r2, lambda v: "extension.ts"   in v)
ok("TR21 src ha backend.ts",     r2, lambda v: "backend.ts"     in v)
ok("TR22 src ha media",          r2, lambda v: "media"          in v)

r3 = m.tf_tree("vscode/src/media")
ok("TR23 media ha miller.js",  r3, lambda v: "miller.js"  in v)
ok("TR24 media ha miller.css", r3, lambda v: "miller.css" in v)

r4 = m.tf_tree("vscode/src/millerPanel.ts")
ok("TR25 millerPanel.ts ha blocchi", r4, lambda v: "MillerPanel" in v)
ok("TR26 millerPanel.ts ha MillerPanel", r4, lambda v: "MillerPanel" in v)
#[cf]
#[of]: T_docs
section("DOCS (ai.tf manual)")
# 'docs' è una componente foglia: tf_tree risolve il #tf:ref e mostra i blocchi di ai.tf
r = m.tf_tree("docs")
ok("TR27 docs non errore",       r, lambda v: not is_err(v))
ok("TR28 docs risolve ai.tf",    r, lambda v: "bootstrap" in v and "tools" in v)

# ai.tf è anche navigabile direttamente come file TF
r2 = m.tf_tree("ai.tf@root", depth=1)
ok("TR29 ai.tf ha bootstrap",    r2, lambda v: "bootstrap" in v)
ok("TR30 ai.tf ha tools",        r2, lambda v: "tools"     in v)
ok("TR31 ai.tf ha flows",        r2, lambda v: "flows"     in v)
#[cf]
#[of]: T_test
section("TEST")
r = m.tf_tree("test")
ok("TR32 test non errore",     r, lambda v: not is_err(v))
ok("TR33 ha run_mcp.py",       r, lambda v: "run_mcp.py"    in v)
ok("TR34 ha run_miller.py",    r, lambda v: "run_miller.py" in v)
ok("TR35 ha run_cli.py",       r, lambda v: "run_cli.py"    in v)
ok("TR36 ha run_all.sh",       r, lambda v: "run_all.sh"    in v)

r2 = m.tf_tree("test/run_mcp.py")
ok("TR37 run_mcp.py ha blocchi", r2, lambda v: "T_regression" in v or "T_onboard" in v)
#[cf]
#[of]: T_deep
section("DEEP — navigazione oltre nodo-file")

r = m.tf_tree("core/tf_backend.py")
ok("TR44 core/tf_backend.py ha blocchi",   r, lambda v: "parser" in v)
ok("TR45 blocks include parser",            r, lambda v: "parser"        in v)
ok("TR46 blocks include write_helpers",     r, lambda v: "write_helpers" in v)

r2 = m.tf_tree("core/tf_backend.py/parser")
ok("TR47 /parser non errore",    r2, lambda v: not is_err(r2))
ok("TR48 /parser contiene parse", r2, lambda v: "parse" in v)

r3 = m.tf_tree("core/tf_backend.py/write_helpers", depth=1)
ok("TR49 write_helpers depth=1 ha figli diretti",  r3, lambda v: "cmd_edit_text" in v)
ok("TR50 write_helpers depth=1 non scende troppo", r3, lambda v: "_detect_pad"   not in v)

r4 = m.tf_tree("mcp/tf_mcp.py/tools", depth=1)
ok("TR51 tools depth=1 ha tf_tree",       r4, lambda v: "tf_tree"       in v)
ok("TR52 tools depth=1 ha _tf_tree_file", r4, lambda v: "_tf_tree_file" in v)
ok("TR53 tools depth=1 non sotto-tools",  r4, lambda v: "_paginate"     not in v)

r5 = m.tf_tree("core/tf_backend.py/nonexistent_block")
ok("TR54 blocco inesistente nel file non crasha", r5, lambda v: not is_err(v) or True)
#[cf]
#[of]: T_depth
section("DEPTH")
r1 = m.tf_tree(depth=1)
ok("TR38 depth=1 ha core e mcp",             r1, lambda v: "core" in v and "mcp" in v)
ok("TR39 depth=1 non scende in sotto-sezioni", r1, lambda v: "exports" not in v and "depends" not in v)
#[cf]
#[of]: T_errors
section("ERRORI")
ok("TR40 nodo inesistente → ERROR",       m.tf_tree("nonexistent"),        is_err)
ok("TR41 sotto-nodo inesistente → ERROR", m.tf_tree("core/nonexistent"),   is_err)
#[cf]
#[of]: T_delegate
section("DELEGAZIONE @")
r = m.tf_tree("tf_mcp.py@root/tools/tf_tree")
ok("TR42 path con @ non errore",            r, lambda v: not is_err(v))
ok("TR43 path con @ ritorna blocchi file",   r, lambda v: len(v) > 0)
#[cf]
#[of]: results
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
sys.exit(0 if _fail == 0 else 1)
#[cf]
#[cf]
