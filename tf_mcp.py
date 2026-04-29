#!/usr/bin/env python3
#[of]: root
"""TextFolding MCP Server — 31 tool.
tf_backend.py = pura libreria, zero dipendenze.
"""
#[of]: imports
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from tf_backend import (
    parse, get_block, get_block_wild, visible_to_physical, tags_for_file, note_tag_for_file, _make_patterns,
    cmd_strip, cmd_edit_text, cmd_init,
    cmd_add_block, cmd_remove_block, cmd_rename_block,
    cmd_duplicate_block, cmd_move_block_to_parent,
    cmd_insert, cmd_insert_note, cmd_insert_ref, cmd_set_block, cmd_wrap_text,
    cmd_search, cmd_diff, cmd_normalize, cmd_health, cmd_scan,
    cmd_set_session, cmd_get_session, cmd_list_sessions, cmd_clean_session,
    cmd_read_session, cmd_write_config,
    cmd_onboard_fix_tags, cmd_onboard_remove_orphan_tags,
    cmd_onboard_add_root, cmd_onboard_scan,
    cmd_replace_in_block,
    _find_child, _block_to_lines, _tag_line, _validate_tags,
    _semantic_chunk,
    OPEN_TAG, CLOSE_TAG, Block, Text, Note,
)
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

# Tool annotation shortcuts (see MCP spec):
#   READONLY:    idempotent, no side effects; client may auto-approve.
#   DESTRUCTIVE: removes data; client should require explicit confirmation.
READONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True)
DESTRUCTIVE = ToolAnnotations(destructiveHint=True)
#[cf]

#[of]: setup
mcp = FastMCP(
    "textfolding",
    instructions="""TextFolding MCP — structural navigation for text files.

PROTOCOL (read once per session):
1. On first use in a session, call tf_man(topic='') to load the full protocol.
2. When asked to 'onboard' a file, the flow is:
   a. tf_onboard(path, write=False)  — preview candidates
   b. tf_onboard(path, write=True)   — apply mechanical wrapping
      (covers top-level classes/functions AND their direct methods)
   c. tf_initProject(cwd) if the project wiki is not yet initialized
   d. Register the file in .tf/components.tf under the right section
   Mechanical wrapping (b) is sufficient for navigation. Steps c-d enable
   project-level features (wiki, cross-file refs).
3. Always call tf_getBlockContent(mode='structured') BEFORE tf_editText on the same block."""
)

# cwd override set by tf_initProject — persists for the lifetime of the MCP server process
# allows agents starting from arbitrary directories to work after the first call
_PROJECT_CWD: str | None = None

#[of]: _get_project_cwd
def _get_project_cwd() -> str | None:
    """Returns project cwd with decreasing priority:
    1. _PROJECT_CWD (set by tf_initProject in the current session)
    2. os.getcwd() if it contains .tf/config.tf
    3. Walk up from os.getcwd() looking for .tf/config.tf
    Returns the absolute project path, or None if not found.
    """
    global _PROJECT_CWD

    def _read_cwd_from_config(config_path: str) -> str | None:
        try:
            with open(config_path) as fh:
                lines = fh.readlines()
            ot, ct = tags_for_file(config_path)
            root = parse(lines, ot, ct)
            blk = get_block(root, "root/config")
            if blk is None:
                return None
            for item in blk.items:
                if hasattr(item, "text"):
                    for line in item.text.splitlines():
                        line = line.strip()
                        if line.startswith("cwd"):
                            _, _, val = line.partition("=")
                            val = val.strip()
                            if val and os.path.isabs(val):
                                return val
        except Exception:
            pass
        return None

    # 0. TF_PROJECT_ROOT env var (set in .mcp.json or shell)
    env_root = os.environ.get("TF_PROJECT_ROOT", "").strip()
    if env_root and os.path.isdir(env_root):
        return env_root

    # 1. session override (tf_initProject or tf('{"cwd":"..."}'))
    if _PROJECT_CWD and os.path.isdir(_PROJECT_CWD):
        return _PROJECT_CWD

    # 2. os.getcwd() direct
    actual = os.getcwd()
    config_path = os.path.join(actual, ".tf", "config.tf")
    if os.path.exists(config_path):
        result = _read_cwd_from_config(config_path)
        if result:
            return result

    # 3. walk up to /
    current = actual
    while True:
        parent = os.path.dirname(current)
        if parent == current:
            break  # reached filesystem root
        current = parent
        config_path = os.path.join(current, ".tf", "config.tf")
        if os.path.exists(config_path):
            result = _read_cwd_from_config(config_path)
            if result:
                return result

    return None
#tf:ref .tf/wiki/decisions.md@root/adr_mcp_cwd_override
#[cf]
#[of]: _auto_init_from_cwd
def _auto_init_from_cwd(path: str = "") -> bool:
    """Transparently detect the project root on every tool call.
    If _PROJECT_CWD is already set, do nothing.
    Strategies tried in order (first hit wins, no creation):
      1. <os.getcwd()>/.tf/config.tf  (benchmark case: .mcp.json sets cwd)
      2. walk up from the absolute `path` argument of the current call.
         The walk starts at the file's dirname and stops at filesystem root.
         This is the AUTOMATED equivalent of:
           tf_check_env() -> identify root from path -> tf_initProject(cwd=...)
         except no creation: only detection of an existing .tf/config.tf.
    Returns True if (re)set.

    Does NOT create config.tf — that pollutes wrong directories. Creation
    remains the explicit responsibility of tf_initProject. The model only
    needs it the very first time a brand-new project is set up."""
    global _PROJECT_CWD
    if _PROJECT_CWD and os.path.isdir(_PROJECT_CWD):
        return False

    def _has_config(d: str) -> bool:
        return os.path.exists(os.path.join(d, ".tf", "config.tf"))

    # 1. os.getcwd() (benchmark / shell-launched case)
    try:
        cwd = os.getcwd()
    except OSError:
        cwd = ""
    if cwd and os.path.isdir(cwd) and _has_config(cwd):
        _PROJECT_CWD = cwd
        return True

    # 2. walk up from the absolute `path` of this call (if any)
    if isinstance(path, str) and path:
        fs_path = path.split("@", 1)[0]
        if os.path.isabs(fs_path):
            current = fs_path if os.path.isdir(fs_path) else os.path.dirname(fs_path)
            while current and current != os.path.dirname(current):
                if _has_config(current):
                    _PROJECT_CWD = current
                    return True
                current = os.path.dirname(current)
    return False
#[cf]
#[of]: _get_config_value
def _get_config_value(key: str) -> str | None:
    """Read an arbitrary value from .tf/config.tf → root/config."""
    cwd = _get_project_cwd()
    if not cwd:
        return None
    config_path = os.path.join(cwd, ".tf", "config.tf")
    if not os.path.exists(config_path):
        return None
    try:
        with open(config_path) as fh:
            lines = fh.readlines()
        ot, ct = tags_for_file(config_path)
        root = parse(lines, ot, ct)
        blk = get_block(root, "root/config")
        if blk is None:
            return None
        for item in blk.items:
            if hasattr(item, "text"):
                for line in item.text.splitlines():
                    line = line.strip()
                    if line.startswith(key):
                        _, _, val = line.partition("=")
                        return val.strip()
    except Exception:
        pass
    return None
#[cf]
#[of]: _require_init
def _require_init() -> dict | None:
    """Returns None if TF is initialized and cwd is valid.
    Otherwise returns dict {ok: False, error: ...} with an explicit message.

    Validation:
    1. .tf/config.tf must exist, found via os.getcwd() or tree walk
    2. cwd in config.tf must be an existing absolute path
    """
    cwd = _get_project_cwd()

    if cwd is None:
        actual = os.getcwd()
        return {"ok": False, "error":
            f"'.tf/config.tf' not found in '{actual}' or any parent directory. "
            f"Run tf_initProject to initialize the project."}

    if not os.path.isdir(cwd):
        return {"ok": False, "error":
            f"cwd '{cwd}' in config.tf does not exist as a directory. "
            f"Update 'cwd' in '.tf/config.tf'."}

    return None
#tf:ref .tf/wiki/decisions.md@root/adr_mcp_stateless
#[cf]
#[of]: _cwd
def _cwd() -> str:
    """Returns the validated cwd. Call after _require_init().
    Raises RuntimeError if cwd is unavailable for any reason."""
    cwd = _get_project_cwd()
    if cwd is None:
        raise RuntimeError("cwd not available — call _require_init() before _cwd()")
    return cwd
#[cf]

#[of]: _get_skip_dirs
def _get_skip_dirs(project_path: str) -> set:
    """Read skip_dirs from .tf/components.tf@root/config of the project.
    Falls back to empty set if the block does not exist."""
    import shlex
    components_path = os.path.join(project_path, ".tf", "components.tf")
    if not os.path.exists(components_path):
        return set()
    try:
        with open(components_path) as fh:
            lines = fh.readlines()
        from tf_backend import parse, tags_for_file, get_block
        ot, ct = tags_for_file(components_path)
        root = parse(lines, ot, ct)
        blk = get_block(root, "root/config")
        if blk is None:
            return set()
        text = "".join(item.text for item in blk.items if hasattr(item, "text"))
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("skip_dirs"):
                _, _, val = line.partition("=")
                return set(shlex.split(val.strip()))
    except Exception:
        pass
    return set()
#[cf]

#[of]: _load
def _load(path: str):
    """Load file and root block from a file@block path."""
    file_path = path.split("@")[0] if "@" in path else path
    if not os.path.isabs(file_path):
        file_path = os.path.join(_cwd(), file_path)
    if not os.path.exists(file_path):
        # If no '@' separator and path looks like file.py/block/path, give a hint
        if "@" not in path and re.search(r'\.[a-zA-Z0-9]+/', path):
            raise FileNotFoundError(
                f"Malformed path: use '@' as separator between file and block "
                f"(e.g. argparse_tf.py@root/parser/ArgumentParser). "
                f"Find the correct path with tf_search(..., mode='paths')."
            )
        raise FileNotFoundError(f"file not found: {file_path}")
    open_tag, close_tag = tags_for_file(file_path)
    note_tag = note_tag_for_file(file_path)
    lines = open(file_path).readlines()
    root  = parse(lines, open_tag, close_tag, note_tag)
    return file_path, lines, root, open_tag, close_tag
#[cf]

#[of]: _block_path
def _block_path(path: str) -> str:
    """Estrae il block path da file@block/path."""
    if "@" not in path:
        return "root"
    return path.split("@", 1)[1] or "root"
#[cf]

#[of]: _reject_tf_markers
def _reject_tf_markers(s, param_name: str, open_tag: str, close_tag: str):
    """Return an error dict if s contains TF block markers; else None.

    Edit payloads (new_str, text, ...) must never carry #[of]: or #[cf]
    — those are structural metadata managed by TF. Agents tend to treat
    them as "changelog annotations", which pollutes the TF tree.
    """
    if not isinstance(s, str):
        return None
    if open_tag in s or close_tag in s:
        return {"ok": False, "error": (
            f"{param_name} must not contain TF markers "
            f"({open_tag!r} or {close_tag!r}). "
            "These are structural metadata managed by TF — do NOT include "
            "them in edit payloads. To create a new block use tf_addBlock "
            "or tf_wrapBlock."
        )}
    return None
#[cf]

