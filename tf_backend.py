#!/usr/bin/env python3
#[of]: root
"""TextFolding — marker-based text folding library"""
#[of]: imports
import re
import sys
import json
import html
import argparse
import os
from dataclasses import dataclass, field
from typing import Optional

#[cf]
#[of]: constants
OPEN_TAG  = r"#[of]:"
CLOSE_TAG = r"#[cf]"
NOTE_TAG  = "#tf:note"
REF_TAG   = "#tf:ref"

# Tag per estensione: (open, close, note_prefix)
_EXT_TAGS: dict[str, tuple[str, str, str]] = {
    ".ts":   ("// [of]:", "// [cf]",      "// tf:note"),
    ".tsx":  ("// [of]:", "// [cf]",      "// tf:note"),
    ".js":   ("// [of]:", "// [cf]",      "// tf:note"),
    ".jsx":  ("// [of]:", "// [cf]",      "// tf:note"),
    ".css":  ("/* [of]:", "/* [cf] */",   "/* tf:note"),
    ".scss": ("/* [of]:", "/* [cf] */",   "/* tf:note"),
    ".md":   ("<!-- [of]:", "<!-- [cf] -->", "<!-- tf:note"),
}
#tf:ref .tf/wiki/decisions.md@root/adr_components_manifest

# Scan filters shared by cmd_scan, cmd_health, cmd_init_project.
# _is_ignored: builds a gitignore-aware matcher for a base directory.
# If pathspec is installed and .gitignore exists, use that (source of truth).
# Otherwise fallback to DEFAULT_SKIP_DIRS (path segment match).
DEFAULT_SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv",
                     ".mypy_cache", ".pytest_cache", "out", "archive",
                     "build", "dist", "tf_public", "backup_claude_config"}
DEFAULT_SKIP_EXTS = {".pyc", ".pyo", ".so", ".o", ".a", ".dll", ".exe",
                     ".jpg", ".jpeg", ".png", ".gif", ".ico", ".svg",
                     ".pdf", ".zip", ".tar", ".gz", ".lock"}
DEFAULT_TEXT_EXTS = {".py", ".ts", ".js", ".tsx", ".jsx", ".md", ".txt",
                     ".yaml", ".yml", ".toml", ".cfg", ".ini", ".sh", ".bash"}

def _build_ignore_matcher(base):
    """Returns a callable (pathlib.Path) -> bool that says whether a path should be ignored.
    Uses the base .gitignore if available (via pathspec), otherwise DEFAULT_SKIP_DIRS.
    """
    try:
        import pathspec
        gitignore_path = base / ".gitignore"
        if gitignore_path.exists():
            spec = pathspec.PathSpec.from_lines("gitwildmatch",
                                                gitignore_path.read_text().splitlines())
        else:
            spec = None
    except ImportError:
        spec = None

    def _is_ignored(fpath):
        # always excluded (even if not in .gitignore)
        if any(part in DEFAULT_SKIP_DIRS for part in fpath.parts):
            return True
        if spec is not None:
            try:
                rel = str(fpath.relative_to(base))
            except ValueError:
                return False
            return spec.match_file(rel)
        return False
    return _is_ignored
#[cf]
#[of]: data_model
#[of]: Text
@dataclass
class Text:
    text: str


@dataclass
class Note:
    """Inline annotation — preserved in the file but invisible to content.
    kind: "note" (#tf:note) or "ref" (#tf:ref)
    """
    text: str
    kind: str = "note"  # "note" | "ref"

#[cf]
#[of]: Block
@dataclass
class Block:
    label: str
    path: str
    start_line: int
    end_line: int
    items: list['Text | Block'] = field(default_factory=list)
    @property
    def children(self) -> list['Block']:
        return [i for i in self.items if isinstance(i, Block)]

    @property
    def lines(self) -> list[str]:
        return [i.text for i in self.items if isinstance(i, Text)]

    @property
    def refs(self) -> list[str]:
        """References declared with #tf:ref in this block (non-recursive)."""
        return [i.text for i in self.items if isinstance(i, Note) and i.kind == "ref"]

#[of]: to_dict
    def to_dict(self) -> dict:
        return {
            self.label: {
                "path":       self.path,
                "start_line": self.start_line,
                "end_line":   self.end_line,
                "items":      [_item_to_dict(i) for i in self.items],
            }
        }
#[cf]
#[of]: to_tree
    def to_tree(self, depth: int = -1, include_text: bool = False) -> dict:
        """Serialize the block as a tree.
        depth=-1  → full recursion (default)
        depth=0   → this block only, no children
        depth=N   → recurse up to N levels
        include_text=False → omit inline Text items (default: compact output)
        include_text=True  → include all inline text (verbose)
        """
        def _item(i):
            if isinstance(i, Text):
                if not include_text:
                    return None
                return {"type": "text", "text": i.text}
            if isinstance(i, Note):
                return {"type": "note", "kind": i.kind, "text": i.text}
            # Block
            if depth == 0:
                return {"type": "block", "label": i.label, "uid": f"{i.label}@{i.start_line}",
                        "path": i.path, "start_line": i.start_line, "end_line": i.end_line}
            return {"type": "block", **i.to_tree(depth - 1 if depth > 0 else -1, include_text=include_text)}

        notes = [i.text for i in self.items if isinstance(i, Note) and i.kind == "note"]
        refs  = [i.text for i in self.items if isinstance(i, Note) and i.kind == "ref"]
        items = [x for x in (_item(i) for i in self.items) if x is not None]
        d = {
            "label":      self.label,
            "uid":        f"{self.label}@{self.start_line}",
            "path":       self.path,
            "start_line": self.start_line,
            "end_line":   self.end_line,
            "items": items,
        }
        if notes:
            d["notes"] = notes
        if refs:
            d["refs"] = refs
        return d
#[cf]
#[of]: to_xml
    def to_xml(self, indent: int = 0) -> str:
        pad = "  " * indent
        lbl = html.escape(self.label)
        parts = [f'{pad}<{lbl} path="{self.path}" start="{self.start_line}" end="{self.end_line}">']
        for item in self.items:
            match item:
                case Text(text=t):
                    parts.append(f'{pad}  <line>{html.escape(t)}</line>')
                case Block() as b:
                    parts.append(b.to_xml(indent + 1))
        parts.append(f'{pad}</{lbl}>')
        return "\n".join(parts)
#[cf]
#[of]: render
    def render(self, expanded: bool = False, marker: str = "[{label}]") -> str:
        out = [f"[{self.label}]"]
        for item in self.items:
            match item:
                case Note():
                    pass  # annotations invisible to content
                case Text(text=t):
                    out.append(t)
                case Block() as b:
                    if expanded:
                        out.append(b.render(expanded=True, marker=marker))
                    else:
                        out.append(marker.format(label=b.label))
        return "\n".join(out)
#[cf]
#[cf]
#[of]: _item_to_dict
def _item_to_dict(item: 'Text | Block') -> dict:
    match item:
        case Text(text=t):
            return {"text": t}
        case Block() as b:
            return b.to_dict()

#[cf]

#tf:ref .tf/wiki/decisions.md@root/adr_components_manifest
#[cf]
#[of]: parser
#[of]: tags_for_file
def tags_for_file(filepath: str) -> tuple[str, str]:
    """Returns (open_tag, close_tag) for the file extension."""
    ext = os.path.splitext(filepath)[1].lower()
    entry = _EXT_TAGS.get(ext)
    if entry:
        return entry[0], entry[1]
    return (OPEN_TAG, CLOSE_TAG)

def note_tag_for_file(filepath: str) -> str:
    """Returns the note_prefix in the correct format for the file extension."""
    ext = os.path.splitext(filepath)[1].lower()
    entry = _EXT_TAGS.get(ext)
    if entry:
        return entry[2]
    return NOTE_TAG
#[cf]
#[of]: _make_patterns
def _make_patterns(open_tag: str, close_tag: str):
    # Il label termina prima di eventuali suffissi di chiusura commento (* / o -->)
    open_re = re.compile(
        rf"^\s*{re.escape(open_tag)}\s*(.+?)(?:\s*(?:\*/|-->))?\s*$"
    )
    close_re = re.compile(
        rf"^\s*{re.escape(close_tag)}\s*.*$"
    )
    return open_re, close_re
#[cf]
#[of]: parse
def parse(lines: list[str], open_tag: str = OPEN_TAG, close_tag: str = CLOSE_TAG, note_tag: str = NOTE_TAG) -> Block:
    open_re, close_re = _make_patterns(open_tag, close_tag)
    # Prima riga (o seconda se shebang) deve essere #[of]: root
    first_tag_idx = next((i for i, l in enumerate(lines) if open_re.match(l)), None)
    if first_tag_idx is None or open_re.match(lines[first_tag_idx]).group(1).strip() != "root":
        raise ValueError("file non strutturato: manca #[of]: root come primo tag")
    root = Block(label="root", path="root", start_line=first_tag_idx, end_line=len(lines) - 1)
    stack: list[Block] = [root]
    for i, raw in enumerate(lines):
        if i == first_tag_idx:
            continue  # already processed as root
        if open_re.match(raw):
            label = open_re.match(raw).group(1).strip()
            block = Block(label=label, path=f"{stack[-1].path}/{label}@{i}", start_line=i, end_line=-1)
            stack.append(block)
        elif close_re.match(raw) and len(stack) > 1:
            block = stack.pop()
            block.end_line = i
            stack[-1].items.append(block)
        elif close_re.match(raw) and len(stack) == 1:
            root.end_line = i
        elif raw.startswith(REF_TAG):
            target = raw[len(REF_TAG):].strip().rstrip(chr(10))
            stack[-1].items.append(Note(text=target, kind="ref"))
        elif raw.startswith(note_tag):
            text = raw[len(note_tag):].strip().rstrip(chr(10))
            text = text.rstrip("*/").rstrip("-->").strip()
            stack[-1].items.append(Note(text=text, kind="note"))
        else:
            stack[-1].items.append(Text(text=raw.rstrip(chr(10))))
    return root
#[cf]

#tf:ref .tf/wiki/decisions.md@root/adr_components_manifest
#[cf]
#[of]: navigation
#[of]: _match_part
def _match_part(block: Block, part: str) -> bool:
    if "@" in part:
        label, line_str = part.rsplit("@", 1)
        try:
            return block.label == label and block.start_line == int(line_str)
        except ValueError:
            return False
    return block.label == part  # match per label, prende il primo

#[cf]
#[of]: get_block
def get_block(root: Block, path: str) -> Optional[Block]:
    if not path or path == "root":
        return root
    if path.startswith("root/"):
        path = path[5:]
    current = root.children
    found = None
    for part in path.split('/'):
        found = next((b for b in current if _match_part(b, part)), None)
        if found is None:
            return None
        current = found.children
    return found

#[cf]
#[of]: get_block_wild
def get_block_wild(root: Block, path: str) -> Optional[Block]:
    """Like get_block but '*' as a path segment matches any single child.
    Returns the first match. Example: 'root/tools/*/tf_tree/l1'
    """
    if not path or path == "root":
        return root
    if path.startswith("root/"):
        path = path[5:]
    parts = path.split('/')

    def _search(current_children, remaining):
        if not remaining:
            return None
        part = remaining[0]
        rest = remaining[1:]
        if part == '*':
            for child in current_children:
                if not rest:
                    return child
                result = _search(child.children, rest)
                if result is not None:
                    return result
        else:
            found = next((b for b in current_children if _match_part(b, part)), None)
            if found is None:
                return None
            if not rest:
                return found
            return _search(found.children, rest)
        return None

    return _search(root.children, parts)
#[cf]
#[of]: all_levels
def all_levels(root: Block) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    def walk(block, lvl):
        result.setdefault(str(lvl), []).extend(b.label for b in block.children)
        for b in block.children:
            walk(b, lvl + 1)
    walk(root, 0)
    return result

#[cf]

#[of]: visible_to_physical
def visible_to_physical(block: Block, lines: list[str], vis_row: int) -> tuple[int, str]:
    """Map a visible row (0-based, as returned by tf_getBlockContent numbered=True structured)
    to an absolute 0-based line number in the file, plus the child_indent string to use
    for content inserted at that position.

    In structured mode each child Block appears as a single placeholder row.
    This function expands them to their physical size when computing the offset.

    Returns (abs_line, child_indent).
    """
    # Detect child_indent: first non-tag, non-empty line inside block
    child_indent = ""
    for i in range(block.start_line + 1, block.end_line):
        raw = lines[i]
        stripped = raw.lstrip()
        if stripped and not stripped.startswith("#[of]:") and not stripped.startswith("#[cf]"):
            child_indent = raw[: len(raw) - len(stripped)]
            break

    abs_line = block.start_line + 1  # first content line after #[of]
    vis = 0
    for item in block.items:
        if vis == vis_row:
            return abs_line, child_indent
        if isinstance(item, Block):
            abs_line += item.end_line - item.start_line + 1
        else:
            abs_line += 1  # Text or Note: one physical line
        vis += 1

    # vis_row == n_items: valid append position (after last item, before close tag)
    if vis_row == vis:
        return abs_line, child_indent
    # vis_row truly out of range
    raise ValueError(
        f"visible row {vis_row} out of range (block has {vis} visible rows 0-{vis-1}). "
        f"Use tf_getBlockContent(path, numbered=True, mode='structured') to get valid row numbers."
    )
