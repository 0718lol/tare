# tare v0.1.0

> Static dead-weight detection for agent harnesses.
> Status: M0 → M1 → M3 done. M2 (active ablation) not started.

---

## What this is

Your harness ships dozens of instruction blocks and hundreds of skills, and you pay for
all of them on every request. `tare` reads your harness's real execution traces, finds the
blocks that were **never touched**, and reports the tokens you could reclaim.

No API keys. No LLM calls. No external dependencies — pure standard library.

**It is a hypothesis generator, not a verdict.** See [Limitations](#limitations).

---

## Install and use

```bash
pip install -e .

tare info                      # what was found, and how big the system prompt is
tare audit                     # colour table in the terminal
tare audit --format md -o AUDIT.md
tare audit --format json       # for CI consumers
tare audit --lang zh           # English by default; zh for a Chinese report
tare audit --adapter generic --trace-dir ./my-traces
```

`tare info` on the reference harness:

```
adapter    : workbuddy
traces     : 51
model      : deepseek-v4.1-flash
total input: 37,239,276
total cached: 36,554,496  (98.2%)
largest system: 41,278 chars
```

---

## Layout

```
tare/
├── pyproject.toml              # packaging + CLI entry point
├── README.md                   # the pitch, a real finding, methodology
├── action.yml                  # GitHub Action (M3)
├── .github/workflows/
│   ├── test.yml                # pytest matrix 3.9 / 3.11 / 3.12 / 3.13
│   └── self-test-action.yml    # runs action.yml for real, on GitHub
├── tare/
│   ├── __init__.py             # version
│   ├── adapters.py             # harness adapter layer (workbuddy / generic)
│   ├── rules.py                # declarative block-probe rules (23 rules)
│   ├── audit.py                # audit engine
│   ├── report.py               # text / md / json renderers, bilingual
│   └── cli.py                  # command line
├── tests/test_tare.py          # 10 unit tests
├── examples/traces/            # sample data
├── m0/                         # M0 methodology + feasibility
└── m1/                         # M1 task suite + ablation scaffolding
```

---

## Architecture

| aspect | before (script) | now (package) |
|---|---|---|
| structure | one file, hard-coded | layered: adapters / rules / audit / report / cli |
| harness support | WorkBuddy only | **adapter pattern**, generic JSON supported |
| rules | inline if-else | **declarative Rule table**, 23 rules |
| output | Markdown only | text / md / json |
| language | Chinese only | English + Chinese (`--lang`) |
| tests | none | 10 unit tests, all passing |
| dependencies | — | none (standard library) |
| distribution | copy files | `pip install -e .` + CLI entry point |
| CI | none | GitHub Actions, 4 Python versions + real action self-test |

### Adapter abstraction

```python
class Adapter:
    def discover(self) -> List[str]      # list available records
    def load(self, ident) -> Trace       # normalise into one shape
    def home(self) -> Optional[str]      # harness root, for path probes
```

`Trace` is the common intermediate representation; derived metrics are properties:

```python
trace.hit_rate            # cache hit rate
trace.tool_error_rate     # tool error rate
trace.tool_repeat_rate    # tool repeat rate (wasteful-exploration signal)
trace.success             # did the session succeed
```

**Any harness that can supply "system prompt + function spans" can be audited.**

---

## The rule table

```python
Rule("my_block", "tooling",
     Probe("span", ["my_tool"], "this block documents my_tool", "high"),
     "what this block is for")
```

Three probe kinds:

| kind | decides by | use for |
|---|---|---|
| `span` | whether a tool was called | mechanism blocks (most common) |
| `path` | whether a path exists and is non-empty | structural dead weight |
| `none` | no probe | policy/convention blocks, flagged for human review |

Current distribution across 23 rules — `span` 13, `none` 9, `path` 1.

**Adding a harness means adding rules, not changing the engine.**

---

## Verified on real traces

Across 51 real traces of the reference harness:

| metric | value |
|---|---|
| system prompt | 10,319 tok / 38 blocks |
| cache hit rate | 98.2% |
| **reclaimable** | **1,733 tok (16.8%)** |
| drop candidates | 6 blocks |
| keep | 12 blocks |
| needs review | 20 blocks |

The bundled sample data (`examples/traces/`) under the generic adapter: 3 blocks,
1 correct drop candidate (569 tok).

---

## The GitHub Action

`action.yml` is a composite action:

- writes a PR comment, marked `<!-- tare-audit -->`, that **updates in place** on re-runs
  rather than posting again
- exposes `droppable-tokens` / `droppable-percent` as step outputs
- **gate**: fails the check when dead weight exceeds a threshold

```yaml
- uses: 0718lol/tare@main
  with:
    fail-on-droppable-percent: "10"
```

The comment renders in English (or Chinese with `lang: zh`).

### What the self-test caught

`self-test-action.yml` runs the action for real on a GitHub runner. It is not ceremony —
it has already caught bugs that local replay cannot see:

1. **Install path.** `github.action_path` differs between a consuming repo and tare's own
   repo, so `pip install -e "$ACTION_DIR/.."` escaped the project and failed on the runner.
   Fixed by probing for `pyproject.toml`.
2. **Chinese report in an English repo.** The action posted a Chinese comment into an
   English-facing project. Fixed with a `--lang` flag, defaulting to `en`.
3. **Section numbering.** The report read `Summary → Block detail → 2. → 3. → 4.`
   Fixed by numbering the detail table as `1.`
4. **Trigger gap.** The self-test only watched `action.yml`, but the action installs the
   package — so a change under `tare/**` could break it just as easily. Trigger widened.

---

## Limitations

| can do | cannot do |
|---|---|
| find blocks **never touched** | judge blocks that were touched but did not help |
| zero cost (reads existing traces) | give causal conclusions (needs active ablation) |
| cross-harness, via adapters | repair your harness |
| quantify reclaimable tokens | cover policy blocks (the review bucket) |

**"Never observed" does not mean "useless".** A block may be untriggered simply because
the sample never exercised it. This is why the output is a list of hypotheses with
evidence attached, not a deletion order.

---

## Status and roadmap

**Done**: M0 (feasibility) → M1 (silent auditor) → M3 (GitHub Action, merged and verified
on a real pull request).

**Not started**:
- **M2 — active ablation.** Remove a block, re-run tasks, measure the delta. This is the
  step that turns a hypothesis into a causal claim. Needs an API key; roughly $0.71 for the
  bundled suite. Scaffolding exists in `m1/`.
- **M4 — cloud sandbox + redundancy detection.**

**Possible next steps:**
1. Run it against a real third-party harness and publish the finding as a case study.
2. Add a `CONTRIBUTING.md` covering how to extend the rule table.
3. Localise the methodology docs (`m0/`, `m1/`), which are still Chinese.

---

## License

MIT.
