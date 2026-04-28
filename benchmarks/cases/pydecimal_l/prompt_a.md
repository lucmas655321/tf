You are working on a Python standard library file. Complete these three
tasks in one conversation. Be concise. Do not restate unchanged code.

The target file is `plain.py` in the current workspace directory.
Do NOT import `decimal` from the system Python — operate on the local file only.
A backup (`plain.py.bak`) is already present in the workspace.

TASK 1 — ARCHITECTURE MAP
List the top-level classes in this file. For each, provide:
- one-line purpose
- its direct parent class (if any)
- the names of its 3 most important methods

TASK 2 — BEHAVIOR QUESTION
When `Decimal.__add__` is called with operands of differing precision,
what exactly happens? Describe the specific logic for coefficient
alignment and rounding.

TASK 3 — TARGETED EDIT
Add a method `as_dict()` to the `Decimal` class. It should return a
plain dict with keys `sign`, `digits`, and `exponent` — the same data
as `as_tuple()` but as a dict for easier unpacking. Implement minimally,
placing it immediately after the existing `as_tuple` method.
Show the unified diff of your changes.