#[of]: _safe_save
def _safe_save(file_path, new_lines, open_tag, close_tag):
    """Save with validation. Returns error string or None."""
    try:
        _validate_tags(new_lines, open_tag, close_tag)
        with open(file_path, "w") as f:
            f.writelines(new_lines)
        return None
    except (ValueError, PermissionError, OSError) as e:
        return str(e)
#[cf]

#[of]: _abs
def _abs(path):
    if os.path.isabs(path):
        return path
    return os.path.join(_cwd(), path)
#[cf]

#[of]: _homonym_warnings
def _homonym_warnings(root: "Block", blk_path: str) -> list:
    """Returns warnings if the requested block has homonyms in the parent."""
    if not blk_path or blk_path == "root":
        return []
    parts = blk_path[5:].split("/") if blk_path.startswith("root/") else blk_path.split("/")
    label = parts[-1].split("@")[0]
    parent_path = "root/" + "/".join(parts[:-1]) if len(parts) > 1 else "root"
    parent = get_block(root, parent_path)
    if parent is None:
        return []
    duplicates = [b for b in parent.children if b.label == label]
    if len(duplicates) > 1:
        return [f"multiple blocks named '{label}' — use @line to disambiguate (e.g. {label}@{duplicates[0].start_line})"]
    return []
#[cf]
#[cf]

#[of]: tools
#[of]: _tf_tree_file
def _tf_tree_file(path: str, depth: int = None, include_text: bool = False, show_path: bool = False) -> str:
    """Helper interno — navigazione diretta file@blocco. Chiamato da tf_tree.
    depth=None: auto-depth (expand to ~200L budget).
    depth=-1: full tree. depth=N: explicit level."""
    try:
        file_path, lines, root, open_tag, close_tag = _load(path)
    except FileNotFoundError as e:
        return f"ERROR: {e}"
    blk_path = _block_path(path)
    blk = get_block(root, blk_path) if blk_path != "root" else root
    if blk is None:
        return f"ERROR: block not found: {blk_path}"

    def _render(b, target, indent=0, max_depth=-1):
        if max_depth == 0:
            return
        if b.label != "root":
            prefix = "  " * indent
            text_preview = ""
            if include_text:
                txt = "".join(i.text for i in b.items if hasattr(i, "text")).strip()
                if txt:
                    text_preview = f"  {txt[:60].splitlines()[0]!r}"
            path_info = f"  ({b.path})" if show_path else ""
            target.append(f"{prefix}{b.label}{path_info}{text_preview}")
        next_d = max_depth - 1 if max_depth > 0 else -1
        for child in b.children:
            _render(child, target, indent + (0 if b.label == "root" else 1), next_d)

    # Auto-depth: probe increasing depths until budget exceeded
    if depth is None:
        best_lines, best_depth = [], 1
        for d in range(1, 10):
            probe = []
            _render(blk, probe, max_depth=d + 1)
            if len(probe) <= _AUTO_DEPTH_BUDGET:
                best_lines, best_depth = probe, d
                # check if deeper would add nothing
                probe_next = []
                _render(blk, probe_next, max_depth=d + 2)
                if len(probe_next) == len(probe):
                    return "\n".join(probe) if probe else "(nessun blocco)"
            else:
                break
        # truncated: show best + hint
        hint = f"\n[auto-depth={best_depth}, {len(best_lines)}L shown; drill via path='file@block' or use depth=N]"
        return ("\n".join(best_lines) + hint) if best_lines else "(nessun blocco)"

    out = []
    effective = (depth + 1) if depth >= 0 else -1
    _render(blk, out, max_depth=effective)
    return "\n".join(out) if out else "(nessun blocco)"
#[cf]
#[of]: tf_tree
@mcp.tool(annotations=READONLY)
def tf_tree(path: str = "", depth: int = None,
            include_text: bool = False, show_path: bool = False) -> str:
    """Navigate logical structure of files/blocks. Auto-depth by default.
    path: ''                     = components.tf overview (project-level)
          'file.py'              = file overview (no components needed)
          'file.py@root/block'   = direct block drill-down
          'section'              = drill into a components.tf section
    depth: None (default) = auto-depth (~200L budget); -1 = full; N = explicit.
    For navigation only — no health alerts. Use tf_audit for gap analysis.
    See tf_man(topic='tf_tree')."""
    if depth == 0:
        return json.dumps({"ok": False, "error": "depth=0 shows nothing — use depth=1 for direct children or depth=-1 for everything."})
    err = _require_init()
    if err:
        return json.dumps(err)
    cwd = _cwd()

    # path con @ → delega a _tf_tree_file (file/block diretto)
    if "@" in path:
        return _tf_tree_file(path, depth=depth, include_text=include_text, show_path=show_path)

    # path è un file standalone (esiste, non in components) → tratta come file
    if path:
        candidate = path if os.path.isabs(path) else os.path.join(cwd, path)
        if os.path.isfile(candidate):
            return _tf_tree_file(candidate + "@root", depth=depth,
                                 include_text=include_text, show_path=show_path)

    # Leggi components da config.tf
    components_name = _get_config_value("components") or _get_config_value("components_new")
    if not components_name:
        return "ERROR: components not configured in .tf/config.tf"
    components_path = os.path.join(cwd, ".tf", components_name)
    if not os.path.exists(components_path):
        return f"ERROR: {components_path} not found"

    ot, ct = tags_for_file(components_path)
    comp_lines = open(components_path).readlines()
    comp_root = parse(comp_lines, ot, ct)

    def _get_file(blk):
        # Supporta "file: X" (legacy), "# tf:ref X@block" (testo), Note kind=ref
        for item in blk.items:
            if hasattr(item, "text"):
                for line in item.text.splitlines():
                    line = line.strip()
                    if line.startswith("file:"):
                        return line.partition(":")[2].strip()
                    if "tf:ref" in line:
                        ref = line.split("tf:ref", 1)[1].strip()
                        return ref.split("@")[0] if "@" in ref else ref
            if hasattr(item, "kind") and item.kind == "ref":
                ref = item.text.strip()
                return ref.split("@")[0] if "@" in ref else ref
        return None

    def _render_comp(blk, indent=0, max_depth=-1):
        """Render components nodes. When it encounters a file node
        with remaining depth, delegates to _tf_tree_file for inner blocks.
        Non-TF files are shown as leaves (no blocks)."""
        out = []
        if max_depth == 0:
            return out
        next_d = max_depth - 1 if max_depth > 0 else -1
        for child in blk.children:
            out.append("  " * indent + child.label)
            file_rel = _get_file(child)
            if file_rel and next_d != 0:
                abs_path = os.path.join(cwd, file_rel)
                try:
                    file_lines = _tf_tree_file(
                        abs_path + "@root",
                        depth=next_d - 1 if next_d > 0 else -1
                    )
                    if file_lines and file_lines != "(nessun blocco)":
                        for l in file_lines.splitlines():
                            out.append("  " * (indent + 1) + l)
                except Exception:
                    pass  # file non strutturato TF — foglia
            elif not file_rel and next_d != 0:
                out.extend(_render_comp(child, indent + 1, next_d))
        return out

    # Naviga components, fermandosi al primo nodo-file
    parts = [p for p in path.split("/") if p] if path else []

    node = comp_root
    file_rel = None
    consumed = 0

    for i, part in enumerate(parts):
        found = None
        for c in node.children:
            if c.label == part:
                found = c
                break
        if found is None:
            return f"ERROR: node '{part}' not found in '{node.path}'"
        node = found
        consumed = i + 1
        file_rel = _get_file(node)
        if file_rel:
            break

    remaining = parts[consumed:]
    # depth=None (auto) is meaningful only inside _tf_tree_file; for the
    # components walk we render the whole subtree (equivalent to -1).
    _depth = -1 if depth is None else depth
    effective = (_depth + 1) if _depth >= 0 else -1

    if file_rel:
        abs_path = os.path.join(cwd, file_rel)
        if not remaining:
            comp_children = [c.label for c in node.children]
            file_depth = (_depth - 1) if _depth > 0 else -1
            # always drill into the file — comp_children are sub-sections, not a reason to skip
            try:
                file_lines = _tf_tree_file(abs_path + "@root", depth=file_depth)
            except Exception:
                file_lines = ""
            if comp_children and file_lines and file_lines not in ("(no blocks)", "(nessun blocco)"):
                out = comp_children + ["[blocks]"] + ["  " + l for l in file_lines.splitlines()]
            elif file_lines and file_lines not in ("(no blocks)", "(nessun blocco)"):
                out = file_lines.splitlines()
            else:
                out = comp_children
            return "\n".join(out) if out else "(no content)"
        else:
            block_path = "root/" + "/".join(remaining)
            return _tf_tree_file(abs_path + "@" + block_path, depth=depth)

    # No file_rel found — render components subtree
    if not parts:
        lines = _render_comp(comp_root, indent=0, max_depth=effective)
    else:
        lines = _render_comp(node, indent=0, max_depth=effective)
    return "\n".join(lines) if lines else "(nessun contenuto)"
#[cf]
#[of]: tf_getBlockContent
@mcp.tool(annotations=READONLY)
def tf_getBlockContent(path: str, mode: str = "structured", raw: bool = False,
                       with_tags: bool = False, scope: str = "block",
                       offset: int = 0, limit: int = 0,
                       min_lines: int = 30, max_lines: int = 200,
                       numbered: bool = False,
                       block: str = "") -> str:
    """Read block content. Do NOT reformat indentation — exact roundtrip.
    mode: 'structured' (default, shows [child] placeholders) | 'expanded' (flat
          text including all descendants — use to read N nested blocks in 1 call).
    path: single block path, OR comma-separated list to BATCH-read multiple
          blocks in one call (replaces N round-trips). Example:
            path="f.py@root/A,f.py@root/B/m,g.py@root/C"
    numbered=True: prefix each line with absolute file number (use for tf_wrapBlock start/end).
    offset/limit: pagination (single-path only). See tf_man(topic='flows/f_read').
    """
    # Multi-path batch: comma-separated paths return all blocks concatenated
    # with a separator. Pagination is disabled (each block uses semantic chunking).
    if "," in path:
        _paths = [p.strip() for p in path.split(",") if p.strip()]
        if len(_paths) > 1:
            parts = []
            for p in _paths:
                content = tf_getBlockContent(
                    p, mode=mode, raw=raw, with_tags=with_tags, scope=scope,
                    min_lines=min_lines, max_lines=max_lines, numbered=numbered,
                )
                parts.append(f"=== {p} ===\n{content}")
            return "\n\n".join(parts)

    if block and "@" not in path:
        path = f"{path}@root/{block.lstrip('/')}"
    try:
        file_path, lines, root, open_tag, close_tag = _load(path)
    except FileNotFoundError as e:
        return json.dumps({"ok": False, "error": str(e)})
    blk_path = _block_path(path)

#[of]: _paginate
    def _paginate(text):
        all_lines = text.splitlines(keepends=True)
        total = len(all_lines)
        if limit:
            start = min(offset, total)
            end = min(start + limit, total)
            chunk = all_lines[start:end]
            header = f"[{end - start}/{total} lines, offset={start}]\n"
            if numbered:
                chunk = [f"{start + i}: {l}" for i, l in enumerate(chunk)]
            return header + "".join(chunk), None
        if not offset and total <= max_lines:
            if numbered:
                all_lines = [f"{i}: {l}" for i, l in enumerate(all_lines)]
            return "".join(all_lines), None
        chunk, next_off = _semantic_chunk(all_lines, offset, min_lines, max_lines)
        n = len(chunk)
        more = next_off < total
        header = f"[{n}/{total} lines, offset={offset}, next_offset={next_off}{',' if more else ' — end of block'}]\n"
        if numbered:
            chunk = [f"{offset + i}: {l}" for i, l in enumerate(chunk)]
        return header + "".join(chunk), next_off if more else None
