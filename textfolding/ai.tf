#[of]: root
#[of]: bootstrap
version: 2026-04-29 19:20
tf reads/edits structured files via labeled block tags (managed by TF).
Project root is auto-detected — do not call tf_check_env / tf_initProject.

Path syntax:  file@root/Class/method   file@root/section
              file (no @) means whole-file overview

Read 1 block:    tf_getBlockContent(path="f@root/X")
Read N blocks:   tf_getBlockContent(path="f@root/X,f@root/Y,g@root/Z")
Read parent+all: tf_getBlockContent(path="f@root/X", mode="expanded")
File structure:  tf_tree(path="f")
Search:          tf_search(path="f", pattern="regex")

Edit text in a block:    tf_replaceInBlock(path, old_str, new_str)
ADD a new sibling block: tf_addBlock(path=parent, label, text, after="sibling")
Rewrite block body:      tf_editText (R1: getBlockContent first, keep [child] placeholders)
Wrap visible lines:      tf_wrapBlock(path=parent, label, start, end)

Rules (read once):
  R1  Read before tf_editText only (NOT replaceInBlock).
  R2  Never invent paths — derive from tf_tree.
  R3  Never write block tags in edit payloads — TF manages them.
  R4  New block = tf_addBlock. Never replaceInBlock for inserting new code.
  R5  Trust write replies — do not re-read to "verify".

On error the reply has a "manual" field — read it before retrying.
Deeper docs: tf_man(topic="<tool>", level=2).
Manual sections (tf_tree on this file): principles, tools, flows, errors.
#[cf]
#[of]: bootstrap_lite
tf reads/edits structured files via labeled block tags.
One tool: tf(cmd) where cmd is a JSON string.
Example: tf({"tool":"tf_tree","path":"file.py"})
Project root: set TF_PROJECT_ROOT env var in .mcp.json, or call tf({"cwd":"/abs/path"}) once at session start.

Path:  file@root/Class/method
       file (no @) = whole-file overview

5 core tools (cover 99% of tasks):

STRUCTURE
  tf_tree(path)                              -> label hierarchy of file/block
  RULE: for overview tasks (list classes, architecture), use tree ONCE
        on the file. Do NOT drill each class separately unless needed.

READ
  tf_getBlockContent(path)                   -> text of one block
  tf_getBlockContent(path="a,b,c")           -> batch read (comma-sep)
  tf_getBlockContent(path, mode="expanded")  -> parent + all descendants flat

SEARCH / TRACE
  tf_search(path, pattern)                   -> list of matching block paths (default)
  tf_search(path, pattern, mode="lines", context=3)
                                             -> grep-like: all hits + N lines around.
                                                USE for call-chain tracing.
  Scope with path="f@root/Class" to limit search to a subtree.

EDIT
  tf_replaceInBlock(path, old_str, new_str)  -> surgical find+replace
                                                (old_str must be unique in block)

ADD NEW BLOCK
  tf_addBlock(path=parent, label, text, after="sibling")
                                             -> new sibling block.
                                                NEVER use replaceInBlock to add
                                                a new function/method — TF will
                                                parse it as raw text, not a block.

6 rules:

R1. For tf_editText ONLY: read first with getBlockContent(mode="structured")
    and keep all [child] placeholders exactly. replaceInBlock/addBlock do NOT
    require this.
R2. Never invent paths. Derive from tf_tree.
R3. Never write TF block tags (open/close markers) in edit payloads — TF
    manages them automatically.
R4. New block = tf_addBlock. Never replaceInBlock for adding a new method/func.
R5. Trust {ok:true} write replies. Do NOT re-read to "verify". Burns turns.
R6. Trace / call-chain questions ("where does X come from?", "who calls Y?"):
    use tf_search(mode="lines", context=3-5). ONE call shows all hits.
    NEVER drill block-by-block for tracing.

errors:

Reply with {ok:false} may include a "manual" field. Read it before retrying.
Multi-line strings in cmd values: use \n for newlines.

advanced:

23 more tools exist (wrap, onboard, audit, move, rename, session, ...).
Not needed for typical read/edit tasks; ignore unless an error suggests one.
#[cf]
#[of]: principles
R1. Read before tf_editText (only).
    tf_editText rewrites the whole block body, so you MUST first call
    tf_getBlockContent(mode='structured') to see [child] placeholders and
    keep them in the new text. Skipping this orphans the children.
    NOT required for tf_replaceInBlock — backend matches old_str literally.