#[cf]

#[cf]
#[of]: read_helpers
def _semantic_chunk(lines: list[str], offset: int, min_lines: int = 30, max_lines: int = 80) -> tuple[list[str], int]:
    """Returns a semantically complete chunk based on indentation.

    Starts at offset, advances to min_lines then closes when indentation
    returns to baseline (line offset). Always closes at max_lines.
    Blank lines and comments do not contribute to indent_ref.

    Returns (chunk_lines, next_offset).
    """
    total = len(lines)
    if offset >= total:
        return [], offset

    # determina indent_ref dalla prima riga non-vuota/commento a partire da offset
    indent_ref = 0
    for i in range(offset, min(offset + max_lines, total)):
        stripped = lines[i].lstrip()
        if stripped and not stripped.startswith('#'):
            indent_ref = len(lines[i]) - len(stripped)
            break

    chunk = []
    entered_body = False  # True dopo aver visto almeno una riga indentata > indent_ref
    for i in range(offset, total):
        stripped = lines[i].lstrip()
        is_blank = not stripped
        is_comment = stripped.startswith('#')

        if not is_blank and not is_comment:
            current_indent = len(lines[i]) - len(stripped)
            if current_indent > indent_ref:
                entered_body = True
            elif entered_body and current_indent <= indent_ref and len(chunk) >= min_lines:
                # torna al livello base dopo aver visto il body: chiudi prima di questa riga
                return chunk, offset + len(chunk)

        chunk.append(lines[i])
        n = len(chunk)

        if n >= max_lines:
            return chunk, offset + n

    return chunk, offset + len(chunk)
#[cf]
#[of]: write_helpers
#[of]: _tag_line
def _tag_line(tag: str, label: str = "") -> str:
    # Alcuni tag di apertura sono commenti che richiedono un suffisso di chiusura:
    #   "<!-- [of]:"  →  " -->"
    #   "/* [of]:"    →  " */"
    # The close tag (no label) already contains the suffix — do not append it.
    if label:
        suffix = ""
        if tag.startswith("<!--"):
            suffix = " -->"
        elif tag.startswith("/*"):
            suffix = " */"
        return f"{tag} {label}{suffix}\n"
    return f"{tag}\n"
#[cf]
#[of]: cmd_set_block
def cmd_set_block(lines, label, start, end, open_tag, close_tag, open_re, close_re):
    if start >= end:
        return None, "START must be less than END"
    if start < 0 or end >= len(lines):
        return None, f"Line numbers out of range (0-{len(lines)-1})"
    return (lines[:start]
            + [_tag_line(open_tag, label)]
            + lines[start:end + 1]
            + [_tag_line(close_tag)]
            + lines[end + 1:]), None
#[cf]
#[of]: cmd_add_block
def cmd_add_block(lines, label, line_pos, content_text, open_tag, close_tag, after_block: Block = None):
    if after_block is not None:
        line_pos = after_block.end_line + 1
    if line_pos < 0:
        line_pos = len(lines)  # append in fondo
    if line_pos > len(lines):
        return None, f"LINE out of range (0-{len(lines)})"
    # line=0 inserirebbe prima del root open tag — sposta a riga 1
    if line_pos == 0 and lines and lines[0].lstrip().startswith(open_tag.strip()):
        line_pos = 1
    content_lines = content_text.splitlines(keepends=True)
    if content_lines and not content_lines[-1].endswith('\n'):
        content_lines[-1] += '\n'
    return (lines[:line_pos]
            + [_tag_line(open_tag, label)]
            + content_lines
            + [_tag_line(close_tag)]
            + lines[line_pos:]), None
#[cf]
#[of]: _block_to_lines
def _block_to_lines(block: Block, open_tag: str = OPEN_TAG, close_tag: str = CLOSE_TAG) -> list[str]:
    out = []
    for item in block.items:
        match item:
            case Note(text=t):
                out.append(t + '\n')
            case Text(text=t):
                out.append(t + '\n')
            case Block() as b:
                out.append(_tag_line(open_tag, b.label))
                out.extend(_block_to_lines(b, open_tag, close_tag))
                out.append(_tag_line(close_tag))
    return out

#[cf]
#[of]: cmd_edit_text
def cmd_edit_text(lines: list[str], block: Block, new_text: str,
                  open_tag: str, close_tag: str,
                  new_blocks: dict | None = None,
                  strict_children: bool = False) -> list[str]:
    children  = {b.label: b for b in block.items if isinstance(b, Block)}
    new_blocks = new_blocks or {}

    referenced = set(re.findall(r"^\s*\[([^\]]+)\]\s*$", new_text, re.MULTILINE))
    referenced_labels = {r.split("@")[0] for r in referenced}

    if strict_children:
        # AI mode: every existing child must appear as a whole-line placeholder [label].
        # Omitting one is an error — remove it explicitly first with tf_removeBlock.
        missing = [label for label in children
                   if label not in referenced_labels and label not in new_blocks]
        if missing:
            raise ValueError(
                f"child block(s) missing from new text: {missing} — "
                f"include each as a whole-line placeholder e.g. [{missing[0]}], "
                f"or remove it first with tf_removeBlock"
            )
    else:
        # Miller/legacy mode: silently drop children not referenced in new text.
        for label in list(children):
            if label not in referenced_labels and label not in new_blocks:
                del children[label]

#[of]: _detect_pad
    # Ricava indentazione per i nuovi sotto-blocchi:
    # 1. Se il blocco ha figli esistenti, usa l indentazione del loro TF-TAGS
    # 2. Altrimenti usa l indentazione della prima riga di contenuto non-TF-TAGS
    pad = ""
    if block.start_line >= 0:
        for child in block.children:
            raw = lines[child.start_line] if child.start_line < len(lines) else ""
            stripped = raw.lstrip()
            if stripped:
                pad = raw[: len(raw) - len(stripped)]
                break
        if not pad:
            for i in range(block.start_line + 1, block.end_line):
                raw = lines[i] if i < len(lines) else ""
                stripped = raw.lstrip()
                if stripped and not stripped.startswith("#[of]:") and not stripped.startswith("#[cf]"):
                    pad = raw[: len(raw) - len(stripped)]
                    break
#[cf]
#[of]: _expand_lines
    open_re, close_re = _make_patterns(open_tag, close_tag)
    def _expand_lines(text: str, child_pad: str) -> list[str]:
        out: list[str] = []
        for raw_line in text.splitlines():
            m = re.match(r"^\s*\[([^\]]+)\]\s*$", raw_line)
            if m:
                ref       = m.group(1).strip()
                ref_label = ref.split("@")[0]
                child = children.get(ref_label) or next(
                    (b for b in children.values() if f"{b.label}@{b.start_line}" == ref), None)
                if child is not None:
                    out.append(_tag_line(open_tag, child.label))
                    out.extend(_block_to_lines(child, open_tag, close_tag))
                    out.append(_tag_line(close_tag))
                elif ref_label in new_blocks:
                    out.append(_tag_line(open_tag, ref_label))
                    out.extend(_expand_lines(new_blocks[ref_label], child_pad))
                    out.append(_tag_line(close_tag))
                else:
                    out.append(raw_line + chr(10))
            else:
                if open_re.match(raw_line) or close_re.match(raw_line):
                    raise ValueError(f"cmd_edit_text: text must not contain TF tags: {raw_line!r}")
                out.append(raw_line + chr(10))
        return out
#[cf]
#[of]: _assemble
    inner: list[str] = _expand_lines(new_text, pad)
    return (lines[:block.start_line]
            + [_tag_line(open_tag, block.label)]
            + inner
            + [_tag_line(close_tag)]
            + lines[block.end_line + 1:])
#[cf]
#[cf]
#[of]: cmd_wrap_text
def cmd_wrap_text(lines: list[str], parent: Block, new_label: str,
                  text: str, open_tag: str, close_tag: str) -> tuple[list[str], str | None]:
    text_stripped = text.strip('\n')
    new_block_lines = (
        [_tag_line(open_tag, new_label)]
        + [l + '\n' for l in text_stripped.splitlines()]
        + [_tag_line(close_tag)]
    )
    body_start = 0 if parent.start_line == -1 else parent.start_line + 1
    body_end   = len(lines) if parent.start_line == -1 else parent.end_line
    body = lines[body_start:body_end]
    search_lines = [l.strip() for l in text_stripped.splitlines() if l.strip()]
    n = len(search_lines)
    if n == 0:
        return None, "empty selection"
    found = next((i for i in range(len(body) - n + 1)
                  if [l.strip() for l in body[i:i+n]] == search_lines), -1)
    if found == -1:
        return None, f"text not found in block '{parent.label}'"
    new_body = body[:found] + new_block_lines + body[found + n:]
    return lines[:body_start] + new_body + lines[body_end:], None

#[cf]
#[of]: cmd_remove_block
def cmd_remove_block(lines, block: Block, keep_content: bool = False) -> list[str]:
    if keep_content:
        return lines[:block.start_line] + _block_to_lines(block) + lines[block.end_line + 1:]
    return lines[:block.start_line] + lines[block.end_line + 1:]

#[cf]
#[of]: cmd_flatten_block
def cmd_flatten_block(lines, block: Block) -> list[str]:
    return lines[:block.start_line] + _block_to_lines(block) + lines[block.end_line + 1:]

#[cf]
#[of]: cmd_rename_block
def cmd_rename_block(lines, block: Block, new_label: str, open_tag: str, close_tag: str) -> list[str]:
    new_lines = list(lines)
    new_lines[block.start_line] = _tag_line(open_tag, new_label)
    new_lines[block.end_line]   = _tag_line(close_tag)
    return new_lines

#[cf]
#[of]: cmd_duplicate_block
def cmd_duplicate_block(lines, block: Block, open_tag: str, close_tag: str, new_label: str = None) -> list[str]:
    label = new_label or (block.label + "_copy")
    block_lines = (
        [_tag_line(open_tag, label)]
        + _block_to_lines(block)
        + [_tag_line(close_tag)]
    )
    return lines[:block.end_line + 1] + block_lines + lines[block.end_line + 1:]

#[cf]
#[of]: cmd_move_block
def cmd_move_block(lines, block: Block, dest_line: int, open_tag: str, close_tag: str):
    if dest_line < 0 or dest_line > len(lines):
        return None, f"dest_line out of range (0-{len(lines)})"
    if block.start_line <= dest_line <= block.end_line:
        return None, "dest_line inside the block itself"
    block_lines = (
        [_tag_line(open_tag, block.label)]
        + _block_to_lines(block)
        + [_tag_line(close_tag)]
    )
    removed = lines[:block.start_line] + lines[block.end_line + 1:]
    if dest_line > block.end_line:
        dest_line -= (block.end_line - block.start_line + 1)
    return removed[:dest_line] + block_lines + removed[dest_line:], None

#[cf]
#[of]: cmd_move_block_to_parent
def cmd_move_block_to_parent(lines, block: Block, new_parent: Block, open_tag: str, close_tag: str, after_block: Block = None):
    if new_parent.start_line >= block.start_line and new_parent.end_line <= block.end_line:
        return None, "cannot move a block inside itself"
    if any(c.start_line == block.start_line for c in new_parent.children):
        return None, "block is already a direct child of new_parent"
    block_lines = (
        [_tag_line(open_tag, block.label)]
        + _block_to_lines(block)
        + [_tag_line(close_tag)]
    )
    removed = lines[:block.start_line] + lines[block.end_line + 1:]
    block_size = block.end_line - block.start_line + 1
    if after_block is not None:
        dest = after_block.end_line + 1
    elif new_parent.start_line == -1:
        dest = len(lines)          # root: append at end of file
    else:
        dest = new_parent.end_line # non-root: before close tag
    if dest > block.end_line:
        dest -= block_size
    return removed[:dest] + block_lines + removed[dest:], None

#[cf]
#[of]: cmd_summary
def cmd_summary(block: 'Block', threshold: int = 10) -> list[dict]:
    """Per ogni blocco nell'albero: righe testo diretto, n. figli, flag dense/mixed."""
    result = []
    def walk(b):
        text_lines = sum(1 for i in b.items if isinstance(i, Text) and i.text.strip())
        children   = [i for i in b.items if isinstance(i, Block)]
        result.append({
            "path":       b.path,
            "label":      b.label,
            "text_lines": text_lines,
            "children":   len(children),
            "dense":      text_lines > threshold and len(children) == 0,
            "mixed":      text_lines > 0 and len(children) > 0,
        })
        for c in children:
            walk(c)
    walk(block)
    return result