#[cf]

    if scope == "file":
        blk = get_block(root, blk_path) if blk_path != "root" else None
        return _paginate("".join(cmd_strip(lines, open_tag, close_tag, blk)))

    blk = get_block(root, blk_path)
    if blk is None:
        return json.dumps({"ok": False, "error": f"block not found: {blk_path}"})

    warnings = _homonym_warnings(root, blk_path)

    total_lines = blk.end_line - blk.start_line if blk.start_line >= 0 else 0

#[of]: _read_raw
    if raw:
        start = blk.start_line
        end = blk.end_line + 1
        if start < 0:
            content = "".join(lines)
        else:
            content = "".join(lines[start:end])
        result, next_off = _paginate(content)
        response = {"result": result}
        if next_off is not None:
            response["next_offset"] = next_off
        if warnings:
            response["warnings"] = warnings
        if set(response.keys()) == {"result"}:
            return result
        return json.dumps(response)
#[cf]

#[of]: _read_with_tags
    if with_tags:
        if blk.label == "root":
            content = "".join(_block_to_lines(blk))
        else:
            res = [_tag_line(open_tag, blk.label)]
            res.extend(_block_to_lines(blk))
            res.append(_tag_line(close_tag))
            content = "".join(res)
        result, next_off = _paginate(content)
        response = {"result": result}
        if next_off is not None:
            response["next_offset"] = next_off
        if warnings:
            response["warnings"] = warnings
        if set(response.keys()) == {"result"}:
            return result
        return json.dumps(response)
#[cf]

#[of]: _read_expanded
    if mode == "expanded":
        result, next_off = _paginate("".join(cmd_strip(lines, open_tag, close_tag, blk)))
        response = {"result": result}
        if next_off is not None:
            response["next_offset"] = next_off
        if warnings:
            response["warnings"] = warnings
        if set(response.keys()) == {"result"}:
            return result
        return json.dumps(response)
#[cf]

#[of]: _read_structured
    # structured (default): show [child_label] as placeholders
    out = []
    for item in blk.items:
        if isinstance(item, Text):
            out.append(item.text)
        elif isinstance(item, Block):
            out.append(f"[{item.label}]")
        elif isinstance(item, Note):
            out.append(item.text)
    result, next_off = _paginate("\n".join(out))
    response = {"result": result}
    if next_off is not None:
        response["next_offset"] = next_off
    if warnings:
        response["warnings"] = warnings
    if set(response.keys()) == {"result"}:
        return result
    return json.dumps(response)
#[cf]
#[cf]
#[of]: tf_editText
@mcp.tool()
def tf_editText(path: str, text: str, new_blocks: dict = None, write: bool = True) -> dict:
    """Edit block text. Always read with tf_getBlockContent(mode='structured') first.
    text: new content (no TF tags). new_blocks: {'label': 'content'} creates new sub-blocks.
    Existing children must appear as [label] in text. See tf_man(topic='flows/f_write').
    """
    file_path, lines, root, open_tag, close_tag = _load(path)
    err = _reject_tf_markers(text, "text", open_tag, close_tag)
    if err:
        return err
    blk_path = _block_path(path)
    blk = get_block(root, blk_path)
    if blk is None:
        return {"ok": False, "error": f"block not found: {blk_path}"}

    warnings = _homonym_warnings(root, blk_path)

    try:
        new_lines = cmd_edit_text(lines, blk, text, open_tag, close_tag, new_blocks,
                                   strict_children=True)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if write:
        err = _safe_save(file_path, new_lines, open_tag, close_tag)
        if err:
            return {"ok": False, "error": err}
    else:
        warnings.append("write=False — file NOT modified")

    result = {"ok": True, "edited": blk_path}
    if warnings:
        result["warnings"] = warnings
    return result
#[cf]
#[of]: tf_insert
@mcp.tool()
def tf_insert(path: str, text: str, row: int = -1, write: bool = True) -> dict:
    """Insert plain text at row in block (row=-1 = append, 0 = prepend). No TF tags in text.
    row is a visible row number (0-based) relative to the block specified in path,
    as returned by tf_getBlockContent(numbered=True, mode='structured').
    """
    file_path, lines, root, open_tag, close_tag = _load(path)
    err = _reject_tf_markers(text, "text", open_tag, close_tag)
    if err:
        return err
    blk_path = _block_path(path)
    blk = get_block(root, blk_path)
    if blk is None:
        return {"ok": False, "error": f"block not found: {blk_path}"}
    try:
        new_lines = cmd_insert(lines, blk, row, text, open_tag, close_tag)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if write:
        err = _safe_save(file_path, new_lines, open_tag, close_tag)
        if err:
            return {"ok": False, "error": err}
    return {"ok": True, "inserted": blk_path, "row": row}
#[cf]
#[of]: tf_insert_note
@mcp.tool()
def tf_insert_note(path: str, text: str, write: bool = True) -> dict:
    """Append a #tf:note in the block (host-language format). Invisible to content, removed by tf_strip.
    """
    file_path, lines, root, open_tag, close_tag = _load(path)
    note_prefix = note_tag_for_file(file_path)
    blk_path = _block_path(path)
    blk = get_block(root, blk_path)
    if blk is None:
        return {"ok": False, "error": f"block not found: {blk_path}"}
    new_lines = cmd_insert_note(lines, blk, text, open_tag, close_tag, note_prefix)
    if write:
        err = _safe_save(file_path, new_lines, open_tag, close_tag)
        if err:
            return {"ok": False, "error": err}
    return {"ok": True, "inserted_note": blk_path, "format": note_prefix}
#[cf]
#[of]: tf_insert_ref
@mcp.tool()
def tf_insert_ref(path: str, target: str, write: bool = True) -> dict:
    """Insert a #tf:ref in the block — cross-file link navigable in Miller.
    target: project-relative path (e.g. '.tf/wiki/decisions.md@root/adr_foo').
    """
    file_path, lines, root, open_tag, close_tag = _load(path)
    blk_path = _block_path(path)
    blk = get_block(root, blk_path)
    if blk is None:
        return {"ok": False, "error": f"block not found: {blk_path}"}
    new_lines = cmd_insert_ref(lines, blk, target, open_tag, close_tag)
    if write:
        err = _safe_save(file_path, new_lines, open_tag, close_tag)
        if err:
            return {"ok": False, "error": err}
    return {"ok": True, "inserted_ref": blk_path, "target": target}
#[cf]
#[of]: tf_replaceInBlock
@mcp.tool()
def tf_replaceInBlock(path: str, old_str: str = None, new_str: str = None,
                      label: str = None, write: bool = True,
                      old_text: str = None, new_text: str = None,
                      block: str = "",
                      old: str = None, new: str = None) -> dict:
    """Find and replace text inside a block. Optionally wrap replaced range in a new sub-block.
    old_str: exact string to find (must be unique in block). new_str: replacement.
    label: if given, wraps the replaced range in a new sub-block with this label.
    Use for surgical edits (e.g. replace a docstring) without rewriting the whole block.
    Backward-compat: old_text/new_text/old/new are aliases for old_str/new_str.
    See tf_man(topic='flows/f_write') for details.
    """
    if block and "@" not in path:
        path = f"{path}@root/{block.lstrip('/')}"
    if old_str is None:
        old_str = old_text or old
    if new_str is None:
        new_str = new_text or new
    if old_str is None or new_str is None:
        return {"ok": False, "error": "missing required arguments: old_str, new_str (aliases: old_text, new_text)"}
    file_path, lines, root, open_tag, close_tag = _load(path)
    err = _reject_tf_markers(new_str, "new_str", open_tag, close_tag)
    if err:
        return err
    blk_path = _block_path(path)
    blk = get_block(root, blk_path)
    if blk is None:
        return {"ok": False, "error": f"block not found: {blk_path}"}
    try:
        new_lines, info = cmd_replace_in_block(lines, blk, old_str, new_str,
                                               label=label,
                                               open_tag=open_tag, close_tag=close_tag)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if write:
        err = _safe_save(file_path, new_lines, open_tag, close_tag)
        if err:
            return {"ok": False, "error": err}
    return {"ok": True, "block": blk_path, **info}
#[cf]
#[of]: tf_addBlock
@mcp.tool()
def tf_addBlock(path: str, label: str, line: int = -1, text: str = "",
                after: str = None, write: bool = True,
                content: str = None) -> dict:
    """Insert a new block as child of the parent declared in path.

    path semantics:
      'file'           -> no parent declared; append in coda al file (backward-compat)
      'file@root'      -> parent = root (insert as last child of root)
      'file@root/X'    -> parent = X (insert as last child of X, unless after/line given)

    Positioning (mutually exclusive, precedence: after > line > append-as-last-child):
      after='root/X/sibling' : new block placed after sibling. If parent declared in path,
                               sibling MUST be a direct child of parent (else ERROR).
      line=N (absolute)       : insert at file line N. If parent declared, N MUST fall
                               inside parent's span [parent.start+1..parent.end] (else ERROR).
      (neither)                : append as last child of parent (before parent's closing tag),
                               or in coda al file if no parent declared.

    text: content of the new block (can be empty).
    Backward-compat: 'content' is an alias for 'text'.

    See tf_man(topic='tf_addBlock').
    """
    # Backward-compat: 'content' alias for 'text'.
    if content is not None:
        text = content
    file_path, lines, root, open_tag, close_tag = _load(path)
    err = _reject_tf_markers(text, "text", open_tag, close_tag)
    if err:
        return err

    # --- 1. Determine declared parent from path ---------------------------------
    parent_block = None
    parent_label = None
    if "@" in path:
        _, parent_label = path.split("@", 1)
        parent_label = parent_label.strip() or "root"
        parent_block = get_block(root, parent_label)
        if parent_block is None:
            return {"ok": False, "error": f"parent block not found in path: {parent_label}"}

    # --- 2. Resolve 'after' (if provided) + congruence check --------------------
    after_block = None
    if after:
        # Validate that 'after' is a string (not boolean or other type)
        if not isinstance(after, str):
            return {"ok": False, "error":
                f"'after' must be a sibling label string, got {type(after).__name__}. "
                f"Use after='label' to insert after a sibling, or omit 'after' to append last."}
        # 'after' may be: label, label@line (uniqueness), path/to/label, path/to/label@line
        # Try the value as-is first (full path support), then fall back to bare label
        after_path = after
        # Resolve 'after' relative to parent first (if parent declared in path),
        # then fall back to absolute lookup from root.
        if parent_block is not None and parent_block is not root:
            # Match by label OR by label@line
            bare = after_path.split("/")[-1].split("@")[0]
            after_block = next((c for c in parent_block.children if c.label == bare), None)
        if after_block is None:
            # Try bare label extraction for uniqueness suffix (label@line -> label)
            bare = after_path.split("/")[-1].split("@")[0] if "@" in after_path else after_path
            after_block = get_block(root, bare)
        if after_block is None:
            after_block = get_block(root, after_path)
        if after_block is None:
            # Build helpful hint listing direct children of parent if available
            hint = ""
            if parent_block is not None:
                siblings = [c.label for c in parent_block.children]
                hint = f" Available siblings in '{parent_label}': {siblings}"
            return {"ok": False, "error": f"after block not found: {after_path}.{hint}"}
        if parent_block is not None and parent_block is not root:
            if after_block not in parent_block.children:
                return {"ok": False, "error":
                    f"incongruence: after='{after_path}' is not a direct child of "
                    f"parent='{parent_label}' declared in path"}

    # --- 3. Compute insert_line honoring precedence -----------------------------
    if after_block is not None:
        insert_line = after_block.end_line + 1
    elif line >= 0:
        if parent_block is not None and parent_block is not root:
            # line must fall inside parent's span (strictly between tags)
            lo, hi = parent_block.start_line + 1, parent_block.end_line
            if not (lo <= line <= hi):
                return {"ok": False, "error":
                    f"incongruence: line={line} outside parent='{parent_label}' "
                    f"(allowed range: {lo}..{hi})"}
        insert_line = line
    elif parent_block is not None:
        # Append as last child of declared parent = insert just before its closing tag
        insert_line = parent_block.end_line
    else:
        # No parent declared, no positioning: fallback to file-append (backward-compat)
        insert_line = -1

    # --- 4. Apply ---------------------------------------------------------------
    new_lines, err = cmd_add_block(lines, label, insert_line, text,
                                   open_tag, close_tag, after_block=None)
    if err:
        return {"ok": False, "error": err}
    if write:
        save_err = _safe_save(file_path, new_lines, open_tag, close_tag)
        if save_err:
            return {"ok": False, "error": save_err}
    return {"ok": True, "label": label,
            "parent": parent_label, "inserted_at_line": insert_line}