R2. Never invent paths.
    Paths only exist if they appear in tf_tree. "block not found" -> rerun
    tf_tree, do not retry path variations.

R3. Preserve indentation and tags.
    tf is line-level. Exact roundtrip. Open/close block tags must remain
    balanced — never write them in edit payloads.

R4. New block = tf_addBlock. Never tf_replaceInBlock.
    tf_replaceInBlock only edits text INSIDE an existing block boundary.
    Inserting a new function/method/section as text via replaceInBlock
    works at file level but TF parses it as raw text inside the parent
    block, NOT as a sibling block (no block tags = no block).
    To add a sibling: tf_addBlock(path=parent, label, text, after="sibling").
    To wrap existing visible lines into a new block: tf_wrapBlock.

R6. For tracing / call-chain questions: tf_search(mode="lines", context=N).
    Questions like "where does X come from?", "trace the lookup chain",
    "who calls Y?" → use tf_search with mode='lines' and context=3-5.
    One call returns ALL hits with surrounding lines. NEVER explore block-
    by-block via tf_getBlockContent for these tasks. Scope with path=
    "f@root/Subtree" if the search space is narrow.

R5. Trust write replies — do not re-verify.
    A successful write returns {"ok": true, ...}. The change is committed.
    Do NOT call tf_getBlockContent / tf_tree afterwards just to "verify".
    Burns turns. Only re-read if you need to chain another edit on the
    SAME block.
#[cf]
#[of]: tools
#[of]: navigate
#[of]: tf_tree
#[of]: l1
firma: tf_tree(path, depth=None, include_text=False, show_path=False)
scopo: navigation tool — label hierarchy of a file/block. Auto-depth by default.
es:    tf({"tool":"tf_tree","path":"file.py"})                          -> file overview
       tf({"tool":"tf_tree","path":"file.py@Class"})                     -> drill into block
       tf({"tool":"tf_tree","path":"file.py","show_path":true})          -> full paths ready to copy into tf_getBlockContent
#[cf]
#[of]: l2
show_path=True: adds full path next to each label (e.g. file.py@root/Class/method) — use this whenever you need to call tf_getBlockContent next, so you can copy the path directly without reconstructing it.
Auto-depth: by default tree expands to deepest level fitting ~200L budget.
If truncated, the output appends '[auto-depth=N, XL shown; drill via path=...]'.
Drill deeper into any block via path='file.py@root/Class' — auto-depth applies.
include_text=True shows inline text: useful only for short blocks.
Advanced: depth=N forces explicit level; depth=-1 forces full tree.
Workflow tip: tf_tree(show_path=True) → tf_getBlockContent(path) — no manual path construction needed.
For health/gap analysis (long/mixed blocks), use tf_audit instead.
#[cf]
#[cf]
#[of]: tf_search
#[of]: l1
firma: tf_search(path, pattern, ignore_case=False, context=0, mode='paths')
scopo: regex search inside a tf file. Returns block paths or lines.
es:    tf({"tool":"tf_search","path":"WS@root","pattern":"TODO"})
#[cf]
#[of]: l2
The parameter is called 'pattern'. Not 'query', not 'text', not 'regex'.
mode='paths' (default): returns list of block paths containing the match.
  -> after the match, enter the blocks with tf_getBlockContent.
mode='lines': returns raw lines with absolute line numbers.
  -> enable context=N to get N lines above/below each match.
ignore_case=True: passes re.IGNORECASE to the matcher.
pattern uses Python re syntax: \b, ., .*, (a|b), etc.
#[cf]
#[of]: l3
Precise semantics:
- search is per-line (not multiline): \n does not match.
- input text includes tag lines: searching "#[of]" will find it in every opening.
- to exclude them, anchor the pattern to useful content e.g. "^[^#]*TODO".
Integration with other tools:
- mode='paths' + tf_getBlockContent: to read the matched block.
- mode='lines' + tf_wrapBlock(start, end): to wrap a found section in a new block.
Edge cases:
- file without "#[of]: root" -> parser fails, tf_search returns error.
- pattern with quotes: remember JSON escaping ("pattern": "\"quoted\"").
#[cf]
#[cf]
#[of]: tf_check_env
#[of]: l1
firma: tf_check_env()
scopo: dump of the MCP process environment (cwd, PWD, HOME, TF_PROJECT_DIR).
es:    tf({"tool":"tf_check_env"})
#[cf]
#[cf]
#[cf]
#[of]: read
#[of]: tf_getBlockContent
#[of]: l1
firma: tf_getBlockContent(path, mode='structured', offset=0, limit=None, numbered=False)
scopo: text of one OR many blocks. Required only before tf_editText (rule R1).
       For tf_replaceInBlock you do NOT need a prior read of the same block.