#[cf]
#[of]: cmd_search
def cmd_search(block: 'Block', pattern: str, ignore_case: bool = False) -> list[dict]:
    """Search regex pattern in all block texts. Returns path + matching lines."""
    flags = re.IGNORECASE if ignore_case else 0
    try:
        rx = re.compile(pattern, flags)
    except re.error as e:
        return [{"error": f"invalid pattern: {e}"}]
    results = []
    def walk(b):
        matches = []
        for item in b.items:
            if isinstance(item, Text) and rx.search(item.text):
                matches.append(item.text)
        if matches:
            full_text = "\n".join(item.text for item in b.items if isinstance(item, Text))
            results.append({"path": b.path, "label": b.label, "matches": matches,
                            "block_text": full_text})
        for child in b.children:
            walk(child)
    walk(block)
    return results

#[cf]
#[of]: cmd_strip
def cmd_strip(lines: list[str], open_tag: str, close_tag: str, block: Block = None) -> list[str]:
    """Remove TF tags and annotations. If block is given, operates only on that block."""
    open_re, close_re = _make_patterns(open_tag, close_tag)
    if block is None:
        return [l for l in lines
                if not open_re.match(l) and not close_re.match(l) and not l.startswith(NOTE_TAG)]
    # estrai solo le righe del blocco (esclusi i tag di apertura/chiusura del blocco stesso)
    block_lines = lines[block.start_line + 1 : block.end_line]
    return [l for l in block_lines
            if not open_re.match(l) and not close_re.match(l) and not l.startswith(NOTE_TAG)]
#[cf]
#[of]: cmd_onboard_fix_tags
def cmd_onboard_fix_tags(lines: list[str], open_tag: str, close_tag: str) -> tuple[list[str], list[dict]]:
    """Step 0: move close_tags not at column 0 to a separate line after the current one.
    Code Browser compatibility: only close_tag can be inline, never open_tag.
    Returns (new_lines, fixes) where fixes is the list of modified lines.
    """
    new_lines = []
    fixes = []
    # close_tag stripped (es. '#[cf]' o '// [cf]')
    ct = close_tag.strip()

    for i, line in enumerate(lines):
        stripped = line.rstrip('\n\r')
        # close_tag at column 0? → leave unchanged
        if stripped.strip() == ct and (stripped == ct or stripped.startswith(ct)):
            new_lines.append(line)
            continue
        # contains close_tag but NOT at column 0 (inline or indented)?
        if ct in stripped and not stripped.lstrip() == ct:
            # remove the tag from the original line
            eol = line[len(stripped):]  # '\n' o '\r\n' o ''
            fixed_line = stripped.replace(ct, '').rstrip() + eol
            new_lines.append(fixed_line)
            # insert close_tag on a separate line at column 0
            new_lines.append(ct + '\n')
            fixes.append({'original_line': i + 1, 'content': stripped})
        else:
            new_lines.append(line)

    return new_lines, fixes
#[cf]
#[of]: cmd_onboard_remove_orphan_tags
def cmd_onboard_remove_orphan_tags(lines: list[str], open_tag: str, close_tag: str) -> tuple[list[str], list[dict]]:
    """Step 0.2: remove unclosed #[of] tags (orphans from old Code Browser style).
    After step 0 (inline #[cf] fixed), any remaining unbalanced #[of] has no matching #[cf]
    and must be removed — it would corrupt TF parsing.
    Returns (new_lines, removed) where removed lists the orphaned open tags dropped.
    """
    ot = open_tag.strip()
    ct = close_tag.strip()
    open_re, close_re = _make_patterns(open_tag, close_tag)

    # first pass: find which open tags are unmatched
    stack = []   # (line_index, label)
    matched_opens = set()
    for i, line in enumerate(lines):
        s = line.strip()
        if open_re.match(line):
            stack.append(i)
        elif close_re.match(line) and stack:
            matched_opens.add(stack.pop())

    # anything left in stack is unmatched
    orphans = set(stack)

    if not orphans:
        return lines, []

    removed = [{'line': i + 1, 'content': lines[i].rstrip()} for i in sorted(orphans)]
    new_lines = [l for i, l in enumerate(lines) if i not in orphans]
    return new_lines, removed
#[cf]
#[of]: cmd_onboard_add_root
def cmd_onboard_add_root(lines: list[str], open_tag: str, close_tag: str) -> tuple[list[str], bool]:
    """Step 0.1: adds root wrapper (open_tag root / close_tag) if missing.
    Respects shebang on line 1. Returns (new_lines, added).
    """
    ot = open_tag.strip()
    ct = close_tag.strip()

    # check if root is already present (line 1 or 2)
    check_lines = [l.strip() for l in lines[:2]]
    for cl in check_lines:
        if cl.startswith(ot) and 'root' in cl:
            return lines, False  # already structured

    new_lines = list(lines)

    # aggiungi #[cf] finale se mancante
    last_content = ''.join(new_lines).rstrip()
    if not last_content.endswith(ct):
        new_lines.append(ct + '\n')

    # aggiungi #[of]: root in testa (dopo shebang se presente)
    root_line = _tag_line(open_tag, 'root')
    if new_lines and new_lines[0].startswith('#!'):
        new_lines.insert(1, root_line)
    else:
        new_lines.insert(0, root_line)

    return new_lines, True
