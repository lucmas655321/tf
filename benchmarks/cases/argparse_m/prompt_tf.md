You are working on a Python standard library file. Complete these three
tasks in one conversation. Be concise. Do not restate unchanged code.

The target file is `tf.py` in the current workspace directory.
Do NOT import `argparse` from the system Python — operate on the local file only.
A backup (`tf.py.bak`) is already present in the workspace.

The file is in TF (TextFolding) format with `#[of]:` / `#[cf]` block markers.
The project is initialized. Use EXCLUSIVELY the `tf` tool for all file access
and edits — no Bash, no generic read/write tools.
The `tf` tool accepts a JSON string: tf('{"tool":"<name>", ...args}')
Example: tf('{"tool":"tf_tree","path":"tf.py"}')
Consult `tf_man` if you need syntax help.
Do NOT call `tf_check_env` or `tf_initProject` — the environment is already set up.

TASK 1 — ARCHITECTURE MAP
List the top-level classes in this file. For each, provide:
- one-line purpose
- its direct parent class (if any)
- the names of its 3 most important methods

TASK 2 — BEHAVIOR QUESTION
When `ArgumentParser.parse_known_args` encounters an unrecognized
argument, what exactly does it do? Describe the specific logic and
how it differs from `parse_args`.

TASK 3 — TARGETED EDIT
Add a new keyword argument `epilog_formatter` (default None) to
`ArgumentParser.__init__`. When set to a callable, it is called with
the epilog string before it is added to the help output, allowing the
caller to transform it (e.g. add ANSI color, wrap differently).
When None, behavior is unchanged. Implement minimally, modifying only
what is strictly necessary. Show the unified diff of your changes.