batch: path can be comma-separated to read multiple blocks in 1 call.
       path="f.py@root/A,f.py@root/B,g.py@root/C"  (replaces N round-trips).
exp:   mode='expanded' returns flat text with all descendants — use to read
       a parent block + all its children at once instead of N separate calls.
es:    tf({"tool":"tf_getBlockContent","path":"WS@root/parser"})
#[cf]
#[of]: l2
mode='structured' (default): children are replaced by [label] placeholders.
  Use this output as the base for tf_editText: you must preserve the [label]s.
mode='expanded': flat text with all children expanded. For inspection, not writing.
numbered=True: prepends the absolute line number to each line. Needed for tf_wrapBlock.
Pagination: blocks > ~50 lines return a chunk and next_offset in the JSON.
  Call again with offset=next_offset to get the continuation.
#[cf]
#[of]: l3
Key interaction with tf_editText:
  1) getBlockContent(path, mode='structured') -> text_with_[children]
  2) modify text keeping [child] placeholders exactly where they were
  3) tf_editText(path, modified_text)
  If you remove a [child] from text, that sub-block is DELETED (irreversible).
  If you add [new_label] in text without new_blocks={}, error: "unknown child".
Edge cases:
- root block: tf_getBlockContent("file@root") returns the whole file stripped.
- empty block: returns empty string, not an error.
- wrong path: {"ok":false,"error":"block not found: ..."} -> re-read tf_tree.
#[cf]
#[cf]
#[of]: tf_strip
#[of]: l1
firma: tf_strip(path, write=False)
scopo: removes all tf tags from a file, returns clean text.
es:    tf({"tool":"tf_strip","path":"WS"})
#[cf]
#[of]: l2
write=False: returns the stripped content without touching the file (default).
write=True:  overwrites the file with the stripped version. Irreversible.
Typical use: before an external PR that should not see tf markers, or for comparison
with an unstructured upstream version.
#[cf]
#[cf]
#[of]: tf_man
#[of]: l1
firma: tf_man(topic='', level=1)
scopo: this manual. topic='' returns the bootstrap; topic=<tool> the tool help.
es:    tf({"tool":"tf_man","topic":"tf_search","level":2})
#[cf]
#[of]: l2
topic='' and level=1            -> root/bootstrap (~20 lines).
topic='principles'              -> root/principles.
topic='<tool>' and level=N      -> root/tools/<group>/<tool>/lN.
topic='flows/f_read' (or similar) -> operational sequences.
If the requested level does not exist, falls back to the highest available level.
Path-based (alternative): tf_getBlockContent("ai.tf@root/tools/navigate/tf_search/l2").
#[cf]
#[cf]
#[cf]
#[of]: write_text
#[of]: tf_editText
#[of]: l1
firma: tf_editText(path, text, write=False, new_blocks={})
scopo: rewrites the text of a block. Hard rule R1: call getBlockContent first.
es:    tf({"tool":"tf_editText","path":"WS@root/foo","text":"new text\n[child]\n"})
#[cf]
#[of]: l2
text must preserve [label] placeholders of existing children (from getBlockContent structured).
  -> missing a [label]: the child is DELETED.
  -> extra [label] without definition: error.
new_blocks={"label":"content"}: creates new inline sub-blocks. Labels used in text
  must all be present in new_blocks (for new ones) or already be children of the block.
write=False (default): preview, returns diff. write=True applies to file.
#[cf]
#[of]: l3
Common errors and how to avoid them:
- "unknown child [x]": text contains [x] that is not a child and not in new_blocks.
- "missing child [y]": text does not contain [y] that existed before -> add it back or
  accept deletion (if intentional, write=True will confirm).