#[cf]
#[of]: tf_wrapBlock
@mcp.tool()
def tf_wrapBlock(path: str, label: str, start: int, end: int, write: bool = True) -> dict:
    """Wrap existing lines into a new block.
    start/end = visible row numbers (0-based) relative to the block specified in path,
    as returned by tf_getBlockContent(numbered=True, mode='structured').
    If path has no '@' block specifier, start/end are treated as absolute 0-based file lines
    (legacy mode, for backward compatibility).
    For multiple wraps use tf_wrapBlocks. See tf_man(topic='flows/f_onboard').
    """
    if end is None:
        return {"ok": False, "error": "end is required"}

    file_path, lines, root, open_tag, close_tag = _load(path)

    # If a block path is specified, convert visible rows to absolute file lines
    if '@' in path:
        block_path = path.split('@', 1)[1]
        block = get_block(root, block_path)
        if block is None:
            return {"ok": False, "error": f"block not found: {block_path}"}
        try:
            abs_start, _ = visible_to_physical(block, lines, start)
            abs_end,   _ = visible_to_physical(block, lines, end)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
    else:
        abs_start, abs_end = start, end

    open_re  = re.compile(re.escape(open_tag) + r'\s*(\S+)')
    close_re = re.compile(re.escape(close_tag))
    new_lines, err = cmd_set_block(lines, label, abs_start, abs_end, open_tag, close_tag,
                                   open_re, close_re)

    if err:
        return {"ok": False, "error": err}
    if write:
        save_err = _safe_save(file_path, new_lines, open_tag, close_tag)
        if save_err:
            return {"ok": False, "error": save_err}

    return {"ok": True, "wrapped": label, "lines_shifted": 2, "shifted_from": abs_end + 1}
#[cf]
#[of]: tf_wrapBlocks
@mcp.tool()
def tf_wrapBlocks(path: str, blocks: list, write: bool = True) -> dict:
    """Wrap multiple line ranges into new blocks in one call (no shift drift).
    blocks: [{label, start, end}] with visible row numbers relative to the block in path
    (0-based, as returned by tf_getBlockContent numbered=True structured).
    If path has no '@' block specifier, start/end are absolute 0-based file lines (legacy).
    PREFER over multiple tf_wrapBlock. See tf_man(topic='flows/f_onboard').
    """
    if not blocks:
        return {"ok": False, "error": "blocks is empty"}

    file_path, lines, root, open_tag, close_tag = _load(path)
    open_re  = re.compile(re.escape(open_tag) + r'\s*(\S+)')
    close_re = re.compile(re.escape(close_tag))

    # If a block path is specified, convert all visible rows to absolute lines up front.
    # Must be done before any wrap (which shifts lines), using the original line map.
    if '@' in path:
        block_path = path.split('@', 1)[1]
        block = get_block(root, block_path)
        if block is None:
            return {"ok": False, "error": f"block not found: {block_path}"}
        resolved = []
        for b in blocks:
            try:
                abs_start, _ = visible_to_physical(block, lines, b["start"])
                abs_end,   _ = visible_to_physical(block, lines, b["end"])
            except ValueError as e:
                return {"ok": False, "error": f"{b['label']}: {e}"}
            resolved.append({"label": b["label"], "start": abs_start, "end": abs_end})
    else:
        resolved = blocks

    # process bottom-up: each wrap does not shift preceding line numbers
    sorted_blocks = sorted(resolved, key=lambda b: b["start"], reverse=True)

    wrapped = []
    for b in sorted_blocks:
        label = b["label"]
        start = b["start"]
        end   = b["end"]
        lines, err = cmd_set_block(lines, label, start, end, open_tag, close_tag,
                                   open_re, close_re)
        if err:
            return {"ok": False, "error": f"{label}: {err}"}
        wrapped.append(label)

    if write:
        save_err = _safe_save(file_path, lines, open_tag, close_tag)
        if save_err:
            return {"ok": False, "error": save_err}

    return {"ok": True, "wrapped": list(reversed(wrapped))}
#[cf]
#[of]: tf_search
@mcp.tool(annotations=READONLY)
def tf_search(path: str, pattern: str, ignore_case: bool = False, context: int = 0, mode: str = "paths") -> str:
    """Search regex pattern in block text under path.
    mode='paths' (default): returns only block paths containing matches — use getBlockContent to read them.
    mode='lines': returns matched lines (path: line). context: lines around each match (mode='lines' only).
    """
    try:
        file_path, lines, root, _, _ = _load(path)
    except FileNotFoundError as e:
        return f"ERROR: {e}"
    blk_path = _block_path(path)
    blk = get_block(root, blk_path)
    if blk is None:
        return f"ERROR: block not found: {blk_path}"
    results = cmd_search(blk, pattern, ignore_case)
    if not results:
        return "0 matches"
    if mode == "paths":
        paths = [r["path"] for r in results if r.get("matches")]
        return f"{len(paths)} block(s) matched:\n" + "\n".join(paths)
    lines_out = [f"{len(results)} match(es)"]
    for r in results:
        matches = r.get("matches", [])
        if context > 0 and matches:
            lines_out.append(f"--- {r['path']}")
            block_lines = r.get("block_text", "").splitlines() if "block_text" in r else []
            flags = re.IGNORECASE if ignore_case else 0
            pat = re.compile(pattern, flags)
            for i, line in enumerate(block_lines):
                if pat.search(line):
                    start = max(0, i - context)
                    end = min(len(block_lines), i + context + 1)
                    for j in range(start, end):
                        marker = ">" if j == i else " "
                        lines_out.append(f"{marker}{j}: {block_lines[j][:120]}")
                    if end < len(block_lines):
                        lines_out.append("  ...")
        else:
            for m in matches:
                lines_out.append(f"{r['path']}: {m.strip()[:120]}")
    return "\n".join(lines_out)
#[cf]
#[of]: tf_renameBlock
@mcp.tool()
def tf_renameBlock(path: str, new_label: str, write: bool = True) -> dict:
    """Rename a block (updates tags only, content unchanged). Cannot rename root.
    See tf_man(topic='flows/f_write').
    """
    file_path, lines, root, open_tag, close_tag = _load(path)
    blk_path = _block_path(path)
    block = get_block(root, blk_path)
    if block is None or block is root:
        return {"ok": False, "error": f"block not found: {blk_path}"}
    new_lines = cmd_rename_block(lines, block, new_label, open_tag, close_tag)
    if write:
        err = _safe_save(file_path, new_lines, open_tag, close_tag)
        if err:
            return {"ok": False, "error": err}
    return {"ok": True, "renamed": blk_path, "newLabel": new_label}
#[cf]
#[of]: tf_moveBlock
@mcp.tool()
def tf_moveBlock(path: str, new_parent: str, after: str = None, write: bool = True) -> dict:
    """Move a block as child of new_parent. after= positions among siblings.
    To reorder existing siblings use tf_editText on parent with [label] in desired order.
    See tf_man(topic='flows/f_write').
    """
    file_path, lines, root, open_tag, close_tag = _load(path)
    blk_path = _block_path(path)
    block = get_block(root, blk_path)
    if block is None or block is root:
        return {"ok": False, "error": f"block not found: {blk_path}"}
    parent_path = new_parent.split("@", 1)[-1] if "@" in new_parent else new_parent
    parent_block = get_block(root, parent_path)
    if parent_block is None:
        return {"ok": False, "error": f"new_parent not found: {parent_path}"}
    after_block = None
    if after:
        after_path = after.split("@", 1)[-1] if "@" in after else after
        after_block = get_block(root, after_path)
        if after_block is None:
            return {"ok": False, "error": f"after block not found: {after_path}"}
    new_lines, err = cmd_move_block_to_parent(lines, block, parent_block, open_tag, close_tag,
                                              after_block=after_block)
    if err:
        return {"ok": False, "error": err}
    if write:
        save_err = _safe_save(file_path, new_lines, open_tag, close_tag)
        if save_err:
            return {"ok": False, "error": save_err}
    return {"ok": True, "moved": blk_path, "newParent": parent_path}
#[cf]
#[of]: tf_removeBlock
@mcp.tool(annotations=DESTRUCTIVE)
def tf_removeBlock(path: str, keep_content: bool = False, write: bool = True) -> dict:
    """Remove a block. keep_content=True removes only TF tags, leaving text inline (flatten).
    Without keep_content: IRREVERSIBLE. Cannot remove root.
    See tf_man(topic='flows/f_write').
    """
    file_path, lines, root, open_tag, close_tag = _load(path)
    blk_path = _block_path(path)
    block = get_block(root, blk_path)
    if block is None or block is root:
        return {"ok": False, "error": f"block not found or is root: {blk_path}"}
    new_lines = cmd_remove_block(lines, block, keep_content=keep_content)
    if write:
        err = _safe_save(file_path, new_lines, open_tag, close_tag)
        if err:
            return {"ok": False, "error": err}
    action = "flattened" if keep_content else "removed"
    return {"ok": True, action: blk_path}
#[cf]
#[of]: tf_duplicateBlock
@mcp.tool()
def tf_duplicateBlock(path: str, new_label: str = None, write: bool = True) -> dict:
    """Duplicate a block, inserting the copy immediately after as a sibling.
    See tf_man(topic='flows/f_write').
    """
    file_path, lines, root, open_tag, close_tag = _load(path)
    blk_path = _block_path(path)
    blk = get_block(root, blk_path)
    if blk is None or blk is root:
        return {"ok": False, "error": f"block not found: {blk_path}"}
    new_lines = cmd_duplicate_block(lines, blk, open_tag, close_tag, new_label=new_label)
    if write:
        err = _safe_save(file_path, new_lines, open_tag, close_tag)
        if err:
            return {"ok": False, "error": err}
    actual_label = new_label or (blk.label + "_copy")
    return {"ok": True, "duplicated": blk_path, "new_label": actual_label}
#[cf]
#[of]: tf_inspect
# Budget for auto-depth mode: target output lines. Allows soft overshoot.
_AUTO_DEPTH_BUDGET = 200

