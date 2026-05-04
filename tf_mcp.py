#[of]: root
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
    # tf_api_helpers
    _get_project_cwd, _auto_init_from_cwd, _get_config_value,
    _require_init, _cwd, _get_skip_dirs,
    _load, _block_path, _reject_tf_markers, _safe_save, _abs, _homonym_warnings,
    # tf_api functions
    tf_tree, tf_getBlockContent, tf_editText, tf_insert, tf_insert_note,
    tf_insert_ref, tf_replaceInBlock, tf_addBlock, tf_wrapBlock, tf_wrapBlocks,
    tf_search, tf_renameBlock, tf_moveBlock, tf_removeBlock, tf_duplicateBlock,
    tf_inspect, tf_normalize, tf_strip, tf_onboard, tf_diff, tf_init,
    tf_createFile, tf_audit, tf_man, tf_session, tf_agent, tf_miller,
    tf_check_env, tf_initProject,
)
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

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
#[cf]
#[of]: tools
mcp.tool(annotations=READONLY)(tf_tree)
mcp.tool(annotations=READONLY)(tf_getBlockContent)
mcp.tool()(tf_editText)
mcp.tool()(tf_insert)
mcp.tool()(tf_insert_note)
mcp.tool()(tf_insert_ref)
mcp.tool()(tf_replaceInBlock)
mcp.tool()(tf_addBlock)
mcp.tool()(tf_wrapBlock)
mcp.tool()(tf_wrapBlocks)
mcp.tool(annotations=READONLY)(tf_search)
mcp.tool()(tf_renameBlock)
mcp.tool()(tf_moveBlock)
mcp.tool(annotations=DESTRUCTIVE)(tf_removeBlock)
mcp.tool()(tf_duplicateBlock)
mcp.tool()(tf_normalize)
mcp.tool(annotations=DESTRUCTIVE)(tf_strip)
mcp.tool()(tf_onboard)
mcp.tool(annotations=READONLY)(tf_diff)
mcp.tool()(tf_init)
mcp.tool()(tf_createFile)
mcp.tool(annotations=READONLY)(tf_audit)
mcp.tool(annotations=READONLY, structured_output=False)(tf_man)
mcp.tool()(tf_session)
mcp.tool()(tf_agent)
mcp.tool()(tf_miller)
mcp.tool(annotations=READONLY)(tf_check_env)
mcp.tool()(tf_initProject)
#[cf]
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

def _safe_man(topic: str = "", level: int = 1) -> str:
    """Fetch the relevant manual section for an error response."""
    try:
        return tf_man(topic=topic, level=level)
    except Exception:
        return ""

@mcp_public.tool(structured_output=False)
def tf(cmd: str) -> str:
    """Run a TF tool: tf('{\"tool\":\"tf_tree\",\"path\":\"file.py\"}').
    Call tf('') to discover all available tools and syntax.

    Output policy: pass-through. Read tools return plain text verbatim;
    write tools and errors return JSON. No {\"result\": ...} wrap.
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
        import tf_backend as _tfb
        cwd = data["cwd"]
        if not os.path.isabs(cwd):
            return json.dumps({"ok": False, "error": "cwd must be an absolute path."})
        if not os.path.isdir(cwd):
            return json.dumps({"ok": False, "error": f"cwd not found: {cwd}"})
        _tfb._PROJECT_CWD = cwd
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
        tool_name = "tf_getBlockContent"

    if tool_name not in ("tf_check_env", "tf_initProject"):
        _auto_init_from_cwd(data.get("path", ""))

    _tools_public = {
        "tf_tree": tf_tree, "tf_inspect": tf_inspect,
        "tf_getBlockContent": tf_getBlockContent, "tf_editText": tf_editText,
        "tf_insert": tf_insert, "tf_insert_note": tf_insert_note,
        "tf_insert_ref": tf_insert_ref, "tf_replaceInBlock": tf_replaceInBlock,
        "tf_addBlock": tf_addBlock,
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
        return json.dumps(_attach_help({"ok": False, "error": str(e)}, tool_name, fn))
    except Exception as e:
        return json.dumps(_attach_help({"ok": False, "error": str(e)}, tool_name, fn))

    if isinstance(result, dict) and result.get("ok") is False:
        result = _attach_help(result, tool_name, fn)

    if isinstance(result, str):
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
    """Enrich an error dict with the tool signature + first docstring line."""
    if "tool" not in err_dict:
        err_dict["tool"] = tool_name
    if "signature" not in err_dict:
        try:
            import inspect as _inspect
            err_dict["signature"] = f"{tool_name}{_inspect.signature(fn)}"
        except Exception:
            pass
    if "manual" not in err_dict:
        man = _safe_man(tool_name)
        if man:
            err_dict["manual"] = man
    return err_dict

@mcp_public.tool(name="tf_man", structured_output=False)
def tf_man_public(topic: str = "", level: int = 1) -> str:
    """TF manual. topic='' -> bootstrap (syntax, tools, quick start).
    topic='<tool_name>' level=1-3 -> tool-specific help.
    """
    return tf_man(topic=topic, level=level)
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