#[cf]
#[of]: cmd_onboard_scan
def cmd_onboard_scan(lines: list[str], open_tag: str, close_tag: str) -> list[dict]:
    """Step 1: individua componenti strutturali del codice (meccanico, no AI).
    For Python files: uses ast for precise class/function/import detection, recursive.
    Fallback (non-Python or parse error): indentation + keyword + pattern matching.
    Returns a list of candidates [{label, start, end, kind, depth}] with 0-based lines.
    Leaves already-structured TF blocks untouched — skips them.
    """
    import re
    import ast as _ast

    ot = open_tag.strip()
    ct = close_tag.strip()

    # existing TF wraps — used by both backends to skip already-wrapped ranges
    existing_ranges = []
    stack = []
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith(ot):
            stack.append(i)
        elif s == ct and stack:
            start = stack.pop()
            if len(stack) >= 1:
                existing_ranges.append((start, i))

    def is_covered(start, end):
        for (ws, we) in existing_ranges:
            if abs(ws - start) <= 2 and abs(we - end) <= 2:
                return True
        return False

    # ------------------------------------------------------------------ ast backend
    def _scan_ast(src: str) -> list[dict]:
        try:
            tree = _ast.parse(src)
        except SyntaxError:
            return None

        candidates = []

        def visit(node, depth):
            # import / import-from at any level
            if isinstance(node, (_ast.Import, _ast.ImportFrom)):
                s = node.lineno - 1
                e = node.end_lineno - 1
                if not is_covered(s, e):
                    candidates.append({'label': 'imports', 'start': s, 'end': e,
                                       'kind': 'imports', 'depth': depth})
                return

            if isinstance(node, _ast.ClassDef):
                s = node.lineno - 1
                e = node.end_lineno - 1
                kind = 'method' if depth >= 2 else 'class'
                if not is_covered(s, e):
                    candidates.append({'label': node.name, 'start': s, 'end': e,
                                       'kind': kind, 'depth': depth})
                # class_attrs: contiguous non-method children before first def
                _emit_class_attrs(node, depth + 1)
                for child in _ast.iter_child_nodes(node):
                    visit(child, depth + 1)
                return

            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                s = node.lineno - 1
                e = node.end_lineno - 1
                kind = 'method' if depth >= 2 else 'function'
                if not is_covered(s, e):
                    candidates.append({'label': node.name, 'start': s, 'end': e,
                                       'kind': kind, 'depth': depth})
                # recurse into nested classes/functions
                for child in _ast.iter_child_nodes(node):
                    visit(child, depth + 1)
                return

        def _emit_class_attrs(cls_node, depth):
            # group contiguous Assign/AnnAssign/Expr(docstring excluded) before first def
            # into a single 'class_attrs' candidate
            children = list(_ast.iter_child_nodes(cls_node))
            # skip leading docstring (Expr with Constant)
            start_idx = 0
            if (children and isinstance(children[0], _ast.Expr)
                    and isinstance(getattr(children[0], 'value', None), _ast.Constant)):
                start_idx = 1
            # collect contiguous non-def/non-class nodes
            attr_nodes = []
            for child in children[start_idx:]:
                if isinstance(child, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
                    break
                if isinstance(child, (_ast.Assign, _ast.AnnAssign, _ast.Delete,
                                       _ast.AugAssign, _ast.Expr)):
                    attr_nodes.append(child)
            if not attr_nodes:
                return
            s = attr_nodes[0].lineno - 1
            e = attr_nodes[-1].end_lineno - 1
            if e > s and not is_covered(s, e):
                candidates.append({'label': 'class_attrs', 'start': s, 'end': e,
                                   'kind': 'class_attrs', 'depth': depth})

        for node in _ast.iter_child_nodes(tree):
            visit(node, 1)

        return candidates

    # ------------------------------------------------------------------ tf_custom fallback
    def _scan_tf_custom() -> list[dict]:
        n = len(lines)
        existing_blocks = set()
        for i, line in enumerate(lines):
            s = line.strip()
            if s.startswith(ot) or s == ct:
                existing_blocks.add(i)

        def get_indent(line):
            return len(line) - len(line.lstrip())

        def find_block_end(start_idx, base_indent):
            end = start_idx
            for j in range(start_idx + 1, n):
                s = lines[j]
                stripped = s.strip()
                if not stripped:
                    continue
                if stripped.startswith(ot) or stripped == ct:
                    end = j - 1
                    while end > start_idx and not lines[end].strip():
                        end -= 1
                    return end
                if stripped.startswith('#'):
                    continue
                if get_indent(s) <= base_indent:
                    end = j - 1
                    while end > start_idx and not lines[end].strip():
                        end -= 1
                    return end
            end = n - 1
            while end > start_idx and not lines[end].strip():
                end -= 1
            return end

        def find_method_indent(class_start, class_end):
            for j in range(class_start + 1, class_end + 1):
                s = lines[j]
                stripped = s.strip()
                if re.match(r'def\s+\w+', stripped):
                    return get_indent(s)
            return None

        def scan_methods(class_start, class_end):
            method_indent = find_method_indent(class_start, class_end)
            if method_indent is None:
                return []
            methods = []
            j = class_start + 1
            while j <= class_end:
                line = lines[j]
                stripped = line.strip()
                if stripped.startswith(ot) or stripped == ct:
                    j += 1
                    continue
                m = re.match(r'def\s+(\w+)', stripped)
                if m and get_indent(line) == method_indent and j not in existing_blocks:
                    label = m.group(1)
                    end = find_block_end(j, method_indent)
                    if end > class_end:
                        end = class_end
                    if not is_covered(j, end):
                        methods.append({'label': label, 'start': j, 'end': end,
                                        'kind': 'method', 'depth': 2})
                    j = end + 1
                    continue
                j += 1
            return methods

        candidates = []
        i = 0
        while i < n:
            line = lines[i]
            stripped = line.strip()
            if stripped.startswith(ot) or stripped == ct:
                i += 1
                continue
            if (stripped.startswith('import ') or stripped.startswith('from ')) and i not in existing_blocks:
                start = i
                end = i
                j = i + 1
                while j < n:
                    s = lines[j].strip()
                    if s.startswith('import ') or s.startswith('from ') or s == '' or s.startswith('#'):
                        if s.startswith('import ') or s.startswith('from '):
                            end = j
                        j += 1
                    else:
                        break
                if not is_covered(start, end):
                    candidates.append({'label': 'imports', 'start': start, 'end': end,
                                       'kind': 'imports', 'depth': 1})
                i = end + 1
                continue
            m = re.match(r'^class\s+(\w+)', line)
            if m and i not in existing_blocks:
                label = m.group(1)
                end = find_block_end(i, 0)
                if not is_covered(i, end):
                    candidates.append({'label': label, 'start': i, 'end': end,
                                       'kind': 'class', 'depth': 1})
                methods = scan_methods(i, end)
                candidates.extend(methods)
                i = end + 1
                continue
            m = re.match(r'^def\s+(\w+)', line)
            if m and i not in existing_blocks:
                label = m.group(1)
                end = find_block_end(i, 0)
                if not is_covered(i, end):
                    candidates.append({'label': label, 'start': i, 'end': end,
                                       'kind': 'function', 'depth': 1})
                i = end + 1
                continue
            i += 1
        return candidates

    # ------------------------------------------------------------------ dispatch
    src = ''.join(lines)
    result = _scan_ast(src)
    if result is None:
        result = _scan_tf_custom()
    return result
#[cf]
#[of]: cmd_append
def cmd_append(lines: list[str], block: Block, text: str, open_tag: str, close_tag: str) -> list[str]:
    """Aggiunge testo puro in fondo al contenuto diretto di un blocco (prima del close tag).
    Non accetta TF-TAGS nel testo — per aggiungere blocchi usa editText + newBlocks.
    """
    open_re, close_re = _make_patterns(open_tag, close_tag)
    for line in text.splitlines():
        if open_re.match(line) or close_re.match(line):
            raise ValueError(f"cmd_append: testo non deve contenere tag: {line!r}")
    insert_line = block.end_line  # riga del close tag
    new_lines = [l + ("" if l.endswith(chr(10)) else chr(10)) for l in text.splitlines()]
    return lines[:insert_line] + new_lines + lines[insert_line:]

#[cf]
#[of]: cmd_session
#[of]: cmd_read_session
def cmd_read_session(root: 'Block', keys: list[str] | None = None) -> dict | None:
    """Read the structured session block.
    Looks for root/roadmap/session or root/session.
    If session has sub-blocks (status, next, decisions, blocks):
      - keys=None → returns status + next (default, lightweight)
      - keys=['decisions','blocks'] → returns only those
      - keys=['*'] → returns everything
    If session is flat (free text, legacy): returns {'status': full_text}.
    """
    session = None
    for path in ("root/roadmap/session", "root/session"):
        session = get_block(root, path)
        if session is not None:
            break
    if session is None:
        return None

    sub_labels = [c.label for c in session.children]
    if not sub_labels:
        return {"status": session.render(expanded=True)}

    if keys is None:
        keys = ["status", "next"]
    elif keys == ["*"]:
        keys = sub_labels

    result = {}
    for k in keys:
        b = _find_child(session, k)
        if b is not None:
            text = b.render(expanded=True)
            lines_b = text.splitlines(keepends=True)
            if lines_b and lines_b[0].strip() in (f"[{b.label}]", f"[{b.label}]:"):
                text = "".join(lines_b[1:])
            result[k] = text.strip()
    return result if result else None


def _find_child(block: 'Block', label: str) -> 'Block | None':
    """Find a direct child by label (case-insensitive)."""
    for c in block.children:
        if c.label.lower() == label.lower():
            return c
    return None
#[cf]
#[of]: _session_helpers
def _tf_dir(filepath: str) -> str:
    """Returns the .tf directory relative to the file or cwd."""
    if not filepath:
        base = os.getcwd()
    else:
        abs_fp = os.path.abspath(filepath)
        base = abs_fp if os.path.isdir(abs_fp) else os.path.dirname(abs_fp)
    return os.path.join(base, ".tf")

def _sess_dir(filepath: str) -> str:
    return os.path.join(_tf_dir(filepath), "sessions")

def _sess_file(filepath: str, agent_id: str) -> str:
    return os.path.join(_sess_dir(filepath), agent_id, "state.json")
#[cf]
#[of]: cmd_set_session
def cmd_set_session(filepath: str, agent_id: str, data: dict = None) -> dict:
    """Scrive/aggiorna .tf/sessions/<agent_id>/state.json.
    Se data contiene 'user' e 'path': aggiorna/aggiunge il focus corrispondente in focuses[].
    Altrimenti aggiorna campi flat (backward compat per campi non-focus).
    """
    import json, time
    sf = _sess_file(filepath, agent_id)
    os.makedirs(os.path.dirname(sf), exist_ok=True)
    state = {}
    if os.path.exists(sf):
        with open(sf) as f:
            state = json.load(f)
    if "started" not in state:
        state["started"] = int(time.time())
    state["last_active"] = int(time.time())
    state["agent_id"] = agent_id
    if data:
        if "user" in data and "path" in data:
            # nuovo modello: aggiorna/inserisce in focuses[]
            focuses = state.get("focuses", [])
            entry = {"user": data["user"], "path": data["path"]}
            if "uuid" in data:
                entry["uuid"] = data["uuid"]
            # sostituisce entry con stesso user (o uuid se presente)
            key = data.get("uuid") or data["user"]
            focuses = [f for f in focuses
                       if not (f.get("uuid") == key or
                               (not data.get("uuid") and f.get("user") == key))]
            focuses.append(entry)
            state["focuses"] = focuses
        else:
            state.update(data)
    with open(sf, "w") as f:
        json.dump(state, f, indent=2)
    return {"agent_id": agent_id, "state": state}
#[cf]
#[of]: cmd_get_session
def cmd_get_session(filepath: str, agent_id: str) -> dict:
    """Read .tf/sessions/<agent_id>/state.json."""
    import json
    sf = _sess_file(filepath, agent_id)
    if not os.path.exists(sf):
        return {"agent_id": agent_id, "state": None}
    with open(sf) as f:
        state = json.load(f)
    return {"agent_id": agent_id, "state": state}
#[cf]
#[of]: cmd_list_sessions
def cmd_list_sessions(filepath: str, stale_secs: int = 300) -> dict:
    """Elenca tutte le sessioni attive in .tf/sessions/."""
    import json, time, glob as _glob
    sd = _sess_dir(filepath)
    if not os.path.exists(sd):
        return {"sessions": []}
    now = int(time.time())
    sessions = []
    for sf in _glob.glob(os.path.join(sd, "*", "state.json")):
        try:
            with open(sf) as f:
                s = json.load(f)
            if now - s.get("last_active", 0) <= stale_secs:
                sessions.append(s)
        except Exception:
            pass
    return {"sessions": sessions}
#[cf]
#[of]: cmd_clean_session
def cmd_clean_session(filepath: str, agent_id: str) -> dict:
    """Remove .tf/sessions/<agent_id>/state.json."""
    import shutil
    sd = os.path.join(_tf_dir(filepath), "sessions", agent_id)
    if os.path.exists(sd):
        shutil.rmtree(sd)
    return {"cleaned": agent_id}
#[cf]
#[cf]
#[of]: cmd_scan
def cmd_scan(directory: str, extensions: list[str] | None = None) -> list[dict]:
    """Scan a directory and return all relevant files.
    Structured files (with open tags): include tree and refs.
    Unstructured files: listed with lines and structured=False.
    Returns files and deps (inverted graph: target -> callers).
    """
    import pathlib
    base = pathlib.Path(directory).resolve()

    SKIP_EXTS = DEFAULT_SKIP_EXTS
    TEXT_EXTS = DEFAULT_TEXT_EXTS
    _is_ignored = _build_ignore_matcher(base)

    def _tree_summary(block):
        r = {
            "label":    block.label,
            "path":     block.path,
            "children": [_tree_summary(c) for c in block.children],
        }
        if block.refs:
            r["refs"] = block.refs
        return r

#[of]: _scan_files
    import pathlib

    open_tag_bytes = OPEN_TAG.encode()
    file_results = []

    if extensions:
        all_files = []
        for ext in extensions:
            for fpath in base.rglob(f"*.{ext.lstrip(chr(46))}"):
                if not _is_ignored(fpath):
                    all_files.append(fpath)
        all_files = sorted(all_files)
    else:
        all_files = []
        for root_dir, dirs, files in os.walk(base):
            root_path = pathlib.Path(root_dir)
            dirs[:] = [d for d in dirs if not _is_ignored(root_path / d)]
            for fname in files:
                fpath = root_path / fname
                if fpath.suffix.lower() not in SKIP_EXTS and fpath.suffix.lower() in TEXT_EXTS:
                    if not _is_ignored(fpath):
                        all_files.append(fpath)
        all_files = sorted(all_files)

    for fpath in all_files:
        try:
            content = fpath.read_bytes()
        except (OSError, PermissionError):
            continue
        file_rel = str(fpath.relative_to(base))
        if open_tag_bytes in content:
            try:
                lines = content.decode("utf-8", errors="replace").splitlines(keepends=True)
            except Exception:
                continue
            try:
                root = parse(lines)
                file_results.append({
                    "file":       file_rel,
                    "lines":      len(lines),
                    "structured": True,
                    "tree":       _tree_summary(root),
                })
            except ValueError as e:
                file_results.append({
                    "file":       file_rel,
                    "lines":      len(lines),
                    "structured": False,
                    "malformed":  True,
                    "error":      str(e),
                })
        else:
            try:
                line_count = len(content.decode("utf-8", errors="replace").splitlines())
            except Exception:
                continue
            file_results.append({
                "file":       file_rel,
                "lines":      line_count,
                "structured": False,
            })
#[cf]
#[of]: _collect_deps
    deps: dict = {}
    def collect_refs(node, file_rel):
        for ref in node.get("refs", []):
            deps.setdefault(ref, []).append({"file": file_rel, "path": node["path"]})
        for child in node.get("children", []):
            collect_refs(child, file_rel)
    for fr in file_results:
        if fr.get("structured"):
            collect_refs(fr["tree"], fr["file"])

    return {"files": file_results, "deps": deps}
#[cf]
#[cf]
#[of]: cmd_insert
def cmd_insert(lines: list[str], block: Block, row: int, text: str, open_tag: str = OPEN_TAG, close_tag: str = CLOSE_TAG) -> list[str]:
    """Insert text at visible row (0-indexed, relative to block content as shown by numbered=True).
    row=0 inserts before the first visible item.
    row=-1 appends before the closing TF tag.
    Uses visible_to_physical to map visible row to physical file line.
    """
    n_items = len(block.items)

    if row < 0:
        # append: insert before closing tag, after last item
        insert_at, _ = visible_to_physical(block, lines, n_items)
    else:
        insert_at, _ = visible_to_physical(block, lines, min(row, n_items))

    open_re, close_re = _make_patterns(open_tag, close_tag)
    for line in text.splitlines():
        if open_re.match(line) or close_re.match(line):
            raise ValueError(f"cmd_insert: text must not contain TF tags: {line!r}")
    new_lines = [l + ("" if l.endswith(chr(10)) else chr(10)) for l in text.splitlines()]
    return lines[:insert_at] + new_lines + lines[insert_at:]
#[cf]
#[of]: cmd_insert_note
def cmd_insert_note(lines: list[str], block: Block, text: str,
                    open_tag: str = OPEN_TAG, close_tag: str = CLOSE_TAG,
                    note_prefix: str = NOTE_TAG) -> list[str]:
    """Insert a TF note in the correct format for the file (at the end of the block).

    - .py / default : # tf:note testo
    - .js/.ts       : // tf:note testo
    - .css/.scss    : /* tf:note testo */
    - .md           : <!-- tf:note testo -->
    """
    suffix = ""
    if note_prefix.startswith("<!--"):
        suffix = " -->"
    elif note_prefix.startswith("/*"):
        suffix = " */"
    note_line = f"{note_prefix} {text}{suffix}"
    return cmd_insert(lines, block, -1, note_line, open_tag, close_tag)
#[cf]
#[of]: cmd_insert_ref
def cmd_insert_ref(lines: list[str], block: Block, target: str,
                   open_tag: str = OPEN_TAG, close_tag: str = CLOSE_TAG) -> list[str]:
    """Insert a #tf:ref in the block (at the end).

    The prefix is always '#tf:ref' regardless of the file extension —
    the parser only recognises this form (REF_TAG).
    target: path del blocco destinazione (es. '.tf/wiki/decisions.md@root/adr_foo')
    """
    ref_line = f"{REF_TAG} {target}"
    return cmd_insert(lines, block, -1, ref_line, open_tag, close_tag)
#[cf]
#[of]: cmd_replace_in_block
def cmd_replace_in_block(lines: list[str], block: Block, old_text: str, new_text: str,
                          label: str = None,
                          open_tag: str = OPEN_TAG, close_tag: str = CLOSE_TAG
                          ) -> tuple[list[str], dict]:
    """Replace old_text with new_text inside block. Optionally wrap the replaced range in a new sub-block.

    old_text: exact string to find (multiline ok, must match exactly including whitespace)
    new_text: replacement text
    label:    if given, wrap the replaced range in a new sub-block with this label

    Raises ValueError if old_text not found or found more than once in block content.
    Returns (new_lines, info) where info = {'replaced': True, 'wrapped': label or None}.
    """
    ot = open_tag.strip()
    ct = close_tag.strip()

    # Extract full block text (expanded — no placeholders)
    content_start = block.start_line + 1
    content_end   = block.end_line
    block_lines   = lines[content_start:content_end]
    block_text    = "".join(block_lines)

    # Find old_text
    idx = block_text.find(old_text)
    if idx == -1:
        raise ValueError(f"cmd_replace_in_block: old_text not found in block '{block.label}'")
    if block_text.find(old_text, idx + 1) != -1:
        raise ValueError(f"cmd_replace_in_block: old_text found more than once in block '{block.label}' — be more specific")

    # Validate new_text has no TF tags
    open_re, close_re = _make_patterns(open_tag, close_tag)
    for line in new_text.splitlines():
        if open_re.match(line.strip()) or close_re.match(line.strip()):
            raise ValueError(f"cmd_replace_in_block: new_text must not contain TF tags: {line!r}")

    # Build new block text
    new_block_text = block_text[:idx] + new_text + block_text[idx + len(old_text):]

    # Rebuild lines for the block content
    new_block_lines = [l + ("" if l.endswith("\n") else "\n") for l in new_block_text.splitlines()]
    new_lines = lines[:content_start] + new_block_lines + lines[content_end:]

    if label is None:
        return new_lines, {"replaced": True, "wrapped": None}

    # Wrap the replaced range in a new sub-block
    # Find the start/end line of new_text in the rebuilt file
    rebuilt_block_text = "".join(new_lines[content_start:content_start + len(new_block_lines)])
    new_idx = rebuilt_block_text.find(new_text)
    if new_idx == -1:
        return new_lines, {"replaced": True, "wrapped": None}

    # Convert char offset to line numbers (absolute in file)
    pre_lines = rebuilt_block_text[:new_idx].splitlines(keepends=True)
    wrap_start = content_start + len(pre_lines)
    new_text_lines = new_text.splitlines(keepends=True)
    wrap_end = wrap_start + len(new_text_lines) - 1

    if wrap_start > wrap_end:
        return new_lines, {"replaced": True, "wrapped": None}

    # Inline wrap: insert open/close tags around the range
    wrapped = (new_lines[:wrap_start]
               + [_tag_line(open_tag, label)]
               + new_lines[wrap_start:wrap_end + 1]
               + [_tag_line(close_tag)]
               + new_lines[wrap_end + 1:])
    return wrapped, {"replaced": True, "wrapped": label}
#[cf]
#[of]: cmd_diff
def cmd_diff(root_a: Block, root_b: Block) -> list[dict]:
    """Semantic diff between two trees. Returns added, removed, and modified blocks."""
    import difflib

    def collect(block, acc=None):
        if acc is None: acc = {}
        # path senza @line per confronto stabile tra versioni
        stable = re.sub(r"@\d+", "", block.path)
        acc[stable] = block.render()
        for c in block.children:
            collect(c, acc)
        return acc

    blocks_a = collect(root_a)
    blocks_b = collect(root_b)

    result = []
    all_paths = sorted(set(blocks_a) | set(blocks_b))
    for path in all_paths:
        if path not in blocks_a:
            result.append({"path": path, "status": "added"})
        elif path not in blocks_b:
            result.append({"path": path, "status": "removed"})
        elif blocks_a[path] != blocks_b[path]:
            diff = list(difflib.unified_diff(
                blocks_a[path].splitlines(keepends=True),
                blocks_b[path].splitlines(keepends=True),
                fromfile=f"a/{path}", tofile=f"b/{path}", lineterm=""
            ))
            result.append({"path": path, "status": "modified", "diff": "".join(diff)})
    return result

#[cf]
#[of]: cmd_normalize
def cmd_normalize(root: Block, open_tag: str = OPEN_TAG, close_tag: str = CLOSE_TAG) -> list[str]:
    """Normalize formatting of all blocks in the file:
    - blank line before the closing TF tag (breathing room at end of each block)
    - no blank lines between sibling blocks (compact in the viewer)
    """
    def _filter_items(items):
        """Remove empty Text items adjacent to Block — eliminates blank lines between blocks."""
        result = []
        for i, item in enumerate(items):
            if isinstance(item, Text) and item.text.strip() == '':
                prev_is_block = i > 0 and isinstance(items[i - 1], Block)
                next_is_block = i < len(items) - 1 and isinstance(items[i + 1], Block)
                if prev_is_block or next_is_block:
                    continue  # salta riga vuota inter-blocco
            result.append(item)
        return result

    def _render_block(block: Block) -> list[str]:
        out = []
        for item in _filter_items(block.items):
            match item:
                case Note(text=t):
                    out.append(t + '\n')
                case Text(text=t):
                    out.append(t + '\n')
                case Block() as b:
                    out.append(_tag_line(open_tag, b.label))
                    out.extend(_render_block(b))
                    out.append(_tag_line(close_tag))
        # riga vuota finale (prima del TF-TAGS di chiusura)
        while out and out[-1].strip() == '':
            out.pop()
        out.append('\n')
        return out

    inner = []
    for item in _filter_items(root.items):
        match item:
            case Note(text=t):
                inner.append(t + '\n')
            case Text(text=t):
                inner.append(t + '\n')
            case Block() as b:
                inner.append(_tag_line(open_tag, b.label))
                inner.extend(_render_block(b))
                inner.append(_tag_line(close_tag))
    return [_tag_line(open_tag, root.label)] + inner + [_tag_line(close_tag)]
#[cf]
#[of]: cmd_health
def cmd_health(directory: str, threshold: int = 20, extensions: list[str] | None = None) -> dict:
    """Health check del progetto: file non strutturati + blocchi troppo lunghi.
    threshold: numero massimo di righe per blocco (default 20)
    Metrica: righe di testo libero + 1 per ogni figlio diretto.
    """
    import pathlib
    base = pathlib.Path(directory).resolve()

    SKIP_EXTS = DEFAULT_SKIP_EXTS
    TEXT_EXTS = DEFAULT_TEXT_EXTS
    _is_ignored = _build_ignore_matcher(base)

    ALL_OPEN_TAGS = {OPEN_TAG} | {t[0] for t in _EXT_TAGS.values()}

    unstructured = []
    no_root      = []
    long_blocks  = []

#[of]: _build_file_list
    if extensions:
        all_files = []
        for ext in extensions:
            all_files.extend(base.rglob(f"*.{ext.lstrip(chr(46))}"))
    else:
        all_files = [p for p in base.rglob("*") if p.is_file()]
#[cf]
#[of]: _helpers
    def _effective_lines(block) -> int:
        """Righe di testo libero + 1 per ogni figlio diretto."""
        free = sum(1 for item in block.items if isinstance(item, Text))
        children = len(block.children)
        return free + children

    def _collect_long(block, file_rel, depth=0):
        if block.label != "root":
            eff = _effective_lines(block)
            if eff > threshold:
                long_blocks.append({
                    "file":   file_rel,
                    "path":   block.path,
                    "lines":  eff,
                    "depth":  depth,
                })
        for child in block.children:
            _collect_long(child, file_rel, depth + 1)
#[cf]
#[of]: _walk_files
    for fpath in sorted(all_files):
        if _is_ignored(fpath):
            continue
        if fpath.suffix.lower() in SKIP_EXTS:
            continue
        if not extensions and fpath.suffix.lower() not in TEXT_EXTS:
            continue

        try:
            content = fpath.read_bytes()
        except (OSError, PermissionError):
            continue

        file_rel = str(fpath.relative_to(base))
        is_structured = any(tag.encode() in content for tag in ALL_OPEN_TAGS)

        if is_structured:
            try:
                lines = content.decode("utf-8", errors="replace").splitlines(keepends=True)
            except Exception:
                continue
            open_tag, close_tag = tags_for_file(str(fpath))
            try:
                root = parse(lines, open_tag, close_tag)
            except ValueError:
                no_root.append({"file": file_rel, "lines": len(lines)})
                continue
            _collect_long(root, file_rel)
        else:
            try:
                raw = content.decode("utf-8", errors="replace")
            except Exception:
                continue
            n = len(raw.splitlines())
            if n < 5:
                continue
            if n >= 80:
                priority = "high"
            elif n >= 30:
                priority = "medium"
            else:
                priority = "low"
            unstructured.append({"file": file_rel, "lines": n, "priority": priority})
#[cf]
#[of]: _return
    long_blocks.sort(key=lambda b: -b["lines"])
    order = {"high": 0, "medium": 1, "low": 2}
    unstructured.sort(key=lambda f: (order[f["priority"]], f["file"]))
    no_root.sort(key=lambda f: f["file"])

    return {
        "ok":           True,
        "threshold":    threshold,
        "long_blocks":  long_blocks,
        "no_root":      no_root,
        "unstructured": unstructured,
    }
#[cf]
#[cf]
#[of]: cmd_init
def cmd_init(file_path: str) -> dict:
    """Prepare the prompt to structure a raw file (without open tags) with TextFolding.
    Returns prompt + raw content + operational instructions.
    Execute the returned prompt: analyse the content and call cmd_edit_text with newBlocks.
    """
    import pathlib
    import os

    abs_path = str(pathlib.Path(file_path).resolve())
    if not os.path.isfile(abs_path):
        return {"ok": False, "error": f"file not found: {abs_path}"}

    open_tag, close_tag = tags_for_file(abs_path)
    try:
        content = open(abs_path).read()
    except (OSError, PermissionError) as e:
        return {"ok": False, "error": str(e)}

    # Check only line 1 or 2 (line 2 if line 1 is a shebang)
    first_lines = content.splitlines()[:2]
    already_structured = any(
        line.strip().startswith(open_tag) and "root" in line
        for line in first_lines
    )
    if already_structured:
        return {"ok": False, "error": f"file gia strutturato con TF: {abs_path}"}

    # Pre-wrappa il file con root esplicito prima di restituire il prompt
    # If the first line is a shebang, insert the root tag AFTER it
    lines = content.splitlines(keepends=True)
    if lines and lines[0].startswith("#!"):
        shebang = lines[0]
        rest = "".join(lines[1:])
        wrapped = f"{shebang}{_tag_line(open_tag, 'root')}{rest}{_tag_line(close_tag)}"
    else:
        wrapped = f"{_tag_line(open_tag, 'root')}{content}{_tag_line(close_tag)}"
    try:
        with open(abs_path, 'w') as f:
            f.write(wrapped)
    except (OSError, PermissionError) as e:
        return {"ok": False, "error": str(e)}

#[of]: _load_prompt
    manual_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "tf_wiki", "manual.md")
    prompt_text = ""
    if os.path.isfile(manual_path):
        try:
            manual_lines = open(manual_path).readlines()
            manual_root = parse(manual_lines)
            prompt_block = get_block(manual_root, "root/training/ai_prompts/init")
            if prompt_block:
                prompt_text = "".join(
                    item.text + "\n"
                    for item in prompt_block.items
                    if isinstance(item, Text)
                ).strip()
        except Exception:
            pass

    if not prompt_text:
        prompt_text = (
            "Analizza il contenuto grezzo ricevuto e strutturalo con TextFolding.\n"
            "Chiama tf_editText con newBlocks per applicare la struttura.\n"
            "NON scrivere TF-TAGS nel testo — ci pensa tf.\n"
            "NON includere [label] come prima riga del testo."
        )