def tf_inspect(path: str = None, block: str = None, depth: int = None,
               mode: str = "read") -> str:
    """DEPRECATED — internal helper used by tests. Use tf_tree (navigation)
    or tf_audit (gap analysis). Kept for backward compatibility only.
    mode='read' = bare; 'inspect' = +alerts; 'audit' = problems only."""
    if depth == 0:
        return json.dumps({"ok": False, "error": "depth=0 shows nothing — use depth=1 for direct children or depth=-1 for everything."})
    if mode not in ("read", "inspect", "audit"):
        return json.dumps({"ok": False, "error": f"mode must be 'read', 'inspect', or 'audit' (got {mode!r})."})
    out_lines = []

#[of]: _render_block
    def _render_block(blk, indent=0, max_depth=-1, is_target=False):
        # is_target=True means this is the explicitly requested block
        # Always print the target block, even if max_depth=0
        if max_depth == 0 and not is_target:
            return
        prefix = "  " * indent
        lines_span = blk.end_line - blk.start_line if blk.start_line >= 0 else 0
        has_children = bool(blk.children)
        has_inline = any(hasattr(i, "text") and i.text.strip() for i in blk.items)
        warns = []
        if has_inline and has_children:
            warns.append(f"MIXED:{lines_span}L")
        if not has_children and lines_span > 30:
            warns.append(f"TEXT:{lines_span}L")
        # mode controls output:
        #   'read'    -> no alerts (bare structure)
        #   'inspect' -> structure + alerts
        #   'audit'   -> show only nodes with alerts (filtered tree)
        show_alerts = (mode != "read")
        warn_str = f"  ⚠ {','.join(warns)}" if (warns and show_alerts) else ""
        label = blk.label if blk.label != "root" else None
        # In audit mode, only emit nodes that have warnings
        if label and (mode != "audit" or warns):
            out_lines.append(f"{prefix}{label}{warn_str}")
        next_depth = max_depth - 1 if max_depth > 0 else -1
        for child in blk.children:
            _render_block(child, indent + (1 if label else 0), next_depth, is_target=False)
#[cf]

#[of]: _render_file
    def _render_file(fabs, frel, start_block=None):
        try:
            with open(fabs) as fh:
                flines = fh.readlines()
            ot, ct = tags_for_file(fabs)
            root_block = parse(flines, ot, ct)
            if start_block:
                blk = get_block(root_block, start_block)
                if blk is None:
                    out_lines.append(f"  [block not found: {start_block}]")
                    return
            else:
                blk = root_block

            if depth is None:
                # Auto-depth: expand progressively until output exceeds budget
                effective_depth, auto_hint = _auto_expand(blk, is_target=(start_block is not None))
                _render_block(blk, max_depth=effective_depth, is_target=(start_block is not None))
                if auto_hint:
                    out_lines.append(auto_hint)
            else:
                effective_depth = (depth + 1) if depth >= 0 else -1
                _render_block(blk, max_depth=effective_depth, is_target=(start_block is not None))
        except Exception as e:
            out_lines.append(f"  [ERROR: {e}]")
#[cf]

#[of]: _auto_expand
    def _auto_expand(blk, is_target=False):
        """Find the largest depth that keeps output under _AUTO_DEPTH_BUDGET lines.
        Returns (effective_depth, hint_str). Always returns at least depth=1."""
        best_depth = 1  # user-facing depth (children levels shown)
        best_lines = []
        for user_depth in range(1, 10):  # reasonable upper bound
            probe = []
            # effective internal depth = user_depth + 1 (root block + N levels)
            _render_block_to(blk, probe, max_depth=user_depth + 1, is_target=is_target)
            if len(probe) <= _AUTO_DEPTH_BUDGET:
                best_depth = user_depth
                best_lines = probe
                # If deeper doesn't add anything, we've reached the full tree.
                probe_next = []
                _render_block_to(blk, probe_next, max_depth=user_depth + 2, is_target=is_target)
                if len(probe_next) == len(probe):
                    return user_depth + 1, None
            else:
                break
        hint = f"\n[auto-depth={best_depth}, {len(best_lines)}L shown; use depth=N for deeper]"
        return best_depth + 1, hint

    def _render_block_to(blk, target_list, indent=0, max_depth=-1, is_target=False):
        """Same as _render_block but writes to given list instead of out_lines closure.
        Honors the 'mode' from the enclosing tf_inspect call."""
        if max_depth == 0 and not is_target:
            return
        prefix = "  " * indent
        lines_span = blk.end_line - blk.start_line if blk.start_line >= 0 else 0
        has_children = bool(blk.children)
        has_inline = any(hasattr(i, "text") and i.text.strip() for i in blk.items)
        warns = []
        if has_inline and has_children:
            warns.append(f"MIXED:{lines_span}L")
        if not has_children and lines_span > 30:
            warns.append(f"TEXT:{lines_span}L")
        show_alerts = (mode != "read")
        warn_str = f"  ⚠ {','.join(warns)}" if (warns and show_alerts) else ""
        label = blk.label if blk.label != "root" else None
        if label and (mode != "audit" or warns):
            target_list.append(f"{prefix}{label}{warn_str}")
        next_depth = max_depth - 1 if max_depth > 0 else -1
        for child in blk.children:
            _render_block_to(child, target_list, indent + (1 if label else 0), next_depth, is_target=False)
#[cf]

    cwd = _get_project_cwd()
    if cwd is None:
        if path is None or path == ".":
            return json.dumps({"ok": False, "error": "TF not initialized. Use an absolute path (e.g. '/abs/path/file.py') or run tf_initProject."})
        cwd = os.getcwd()

    # Extract block from path if path contains '@' and block parameter is not provided
    if path and "@" in path and block is None:
        path_part, block = path.split("@", 1)
        path = path_part
#[cf]

#[of]: _inspect_components
    if path is None:
        components_path = os.path.join(cwd, ".tf/components.tf")
        if not os.path.exists(components_path):
            return "components.tf not found. Use path='.' for the full project."
        out_lines.append(".tf/components.tf:")
        _render_file(components_path, ".tf/components.tf", start_block=block)
        return "\n".join(out_lines)
#[cf]

    abs_path = _abs(path)

    if os.path.isfile(abs_path):
        frel = os.path.relpath(abs_path, cwd)
        _render_file(abs_path, frel, start_block=block)
        return "\n".join(out_lines)

#[of]: _inspect_dir
    SKIP_DIRS = _get_skip_dirs(abs_path)
    scan = cmd_scan(abs_path)
    tf_files = []
    for f in scan.get("files", []):
        if not f.get("structured"):
            continue
        frel = os.path.relpath(f["file"], abs_path) if os.path.isabs(f["file"]) else f["file"]
        top = frel.replace("\\", "/").split("/")[0]
        if top in SKIP_DIRS:
            continue
        tf_files.append((frel, f["file"]))

    for frel, fabs in sorted(tf_files):
        out_lines.append(f"\n{frel}:")
        full = fabs if os.path.isabs(fabs) else os.path.join(abs_path, fabs)
        _render_file(full, frel, start_block=block)

    return "\n".join(out_lines)
#[cf]
#[cf]
#[of]: tf_normalize
@mcp.tool()
def tf_normalize(path: str, write: bool = False) -> dict:
    """Normalize TF file formatting (blank line before close tags, none between siblings).
    write=False (default) = preview only.
    See tf_man(topic='flows/f_onboard').
    """
    file_path, lines, root, open_tag, close_tag = _load(path)
    new_lines = cmd_normalize(root, open_tag, close_tag)
    if write:
        err = _safe_save(file_path, new_lines, open_tag, close_tag)
        if err:
            return {"ok": False, "error": err}
    return {"ok": True, "normalized": file_path, "written": write, "lines": len(new_lines)}
#[cf]
#[of]: tf_strip
@mcp.tool(annotations=DESTRUCTIVE)
def tf_strip(path: str, write: bool = False) -> dict:
    """Remove all TF markers from a file, returning plain text.
    write: False (default) = preview only, True = overwrites (irreversible — commit first).
    See tf_man(topic='flows/f_onboard').
    """
    file_path = _abs(path.split('@')[0])
    with open(file_path, encoding='utf-8') as f:
        lines = f.readlines()
    open_tag, close_tag = tags_for_file(file_path)
    open_re, close_re = _make_patterns(open_tag, close_tag)

    # detect inline tags — tags that appear mid-line (not at column 0 alone)
    inline = []
    for i, line in enumerate(lines, 1):
        stripped = line.rstrip('\n')
        if open_tag in stripped or close_tag in stripped:
            if not open_re.match(line) and not close_re.match(line):
                inline.append({'line': i, 'content': stripped})

    stripped_lines = cmd_strip(lines, open_tag, close_tag)

    if write:
        if inline:
            return {
                'ok': False,
                'error': f'Found {len(inline)} inline tag(s) — fix manually before stripping',
                'inline_tags': inline,
            }
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(stripped_lines)

    return {
        'ok': True,
        'written': write,
        'lines_before': len(lines),
        'lines_after': len(stripped_lines),
        'inline_tags': inline,
        'warning': f'{len(inline)} inline tag(s) not removed — fix manually' if inline else None,
    }
