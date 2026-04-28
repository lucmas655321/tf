You are working on a Python standard library file. Complete these three
tasks in one conversation. Be concise. Do not restate unchanged code.

The target file is `plain.py` in the current workspace directory.
Do NOT import `argparse` from the system Python — operate on the local file only.
A backup (`plain.py.bak`) is already present in the workspace.

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