#[cf]
#[of]: _return
    n_lines = len(content.splitlines())
    return {
        "ok":          True,
        "file":        abs_path,
        "lines":       n_lines,
        "prompt":      prompt_text,
        "content":     content,
        "instruction": (
            f"Esegui il prompt qui sopra su '{abs_path}' ({n_lines} righe). "
            "Chiama tf_editText(path=FILE@root, text=..., newBlocks=..., write=True) per applicare la struttura."
        ),
    }
#[cf]
#[cf]
#[of]: cmd_create_file
def cmd_create_file(file_path: str) -> dict:
    """Create a new TF-structured file with root open/close tag wrapper.
    The file must NOT exist — error if already present.
    After this call the file is ready for tf_editText/tf_addBlock without further steps.
    """
    import pathlib, os

    abs_path = str(pathlib.Path(file_path).resolve())
    if os.path.exists(abs_path):
        return {"ok": False, "error": f"file already exists: {abs_path}"}

    parent = os.path.dirname(abs_path)
    if parent and not os.path.isdir(parent):
        return {"ok": False, "error": f"directory non esistente: {parent}"}

    open_tag, close_tag = tags_for_file(abs_path)
    content = f"{_tag_line(open_tag, 'root')}\n{_tag_line(close_tag)}"
    try:
        with open(abs_path, "w") as f:
            f.write(content)
    except (OSError, PermissionError) as e:
        return {"ok": False, "error": str(e)}

    return {"ok": True, "path": abs_path, "open_tag": open_tag, "close_tag": close_tag}
#[cf]
#[of]: cmd_init_project
def cmd_init_project(directory: str) -> dict:
    """Scan a directory and return NON-structured files as candidates for tf_init.
    Separates already-TF files (structured) from candidates, with priority high/medium/low.
    For each candidate: call cmd_init(path) and execute the returned prompt.
    """
    import pathlib
    base = pathlib.Path(directory).resolve()

    SKIP_EXTS = DEFAULT_SKIP_EXTS
    TEXT_EXTS = DEFAULT_TEXT_EXTS
    _is_ignored = _build_ignore_matcher(base)
    ALL_OPEN_TAGS = {OPEN_TAG} | {t[0] for t in _EXT_TAGS.values()}

#[of]: _walk_candidates
    all_files = [p for p in base.rglob("*") if p.is_file()]
    candidates = []
    already_tf = []

    for fpath in sorted(all_files):
        if _is_ignored(fpath):
            continue
        if fpath.suffix.lower() in SKIP_EXTS:
            continue
        if fpath.suffix.lower() not in TEXT_EXTS:
            continue
        try:
            content = fpath.read_bytes()
        except (OSError, PermissionError):
            continue
        file_rel = str(fpath.relative_to(base))
        is_structured = any(tag.encode() in content for tag in ALL_OPEN_TAGS)
        if is_structured:
            already_tf.append(file_rel)
        else:
            try:
                raw = content.decode("utf-8", errors="replace")
            except Exception:
                continue
            n = len(raw.splitlines())
            if n < 5:
                continue
            if n >= 80:
                priority = "high"
            elif n >= 30:
                priority = "medium"
            else:
                priority = "low"
            candidates.append({"file": file_rel, "lines": n, "priority": priority})