#[cf]
#[of]: tf_onboard
@mcp.tool()
def tf_onboard(path: str, write: bool = False) -> dict:
    """Mechanical onboarding: wraps top-level blocks (classes/functions) AND
    their direct methods in one call. write: False = preview, True = apply.
    Always preview first. See tf_man(topic='flows/f_onboard').
    """
    file_path = _abs(path.split('@')[0])
    open_tag, close_tag = tags_for_file(file_path)

    with open(file_path, encoding='utf-8') as f:
        lines = f.readlines()

    # --- Step 0: fix inline close tags ---
    fixed_lines, fixes = cmd_onboard_fix_tags(lines, open_tag, close_tag)

    # --- Step 0.2: remove orphan open tags ---
    cleaned_lines, orphans = cmd_onboard_remove_orphan_tags(fixed_lines, open_tag, close_tag)

    # --- Step 0.1: add root wrapper ---
    rooted_lines, root_added = cmd_onboard_add_root(cleaned_lines, open_tag, close_tag)

    # --- Step 1: mechanical scan (for preview) ---
    candidates = cmd_onboard_scan(rooted_lines, open_tag, close_tag)

    result = {
        'ok': True,
        'file': file_path,
        'written': False,
        'fix_tags':       {'inline_tags_found': len(fixes), 'fixes': fixes},
        'remove_orphans': {'orphans_removed': len(orphans), 'removed': orphans},
        'add_root':       {'root_added': root_added},
        'scan':           {'candidates_found': len(candidates)},
    }

    if not write:
        result['scan']['candidates'] = candidates
        result['note'] = (
            'Preview only. Call with write=True to apply. Mechanical wrapping '
            'covers top-level classes/functions AND their direct methods. '
            'After applying: tf_initProject (wiki) and register in components.tf.'
        )
        return result

    # --- Write: apply steps 0 + 0.2 + 0.1 ---
    if fixes or orphans or root_added:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(rooted_lines)
        result['written'] = True
        with open(file_path, encoding='utf-8') as f:
            rooted_lines = f.readlines()

    # --- Write: step 1 — top-down then bottom-up within each level ---
    # Strategy: wrap depth=1 (classes) first on clean coordinates,
    # then rescan and wrap depth=2 (methods) bottom-up inside each class.
    # This avoids the coordinate corruption caused by wrapping methods first
    # (their tags at col-0 break find_block_end for the parent class scan).
    open_re, close_re = _make_patterns(open_tag, close_tag)
    current_lines = list(rooted_lines)
    wrapped = []
    skipped = []

    # pass 1: classes/functions (depth=1) bottom-up on original coordinates
    depth1 = sorted(
        [c for c in candidates if c.get('depth', 1) == 1],
        key=lambda c: c['start'], reverse=True
    )
    for c in depth1:
        new_lines, err = cmd_set_block(
            current_lines, c['label'], c['start'], c['end'],
            open_tag, close_tag, open_re, close_re
        )
        if err:
            skipped.append({'label': c['label'], 'reason': err,
                            'start': c['start'], 'end': c['end']})
        else:
            current_lines = new_lines
            wrapped.append(c['label'])

    # pass 2: rescan for methods (depth=2) — now inside wrapped class blocks
    candidates2 = cmd_onboard_scan(current_lines, open_tag, close_tag)
    depth2 = sorted(
        [c for c in candidates2 if c.get('depth', 1) == 2],
        key=lambda c: c['start'], reverse=True
    )
    for c in depth2:
        new_lines, err = cmd_set_block(
            current_lines, c['label'], c['start'], c['end'],
            open_tag, close_tag, open_re, close_re
        )
        if err:
            skipped.append({'label': c['label'], 'reason': err,
                            'start': c['start'], 'end': c['end']})
        else:
            current_lines = new_lines
            wrapped.append(c['label'])

    save_err = _safe_save(file_path, current_lines, open_tag, close_tag)
    if save_err:
        result['ok'] = False
        result['error'] = save_err
        return result

    result['written'] = True
    result['phase'] = 'mechanical_complete'
    # Conta wrapped per depth (pass 1 = depth1, pass 2 = depth2)
    _n_d1 = len(depth1) - sum(1 for s in skipped if s.get('start') in [c['start'] for c in depth1])
    _n_d2 = len(wrapped) - _n_d1
    result['scan']['wrapped'] = len(wrapped)
    result['scan']['wrapped_depth1'] = _n_d1
    result['scan']['wrapped_depth2'] = _n_d2
    result['scan']['skipped'] = skipped
    if skipped:
        result['scan']['note'] = (
            f"{len(skipped)} candidate(s) skipped — will appear as MIXED in tf_inspect. "
            "Handle manually with tf_wrapBlock."
        )
    result['next_required_steps'] = (
        "Mechanical block-wrapping complete (classes + methods). Remaining: "
        "(1) tf_initProject(cwd) if project wiki is not yet initialized; "
        "(2) update .tf/components.tf to register this file under the right section. "
        "Optional: review tf_audit output — any long leaf block (>80L) may benefit "
        "from further manual grouping via tf_wrapBlock."
    )

    return result
#[cf]
#[of]: tf_diff
@mcp.tool(annotations=READONLY)
def tf_diff(path_a: str, path_b: str) -> dict:
    """Semantic diff between two TF files: added, removed, modified blocks.
    See tf_man(topic='flows/f_read').
    """
    def _load_file(p):
        abs_p = _abs(p)
        ot, ct = tags_for_file(abs_p)
        flines = open(abs_p).readlines()
        return parse(flines, ot, ct)
    try:
        root_a = _load_file(path_a)
        root_b = _load_file(path_b)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "diff": cmd_diff(root_a, root_b)}
#[cf]
#[of]: tf_init
@mcp.tool()
def tf_init(path: str) -> dict:
    """Prepare prompt to AI-structure a raw file (no TF tags). Returns prompt + content + instructions.
    Execute the returned prompt: analyze → tf_editText with newBlocks. For raw files only.
    See tf_man(topic='flows/f_onboard').
    """
    return cmd_init(_abs(path))
#[cf]
#[of]: tf_createFile
@mcp.tool()
def tf_createFile(path: str) -> dict:
    """Create a new TF-ready file with #[of]: root / #[cf] wrapper. File must not exist.
    See tf_man(topic='flows/f_onboard').
    """
    from tf_backend import cmd_create_file
    result = cmd_create_file(_abs(path))
    if result.get("ok"):
        result["hint"] = "File created. This is a one-shot operation — if this file is part of the project, register it in .tf/components.tf now (add a node with #tf:ref pointing to the new file)."
    return result
#[cf]
#[of]: tf_audit
@mcp.tool(annotations=READONLY)
def tf_audit(path: str = ".", threshold: int = 20) -> str:
    """TF consistency audit: long blocks, unstructured files, duplicates, TODOs, misplaced tags.
    Run at session start or after refactor. See tf_man(topic='flows/f_onboard').
    """
    err = _require_init()
    if err:
        return json.dumps(err)
    import difflib
    abs_path = _abs(path)
    SKIP_DIRS = _get_skip_dirs(abs_path)
    issues = []

#[of]: _health
# --- HEALTH: long blocks, no_root, unstructured ---
    health = cmd_health(abs_path, threshold)
    long_blocks = health.get("long_blocks", [])
    no_root = health.get("no_root", [])
    unstructured = health.get("unstructured", [])
#[cf]

#[of]: _collect_files
# Raccoglie tf_files dal progetto (strutturati, no duplicati symlink)
    block_texts = []
    scan = cmd_scan(abs_path)
    tf_files = []
    seen_realpaths = set()
    for f in scan.get("files", []):
        if not f.get("structured"):
            continue
        frel = os.path.relpath(f["file"], abs_path) if os.path.isabs(f["file"]) else f["file"]
        top = frel.replace("\\", "/").split("/")[0]
        if top in SKIP_DIRS:
            continue
        full = f["file"] if os.path.isabs(f["file"]) else os.path.join(abs_path, f["file"])
        realpath = os.path.realpath(full)
        if realpath in seen_realpaths:
            continue
        seen_realpaths.add(realpath)
        tf_files.append((frel, full))
#[cf]

#[of]: _collect_leaves
# collect text of all leaf blocks
    def _collect_leaf(blk_node, file_rel, flines):
        if not blk_node.children and blk_node.label != "root":
            txt = "".join(item.text for item in blk_node.items if hasattr(item, "text")).strip()
            if txt:
                block_texts.append({"file": file_rel, "path": blk_node.path,
                                    "label": blk_node.label, "text": txt})
        for child in blk_node.children:
            _collect_leaf(child, file_rel, flines)

    for frel, full in tf_files:
        try:
            with open(full) as fh:
                flines = fh.readlines()
            ot, ct = tags_for_file(full)
            root_block = parse(flines, ot, ct)
            _collect_leaf(root_block, frel, flines)
        except Exception:
            pass
#[cf]

#[of]: _checks
# Duplicati >80%
    seen_pairs = set()
    for i, a in enumerate(block_texts):
        for b in block_texts[i+1:]:
            if a["file"] == b["file"] and a["path"] == b["path"]:
                continue
            key = tuple(sorted([a["path"], b["path"]]))
            if key in seen_pairs:
                continue
            ratio = difflib.SequenceMatcher(None, a["text"], b["text"]).ratio()
            if ratio >= 0.80:
                seen_pairs.add(key)
                issues.append({"type": "duplicate_code", "similarity": round(ratio, 2),
                               "block_a": f"{a['file']}@{a['path']}",
                               "block_b": f"{b['file']}@{b['path']}",
                               "label": a["label"]})

    # Costanti ridondanti
    CONST_PATTERNS = {
        "SKIP_DIRS": r'SKIP_DIRS\s*=\s*\{([^}]+)\}',
        "SKIP_EXTS": r'SKIP_EXTS\s*=\s*\{([^}]+)\}',
        "TEXT_EXTS": r'TEXT_EXTS\s*=\s*\{([^}]+)\}',
    }
    const_occurrences = {k: [] for k in CONST_PATTERNS}
    for blk_item in block_texts:
        for const_name, pattern in CONST_PATTERNS.items():
            m = re.search(pattern, blk_item["text"], re.DOTALL)
            if m:
                const_occurrences[const_name].append(f"{blk_item['file']}@{blk_item['path']}")
    for const_name, locations in const_occurrences.items():
        if len(locations) > 1:
            issues.append({"type": "repeated_constant", "constant": const_name,
                           "locations": locations, "count": len(locations)})

    # TODO/FIXME/HACK/XXX
    MARKER_RE = re.compile(r'^(?:#|//|--|/\*)?\s*(TODO|FIXME|HACK|XXX)\b', re.IGNORECASE)
    for blk_item in block_texts:
        for line in blk_item["text"].splitlines():
            stripped = line.strip()
            m = MARKER_RE.match(stripped)
            if m:
                issues.append({"type": "todo", "kind": m.group(1).upper(),
                               "block": f"{blk_item['file']}@{blk_item['path']}",
                               "text": stripped[:120]})

    # Tag TF indentati o in commenti
    INDENTED_TAG_RE = re.compile(r'^[ \t]+#\[(?:of|cf)\]', re.MULTILINE)
    COMMENT_TAG_RE  = re.compile(r'^(?!#\[(?:of|cf)\]).*#\[(?:of|cf)\]', re.MULTILINE)
    for frel, full in tf_files:
        try:
            with open(full) as fh:
                raw = fh.read()
            for m in INDENTED_TAG_RE.finditer(raw):
                line_no = raw[:m.start()].count("\n") + 1
                issues.append({"type": "tag_indented", "file": frel,
                               "line": line_no, "text": m.group(0).strip()[:80]})
            for m in COMMENT_TAG_RE.finditer(raw):
                line_no = raw[:m.start()].count("\n") + 1
                issues.append({"type": "tag_in_comment", "file": frel,
                               "line": line_no, "text": m.group(0).strip()[:80]})
        except Exception:
            pass
#[cf]

#[of]: _format_output
    total = len(issues) + len(long_blocks) + len(no_root) + len(unstructured)
    lines_out = [f"AUDIT: {total} issue(s)"]
    if long_blocks:
        lines_out.append(f"LONG({len(long_blocks)},>{threshold}L):")
        for b in long_blocks:
            lines_out.append(f"  {b['lines']}L {b['file']}@{b['path']}")
    if no_root:
        lines_out.append(f"NO_ROOT({len(no_root)}):")
        for f in no_root:
            lines_out.append(f"  {f['file']} {f['lines']}L")
    if unstructured:
        lines_out.append(f"UNSTRUCTURED({len(unstructured)}):")
        for f in unstructured:
            lines_out.append(f"  {f['priority']} {f['file']} {f['lines']}L")
    for iss in issues:
        if iss["type"] == "duplicate_code":
            lines_out.append(f"DUP({iss['similarity']}) {iss['block_a']} <> {iss['block_b']}")
        elif iss["type"] == "repeated_constant":
            lines_out.append(f"CONST {iss['constant']}x{iss['count']}: {', '.join(iss['locations'])}")
        elif iss["type"] == "todo":
            lines_out.append(f"{iss['kind']} {iss['block']}: {iss['text'][:80]}")
        elif iss["type"] == "tag_indented":
            lines_out.append(f"TAG_INDENT {iss['file']}:{iss['line']}")
        elif iss["type"] == "tag_in_comment":
            lines_out.append(f"TAG_COMMENT {iss['file']}:{iss['line']}")
    if issues or long_blocks or no_root or unstructured:
        lines_out.append("FIX: LONG>UNSTRUCTURED>CONST>DUP>TODO>TAG")
    return "\n".join(lines_out)
