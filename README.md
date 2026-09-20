# tare

[![test](https://github.com/0718lol/tare/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/0718lol/tare/actions/workflows/test.yml)
[![self-test action](https://github.com/0718lol/tare/actions/workflows/self-test-action.yml/badge.svg?branch=main)](https://github.com/0718lol/tare/actions/workflows/self-test-action.yml)
[![python](https://img.shields.io/badge/python-3.9%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://github.com/0718lol/tare/actions/workflows/test.yml)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> Static dead-weight detection for agent harnesses.

**tare** (the weight of an empty container) — strip the container's own weight, measure what's actually carrying load.

Your harness ships dozens of instruction blocks and hundreds of skills. **Which ones are actually doing work?**

`tare` reads your harness's real execution traces, finds the blocks that were **never touched**, and reports the tokens you could reclaim.

No API keys. No LLM calls. No external dependencies.

---

## The problem

The entire ecosystem is optimized for **adding** capability — hundreds of skills, dozens of agents, endless instruction blocks. Almost nothing tells you what to **remove**.

The consequences compound:

- Skill lists only grow; context budgets only inflate
- When a task fails, you can't tell if it's the model or a conflicting instruction
- You change the harness, results move, and you can't explain why — so the finding doesn't transfer

And harness effects are **order-of-magnitude**, not cosmetic:

| Change | Effect |
|---|---|
| Edit-format only | Grok Code Fast 1: **6.7% → 68.3%** |
| Harness only | Terminal Bench 2.0: **52.8% → 66.5%** |

If harness composition swings results that hard, "which blocks earn their tokens" is a first-class question.

---

## How it works

### 1. Reconstruct the real system prompt

`tare` replays the actual injected prompt from trace records and splits it into top-level blocks.

```
system prompt: 41,278 chars ≈ 10,319 tok
  ├── <agent_skills>            1,584 tok
  ├── <automations>               800 tok
  ├── <personal_files_safety>     571 tok
  └── ... 38 blocks total
```

### 2. Run behavior probes

For each block, check whether **the mechanism it describes was ever actually invoked**.

| Block | Probe | Verdict |
|---|---|---|
| `<automations>` | was `automation_update` called? | never → 🔥 |
| `<result_presentation>` | was `present_files` called? | 7 times → ✅ |
| `<asking_questions>` | was `AskUserQuestion` called? | 4 times → ✅ |

Three probe types:

| Type | Use |
|---|---|
| `span` | requires a tool/span to have been invoked (most common) |
| `path` | requires a filesystem path to exist and be non-empty (structural dead weight) |
| `none` | no probe available — flagged for human review |

### 3. Three-way classification

```
DROP candidates    6 blocks   1,733 tok  (16.8%)
KEEP              12 blocks   3,650 tok  (35.4%)
REVIEW            20 blocks   4,923 tok  (47.7%)

⚠ reclaimable: 1,733 tok
```

---

## Install

```bash
pip install -e .
```

Pure standard library. Python 3.9+.

---

## Usage

```bash
# What trace data is available?
tare info

# Audit (defaults to WorkBuddy traces)
tare audit

# Markdown report to a file
tare audit --format md -o AUDIT.md

# JSON for CI consumption
tare audit --format json

# Any harness — bring your own traces
tare audit --adapter generic --trace-dir ./my-traces
```

Exit code is `0` on success, `2` on missing/unparseable traces — so it drops into scripts directly.

---

## CI usage

`action.yml` posts the audit as a PR comment (updating one comment in place rather than spamming) and can fail the check on a threshold:

```yaml
- uses: 0718lol/tare@main
  with:
    trace-dir: ./.traces
    adapter: generic
    fail-on-droppable-percent: "25"   # fail if >25% of the prompt is dead weight
    lang: en                          # or "zh" for a Chinese report
```

Outputs `droppable-tokens` and `droppable-percent` for downstream steps.

> Note: adding a workflow file to a repository requires a token with the `workflow` scope. If you hit `refusing to allow an OAuth App to create or update workflow`, re-authorize with `gh auth refresh -s workflow`.

---

## A real finding

On one actual run, `tare` surfaced this:

```
<agent_skills>   ← largest single block in the system prompt, 1,584 tok
    "User-level Skills:   ~/.workbuddy-ai/skills/"
    "Project-level Skills: {workspace}/.workbuddy-ai/skills/"

Measured:
    ~/.workbuddy-ai/skills/            → migration markers only, 0 real skills
    {workspace}/.workbuddy-ai/skills/  → directory does not exist
```

**A 1,584-token specification, running against an empty directory.**

That's the shape of finding `tare` is built for: not "this instruction is redundant" (a judgment call), but "this block documents a location that is empty on disk" (a fact).

---

## ⚠️ Limitations

**The static audit is a hypothesis generator, not a verdict.**

1. **"Not observed" ≠ "useless."**
   The sample may simply not cover that scenario. `<mcp_configuration>` is only needed when installing an MCP server.

2. **Policy blocks can't be judged by behavior probes.**
   Content policy and safety blocks aren't "used." In practice ~**47.7%** of blocks fall into this bucket.

3. **Triggered ≠ effective.**
   A block being consumed doesn't mean it earns its tokens. Only an **active ablation** (measuring ΔS) can settle that.

> `tare`'s value is narrowing the candidate set from "every block" to "a handful worth deep investigation" — at zero cost.

---

## Adding a harness

Adapter architecture. WorkBuddy is built in; `<code>generic</code>` handles anything else:

```bash
tare audit --adapter generic --trace-dir ./my-traces
```

Generic format (`.json`):

```json
{
  "trace": {
    "traceId": "abc",
    "status": "ok",
    "modelInfo": {
      "models": ["your-model"],
      "totalInputTokens": 100000,
      "totalCachedTokens": 95000,
      "totalOutputTokens": 2000,
      "callCount": 8
    }
  },
  "spans": [
    { "name": "generation", "type": "generation", "toolInput": "[{...system prompt...}]" },
    { "name": "present_files", "type": "function", "toolName": "present_files" }
  ]
}
```

All `tare` needs is a `system`-role prompt and your function spans.

---

## Extending the rules

Probes are declared in `tare/rules.py`:

```python
Rule("my_block", "Tools",
     Probe("span", ["my_tool"], "Block documents my_tool usage", "high"),
     "what this block is for"),
```

Adding a harness means adding rules — the engine stays untouched.

---

## Roadmap

- [x] **M0** Feasibility — cache mechanics + component mapping
- [x] **M1** Static auditor (current release)
- [ ] **M2** Active ablation (measure causal ΔS)
- [ ] **M3** GitHub Action integration (block negative-ROI merges in CI)
- [ ] **M4** Cloud sandbox execution + redundancy detection

---

## Methodology docs

| Document | Contents |
|---|---|
| `m0/M0_REPORT.md` | Cache measurements, context layering, skill injection analysis |
| `m0/SILENT_AUDIT.md` | Full static audit report |
| `m1/M1_REPORT.md` | Task suite design, judge validation, natural experiment |
| `m1/TASK_SUITE.md` | 13 verifiable tasks and ablation design |

---

## Status

`v0.1.0` — early. The auditor is tested and works on real traces, but the API may move. Issues and counterexamples welcome; disagreement with a finding is the most useful input this project can get.

---

## License

MIT