#[cf]
#[of]: _load_prompt
    import os
    manual_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "tf_wiki", "manual.md")
    prompt_text = ""
    if os.path.isfile(manual_path):
        try:
            manual_lines = open(manual_path).readlines()
            manual_root = parse(manual_lines)
            prompt_block = get_block(manual_root, "root/training/ai_prompts/init_project")
            if prompt_block:
                prompt_text = "".join(
                    item.text + "\n"
                    for item in prompt_block.items
                    if isinstance(item, Text)
                ).strip()
        except Exception:
            pass
#[cf]
#[of]: _return
    order = {"high": 0, "medium": 1, "low": 2}
    candidates.sort(key=lambda f: (order[f["priority"]], f["file"]))

    return {
        "ok":         True,
        "candidates": candidates,
        "already_tf": already_tf,
        "prompt":     prompt_text,
    }
#[cf]
#[cf]
#[of]: cmd_write_config
def cmd_write_config(directory: str) -> dict:
    """Create .tf/ and write .tf/config.tf with cwd = directory.
    If .tf/config.tf already exists: update ONLY the cwd line, preserve all other keys
    (components, skip_dirs, etc.). If it does not exist: create with minimal template.
    Returns {ok, created, config_path}.
    """
    import pathlib, re
    base = pathlib.Path(directory).resolve()
    tf_dir = base / ".tf"
    tf_dir.mkdir(exist_ok=True)
    config_path = tf_dir / "config.tf"

    existed = config_path.exists()
    if existed:
        # Preserve existing content, replacing only the cwd line.
        old = config_path.read_text(encoding="utf-8")
        new, n = re.subn(r"^(\s*cwd\s*=\s*).*$", r"\g<1>" + str(base), old, count=1, flags=re.MULTILINE)
        if n == 0:
            # cwd mancante: lo aggiungiamo dopo l'apertura del blocco 'config' (o in testa se manca)
            if "#[of]: config" in new:
                new = new.replace("#[of]: config", f"#[of]: config\ncwd = {base}", 1)
            else:
                new = f"cwd = {base}\n" + new
        if new != old:
            config_path.write_text(new, encoding="utf-8")
    else:
        content = f"#[of]: root\n#[of]: config\ncwd = {base}\n#[cf]\n#[cf]\n"
        config_path.write_text(content, encoding="utf-8")

    return {
        "ok": True,
        "created": not existed,
        "config_path": str(config_path),
        "cwd": str(base),
    }
#[cf]
#tf:ref .tf/wiki/decisions.md@root/adr_components_manifest
#[cf]
#[of]: tf_api_helpers
# cwd override set by tf_initProject — persists for the lifetime of the process
_PROJECT_CWD: str | None = None

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

    env_root = os.environ.get("TF_PROJECT_ROOT", "").strip()
    if env_root and os.path.isdir(env_root):
        return env_root

    if _PROJECT_CWD and os.path.isdir(_PROJECT_CWD):
        return _PROJECT_CWD

    actual = os.getcwd()
    config_path = os.path.join(actual, ".tf", "config.tf")
    if os.path.exists(config_path):
        result = _read_cwd_from_config(config_path)
        if result:
            return result

    current = actual
    while True:
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
        config_path = os.path.join(current, ".tf", "config.tf")
        if os.path.exists(config_path):
            result = _read_cwd_from_config(config_path)
            if result:
                return result

    return None


def _auto_init_from_cwd(path: str = "") -> bool:
    """Transparently detect the project root on every tool call."""
    global _PROJECT_CWD
    if _PROJECT_CWD and os.path.isdir(_PROJECT_CWD):
        return False

    def _has_config(d: str) -> bool:
        return os.path.exists(os.path.join(d, ".tf", "config.tf"))

    try:
        cwd = os.getcwd()
    except OSError:
        cwd = ""
    if cwd and os.path.isdir(cwd) and _has_config(cwd):
        _PROJECT_CWD = cwd
        return True

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


def _require_init() -> dict | None:
    """Returns None if TF is initialized and cwd is valid, else error dict."""
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


def _cwd() -> str:
    """Returns the validated cwd. Raises RuntimeError if unavailable."""
    cwd = _get_project_cwd()
    if cwd is None:
        raise RuntimeError("cwd not available — call _require_init() before _cwd()")
    return cwd


def _get_skip_dirs(project_path: str) -> set:
    """Read skip_dirs from .tf/components.tf@root/config."""
    import shlex
    components_path = os.path.join(project_path, ".tf", "components.tf")
    if not os.path.exists(components_path):
        return set()
    try:
        with open(components_path) as fh:
            lines = fh.readlines()
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


def _load(path: str):
    """Load file and root block from a file@block path."""
    file_path = path.split("@")[0] if "@" in path else path
    if not os.path.isabs(file_path):
        file_path = os.path.join(_cwd(), file_path)
    if not os.path.exists(file_path):
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


def _block_path(path: str) -> str:
    """Estrae il block path da file@block/path."""
    if "@" not in path:
        return "root"
    return path.split("@", 1)[1] or "root"


def _reject_tf_markers(s, param_name: str, open_tag: str, close_tag: str):
    """Return an error dict if s contains TF block markers; else None."""
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


def _safe_save(file_path, new_lines, open_tag, close_tag):
    """Save with validation. Returns error string or None."""
    try:
        _validate_tags(new_lines, open_tag, close_tag)
        with open(file_path, "w") as f:
            f.writelines(new_lines)
        return None
    except (ValueError, PermissionError, OSError) as e:
        return str(e)


def _abs(path):
    if os.path.isabs(path):
        return path
    return os.path.join(_cwd(), path)


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
#[of]: tf_api
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

    if scope == "file":
        blk = get_block(root, blk_path) if blk_path != "root" else None
        return _paginate("".join(cmd_strip(lines, open_tag, close_tag, blk)))

    blk = get_block(root, blk_path)
    if blk is None:
        return json.dumps({"ok": False, "error": f"block not found: {blk_path}"})

    warnings = _homonym_warnings(root, blk_path)

    total_lines = blk.end_line - blk.start_line if blk.start_line >= 0 else 0

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
def tf_wrapBlock(path: str, label: str, start: int, end: int, write: bool = True) -> dict:
    """Wrap existing lines into a new block.
    path MUST include a block specifier (e.g. 'file.py@root').
    start/end = visible row numbers (0-based) relative to that block,
    as returned by tf_getBlockContent(numbered=True, mode='structured').
    For multiple wraps use tf_wrapBlocks. See tf_man(topic='flows/f_onboard').
    """
    if end is None:
        return {"ok": False, "error": "end is required"}
    if '@' not in path:
        return {"ok": False, "error": "path must include a block specifier (e.g. 'file.py@root'). Use tf_onboard() to initialize a file before wrapping blocks."}

    file_path, lines, root, open_tag, close_tag = _load(path)

    block_path = path.split('@', 1)[1]
    block = get_block(root, block_path)
    if block is None:
        return {"ok": False, "error": f"block not found: {block_path}"}
    try:
        abs_start, _ = visible_to_physical(block, lines, start)
        abs_end,   _ = visible_to_physical(block, lines, end)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

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
def tf_wrapBlocks(path: str, blocks: list, write: bool = True) -> dict:
    """Wrap multiple line ranges into new blocks in one call (no shift drift).
    path MUST include a block specifier (e.g. 'file.py@root').
    blocks: [{label, start, end}] with visible row numbers relative to that block
    (0-based, as returned by tf_getBlockContent numbered=True structured).
    PREFER over multiple tf_wrapBlock. See tf_man(topic='flows/f_onboard').
    """
    if not blocks:
        return {"ok": False, "error": "blocks is empty"}
    if '@' not in path:
        return {"ok": False, "error": "path must include a block specifier (e.g. 'file.py@root'). Use tf_onboard() to initialize a file before wrapping blocks."}

    file_path, lines, root, open_tag, close_tag = _load(path)
    open_re  = re.compile(re.escape(open_tag) + r'\s*(\S+)')
    close_re = re.compile(re.escape(close_tag))

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

    cwd = _get_project_cwd()
    if cwd is None:
        if path is None or path == ".":
            return json.dumps({"ok": False, "error": "TF not initialized. Use an absolute path (e.g. '/abs/path/file.py') or run tf_initProject."})
        cwd = os.getcwd()

    # Extract block from path if path contains '@' and block parameter is not provided
    if path and "@" in path and block is None:
        path_part, block = path.split("@", 1)
        path = path_part

    if path is None:
        components_path = os.path.join(cwd, ".tf/components.tf")
        if not os.path.exists(components_path):
            return "components.tf not found. Use path='.' for the full project."
        out_lines.append(".tf/components.tf:")
        _render_file(components_path, ".tf/components.tf", start_block=block)
        return "\n".join(out_lines)

    abs_path = _abs(path)

    if os.path.isfile(abs_path):
        frel = os.path.relpath(abs_path, cwd)
        _render_file(abs_path, frel, start_block=block)
        return "\n".join(out_lines)

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
def tf_init(path: str) -> dict:
    """Prepare prompt to AI-structure a raw file (no TF tags). Returns prompt + content + instructions.
    Execute the returned prompt: analyze → tf_editText with newBlocks. For raw files only.
    See tf_man(topic='flows/f_onboard').
    """
    return cmd_init(_abs(path))
def tf_createFile(path: str) -> dict:
    """Create a new TF-ready file with open/close tag wrapper around root. File must not exist.
    See tf_man(topic='flows/f_onboard').
    """
    result = cmd_create_file(_abs(path))
    if result.get("ok"):
        result["hint"] = "File created. This is a one-shot operation — if this file is part of the project, register it in .tf/components.tf now (add a node with #tf:ref pointing to the new file)."
    return result
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

# --- HEALTH: long blocks, no_root, unstructured ---
    health = cmd_health(abs_path, threshold)
    long_blocks = health.get("long_blocks", [])
    no_root = health.get("no_root", [])
    unstructured = health.get("unstructured", [])

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
        session = cmd_read_session(root, keys)
        if session is None:
            return "No saved session."
        parts = []
        for k, v in session.items():
            if v and v.strip():
                parts.append(f"## {k}\n{v.strip()}")
        return "\n\n".join(parts) if parts else "Empty session."

    if action == "save":
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

    return {"ok": False, "error": f"unknown action: {action}. Use 'save' or 'load'."}
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
#[of]: server
#[of]: _io
def _die(msg: str):
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)

def _load_file(filepath: str, open_tag: str = None, close_tag: str = None):
    if open_tag is None or close_tag is None:
        open_tag, close_tag = tags_for_file(filepath)
    note_tag = note_tag_for_file(filepath)
    if not os.path.isfile(filepath):
        raise FileNotFoundError(filepath)
    with open(filepath) as f:
        lines = f.readlines()
    try:
        root = parse(lines, open_tag, close_tag, note_tag)
    except ValueError as e:
        raise ValueError(f"{filepath}: {e}")
    return lines, root, open_tag, close_tag

def _validate_tags(lines: list[str], open_tag: str = OPEN_TAG, close_tag: str = CLOSE_TAG):
    """Verifica che open/close tag siano bilanciati. Lancia ValueError se corrotti."""
    open_re, close_re = _make_patterns(open_tag, close_tag)
    stack = []
    for i, line in enumerate(lines):
        if open_re.match(line):
            stack.append((i + 1, line.strip()))
        elif close_re.match(line):
            if stack:
                stack.pop()
            else:
                raise ValueError(f"extra #[cf] at line {i + 1}")
    if stack:
        unclosed = ", ".join(f"line {l}: {t}" for l, t in stack)
        raise ValueError(f"unclosed blocks: {unclosed}")

def _save(filepath: str, lines: list[str], open_tag: str = OPEN_TAG, close_tag: str = CLOSE_TAG):
    _validate_tags(lines, open_tag, close_tag)
    with open(filepath, 'w') as f:
        f.writelines(lines)

def _ok(payload: dict = None) -> dict:
    return {"ok": True, **(payload or {})}

def _err(msg: str) -> dict:
    return {"ok": False, "error": msg}
#[cf]
#[of]: run_server
def run_server():
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            req = json.loads(raw_line)
        except json.JSONDecodeError as e:
            print(json.dumps(_err(f"invalid JSON: {e}")), flush=True)
            continue
        try:
            resp = _dispatch(req)
        except Exception as e:
            resp = _err(str(e))
        if "_raw" in resp:
            print(resp["_raw"], flush=True)
        else:
            print(json.dumps(resp), flush=True)