#[cf]
#[cf]
#[of]: tf_man
@mcp.tool(annotations=READONLY, structured_output=False)
def tf_man(topic: str = "", level: int = 1) -> str:
    """TF AI manual with progressive disclosure.
    topic='' level=1  -> root/bootstrap (~20 lines, start here).
    topic='principles' -> the 3 iron rules.
    topic='<tool_name>' level=N -> root/tools/<group>/<tool>/lN (1=min, 2=mid, 3=max).
      If level N is missing for that tool, falls back to the highest available level.
    topic='flows/<name>' -> end-to-end sequence (f_bootstrap, f_read, f_write, f_onboard).
    topic='errors' -> common error -> cause -> remedy table.
    The manual is itself a TF file at ai.tf in the textfolding package.
    """
    base = os.path.dirname(os.path.realpath(__file__))
    manual = os.path.join(base, "textfolding", "ai.tf")
    if not os.path.exists(manual):
        return f"Manual not found — reinstall textfolding (pip install git+https://github.com/lucmas655321/tf)."

    flines = open(manual).readlines()
    ot, ct = tags_for_file(manual)
    root   = parse(flines, ot, ct)

    def _render(blk):
        return "".join(cmd_strip(flines, ot, ct, blk))

    # topic='' or 'bootstrap' -> bootstrap block
    if topic in ("", "bootstrap"):
        blk = get_block(root, "root/bootstrap")
        return _render(blk) if blk else "root/bootstrap not found in ai.tf."

    # topic direct children of root: principles, errors
    if topic in ("principles", "errors"):
        blk = get_block(root, f"root/{topic}")
        return _render(blk) if blk else f"root/{topic} not found in ai.tf."

    # topic='flows/<name>'
    if topic.startswith("flows/"):
        blk = get_block(root, f"root/{topic}")
        if blk is None:
            flows = [c.label for c in (get_block(root, "root/flows").children if get_block(root, "root/flows") else [])]
            return f"flow '{topic[6:]}' not found. Available: {flows}"
        return _render(blk)

    # topic='<tool_name>' -> search under root/tools/*/<tool>/l<level>
    tools_root = get_block(root, "root/tools")
    if tools_root is None:
        return "Section root/tools not found in ai.tf."

    # find tool block via wildcard
    tool = get_block_wild(root, f"root/tools/*/{topic}")
    if tool is not None:
        group_label = tool.parent.label if hasattr(tool, 'parent') and tool.parent else "?"
        available = sorted(
            [c.label for c in tool.children if c.label.startswith("l") and c.label[1:].isdigit()],
            key=lambda s: int(s[1:]),
        )
        if not available:
            return _render(tool)
        target = f"l{level}"
        if target not in available:
            lower = [x for x in available if int(x[1:]) <= level]
            target = lower[-1] if lower else available[-1]
        for c in tool.children:
            if c.label == target:
                body = _render(c)
                header = f"{topic} — {target}"
                if target != f"l{level}":
                    header += f"  (requested l{level}, returned highest available)"
                return header + "\n" + body

    # unknown topic: list available tools
    tools_list = []
    for group in tools_root.children:
        for tool in group.children:
            tools_list.append(f"{tool.label} ({group.label})")
    return (f"unknown topic '{topic}'. "
            f"Use topic='' (bootstrap), 'principles', 'errors', 'flows/<name>' or a tool name. "
            f"Available tools: {', '.join(tools_list)}")
#[cf]
#[of]: tf_session
@mcp.tool()
def tf_session(path: str, action: str = "load",
               status: str = "", next: str = "",
               decisions: str = "", blocks: str = "",
               keys: list[str] = None) -> str | dict:
    """Save/load session context between sessions.
    action: 'save' (status, next, decisions, blocks) | 'load' (keys=None → status+next).
    path: any TF file block (no default wiki anymore). See tf_man(topic='tf_session', level=1).
    """
    file_path, lines, root, open_tag, close_tag = _load(path)

    if action == "load":
#[of]: _load_session
        session = cmd_read_session(root, keys)
        if session is None:
            return "No saved session."
        parts = []
        for k, v in session.items():
            if v and v.strip():
                parts.append(f"## {k}\n{v.strip()}")
        return "\n\n".join(parts) if parts else "Empty session."
#[cf]

    if action == "save":
#[of]: _save_session
        data = {k: v for k, v in
                {"status": status, "next": next, "decisions": decisions, "blocks": blocks}.items()
                if v}
        if not data:
            return {"ok": False, "error": "no data to save"}

        session_block = None
        for spath in ("root/roadmap/session", "root/session"):
            session_block = get_block(root, spath)
            if session_block:
                break

        if not session_block:
            parent_path = "root/roadmap" if get_block(root, "root/roadmap") else "root"
            parent = get_block(root, parent_path)
            cur = parent.render()
            try:
                new_lines = cmd_edit_text(lines, parent, cur + "\n[session]", open_tag, close_tag, {
                    "session": "[status]\n[next]\n[decisions]\n[blocks]",
                    "status": status, "next": next, "decisions": decisions, "blocks": blocks,
                })
            except Exception as e:
                return {"ok": False, "error": str(e)}
            err = _safe_save(file_path, new_lines, open_tag, close_tag)
            if err:
                return {"ok": False, "error": err}
            return {"ok": True, "session": "created"}

        sub_labels = [c.label for c in session_block.children]
        if not sub_labels:
            try:
                new_lines = cmd_edit_text(lines, session_block,
                                          "[status]\n[next]\n[decisions]\n[blocks]",
                                          open_tag, close_tag,
                                          {"status": status, "next": next,
                                           "decisions": decisions, "blocks": blocks})
            except Exception as e:
                return {"ok": False, "error": str(e)}
            err = _safe_save(file_path, new_lines, open_tag, close_tag)
            if err:
                return {"ok": False, "error": err}
            return {"ok": True, "session": "migrated+saved"}

        new_lines = lines
        updated = []
        for key, value in data.items():
            sub = _find_child(session_block, key)
            if sub is not None:
                try:
                    new_lines = cmd_edit_text(new_lines, sub, value, open_tag, close_tag, None)
                except Exception as e:
                    return {"ok": False, "error": str(e)}
                root = parse(new_lines, open_tag, close_tag)
                session_block = None
                for spath in ("root/roadmap/session", "root/session"):
                    session_block = get_block(root, spath)
                    if session_block:
                        break
                updated.append(key)
        err = _safe_save(file_path, new_lines, open_tag, close_tag)
        if err:
            return {"ok": False, "error": err}
        return {"ok": True, "session": "saved", "updated": updated}
#[cf]

    return {"ok": False, "error": f"unknown action: {action}. Use 'save' or 'load'."}
#[cf]
#[of]: tf_agent
@mcp.tool()
def tf_agent(path: str, action: str, agent_id: str = "miller", data: dict = None,
             stale_secs: int = 300) -> dict:
    """Manage multi-agent sessions (.tf/sessions/).
    action: 'set'|'get'|'list'|'clean'. agent_id: caller identity (default 'miller').
    data focus path must be absolute. See tf_man(topic='flows/f_session').
    """
    err = _require_init()
    if err:
        return err
    abs_path = _abs(path)

    if action == "set":
        if not agent_id:
            return {"ok": False, "error": "agent_id is required"}
        if data and "path" in data:
            if not data["path"].startswith("/"):
                return {"ok": False, "error": f"path must be absolute, got: '{data['path']}'"}
            if "@" not in data["path"]:
                return {"ok": False, "error": f"path must include the file: '/abs/file.tf@root/block', got: '{data['path']}'"}
        result = cmd_set_session(abs_path, agent_id, data)
        return {"ok": True, **result}

    if action == "get":
        if not agent_id:
            return {"ok": False, "error": "agent_id is required"}
        result = cmd_get_session(abs_path, agent_id)
        return {"ok": True, **result}

    if action == "list":
        result = cmd_list_sessions(abs_path, stale_secs)
        return {"ok": True, **result}

    if action == "clean":
        if not agent_id:
            return {"ok": False, "error": "agent_id is required"}
        result = cmd_clean_session(abs_path, agent_id)
        return {"ok": True, **result}

    return {"ok": False, "error": f"unknown action: {action}. Use 'set', 'get', 'list', 'clean'."}
