# TextFolding — Benchmark Protocol

Controlled A/B experiment: **condition A** (plain Claude, no MCP) vs
**condition TF** (Claude + TextFolding MCP server) on identical tasks,
model, and target file.

---

## 0. Goal

Measure whether TF reduces cost (input tokens / USD) without hurting task
quality, across file sizes and session lengths.

Hypotheses (falsifiable):

- **H1 (amortization):** savings are negative on small files/tasks and grow
  with file size and prompt count per session. There is a breakeven.
- **H2 (session depth):** in a multi-prompt session, each subsequent prompt
  amortizes the warmup cost further — TF advantage compounds.
- **H3 (non-regression):** above breakeven, TF does not degrade output quality.

> **Honesty clause.** Below the breakeven TF is expected to cost *more*.
> The benchmark is designed to locate the breakeven, not hide it.

---

## 1. File tiers

| Tier | Case dir         | File                  | Lines  | Expected regime         |
|------|------------------|-----------------------|-------:|-------------------------|
| S    | `textwrap_s`     | CPython `textwrap.py` |   ~400 | TF likely loses         |
| M    | `argparse_m`     | CPython `argparse.py` | ~2,650 | near breakeven          |
| L    | `pydecimal_l`    | CPython `_pydecimal.py` | ~6,400 | TF expected to win    |

Source files are pinned to CPython `v3.12.2` (see `CPYTHON_TAG`).
SHA256 checksums in `BASELINE_SHA256.txt`. The TF-onboarded variants
(`tf.py`) were produced once via `tf_onboard` and committed as baseline.

---

## 2. Session modes

### Single-prompt (`--size s|m|l`)

One prompt per session. Measures pure per-task efficiency.

### Multi-prompt (`--case <case-dir>`)

N prompts in sequence within the same session, chained via `--resume`.
Protocol overhead paid once; subsequent prompts amortize it.

Available cases:

| Case dir          | Prompts | File      | Focus |
|-------------------|--------:|-----------|-------|
| `argparse_multi`  | 6       | argparse  | arch → behavior → edit → verify → feature → consistency |
| `pydecimal_multi` | 15      | pydecimal | same pattern, extended |

---

## 3. Quick start

### Install

```bash
pip install git+https://github.com/lucmas655321/tf
```

### Run a single experiment

```bash
# Single-prompt, both conditions, 3 reps
bash benchmarks/bench.sh both exp01 s --n 3    # textwrap_s
bash benchmarks/bench.sh both exp02 m --n 3    # argparse_m
bash benchmarks/bench.sh both exp03 l --n 3    # pydecimal_l

# Multi-prompt, both conditions, 3 reps
bash benchmarks/bench.sh both exp04 --case argparse_multi --n 3
bash benchmarks/bench.sh both exp05 --case pydecimal_multi --n 3

# pydecimal_multi first 15 prompts only
bash benchmarks/bench15.sh exp06 --n 3
```

### Output

Each run produces `runs/<id>/session_summary.json`:

```json
{
  "id": "exp01_a_1",
  "cond": "a",
  "mode": "single",
  "totals": {
    "task_cost_usd": 0.085,
    "task_cache_create": 3200,
    "task_cache_read": 18400,
    "full_cost_usd": 0.097
  }
}
```

Multi-prompt runs also have `per_prompt[]` with per-step breakdown.

---

## 4. Conditions

| Cond | MCP config              | Target file | Native tools |
|------|-------------------------|-------------|--------------|
| `a`  | no MCP                  | `plain.py`  | Bash, Read, Write, Edit (all) |
| `tf` | `tf-mcp` (single tool)  | `tf.py`     | **Bash/Read/Write/Edit disabled** |

Condition TF runs with `--disallowedTools Bash,Read,Write,Edit,...` to
prevent the agent from bypassing the TF protocol with native tools.