#[cf]
#[of]: _dispatch
def _dispatch(req: dict) -> dict:
    cmd      = req.get("cmd", "")
    filepath = req.get("file", "")
    # sintassi abbreviata: path="file@block/path"
    path_val = req.get("path", "")
    if not filepath and path_val and "@" in path_val:
        filepath, path_val = path_val.split("@", 1)
        req = {**req, "file": filepath, "path": path_val}
    open_tag  = req.get("openTag") or None
    close_tag = req.get("closeTag") or None
    if not open_tag or not close_tag:
        open_tag, close_tag = tags_for_file(filepath)
    open_re, close_re = _make_patterns(open_tag, close_tag)
    def load():
        try:
            return _load_file(filepath, open_tag, close_tag)
        except FileNotFoundError:
            raise
        except ValueError as e:
            raise
    try:
        return _dispatch_read(cmd, req, load, open_tag, close_tag) \
            or _dispatch_write(cmd, req, load, open_tag, close_tag, open_re, close_re) \
            or _err(f"unknown command: {cmd}")
    except FileNotFoundError:
        return _err(f"file not found: {filepath}")
    except ValueError as e:
        return _err(str(e))
#[of]: _dispatch_read
def _dispatch_read(cmd, req, load, open_tag, close_tag) -> dict | None:
#[of]: nav_ops
    if cmd == "nav":
        lines, root, _, _ = load()
        block = get_block(root, req.get("path", "root"))
        if block is None:
            return _err(f"block not found: {req.get('path')}")
        return _ok({"levels": all_levels(root), "block": {
            "label":    block.label, "path": block.path,
            "content":  block.render(), "children": [c.label for c in block.children],
        }})
    if cmd == "getBlock":
        lines, root, _, _ = load()
        block = get_block(root, req.get("path", "root"))
        if block is None:
            return _err(f"block not found: {req.get('path')}")
        return _ok({"content": block.render(expanded=req.get("expanded", False))})
    if cmd == "getBlockContent":
        lines, root, _, _ = load()
        block = get_block(root, req.get("path", "root"))
        if block is None:
            return _err(f"block not found: {req.get('path')}")
        return {"_raw": block.render(expanded=req.get("expanded", False))}
    if cmd == "list":
        lines, root, _, _ = load()
        block = get_block(root, req.get("path", "root"))
        if block is None:
            return _err(f"block not found: {req.get('path')}")
        return _ok({"children": [c.label for c in block.children]})
    if cmd == "tree":
        lines, root, _, _ = load()
        blk_path = req.get("path", "root")
        block = get_block(root, blk_path) if blk_path != "root" else root
        if block is None:
            return _err(f"block not found: {blk_path}")
        depth = req.get("depth", -1)
        include_text = req.get("includeText", False)
        if req.get("format") == "xml":
            return _ok({"tree": block.to_xml()})
        return _ok({"tree": block.to_tree(depth, include_text=include_text)})
#[cf]
#[of]: analysis_ops
    if cmd == "summary":
        lines, root, _, _ = load()
        block = get_block(root, req.get("path", "root"))
        if block is None:
            return _err(f"block not found: {req.get('path')}")
        return _ok({"summary": cmd_summary(block, req.get("threshold", 10))})
    if cmd == "search":
        lines, root, _, _ = load()
        block = get_block(root, req.get("path", "root"))
        if block is None:
            return _err(f"block not found: {req.get('path')}")
        return _ok({"results": cmd_search(block, req.get("pattern", ""), req.get("ignoreCase", False))})
    if cmd == "strip":
        lines, root, _, _ = load()
        blk_path = req["path"].split("@", 1)[1] if "@" in req.get("path", "") else None
        blk = get_block(root, blk_path) if blk_path and blk_path != "root" else None
        clean = cmd_strip(lines, open_tag, close_tag, blk)
        out = req.get("out")
        if out:
            _save(out, clean)
            return _ok({"stripped": out, "lines": len(clean)})
        return {"_raw": "".join(clean)}
    if cmd == "diff":
        file_a = req.get("fileA") or req.get("file")
        file_b = req.get("fileB")
        if not file_a or not file_b:
            return _err("diff requires fileA and fileB")
        ot_a, ct_a = tags_for_file(file_a)
        ot_b, ct_b = tags_for_file(file_b)
        lines_a = open(file_a).readlines()
        lines_b = open(file_b).readlines()
        root_a = parse(lines_a, ot_a, ct_a)
        root_b = parse(lines_b, ot_b, ct_b)
        return _ok({"diff": cmd_diff(root_a, root_b)})
#[cf]
#[of]: session_ops
    if cmd == "loadSession":
        lines, root, _, _ = load()
        keys = req.get("keys")
        session = cmd_read_session(root, keys)
        if session is None:
            return _err("no session block found")
        if isinstance(session, dict):
            return _ok({"session": session})
        return {"_raw": session}
    if cmd == "getSession":
        filepath = req.get("file", "")
        agent_id = req.get("agentId", "")
        if not agent_id:
            return _err("getSession requires agentId")
        return _ok(cmd_get_session(filepath, agent_id))
    if cmd == "listSessions":
        filepath = req.get("file", "")
        stale_secs = req.get("staleSecs", 300)
        return _ok(cmd_list_sessions(filepath, stale_secs))
#[cf]
#[of]: file_ops
    if cmd == "scan":
        directory = req.get("path", ".")
        extensions = req.get("ext") or req.get("extensions")
        return _ok(cmd_scan(directory, extensions))
    if cmd == "init":
        filepath = req.get("path", "")
        return cmd_init(filepath)
    if cmd == "initProject":
        directory = req.get("path", ".")
        return cmd_init_project(directory)
    if cmd == "health":
        directory = req.get("path", ".")
        threshold = req.get("threshold", 20)
        extensions = req.get("extensions")
        return cmd_health(directory, threshold, extensions)
#[cf]
    return None
#[cf]
#[of]: _dispatch_write
def _dispatch_write(cmd, req, load, open_tag, close_tag, open_re, close_re) -> dict | None:
#[of]: block_ops
    if cmd == "addBlock":
        lines, root, _, _ = load()
        line_pos = req.get("line", -1)
        new_lines, err = cmd_add_block(lines, req["label"], line_pos,
                                       req.get("content", ""), open_tag, close_tag)
        if err: return _err(err)
        if req.get("write", True): _save(req["file"], new_lines, open_tag, close_tag)
        return _ok({"label": req["label"], "line": line_pos})
    if cmd == "removeBlock":
        lines, root, _, _ = load()
        block = get_block(root, req["path"])
        if block is None or block is root: return _err(f"block not found: {req['path']}")
        if req.get("write", True): _save(req["file"], cmd_remove_block(lines, block), open_tag, close_tag)
        return _ok({"removed": req["path"]})
    if cmd == "renameBlock":
        lines, root, _, _ = load()
        block = get_block(root, req["path"])
        if block is None or block is root: return _err(f"block not found: {req['path']}")
        new_lines = cmd_rename_block(lines, block, req["newLabel"], open_tag, close_tag)
        if req.get("write", True): _save(req["file"], new_lines, open_tag, close_tag)
        return _ok({"renamed": req["path"], "newLabel": req["newLabel"]})
    if cmd == "duplicateBlock":
        lines, root, _, _ = load()
        block = get_block(root, req["path"])
        if block is None or block is root: return _err(f"block not found: {req['path']}")
        if req.get("write", True): _save(req["file"], cmd_duplicate_block(lines, block, open_tag, close_tag), open_tag, close_tag)
        return _ok({"duplicated": req["path"]})
    if cmd == "flattenBlock":
        lines, root, _, _ = load()
        block = get_block(root, req["path"])
        if block is None or block is root: return _err(f"block not found: {req['path']}")
        if req.get("write", True): _save(req["file"], cmd_flatten_block(lines, block), open_tag, close_tag)
        return _ok({"flattened": req["path"]})
#[cf]
#[of]: move_ops
    if cmd == "moveBlock":
        lines, root, _, _ = load()
        block = get_block(root, req["path"])
        if block is None or block is root: return _err(f"block not found: {req['path']}")
        new_lines, err = cmd_move_block(lines, block, req["destLine"], open_tag, close_tag)
        if err: return _err(err)
        if req.get("write", True): _save(req["file"], new_lines, open_tag, close_tag)
        return _ok({"moved": req["path"], "destLine": req["destLine"]})
    if cmd == "moveBlockToParent":
        lines, root, _, _ = load()
        block = get_block(root, req["path"])
        if block is None or block is root: return _err(f"block not found: {req['path']}")
        new_parent = get_block(root, req["newParent"])
        if new_parent is None: return _err(f"newParent not found: {req['newParent']}")
        new_lines, err = cmd_move_block_to_parent(lines, block, new_parent, open_tag, close_tag)
        if err: return _err(err)
        if req.get("write", True): _save(req["file"], new_lines, open_tag, close_tag)
        return _ok({"moved": req["path"], "newParent": req["newParent"]})
#[cf]
#[of]: text_ops
    if cmd == "setBlock":
        lines, root, _, _ = load()
        new_lines, err = cmd_set_block(lines, req["label"], req["start"], req["end"],
                                       open_tag, close_tag, open_re, close_re)
        if err: return _err(err)
        if req.get("write", True): _save(req["file"], new_lines, open_tag, close_tag)
        return _ok({"label": req["label"]})
    if cmd == "editText":
        lines, root, _, _ = load()
        block = get_block(root, req["path"])
        if block is None: return _err(f"block not found: {req['path']}")
        new_lines = cmd_edit_text(lines, block, req.get("text", ""), open_tag, close_tag,
                                  req.get("newBlocks"))
        if req.get("write", True): _save(req["file"], new_lines, open_tag, close_tag)
        return _ok({"edited": req["path"]})
    if cmd == "insert":
        lines, root, _, _ = load()
        block = get_block(root, req["path"])
        if block is None: return _err(f"block not found: {req['path']}")
        new_lines = cmd_insert(lines, block, req.get("row", -1), req.get("text", ""))
        if req.get("write", True): _save(req["file"], new_lines, open_tag, close_tag)
        return _ok({"inserted": req["path"], "row": req.get("row", -1)})
    if cmd == "insertNote":
        lines, root, _, _ = load()
        block = get_block(root, req["path"])
        if block is None: return _err(f"block not found: {req['path']}")
        note_prefix = note_tag_for_file(req["file"])
        new_lines = cmd_insert_note(lines, block, req.get("text", ""), open_tag, close_tag, note_prefix)
        if req.get("write", True): _save(req["file"], new_lines, open_tag, close_tag)
        return _ok({"inserted_note": req["path"]})
    if cmd == "insertRef":
        lines, root, _, _ = load()
        block = get_block(root, req["path"])
        if block is None: return _err(f"block not found: {req['path']}")
        new_lines = cmd_insert_ref(lines, block, req.get("target", ""), open_tag, close_tag)
        if req.get("write", True): _save(req["file"], new_lines, open_tag, close_tag)
        return _ok({"inserted_ref": req["path"], "target": req.get("target", "")})
    if cmd == "wrapText":
        lines, root, _, _ = load()
        parent = get_block(root, req.get("parentPath", "root"))
        if parent is None: return _err(f"block not found: {req.get('parentPath')}")
        new_lines, err = cmd_wrap_text(lines, parent, req["label"],
                                       req.get("text", ""), open_tag, close_tag)
        if err: return _err(err)
        if req.get("write", True): _save(req["file"], new_lines, open_tag, close_tag)
        return _ok({"wrapped": req["label"]})
    if cmd == "append":
        lines, root, _, _ = load()
        block = get_block(root, req["path"])
        if block is None: return _err(f"block not found: {req['path']}")
        try:
            new_lines = cmd_append(lines, block, req.get("text", ""), open_tag, close_tag)
        except ValueError as e:
            return _err(str(e))
        if req.get("write", True): _save(req["file"], new_lines, open_tag, close_tag)
        return _ok({"appended": req["path"]})
#[cf]
#[of]: session_ops
    if cmd == "saveSession":
        lines, root, _, _ = load()
        session_block = None
        for spath in ("root/roadmap/session", "root/session"):
            session_block = get_block(root, spath)
            if session_block: break

        data = req.get("data") or {}
        text_legacy = req.get("text", "")

#[of]: _create_session
        if not session_block:
            parent_path = "root/roadmap" if get_block(root, "root/roadmap") else "root"
            parent = get_block(root, parent_path)
            cur = parent.render()
            sub_text = "[status]\n[next]\n[decisions]\n[blocks]"
            sub_blocks = {
                "status":    data.get("status", ""),
                "next":      data.get("next", ""),
                "decisions": data.get("decisions", ""),
                "blocks":    data.get("blocks", ""),
            }
            new_lines = cmd_edit_text(lines, parent, cur + "\n[session]",
                                      open_tag, close_tag,
                                      {"session": sub_text, **sub_blocks})
            _save(req["file"], new_lines, open_tag, close_tag)
            return _ok({"session": "created"})
#[cf]
#[of]: _init_sub_blocks
        sub_labels = [c.label for c in session_block.children]
        if not sub_labels:
            if data:
                sub_text = "[status]\n[next]\n[decisions]\n[blocks]"
                sub_blocks = {
                    "status":    data.get("status", ""),
                    "next":      data.get("next", ""),
                    "decisions": data.get("decisions", ""),
                    "blocks":    data.get("blocks", ""),
                }
                new_lines = cmd_edit_text(lines, session_block, sub_text,
                                          open_tag, close_tag, sub_blocks)
            else:
                new_lines = cmd_edit_text(lines, session_block, text_legacy,
                                          open_tag, close_tag, None)
            _save(req["file"], new_lines, open_tag, close_tag)
            return _ok({"session": "saved"})