#[cf]
#[of]: tf_miller
@mcp.tool()
def tf_miller(cmd: str, path: str = None, action: str = None,
              from_line: int = None, to_line: int = None,
              label: str = None, text: str = None,
              new_blocks: dict = None, port: int = 7891) -> dict:
    """Control Miller via HTTP RPC (port 7891).
    cmd: 'state'|'focus'|'open'|'command'|'navigateRef'|'select'|'wrap'|'propose'.
    'propose' blocks until user clicks Apply/Discard → {result, changed}. See tf_man(topic='flows/f_session').
    """
    import urllib.request, json as _json, urllib.error

    base = f"http://127.0.0.1:{port}"

    def _get(endpoint):
        try:
            with urllib.request.urlopen(f"{base}{endpoint}", timeout=6) as r:
                return _json.loads(r.read())
        except urllib.error.URLError as e:
            return {"error": f"Miller unreachable: {e}"}

    def _post(endpoint, payload, timeout=6):
        try:
            data = _json.dumps(payload).encode()
            req = urllib.request.Request(f"{base}{endpoint}", data=data,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return _json.loads(r.read())
        except urllib.error.URLError as e:
            return {"error": f"Miller unreachable: {e}"}

    if cmd == "state":
        return _get("/state")
    elif cmd == "focus":
        if not path:
            return {"ok": False, "error": "path required for 'focus'"}
        return _post("/focus", {"path": path})
    elif cmd == "open":
        if not path:
            return {"ok": False, "error": "path required for 'open' (format: /abs/file.txt@root/block)"}
        if "@" in path:
            file_path, block_path = path.split("@", 1)
        else:
            file_path, block_path = path, "root"
        return _post("/open", {"file": file_path, "path": block_path})
    elif cmd == "navigateRef":
        if not path:
            return {"ok": False, "error": "path required for 'navigateRef'"}
        return _post("/navigateRef", {"target": path})
    elif cmd == "command":
        if not action:
            return {"ok": False, "error": "action required for 'command'"}
        return _post("/command", {"action": action})
    elif cmd == "propose":
        if text is None:
            return {"ok": False, "error": "text required for 'propose'"}
        return _post("/propose", {"text": text, "newBlocks": new_blocks or {}}, timeout=35)
    elif cmd == "select":
        if from_line is None or to_line is None:
            return {"ok": False, "error": "from_line and to_line required for 'select'"}
        return _post("/select", {"from": from_line, "to": to_line})
    elif cmd == "wrap":
        if not label:
            return {"ok": False, "error": "label required for 'wrap'"}
        return _post("/wrap", {"label": label})
    else:
        return {"ok": False, "error": f"unknown cmd: {cmd}. Use 'state','focus','open','command','navigateRef','select','wrap','propose'"}
#[cf]
#[of]: tf_check_env
@mcp.tool(annotations=READONLY)
def tf_check_env() -> dict:
    """Diagnose MCP process environment. Call BEFORE tf_initProject if tools can't find project.
    Returns os_getcwd, env_PWD, _PROJECT_CWD and all env vars. Works without TF initialized.
    """
    import os
    return {
        "ok": True,
        "os_getcwd": os.getcwd(),
        "env_PWD": os.environ.get("PWD"),
        "env_HOME": os.environ.get("HOME"),
        "env_TF_PROJECT_DIR": os.environ.get("TF_PROJECT_DIR"),
        "_PROJECT_CWD": _PROJECT_CWD,
        "all_env": dict(os.environ),
    }
#[cf]
#[of]: tf_initProject
@mcp.tool()
def tf_initProject(cwd: str) -> dict:
    """Initialize TextFolding in a project. Creates .tf/config.tf only.
    cwd: absolute path of the project directory. ONLY tool that works without .tf/config.tf.
    No wiki template copy (removed 2026-04-21 — KISS: workspace holds only config+components+sessions).
    See tf_man(topic='tf_initProject', level=1).
    """
    global _PROJECT_CWD

    if not cwd or not os.path.isabs(cwd):
        return {"ok": False, "error": f"cwd must be an absolute path, got: '{cwd}'"}
    if not os.path.isdir(cwd):
        return {"ok": False, "error": f"directory not found: '{cwd}'"}

    result = cmd_write_config(cwd)
    if not result.get("ok"):
        return result

    # persist cwd for the session — lets subsequent tools work even if
    # os.getcwd() points to a different directory
    _PROJECT_CWD = cwd

    return result
#[cf]
#tf:ref archive/wiki_legacy_2026-04-21/  (wiki_index rimosso — KISS: nessun wiki nei workspace)
#[of]: _public_server
_AI_TF = os.path.join(os.path.dirname(os.path.realpath(__file__)), "textfolding", "ai.tf")
_BOOTSTRAP_PATH = _AI_TF + "@root/bootstrap_lite"
_BOOTSTRAP_FALLBACK = (
    'TextFolding — tf({"tool":"<name>",...kwargs})\n'
    'Call tf(\'{"tool":"tf_man","topic":""}\') for the bootstrap.\n'
)

mcp_public = FastMCP(
    "textfolding",
    instructions="""TextFolding — structural navigation for text files.
Use tf(cmd) for ALL file access. Do NOT use Read/Edit/Write/Bash on source files.
Call tf('') for syntax and available tools.
Call tf_man() for the quick-start guide."""
)

#[of]: _bootstrap
def _bootstrap() -> str:
    """Load bootstrap_lite from ai.tf for the public server."""
    try:
        result = tf_getBlockContent(path=_BOOTSTRAP_PATH, mode="structured")
        if isinstance(result, str):
            return result
        if isinstance(result, dict) and "result" in result:
            return result["result"]
        return str(result)
    except Exception:
        return _BOOTSTRAP_FALLBACK
#[cf]
#[of]: _safe_man
def _safe_man(topic: str = "", level: int = 1) -> str:
    """Fetch the relevant manual section for an error response.
    Single source of truth: ai.tf via tf_man().
    Empty string on any failure (errors must never crash the dispatcher)."""
    try:
        return tf_man(topic=topic, level=level)
    except Exception:
        return ""
#[cf]

#[of]: tf
@mcp_public.tool(structured_output=False)
def tf(cmd: str) -> str:
    """Run a TF tool: tf('{"tool":"tf_tree","path":"file.py"}').
    Call tf('') to discover all available tools and syntax.

    Output policy: pass-through. Read tools return plain text verbatim;
    write tools and errors return JSON. No {"result": ...} wrap.
    """
    if not cmd or not cmd.strip():
        if _get_project_cwd() is None:
            return json.dumps({
                "ok": False,
                "error": "cwd required",
                "manual": _safe_man("errors")
            })
        return _bootstrap()

    try:
        data = json.loads(cmd)
    except json.JSONDecodeError as e:
        return json.dumps({"ok": False,
            "error": f"Invalid JSON: {e}",
            "manual": _safe_man("errors")})

    if not isinstance(data, dict):
        return json.dumps({"ok": False,
            "error": f"tf(cmd) expects a JSON object, got {type(data).__name__}.",
            "manual": _safe_man("")})

    # {"cwd": "/path"} — set project root and return bootstrap
    if "cwd" in data and "tool" not in data:
        global _PROJECT_CWD
        cwd = data["cwd"]
        if not os.path.isabs(cwd):
            return json.dumps({"ok": False, "error": "cwd must be an absolute path."})
        if not os.path.isdir(cwd):
            return json.dumps({"ok": False, "error": f"cwd not found: {cwd}"})
        _PROJECT_CWD = cwd
        return _bootstrap()

    tool_name = data.pop("tool", None)
    if tool_name is None:
        return json.dumps({"ok": False,
            "error": "Missing 'tool' key in JSON.",
            "manual": _safe_man("")})

    if tool_name == "tf_man":
        topic = data.get("topic", "")
        level = int(data.get("level", 1))
        return tf_man(topic=topic, level=level)

    if tool_name == "tf_read":
        # AI consistently invents tf_read — alias to tf_getBlockContent
        tool_name = "tf_getBlockContent"

    # Auto-bootstrap: replicate tf_check_env + tf_initProject(cwd=os.getcwd())
    # transparently on the first call. Predetermined steps, no reason to
    # delegate them to the model.
    if tool_name not in ("tf_check_env", "tf_initProject"):
        _auto_init_from_cwd(data.get("path", ""))

    # tf_inspect: kept as backward-compat alias (not advertised in manual).
    # Canonical navigation tool is tf_tree.
    _tools_public = {
        "tf_tree": tf_tree, "tf_inspect": tf_inspect,  # alias
        "tf_getBlockContent": tf_getBlockContent, "tf_editText": tf_editText,
        "tf_insert": tf_insert, "tf_insert_note": tf_insert_note,
        "tf_insert_ref": tf_insert_ref, "tf_replaceInBlock": tf_replaceInBlock,
        "tf_addBlock": tf_addBlock, "tf_wrapBlock": tf_wrapBlock,
        "tf_wrapBlocks": tf_wrapBlocks, "tf_renameBlock": tf_renameBlock,
        "tf_moveBlock": tf_moveBlock, "tf_removeBlock": tf_removeBlock,
        "tf_duplicateBlock": tf_duplicateBlock, "tf_search": tf_search,
        "tf_normalize": tf_normalize, "tf_strip": tf_strip,
        "tf_onboard": tf_onboard, "tf_diff": tf_diff, "tf_init": tf_init,
        "tf_createFile": tf_createFile, "tf_audit": tf_audit,
        "tf_session": tf_session, "tf_agent": tf_agent,
        "tf_miller": tf_miller, "tf_check_env": tf_check_env,
        "tf_initProject": tf_initProject,
    }

    fn = _tools_public.get(tool_name)
    if fn is None:
        return json.dumps({"ok": False, "error": f"unknown tool: {tool_name}",
                           "available": list(_tools_public.keys()),
                           "manual": _safe_man("")})

    try:
        result = fn(**data)
    except TypeError as e:
        # Wrong/extra/missing kwargs — _attach_help adds signature + manual.
        return json.dumps(_attach_help({"ok": False, "error": str(e)}, tool_name, fn))
    except Exception as e:
        return json.dumps(_attach_help({"ok": False, "error": str(e)}, tool_name, fn))

    # Post-process: on tool-level errors, attach syntax help so the model
    # does not need to call tf_man for recovery.
    if isinstance(result, dict) and result.get("ok") is False:
        result = _attach_help(result, tool_name, fn)

    if isinstance(result, str):
        # Many internal tools return errors as json.dumps({"ok": False, ...}).
        # Detect and enrich those too, so help is consistent across all paths.
        s = result.lstrip()
        if s.startswith("{") and '"ok"' in s and '"error"' in s:
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and parsed.get("ok") is False:
                    return json.dumps(_attach_help(parsed, tool_name, fn))
            except json.JSONDecodeError:
                pass
        return result
    return json.dumps(result)


def _attach_help(err_dict: dict, tool_name: str, fn) -> dict:
    """Enrich an error dict with the tool signature + first docstring line.
    Lets the model self-recover without an extra tf_man round-trip."""
    if "tool" not in err_dict:
        err_dict["tool"] = tool_name
    if "signature" not in err_dict:
        try:
            import inspect as _inspect
            err_dict["signature"] = f"{tool_name}{_inspect.signature(fn)}"
        except Exception:
            pass
    if "manual" not in err_dict:
        # Single source of truth: ai.tf via tf_man. No proprietary hint strings.
        man = _safe_man(tool_name)
        if man:
            err_dict["manual"] = man
    return err_dict
#[cf]

#[of]: tf_man_public
@mcp_public.tool(name="tf_man", structured_output=False)
def tf_man_public(topic: str = "", level: int = 1) -> str:
    """TF manual. topic='' -> bootstrap (syntax, tools, quick start).
    topic='<tool_name>' level=1-3 -> tool-specific help.
    """
    return tf_man(topic=topic, level=level)
#[cf]
#[cf]

#[of]: main
def main():
    mcp_public.run(transport="stdio")


def main_dev():
    mcp.run(transport="stdio")


def main_ai():
    """CLI entry point: same logic as MCP tools, zero schema overhead.
    Usage: tf-ai <tool_name> <json_kwargs>
    Example: tf-ai tf_tree '{"path": "file.py"}'
    Run: tf-ai tf_man '{}' to load the bootstrap.
    """
    _tools = {
        "tf_tree": tf_tree, "tf_inspect": tf_inspect,
        "tf_getBlockContent": tf_getBlockContent, "tf_editText": tf_editText,
        "tf_insert": tf_insert, "tf_insert_note": tf_insert_note,
        "tf_insert_ref": tf_insert_ref, "tf_replaceInBlock": tf_replaceInBlock,
        "tf_addBlock": tf_addBlock, "tf_wrapBlock": tf_wrapBlock,
        "tf_wrapBlocks": tf_wrapBlocks, "tf_renameBlock": tf_renameBlock,
        "tf_moveBlock": tf_moveBlock, "tf_removeBlock": tf_removeBlock,
        "tf_duplicateBlock": tf_duplicateBlock, "tf_search": tf_search,
        "tf_normalize": tf_normalize, "tf_strip": tf_strip,
        "tf_onboard": tf_onboard, "tf_diff": tf_diff, "tf_init": tf_init,
        "tf_createFile": tf_createFile, "tf_audit": tf_audit,
        "tf_man": tf_man, "tf_session": tf_session, "tf_agent": tf_agent,
        "tf_miller": tf_miller, "tf_check_env": tf_check_env,
        "tf_initProject": tf_initProject,
    }

    args = sys.argv[1:]
    if not args:
        print(json.dumps({"ok": False, "error": "usage: tf-ai <tool_name> [json_kwargs]"}))
        sys.exit(1)

    tool_name = args[0]
    kwargs = json.loads(args[1]) if len(args) > 1 else {}

    if tool_name not in _tools:
        print(json.dumps({"ok": False, "error": f"unknown tool: {tool_name}",
                          "available": list(_tools.keys())}))
        sys.exit(1)

    try:
        r = _tools[tool_name](**kwargs)
    except TypeError as e:
        # wrong kwargs (unknown param, missing required, etc.):
        # reply with the real tool signature so the agent can self-correct
        # instead of hallucinating again (classic failure mode in lite mode).
        import inspect as _inspect
        try:
            sig = str(_inspect.signature(_tools[tool_name]))
        except (TypeError, ValueError):
            sig = "(signature unavailable)"
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "tool": tool_name,
            "signature": f"{tool_name}{sig}",
            "hint": "Check the parameter names above — do not guess. "
                    "Run tf_man(topic='') for the full tool reference.",
        }))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e), "tool": tool_name}))
        sys.exit(1)

    if isinstance(r, str):
        print(r)
    else:
        print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
#[cf]
#[cf]