- Wrong indentation: the parser counts columns strictly. Copy exact indent.
Recommended strategy for blocks with many children: use tf_replaceInBlock (surgical) instead
of rewriting the whole text. Reduces risk of losing [label]s by mistake.
Sanity check: after tf_editText with write=True, call tf_tree on the same path:
if child count changed unexpectedly, you have a bug.
#[cf]
#[cf]
#[of]: tf_replaceInBlock
#[of]: l1
firma: tf_replaceInBlock(path, old_str, new_str, label=None, write=False)
scopo: surgical find+replace inside a block. Preferred over tf_editText for a single change.
es:    tf({"tool":"tf_replaceInBlock","path":"WS@root/foo","old_str":"x = 1","new_str":"x = 2"})
alias (backward-compat): old_text/new_text are still accepted.
#[cf]
#[of]: l2
old_str must be UNIQUE in the block: if it appears more than once, error. Expand context
(more lines) to make it unique.
label=None (default): replace in place, no new wrap.
label='name': after the replace, wraps the new range in a sub-block "name". Useful
for incremental structuring while editing.
write=True to apply. Without write, preview with diff.
#[cf]
#[cf]
#[of]: tf_insert
#[of]: l1
firma: tf_insert(path, text, row=-1, write=False)
scopo: inserts raw text in a block at a specific line.
es:    tf({"tool":"tf_insert","path":"WS@root/imports","text":"import os\n","row":0})
#[cf]
#[of]: l2
row=-1  -> append at the end of the block (default).
row=0   -> prepend at the start of the block.
row=N   -> insert before VISIBLE row N (0-based, relative to the block in path,
           as returned by tf_getBlockContent(numbered=True, mode='structured')).
Note: tf_insert does NOT create children and does NOT handle [label] placeholders. For
structured insert use tf_addBlock. For invisible notes, tf_insert_note.
#[cf]
#[cf]
#[of]: tf_insert_note
#[of]: l1
firma: tf_insert_note(path, text, write=False)
scopo: inserts a host-language note (#tf:note) invisible to tf_strip output.
es:    tf({"tool":"tf_insert_note","path":"WS@root/foo","text":"revisit after ADR-42"})
#[cf]
#[cf]
#[of]: tf_insert_ref
#[of]: l1
firma: tf_insert_ref(path, target, write=False)
scopo: inserts a cross-file ref (#tf:ref target) navigable from Miller.
es:    tf({"tool":"tf_insert_ref","path":"WS@root/foo","target":"other.py@root/bar"})
#[cf]
#[cf]
#[cf]
#[of]: modify_blocks
#[of]: tf_addBlock
#[of]: l1
firma: tf_addBlock(path, label, text='', line=-1, after=None, write=False)
scopo: adds a new sub-block to the block pointed to by path.
es:    tf({"tool":"tf_addBlock","path":"WS@root","label":"utils","text":"..."})
alias (backward-compat): 'content' is still accepted as a synonym for 'text'.
#[cf]
#[of]: l2
label: name of the new block (must be unique among siblings).
text: initial content. Empty = empty block with only tags.
after=None (default): append as last child of the parent (block in 'path').
after='sibling_label': insert immediately after that sibling. Must be a STRING
                      (label of an existing sibling). NOT a flag — never pass a bool.
line=N: insert at absolute line N in the file (advanced — prefer 'after').
Tip: to insert a method between two existing methods, use after='prev_method'.
#[cf]
#[cf]
#[of]: tf_wrapBlock
#[of]: l1
firma: tf_wrapBlock(path, label, start, end, write=False)
scopo: wraps lines [start..end] of the block specified in path in a new sub-block "label".
es:    tf({"tool":"tf_wrapBlock","path":"WS@root/myclass","label":"helpers","start":2,"end":5})
#[cf]
#[of]: l2
start/end are VISIBLE ROW numbers (0-based) relative to the block in path
(as returned by tf_getBlockContent(numbered=True, mode='structured')).
If path has no '@' block specifier, start/end are treated as absolute 0-based file lines (legacy).
After the wrap, all subsequent lines shift by +2 (open + close tag).
  -> if you need multiple wraps in the same file, PREFER tf_wrapBlocks to avoid shift drift.
Returns 'shifted_from': the absolute line from which original numbers are invalidated.
#[cf]
#[cf]
#[of]: tf_wrapBlocks
#[of]: l1
firma: tf_wrapBlocks(path, blocks, write=False)
scopo: wraps multiple ranges in one shot, without shift drift. Preferred over repeated tf_wrapBlock.
es:    tf({"tool":"tf_wrapBlocks","path":"WS@root/myclass","blocks":[{"label":"a","start":0,"end":2},{"label":"b","start":4,"end":6}]})
#[cf]
#[of]: l2
blocks: list of {label, start, end}. start/end are VISIBLE ROW numbers (0-based) relative to
the block in path (as returned by tf_getBlockContent(numbered=True, mode='structured')).
If path has no '@' block specifier, start/end are absolute 0-based file lines (legacy).
Each placeholder [child] counts as 1 visible row regardless of its physical size.
Works on FREE TEXT, EXISTING CHILD BLOCKS, or a MIX — always safe (_safe_save validates).
Ranges must not overlap. Order in the list is free: resolved up front, applied bottom-up.
All labels must be unique among the resulting siblings.
Error -> rollback: no partial modification.
#[cf]
#[of]: l3
Typical use in onboarding:
  1) tf_onboard(path, write=False)  -> preview with candidates (suggested start/end).
  2) filter the interesting candidates, remap them to [{label,start,end},...].
     start/end must be visible row numbers relative to the parent block.
  3) tf_wrapBlocks(path+"@root/parent", filtered, write=True).