#[cf]
#[of]: _update_keys
        new_lines = lines
        for key, value in data.items():
            sub = _find_child(session_block, key)
            if sub is not None and value:
                new_lines = cmd_edit_text(new_lines, sub, value, open_tag, close_tag, None)
                root = parse(new_lines, open_tag, close_tag)
                session_block = None
                for spath in ("root/roadmap/session", "root/session"):
                    session_block = get_block(root, spath)
                    if session_block: break
        _save(req["file"], new_lines, open_tag, close_tag)
        return _ok({"session": "saved", "updated": list(data.keys())})
#[cf]
#[cf]
#[of]: misc_ops
    if cmd == "normalize":
        lines, root, open_tag, close_tag = load()
        new_lines = cmd_normalize(root, open_tag, close_tag)
        if req.get("write", False): _save(req["file"], new_lines, open_tag, close_tag)
        return _ok({"normalized": req["file"], "written": req.get("write", False)})
    if cmd == "setSession":
        filepath = req.get("file", "")
        agent_id = req.get("agentId", "")
        if not agent_id:
            return _err("setSession requires agentId")
        return _ok(cmd_set_session(filepath, agent_id, req.get("data")))
    if cmd == "cleanSession":
        filepath = req.get("file", "")
        agent_id = req.get("agentId", "")
        if not agent_id:
            return _err("cleanSession requires agentId")
        return _ok(cmd_clean_session(filepath, agent_id))
#[cf]
    return None
#[cf]
#[cf]

#tf:ref .tf/wiki/decisions.md@root/adr_components_manifest
#[cf]
#[of]: interactive
#[of]: _interactive
def _interactive(root: Block):
    COL_W = 24

    def get_parent(block):
        if block is root: return None
        return get_block(root, '/'.join(block.path.split('/')[:-1]))

    def ancestors(block):
        if block is root: return []
        chain, b = [root], root
        for part in block.path.split('/')[1:-1]:
            b = next(c for c in b.children if c.label == part)
            chain.append(b)
        return chain

    def render_col(items, selected):
        return [f" {'>' if b is selected else ' '} {b.label[:COL_W - 4]}" for b in items]

#[of]: _draw
    def draw(current):
        chain = ancestors(current)
        cols  = [render_col(node.children,
                            chain[i + 1] if i + 1 < len(chain) else current)
                 for i, node in enumerate(chain)]
        if current.children:
            cols.append(render_col(current.children, None))
        if cols:
            max_rows = max(len(c) for c in cols)
            total_w  = COL_W * len(cols)
            print("  " + "─" * total_w)
            for r in range(max_rows):
                row = ""
                for ci, col in enumerate(cols):
                    cell = col[r] if r < len(col) else ""
                    row += f"{cell:<{COL_W}}"
                    if ci < len(cols) - 1: row += "│"
                print(row)
            print("  " + "─" * total_w)
        else:
            print("  " + "─" * COL_W)
        print(current.render())
        print("  " + "─" * max(COL_W, 40))
        print(f"  path: {current.path}   < back   q quit")
#[cf]
#[of]: _loop
    current = root
    while True:
        print()
        draw(current)
        try:
            cmd = input("  > ").strip()
        except EOFError:
            break
        if cmd == 'q':
            break
        elif cmd == '<':
            parent = get_parent(current)
            if parent is not None: current = parent
        else:
            target = next((b for b in current.children if b.label == cmd), None)
            if target:
                current = target
            else:
                print(f"  '{cmd}' not found")
#[cf]
#[cf]

#[cf]
#[of]: main
#[of]: _parse_args
def _parse_args():
    ap = argparse.ArgumentParser(description="TextFolding Parser")
    ap.add_argument("file",            nargs="?", default=None)
    ap.add_argument("--openTag",       default=OPEN_TAG)
    ap.add_argument("--closeTag",      default=CLOSE_TAG)
    ap.add_argument("--expand",        action="store_true")
    ap.add_argument("--showTags",      action="store_true")
    ap.add_argument("--markerFormat",  default="<{label}>")
    ap.add_argument("--write",         action="store_true")
    ap.add_argument("--getBlock",      dest="block_path", nargs="?", const="")
    ap.add_argument("--list",          dest="list_path",  nargs="?", const="")
    ap.add_argument("--tree",          choices=["json", "xml"])
    ap.add_argument("--nav",           nargs="?", const="")
    ap.add_argument("--interactive",   action="store_true")
    ap.add_argument("--setBlock",      nargs=3, metavar=("LABEL", "START", "END"))
    ap.add_argument("--addBlock",      nargs=2, metavar=("LABEL", "LINE"))
    ap.add_argument("--removeBlock",   metavar="PATH")
    ap.add_argument("--flatten",       metavar="PATH")
    ap.add_argument("--renameBlock",   nargs=2, metavar=("PATH", "NEW_LABEL"))
    ap.add_argument("--duplicateBlock",metavar="PATH")
    ap.add_argument("--moveBlock",     nargs=2, metavar=("PATH", "DEST_LINE"))
    ap.add_argument("--server",        action="store_true", help="JSON server mode (stdio)")
    ap.add_argument("-d", "--data",    metavar="JSON",      help="Esegui comando JSON singolo e stampa output")
    ap.add_argument("--man",           nargs="?", const="human", metavar="MODE",
                                       help="Mostra il manuale: --man (umano), --man ai (protocollo AI), --man learning (percorso formativo)")
    return ap.parse_args()

#[cf]
#[of]: _run_cli
def _run_cli(args):
    try:
        with open(args.file) as f:
            lines = f.readlines()
    except FileNotFoundError:
        _die(f"File '{args.file}' not found")

    open_re, close_re = _make_patterns(args.openTag, args.closeTag)
    root   = parse(lines, args.openTag, args.closeTag)
    marker = args.markerFormat if args.showTags else "[{label}]"

    if args.interactive:
        _interactive(root); return

#[of]: read_cmds
    if args.block_path is not None:
        block = get_block(root, args.block_path or "root")
        if block is None: _die(f"Block not found: {args.block_path}")
        print(block.render(expanded=args.expand, marker=marker))

    elif args.list_path is not None:
        block = get_block(root, args.list_path or "root")
        if block is None: _die(f"Block not found: {args.list_path}")
        print("\n".join(b.label for b in block.children))

    elif args.tree:
        if args.tree == "json":
            print(json.dumps(root.to_dict(), indent=2))
        else:
            print('<?xml version="1.0" encoding="UTF-8"?>')
            print(root.to_xml())

    elif args.nav is not None:
        block = get_block(root, args.nav or "root")
        if block is None: _die(f"Block not found: {args.nav}")
        print(json.dumps({"levels": all_levels(root), "block": {
            "label":    block.label, "path": block.path,
            "content":  block.render(marker=args.markerFormat),
            "children": [c.label for c in block.children],
        }}, indent=2))
#[cf]
#[of]: block_cmds
#[of]: _setBlock
    elif args.setBlock:
        label, s, e = args.setBlock
        try: start, end = int(s), int(e)
        except ValueError: _die("START and END must be integers")
        new_lines, err = cmd_set_block(lines, label, start, end,
                                       args.openTag, args.closeTag, open_re, close_re)
        if err: _die(err)
        if args.write:
            open(args.file, 'w').writelines(new_lines)
            print(f"Tags written to {args.file}", file=sys.stderr)
        else:
            block = get_block(parse(new_lines, args.openTag, args.closeTag), label)
            print(json.dumps(block.to_dict() if block else {}, indent=2))
#[cf]
#[of]: _addBlock
    elif args.addBlock:
        label, lstr = args.addBlock
        try: line_pos = int(lstr)
        except ValueError: _die("LINE must be an integer")
        content_text = sys.stdin.read()
        new_lines, err = cmd_add_block(lines, label, line_pos, content_text,
                                       args.openTag, args.closeTag)
        if err: _die(err)
        if args.write:
            open(args.file, 'w').writelines(new_lines)
            print(f"Block '{label}' added at line {line_pos} in {args.file}", file=sys.stderr)
        else:
            print(json.dumps({"label": label, "line": line_pos,
                              "content": content_text.splitlines()}, indent=2))
#[cf]
#[of]: _removeBlock_flatten
    elif args.removeBlock:
        block = get_block(root, args.removeBlock)
        if block is None or block is root: _die(f"Block not found: {args.removeBlock}")
        if args.write:
            open(args.file, 'w').writelines(cmd_remove_block(lines, block))
            print(f"Block '{args.removeBlock}' removed from {args.file}", file=sys.stderr)
        else:
            print(json.dumps(block.to_dict(), indent=2))

    elif args.flatten:
        block = get_block(root, args.flatten)
        if block is None or block is root: _die(f"Block not found: {args.flatten}")
        if args.write:
            open(args.file, 'w').writelines(cmd_flatten_block(lines, block))
            print(f"Block '{args.flatten}' flattened in {args.file}", file=sys.stderr)
        else:
            print(json.dumps(block.to_dict(), indent=2))
#[cf]
#[of]: _rename_dup_move
    elif args.renameBlock:
        path, new_label = args.renameBlock
        block = get_block(root, path)
        if block is None or block is root: _die(f"Block not found: {path}")
        new_lines = cmd_rename_block(lines, block, new_label, args.openTag, args.closeTag)
        if args.write:
            open(args.file, 'w').writelines(new_lines)
            print(f"Block '{path}' renamed to '{new_label}'", file=sys.stderr)
        else:
            print(json.dumps({"renamed": path, "newLabel": new_label}))

    elif args.duplicateBlock:
        block = get_block(root, args.duplicateBlock)
        if block is None or block is root: _die(f"Block not found: {args.duplicateBlock}")
        new_lines = cmd_duplicate_block(lines, block, args.openTag, args.closeTag)
        if args.write:
            open(args.file, 'w').writelines(new_lines)
            print(f"Block '{args.duplicateBlock}' duplicated", file=sys.stderr)
        else:
            print(json.dumps({"duplicated": args.duplicateBlock}))

    elif args.moveBlock:
        path, dest_str = args.moveBlock
        try: dest_line = int(dest_str)
        except ValueError: _die("DEST_LINE must be an integer")
        block = get_block(root, path)
        if block is None or block is root: _die(f"Block not found: {path}")
        new_lines, err = cmd_move_block(lines, block, dest_line, args.openTag, args.closeTag)
        if err: _die(err)
        if args.write:
            open(args.file, 'w').writelines(new_lines)
            print(f"Block '{path}' moved to line {dest_line}", file=sys.stderr)
        else:
            print(json.dumps({"moved": path, "destLine": dest_line}))
#[cf]
#[cf]
#[cf]
#[of]: _show_manual
def _show_manual(mode: str = "human"):
    """Print the manual by reading tf_wiki/manual.md.
    mode="human"    → full manual
    mode="ai"       → ai_protocol only
    mode="learning" → training only
    """
    manual = os.path.join(os.path.dirname(os.path.realpath(__file__)), "textfolding", "user_man.txt")
    if not os.path.exists(manual):
        print("Manual not found — reinstall textfolding (pip install git+https://github.com/lucmas655321/tf)", file=sys.stderr); return
    lines = open(manual).readlines()
    root  = parse(lines)
    open_tag, close_tag = tags_for_file(manual)
    block_map = {"ai": "root/ai_protocol", "learning": "root/training"}
    if mode in block_map:
        blk = get_block(root, block_map[mode])
        if blk is None:
            print(f"Block {block_map[mode]} not found", file=sys.stderr); return
        print("".join(cmd_strip(lines, open_tag, close_tag, blk)), end="")
    else:
        print("".join(cmd_strip(lines, open_tag, close_tag)), end="")
#[cf]
#[of]: main_fn
def main():
    args = _parse_args()
    if args.man:
        _show_manual(args.man)
        sys.exit(0)

    # Read JSON from stdin if: not a tty AND not --server AND no -d flag
    # Questo permette:  echo '{"cmd":"..."}' | tf
    #                   tf < req.json
    #                   cat req.json | tf
    stdin_data = None
    if not args.data and not args.server and not sys.stdin.isatty():
        stdin_data = sys.stdin.read().strip()

    if args.data or stdin_data:
        raw = args.data if args.data else stdin_data
        try:
            req = json.loads(raw)
        except json.JSONDecodeError as e:
            _die(f"invalid JSON: {e}")
        resp = _dispatch(req)
        if "_raw" in resp:
            print(resp["_raw"])
        else:
            print(json.dumps(resp, indent=2))
        sys.exit(0)

    if args.server:
        run_server()
        sys.exit(0)
    if args.file is None:
        print('Usage: tf FILE [options]  |  tf -d JSON  |  echo JSON | tf', file=sys.stderr)
        sys.exit(1)
    _run_cli(args)

#[cf]

#[cf]
if __name__ == "__main__":
    main()
#[cf]
