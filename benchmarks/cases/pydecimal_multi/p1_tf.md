You are working on a Python standard library file. Be concise.

The target file is `tf.py` in the current workspace directory.
Do NOT import `decimal` from the system Python — operate on the local file only.
A backup (`tf.py.bak`) is already present in the workspace.

The file is in TF (TextFolding) format with `#[of]:` / `#[cf]` block markers.
The project is initialized. Use EXCLUSIVELY the `tf` tool for all file access
and edits — no Bash, no generic read/write tools.
The `tf` tool accepts a JSON string: tf('{"tool":"<name>", ...args}')
Example: tf('{"tool":"tf_tree","path":"tf.py"}')   (auto-depth: one call returns optimal overview)
Consult `tf_man` if you need syntax help.
Do NOT call `tf_check_env` or `tf_initProject` — the environment is already set up.

TASK — ARCHITECTURE MAP
List the top-level classes in this file. For each, provide:
- one-line purpose
- its direct parent class (if any)
- the names of its 3 most important methods