Warmup prompt for TF: `Call tf('') to read the TF manual, then reply READY`.
This loads the protocol once per session; subsequent prompts reuse the cache.

---

## 5. Protocol (3-step per session)

```
step 01 — cold   : "READY" with cache DISABLED  → baseline overhead
step 02 — warmup : cache ON, condition-specific  → populates cache
step 03 — task   : N prompts, stream-json        → measured run
```

Steps 01–02 are infrastructure cost; `task_cost_usd` covers step 03 only.
`full_cost_usd` includes all three steps.

---

## 6. Metrics

| Metric | Definition |
|--------|-----------|
| `task_cost_usd` | USD for step 03 only (task prompts) |
| `full_cost_usd` | USD for all 3 steps |
| `task_cache_read` | Cache read tokens during task |
| `num_turns` | Tool call round-trips per prompt |
| Δ cost | `1 − (tf_cost / a_cost)` — positive = TF cheaper |

---

## 7. Experimental results (summary)

### Single-prompt (exp01–exp03 style, n=3)

| File tier | A median | TF median | Δ cost |
|-----------|----------|-----------|--------|
| S textwrap (~400L) | ~$0.086 | ~$0.090 | −5% (TF loses) |
| M argparse (~2.6kL) | ~$0.110 | ~$0.116 | −5% (near breakeven) |
| L pydecimal (~6.4kL) | ~$0.230 | ~$0.144 | **+37%** |

### Multi-prompt argparse (6 prompts, exp10/13)

| Run | Cond | Task cost | vs A |
|-----|------|-----------|------|
| exp06 | A | $0.321 | baseline |
| exp10 | TF (post bug-fixes) | $0.302 | **−6%** |
| exp13 | TF (no Bash) | $0.350 | −9% vs A |

High variance on p5 (new feature prompt) — 9–19 turns depending on run.

### Multi-prompt pydecimal (6 prompts, exp20, n=3)

| Cond | Mean task cost | vs A |
|------|---------------|------|
| A    | $0.231 | baseline |
| TF   | $0.137 | **−41%** |

On the large file (6.4k lines) TF wins clearly on every prompt including
architecture scan (p1: 2 turns vs 6 for A).

---

## 8. Known behavioral issues fixed during experiments

| Bug | Impact | Fix |
|-----|--------|-----|
| `tf_inspect` on leaf block returned empty | +10 turns on scan tasks | Added `is_target` param |
| `tf_addBlock after=bool` crashed | rare | isinstance validation |
| `tf_addBlock after=label` searched from root, not parent | +6 turns on feature prompts | Relative lookup in parent children first |
| Agent uses Bash to verify edits when available | +4 turns, defeats isolation | `--disallowedTools` in TF condition |
| Prompt example used `depth=2` → agent iterated every class | +10 turns on p1 | Removed depth from example; tf_tree auto-depth |

---

## 9. What counts as win / loss / neutral

Judged on `task_cost_usd` delta (A vs TF), 3-run median:

| Outcome | Condition |
|---------|-----------|
| **Win** | TF cost ≤ A cost − 10% |
| **Neutral** | within ±10% |
| **Loss** | TF cost > A cost + 10% |

Quality is not automatically measured — visual inspection of diffs and
model output. A cost win that produces wrong output is not a win.

---

## 10. Anti-patterns — when not to use TF

- Files < ~500 lines + one-shot Q&A: protocol overhead dominates.
- Single-turn sessions: no amortization.
- Files the model has memorized (frontier models + classic stdlib).

The benchmark locates the concrete breakeven. Below it, TF is an anti-pattern.

---

## 11. Reproducing

```bash
# Clone and install
git clone https://github.com/lucmas655321/tf && cd tf
pip install .

# Verify baseline hashes
sha256sum -c benchmarks/BASELINE_SHA256.txt

# Run
bash benchmarks/bench.sh both repro01 --case argparse_multi --n 3
```

Results land in `runs/`. Compare `session_summary.json` totals.
