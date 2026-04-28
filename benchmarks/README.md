# benchmarks/

TF head-to-head benchmark. Full protocol in `EXPERIMENT.md`.

## Layout

```
benchmarks/
├── CPYTHON_TAG              # cpython tag used as pin source (v3.12.2)
├── PYTHON_VERSION           # python runtime version (3.12.2)
├── EXPERIMENT.md            # full protocol (read this first)
├── README.md                # this file
├── run.sh                   # one-shot runner: prepare | score | list
├── prompt.md                # "small" prompt tier (§6b of EXPERIMENT.md)
├── argparse/
│   ├── argparse.py          # pinned v3.12.2, source for condition A
│   └── test_argparse.py     # pinned v3.12.2, baseline/delta oracle
├── argparse_tf/             # (gitignored) TF-onboarded package for B
│   ├── argparse.py          #   pinned source + TF markers
│   └── .tf/                 #   TF project scaffolding
├── templates/
│   ├── A_vanilla/.mcp.json  # materialised into each run workspace
│   └── B_tf/.mcp.json
├── runs/                    # (gitignored) ephemeral per-run workspaces
│   └── <run_id>/            #   argparse.py + PROMPT.md + .mcp.json + .bench/
├── validation/
│   ├── baseline_probe.sh    # §9bis.7.2 — produces G_pre
│   ├── delta_probe.sh       # §9bis.7.3 — applies agent diff, computes delta
│   ├── extract_diff.py      # extracts first unified diff from a transcript
│   └── out/argparse/        # baseline + per-run sandboxes (see .gitignore)
└── _legacy/                 # previous unpinned files, kept for reference
```

## Confirmed baseline

- cpython tag: `v3.12.2`
- Python:      `3.12.2`
- `argparse.py` unmodified + `test_argparse.py` → **1709 green / 0 red / 0 skipped** in ~1.1s.
- `G_pre` is non-empty and stable. The "already broken" alibi is dismantled.

## Quick start (zero-contamination workflow)

The runner does everything; you never hand-craft a workspace.

```bash
# 0. One-time: verify baseline is green (1709/0/0 expected).
bash validation/baseline_probe.sh

# 1. Prepare an ephemeral workspace for a run.
./run.sh prepare --prompt prompt.md --condition A --model "Claude Sonnet 4.6"
#   -> prints the workspace path + step-by-step instructions
#   -> workspace contains ONLY: argparse.py, PROMPT.md, .mcp.json
#      (no README, no EXPERIMENT, no benchmark metadata visible to the agent)

# 2. You: open the workspace in your IDE, start a fresh conversation,
#    paste PROMPT.md, let the agent run, save the transcript as
#    transcript.md in the workspace.

# 3. Score automatically.
./run.sh score --run-id 20260418-HHMMSS-A-claude_sonnet_4_6
#   -> extracts first unified diff from transcript
#   -> runs delta_probe against G_pre
#   -> writes verdict.json in the workspace AND in validation/out/

# 4. Aggregate view.
./run.sh list
```

A run is correct iff `verdict.json` shows
`patch_applied=true`, `import_ok=true`, `regressions_count=0`,
`actually_correct=true`.

For prompts that don't require an edit (micro / Q&A), `score` will
report `has_diff=false`; grading such runs is a separate oracle
(§9bis.1 of `EXPERIMENT.md`) and is not automated yet.

## Templates

Used only by `run.sh prepare`. **Do not open these directly.**

- `templates/A_vanilla/.mcp.json` — empty MCP registry (vanilla).
- `templates/B_tf/.mcp.json` — registers TF MCP. `cwd` is a placeholder
  (`__WORKSPACE_CWD__`) replaced at materialisation time.

## Still TODO

- **TF-onboarded package** `argparse_tf/` (pinned v3.12.2 file +
  `.tf/`). Produce via a dedicated TF MCP session, then condition B
  becomes usable via `run.sh prepare --condition B ...`.
- Size tiers S (`colorsys.py`) and L (candidate: `Lib/inspect.py` —
  `_pydecimal.py` likely fails the §9bis.7.5 fallback).
- Prompt files for micro (§6a) and large (§6c) tiers.
- Oracle for micro prompts (exact-match against `micro_oracles.json`)
  wired into `run.sh score`.
