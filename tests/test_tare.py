"""tare 单元测试（无外部依赖，可 pytest 或直接 python 运行）"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tare.adapters import Span, Trace, extract_system_prompt  # noqa
from tare.audit import split_blocks, audit, collect_evidence, VERDICT_KEEP, VERDICT_DROP  # noqa
from tare import rules  # noqa


def test_split_blocks_xml():
    text = "<alpha>\ncontent a\n</alpha>\n<beta>\ncontent b\n</beta>\n"
    blocks = split_blocks(text)
    labels = [b[0] for b in blocks]
    assert "alpha" in labels and "beta" in labels


def test_split_blocks_preamble():
    text = "intro text\n<alpha>\nbody\n</alpha>"
    blocks = split_blocks(text)
    assert blocks[0][0] == "(preamble)"


def test_split_blocks_markdown():
    text = "# Section One\ntext\n## Sub\ntext2\n"
    blocks = split_blocks(text)
    labels = [b[0] for b in blocks]
    assert "Section One" in labels


def test_rules_lookup_and_alias():
    assert rules.lookup("automations") is not None
    assert rules.lookup("automations").probe.kind == "span"
    # 别名归一
    r = rules.lookup("Layer 1 — Cloud Memory")
    assert r is not None and r.block == "memory_system"


def test_trace_derived_metrics():
    t = Trace(
        id="t1", status="ok", input_tokens=1000, cached_tokens=900,
        spans=[
            Span("gen", "generation"),
            Span("fn", "function", tool_name="Bash", status="ok"),
            Span("fn2", "function", tool_name="Bash", status="error"),
        ],
    )
    assert abs(t.hit_rate - 0.9) < 1e-9
    assert t.success == 1
    assert t.tool_error_rate == 0.5
    assert t.tool_repeat_rate == 0.5  # Bash, Bash → 1/2


def test_extract_system_prompt():
    blocks = [
        {"role": "system", "content": "short"},
        {"role": "system", "content": "a much longer system prompt here"},
    ]
    spans = [Span("gen", "generation", tool_input=json.dumps(blocks))]
    assert extract_system_prompt(spans) == "a much longer system prompt here"


def test_collect_evidence_skill_arg():
    import json as _j
    spans = [Span("Skill", "function", tool_name="Skill",
                  tool_input=_j.dumps({"skill": "find-skills"}))]
    t = Trace(id="x", spans=spans)
    _, tools = collect_evidence([t])
    assert "find-skills" in tools


def test_audit_detects_drop():
    """构造一个 harness：present_files 被调用，automation 从未调用"""
    sys_text = "<result_presentation>\ndeliver via present_files\n</result_presentation>\n" \
               "<automations>\nuse automation_update\n</automations>\n"
    blocks = [{"role": "system", "content": sys_text}]
    spans = [
        Span("generation", "generation", tool_input=json.dumps(blocks)),
        Span("present_files", "function", tool_name="present_files"),
    ]
    t = Trace(id="t", status="ok", spans=spans, system_prompt=sys_text)
    r = audit([t])
    got = {b.block: b.verdict for b in r.blocks}
    assert got["result_presentation"] == VERDICT_KEEP
    assert got["automations"] == VERDICT_DROP


def test_droppable_tokens():
    sys_text = "<a>\n" + "x" * 400 + "\n</a>\n<b>\n" + "y" * 800 + "\n</b>\n"
    blocks = [{"role": "system", "content": sys_text}]
    spans = [Span("generation", "generation", tool_input=json.dumps(blocks)),
             Span("AskUserQuestion", "function", tool_name="AskUserQuestion")]
    t = Trace(id="t", spans=spans, system_prompt=sys_text)
    r = audit([t])
    assert r.droppable_tokens >= 0
    assert r.system_tokens > 0


def test_report_renderers_do_not_crash():
    from tare.report import render_json, render_markdown, render_text
    sys_text = "<automations>\n" + "z" * 300 + "\n</automations>\n"
    blocks = [{"role": "system", "content": sys_text}]
    t = Trace(id="t", spans=[Span("gen", "generation", tool_input=json.dumps(blocks))],
              system_prompt=sys_text)
    r = audit([t])
    assert "automations" in render_text(r, color=False)
    assert "# tare" in render_markdown(r)
    assert json.loads(render_json(r))["blocks"]


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} 通过")
    sys.exit(1 if failed else 0)