Alternative: let tf_onboard(write=True) do the full automatic wrap, then refine.
#[cf]
#[cf]
#[of]: tf_renameBlock
#[of]: l1
firma: tf_renameBlock(path, new_label, write=False)
scopo: renames the block pointed to by path. Does not touch content.
es:    tf({"tool":"tf_renameBlock","path":"WS@root/old","new_label":"new"})
#[cf]
#[cf]
#[of]: tf_moveBlock
#[of]: l1
firma: tf_moveBlock(path, new_parent, after=None, write=False)
scopo: moves a block under another parent (same file).
es:    tf({"tool":"tf_moveBlock","path":"WS@root/foo/bar","new_parent":"WS@root/utils"})
#[cf]
#[of]: l2
after=None: the moved block becomes the last child of new_parent.
after='sibling_label': the block is inserted immediately after that sibling.
Cross-file move not supported: use tf_getBlockContent + tf_addBlock manually.
#[cf]
#[cf]
#[of]: tf_removeBlock
#[of]: l1
firma: tf_removeBlock(path, write=False)
scopo: removes a block and all its children. Irreversible with write=True.
es:    tf({"tool":"tf_removeBlock","path":"WS@root/dead_code"})
#[cf]
#[cf]
#[of]: tf_duplicateBlock
#[of]: l1
firma: tf_duplicateBlock(path, new_label=None, write=False)
scopo: duplicates a block as a sibling, optionally with a new label.
es:    tf({"tool":"tf_duplicateBlock","path":"WS@root/template","new_label":"copy1"})
#[cf]
#[cf]
#[of]: tf_normalize
#[of]: l1
firma: tf_normalize(path, write=False)
scopo: fixes blank lines around tags for canonical formatting.
es:    tf({"tool":"tf_normalize","path":"WS"})
#[cf]
#[cf]
#[cf]
#[of]: setup
#[of]: tf_createFile
#[of]: l1
firma: tf_createFile(path)
scopo: creates a new tf-ready file (with #[of]:root / #[cf] already present).
es:    tf({"tool":"tf_createFile","path":"WS/new_module.py"})
#[cf]
#[cf]
#[of]: tf_init
#[of]: l1
firma: tf_init(file_path)
scopo: AI-guided prompt to structure a raw (non-tf) file via tf_editText + new_blocks.
es:    tf({"tool":"tf_init","file_path":"WS/legacy.py"})
#[cf]
#[of]: l2
Returns a prompt describing the structure to impose + raw content.
The AI reads the prompt, decides the blocks, calls tf_editText with newBlocks.
Difference from tf_onboard: tf_init is AI-guided (semantic choice); tf_onboard is
mechanical (wraps classes/functions automatically). For Python code, prefer tf_onboard.
#[cf]
#[cf]
#[of]: tf_onboard
#[of]: l1
firma: tf_onboard(path, write=False)
scopo: mechanical structuring: wraps classes, methods, nested functions, class_attrs. Idempotent.
es:    tf({"tool":"tf_onboard","path":"WS/legacy.py"})
#[cf]
#[of]: l2
write=False (default): preview. Returns candidates_found + list of {label,start,end,kind}.
write=True: applies wrapping: root + blocks for each top-level class/def + methods.
Idempotent: re-applying does not duplicate tags.
After write=True: call tf_audit to see any long blocks to refine,
and tf_tree for the logical structure.
#[cf]
#[of]: l3
What it covers (Python): all classes, methods, nested functions, class_attrs blocks — via ast.
What it covers (other files): top-level def/class + direct methods — via tf_custom (indent+keyword).
What it does NOT cover: logical groupings inside a long method, semantic sections
(e.g. all BooleanAction under "actions"). For these use tf_wrapBlocks manually.
After onboard: tf_audit for long leaf blocks, tf_tree for structure verification.
#[cf]
#[cf]
#[of]: tf_audit
#[of]: l1
firma: tf_audit(path='.', threshold=20)
scopo: quality check. Identifies long, mixed, TODO, or unstructured blocks.
es:    tf({"tool":"tf_audit","path":"WS","threshold":30})
#[cf]
#[of]: l2
Markers:
  LONG:N   leaf block of N lines > threshold.
  MIXED    contains sub-blocks AND free text > 5 lines.
  EMPTY    empty block.
  TODO:N   N occurrences of 'TODO' in the text.
path='.' scans the whole project (via components.tf if present).
#[cf]
#[cf]
#[of]: tf_diff
#[of]: l1
firma: tf_diff(path_a, path_b)
scopo: semantic diff between two tf files (at block level, not line level).
es:    tf({"tool":"tf_diff","path_a":"WS/a.py","path_b":"WS/b.py"})
#[cf]
#[of]: l2
Output: lists of added/removed/modified blocks with paths relative to root.
Does not replace a textual diff: it shows AT A GLANCE what structure changed.
For textual diff inside a modified block, use tf_getBlockContent on both files.
#[cf]
#[cf]
#[of]: tf_initProject
#[of]: l1
firma: tf_initProject(cwd)
scopo: initializes tf in a project. Creates .tf/config.tf with cwd.
es:    tf({"tool":"tf_initProject","cwd":"/abs/path/to/project"})
#[cf]
#[of]: l2
cwd MUST be an absolute path to an existing directory.
Effect: creates .tf/config.tf with 'cwd = <cwd>'. No wiki template copy (removed).
After init: all other tools (tf_tree, tf_editText, etc.) resolve relative paths from this cwd.
Re-run tf_initProject to switch projects in the same MCP process.
#[cf]
#[cf]
#[cf]
#[of]: session
#[of]: tf_session
#[of]: l1
firma: tf_session(path, action='load', status='', next='', decisions='', blocks='', keys=None)
scopo: saves/loads session context in a tf file block (e.g. session.md@root).
es:    tf({"tool":"tf_session","path":"WS/session.md@root","action":"save","status":"done X","next":"do Y"})
#[cf]
#[of]: l2
action='save':  writes status/next/decisions/blocks as standard sub-blocks.
action='load' with keys=None: returns status+next (the minimum to resume).
action='load' with keys=['decisions','blocks']: returns only those requested.
Typical use: end of turn -> save. Start of next turn -> load.
#[cf]
#[cf]
#[of]: tf_agent
#[of]: l1
firma: tf_agent(path, action='get', agent_id='default', data=None, stale_secs=3600)
scopo: multi-agent state in .tf/sessions/<id>.json. For coordinating multiple processes.
es:    tf({"tool":"tf_agent","path":"irrelevant","action":"set","agent_id":"ai_a","data":{"k":"v"}})
#[cf]
#[of]: l2
action='set'   persists data for agent_id.
action='get'   returns data for agent_id, or None if stale/missing.
action='list'  lists active agent_ids.
action='clean' removes states older than stale_secs.
#[cf]
#[cf]
#[of]: tf_miller
#[of]: l1
firma: tf_miller(cmd, path=None, block=None, text=None)
scopo: controls the Miller UI (VSCode webview) via HTTP RPC on port 7891.
es:    tf({"tool":"tf_miller","cmd":"open","path":"WS/file.py@root/foo"})
#[cf]
#[of]: l2
cmd='state'    current state of the webview (path, history, editMode).
cmd='open'     opens a file and navigates to the block.
cmd='focus'    focuses on a block in the already-open file.
cmd='propose'  shows diff in propose-mode, waits for human Apply/Discard.
cmd='command'  executes an action (enterEdit, saveText, historyBack).
Requires VSCode to be open and MillerPanel active.
#[cf]
#[cf]
#[cf]
#[cf]
#[of]: flows
#[of]: f_bootstrap
Just call the tool you need. Project root is auto-detected from os.getcwd()
or by walking up from the `path` argument. No init step required.

New file (not tf-yet):  tf_onboard(path, write=True)
Brand-new project (no .tf anywhere): tf_initProject(cwd=<abs>) once.
#[cf]
#[of]: f_read
Overview:    tf_tree(path="f@root")
Drill:       tf_tree(path="f@root/section")
Block text:  tf_getBlockContent(path="f@root/section/X")
Many blocks: tf_getBlockContent(path="f@root/X,f@root/Y")
Deep parent: tf_getBlockContent(path="f@root/X", mode="expanded")
Search:      tf_search(path="f", pattern="regex")

If JSON reply has next_offset: call again with offset=next_offset.
Never invent paths — derive from tf_tree.
#[cf]
#[of]: f_write
Edit text in a block:    tf_replaceInBlock(path, old_str, new_str)
  - old_str must be unique in the block (expand context if needed).
  - no prior read required; backend matches literally.

ADD a new sibling block: tf_addBlock(path=parent, label, text, after="sibling")
  - NEVER use tf_replaceInBlock to insert a new function/method (R4).

Wrap visible lines:      tf_wrapBlock(path=parent, label, start, end)
  - start/end are visible row numbers from getBlockContent(numbered=True).
  - many wraps in one shot: tf_wrapBlocks (no shift drift).

Rewrite block body:      tf_editText(path, text, new_blocks={})
  - R1: getBlockContent(structured) first, keep all [child] placeholders.
  - missing [child] in text -> child DELETED. Extra [x] without new_blocks -> error.

After a successful write: trust the {ok:true} reply. Do NOT re-read to verify (R5).
write=False for preview, write=True (default for most) to apply.
#[cf]
#[of]: f_onboard
Structure a raw (non-tf) file.

1. tf_onboard(path, write=False)  -> preview candidates (auto: classes/defs/methods).
2. tf_onboard(path, write=True)   -> apply if preview is good.
3. Group siblings into sections (optional):
   - tf_getBlockContent(path="f@root", numbered=True) for visible row numbers.
   - tf_wrapBlocks(path="f@root", [{label, start, end}, ...]) — atomic, no shift drift.
4. tf_audit(path) to find LONG/MIXED leaf blocks worth splitting.
5. tf_tree(path) for final verification.
#[cf]
#[cf]
#[of]: errors
message -> cause -> fix

"Invalid JSON: Invalid control character"
  literal newline/tab/quote in cmd. Use \n, \t, \" escapes.

"Invalid JSON: Expecting value / delimiter / unterminated string"
  malformed JSON. Single-line, balanced quotes, no trailing comma.

"Missing 'tool' key in JSON" / "unknown tool: <name>"
  cmd has no tool field, or typo. Reply includes 'available'.

"block not found: <path>"
  stale path. Rerun tf_tree(parent), do NOT retry variants.

"<tool>() got an unexpected keyword argument '<k>'"
  hallucinated param. Reply includes 'signature' — copy literally.

"unknown child [label]" (tf_editText)
  text has [label] not in current children and not in new_blocks={}.
  Re-read getBlockContent(structured); keep existing [labels] verbatim.

"missing child [label]" (tf_editText)
  text dropped a [label] of an existing child. Add it back, or accept deletion.

"old_str not found / not unique" (tf_replaceInBlock)
  old_str doesn't match, or matches >1 time. Expand context until unique.

"pattern is required" / regex error (tf_search)
  param name is 'pattern' (not 'query'/'regex'/'text').

"components not configured" (tf_tree on '')
  pass a file path (not '') OR add 'components = components.tf' to .tf/config.tf.

"cwd must be an absolute path" (tf_initProject)
  pass os.path.abspath(...).

"cwd required"
  TF does not know the project root. Fix (pick one):
  a. Call tf({"cwd":"/abs/path"}) — sets root for this session.
  b. Set TF_PROJECT_ROOT env var in .mcp.json: "env": {"TF_PROJECT_ROOT": "/abs/path"}
#[cf]
#[cf]

