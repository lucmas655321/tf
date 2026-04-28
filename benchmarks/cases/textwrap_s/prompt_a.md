You are working on a Python standard library file. Complete these three
tasks in one conversation. Be concise. Do not restate unchanged code.

The target file is `plain.py` in the current workspace directory.
Do NOT import `textwrap` from the system Python — operate on the local file only.
A backup (`plain.py.bak`) is already present in the workspace.

TASK 1 — ARCHITECTURE MAP
List the top-level classes in this file. For each, provide:
- one-line purpose
- its direct parent class (if any)
- the names of its 3 most important methods

TASK 2 — BEHAVIOR QUESTION
When `TextWrapper._handle_long_word` encounters a word longer than the
available width, what exactly does it do? Describe the specific logic.

TASK 3 — TARGETED EDIT
Add a new keyword argument `line_prefix` (default empty string) to
`TextWrapper.__init__`. When non-empty, every wrapped line (except the
first, which uses `initial_indent`) must be prefixed with this string.
Currently only `subsequent_indent` exists for this purpose, but it
requires the caller to build the prefix string manually. `line_prefix`
should be prepended AFTER `subsequent_indent` is applied. Implement
minimally, modifying only what is strictly necessary. Show the unified
diff of your changes.
