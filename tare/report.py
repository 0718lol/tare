"""
tare.report — report renderers

Formats:
  md     — Markdown report (used by the GitHub Action PR comment)
  text   — terminal table with colour
  json   — structured result for CI

Localisation: every renderer takes lang="en" | "zh". English is the default
because this is an English-facing project, but the Chinese output is kept
intact for the M0/M1 methodology write-ups and for local use.
"""
import json
from datetime import datetime
from typing import Dict, List

from .audit import (AuditResult, VERDICT_KEEP, VERDICT_DROP, VERDICT_MANUAL,
                    VERDICT_LABELS)

# ANSI
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"


def _vlabel(v: str, lang: str) -> str:
    return VERDICT_LABELS.get(lang, VERDICT_LABELS["en"]).get(v, v)


def _verdict_color(v: str) -> str:
    return {VERDICT_KEEP: GREEN, VERDICT_DROP: RED, VERDICT_MANUAL: YELLOW}.get(v, "")


# ------------------------------------------------------------------ strings

T = {
    "en": {
        "title": "tare — static harness audit",
        "generated": "generated",
        "source": "source",
        "traces": "traces",
        "model": "model",
        "scope": "scope",
        "blocks_n": "blocks",
        "totalling": "totalling",
        "summary": "Summary",
        "col_class": "class", "col_blocks": "blocks", "col_tokens": "tokens",
        "col_share": "share of system",
        "reclaimable": "Potentially reclaimable",
        "of_system": "of the system prompt",
        "cache_hit": "Cache hit rate",
        "detail": "Block detail",
        "c_block": "block", "c_cat": "category", "c_tok": "tokens",
        "c_pct": "share", "c_verdict": "verdict", "c_conf": "conf",
        "c_evidence": "evidence",
        "drop_detail": "Drop candidates",
        "none": "None.",
        "confidence": "Confidence",
        "evidence": "Evidence",
        "note": "Note",
        "tool_evidence": "Tool-call evidence",
        "t_tool": "tool", "t_calls": "calls",
        "method": "Method and limitations",
        "how": "How it decides",
        "how_body": ("Behavior probes: for each block, check whether the mechanism it "
                     "describes was actually invoked."),
        "limits": "Limitations (important)",
        "lim1": "**\"Not observed\" != \"useless\".** The sample may not cover that scenario.",
        "lim2": "**Blocks without a behavior probe may be a large share** — the value of "
                "policy/output-spec blocks cannot be measured by \"was it called\".",
        "lim3": "**Triggered != effective.** A block being consumed does not mean it earns "
                "its tokens — that needs an **active ablation** to establish.",
        "caveat": ("> The static audit is **not a verdict, it is a hypothesis generator**. "
                   "It narrows the candidate set from \"every block\" to \"the few worth "
                   "ablating\", at essentially zero cost."),
        "footer1": "'Never observed' does not mean 'useless'. This is a hypothesis generator, "
                   "not a verdict.",
        "footer2": "Causal conclusions need an active ablation experiment.",
        "warn_reclaim": "potentially reclaimable",
        "summary_hdr": "Breakdown",
    },
    "zh": {
        "title": "tare — 静默审计",
        "generated": "生成时间",
        "source": "数据源",
        "traces": "条 trace",
        "model": "模型",
        "scope": "审计对象",
        "blocks_n": "个区块",
        "totalling": "合计",
        "summary": "核心结论",
        "col_class": "分类", "col_blocks": "区块数", "col_tokens": "token",
        "col_share": "占 system",
        "reclaimable": "潜在可回收",
        "of_system": "的 system prompt",
        "cache_hit": "缓存命中率",
        "detail": "区块明细",
        "c_block": "区块", "c_cat": "类别", "c_tok": "tokens",
        "c_pct": "占比", "c_verdict": "判定", "c_conf": "置信度",
        "c_evidence": "证据",
        "drop_detail": "删除候选明细",
        "none": "无。",
        "confidence": "置信度",
        "evidence": "证据",
        "note": "说明",
        "tool_evidence": "工具调用证据",
        "t_tool": "工具", "t_calls": "调用次数",
        "method": "方法与局限",
        "how": "判定方法",
        "how_body": "采用**行为探针**：对每个区块，检查它所描述的机制是否被实际调用。",
        "limits": "局限（重要）",
        "lim1": "**「未观察到」≠「无用」**。样本可能未覆盖该场景。",
        "lim2": "**无行为探针的区块占比可能很高** —— 策略类/输出规范类的价值无法用"
                "「是否被调用」衡量。",
        "lim3": "**触发 ≠ 有效**。区块被消费不代表它产生正收益 —— 这需要**主动消融实验**"
                "才能确定。",
        "caveat": ("> 静默审计**不是结论，是假设生成器**。它把候选集从「所有区块」"
                   "缩小到「少数几个值得做消融实验的目标」，成本几乎为零。"),
        "footer1": "'从未出现' 不等于 '无用'。这是假设生成器，不是判决书。",
        "footer2": "因果结论需要主动消融实验。",
        "warn_reclaim": "潜在可回收",
        "summary_hdr": "分类汇总",
    },
}


def _s(lang: str, key: str) -> str:
    return T.get(lang, T["en"]).get(key, key)


# ------------------------------------------------------------------ renderers

def render_text(r: AuditResult, color: bool = True, lang: str = "en") -> str:
    C = (lambda s, c: f"{c}{s}{RESET}") if color else (lambda s, c: s)
    L: List[str] = []
    A = L.append

    A(C("=" * 72, DIM))
    A(C(f"tare — {_s(lang, 'title').split('— ', 1)[-1]}", BOLD))
    A(C("=" * 72, DIM))
    if r.model:
        A(f"  {_s(lang,'model'):<12}: {r.model}")
    A(f"  {'trace' if lang == 'en' else 'trace 数':<12}: {r.trace_count}")
    A(f"  system      : {r.system_chars:,} chars ~ {r.system_tokens:,} tok")
    if r.total_input:
        A(f"  {_s(lang,'cache_hit'):<12}: {r.hit_rate*100:.1f}%")
    A("")

    hdr = (f"  {'block':<34}{'tok':>7}{'share':>7}  {'verdict':<12}evidence"
           if lang == "en" else
           f"  {'区块':<34}{'tok':>7}{'占比':>7}  {'判定':<12}证据")
    A(C(hdr, BOLD))
    A("  " + "-" * 74)
    for b in r.blocks:
        col = _verdict_color(b.verdict)
        A(f"  {b.block[:33]:<34}{b.tokens:>7,}{b.pct:>6.1f}%  "
          f"{C(f'{_vlabel(b.verdict, lang):<12}', col)}{b.evidence[:36]}")

    A("")
    A(C("-" * 72, DIM))
    A(C(f"  {_s(lang,'summary_hdr')}", BOLD))
    A(C("-" * 72, DIM))
    for v, col in [(VERDICT_DROP, RED), (VERDICT_KEEP, GREEN), (VERDICT_MANUAL, YELLOW)]:
        items = r.by_verdict(v)
        tok = sum(b.tokens for b in items)
        pct = tok / r.system_tokens * 100 if r.system_tokens else 0
        unit = "blocks" if lang == "en" else "区块"
        A(f"  {C(f'{_vlabel(v, lang):<12}', col)} {len(items):>2} {unit}  "
          f"{tok:>7,} tok  ({pct:.1f}%)")
    A("")
    if r.droppable_tokens:
        A(C(f"  ! {_s(lang,'warn_reclaim')}: {r.droppable_tokens:,} tok "
            f"({r.droppable_tokens/r.system_tokens*100:.1f}% of system)", YELLOW))
    A("")
    A(C(f"  {_s(lang,'footer1')}", DIM))
    A(C(f"  {_s(lang,'footer2')}", DIM))
    return "\n".join(L)


def render_markdown(r: AuditResult, lang: str = "en") -> str:
    L: List[str] = []
    A = L.append

    A(f"# {_s(lang,'title')}")
    A("")
    A(f"> {_s(lang,'generated')}: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    A(f"> {_s(lang,'source')}: {r.trace_count} {_s(lang,'traces')}")
    if r.model:
        A(f"> {_s(lang,'model')}: {r.model}")
    A(f"> {_s(lang,'scope')}: {len(r.blocks)} blocks, "
      f"{r.system_chars:,} chars ~ {r.system_tokens:,} tok")
    A("")
    A("---")
    A("")
    A(f"## {_s(lang,'summary')}")
    A("")
    A(f"| {_s(lang,'col_class')} | {_s(lang,'col_blocks')} | "
      f"{_s(lang,'col_tokens')} | {_s(lang,'col_share')} |")
    A("|---|---:|---:|---:|")
    for v in [VERDICT_DROP, VERDICT_KEEP, VERDICT_MANUAL]:
        items = r.by_verdict(v)
        tok = sum(b.tokens for b in items)
        pct = tok / r.system_tokens * 100 if r.system_tokens else 0
        A(f"| {_vlabel(v, lang)} | {len(items)} | {tok:,} | {pct:.1f}% |")
    A("")
    if r.droppable_tokens:
        A(f"**{_s(lang,'reclaimable')}: {r.droppable_tokens:,} tok "
          f"({r.droppable_tokens/r.system_tokens*100:.1f}% {_s(lang,'of_system')})**")
        A("")
    if r.total_input:
        A(f"{_s(lang,'cache_hit')}: **{r.hit_rate*100:.1f}%** "
          f"({r.total_cached:,} / {r.total_input:,})")
        A("")
    A("---")
    A("")
    A(f"## {_s(lang,'detail')}")
    A("")
    A(f"| {_s(lang,'c_block')} | {_s(lang,'c_cat')} | {_s(lang,'c_tok')} | "
      f"{_s(lang,'c_pct')} | {_s(lang,'c_verdict')} | {_s(lang,'c_conf')} | "
      f"{_s(lang,'c_evidence')} |")
    A("|---|---|---:|---:|---|---|---|")
    for b in r.blocks:
        A(f"| `{b.block}` | {b.category or '—'} | {b.tokens:,} | {b.pct:.1f}% | "
          f"{_vlabel(b.verdict, lang)} | {b.confidence} | {b.evidence} |")
    A("")
    A("---")
    A("")
    A(f"## 2. {_s(lang,'drop_detail')}")
    A("")
    drops = r.by_verdict(VERDICT_DROP)
    if not drops:
        A(_s(lang, "none"))
    else:
        for b in drops:
            A(f"### `{b.block}` — {b.tokens:,} tok ({b.pct:.1f}%)")
            A("")
            A(f"- **{_s(lang,'confidence')}**: {b.confidence}")
            A(f"- **{_s(lang,'evidence')}**: {b.evidence}")
            if b.note:
                A(f"- **{_s(lang,'note')}**: {b.note}")
            A("")
    A("---")
    A("")
    A(f"## 3. {_s(lang,'tool_evidence')}")
    A("")
    if r.tool_counts:
        A(f"| {_s(lang,'t_tool')} | {_s(lang,'t_calls')} |")
        A("|---|---:|")
        for k, v in sorted(r.tool_counts.items(), key=lambda x: -x[1]):
            A(f"| `{k}` | {v} |")
    A("")
    A("---")
    A("")
    A(f"## 4. {_s(lang,'method')}")
    A("")
    A(f"### {_s(lang,'how')}")
    A("")
    A(_s(lang, "how_body"))
    A("")
    A(f"### {_s(lang,'limits')}")
    A("")
    A(f"1. {_s(lang,'lim1')}")
    A(f"2. {_s(lang,'lim2')}")
    A(f"3. {_s(lang,'lim3')}")
    A("")
    A(_s(lang, "caveat"))
    A("")
    return "\n".join(L)


def render_json(r: AuditResult, lang: str = "en") -> str:
    return json.dumps({
        "trace_count": r.trace_count,
        "model": r.model,
        "system_chars": r.system_chars,
        "system_tokens": r.system_tokens,
        "cache_hit_rate": round(r.hit_rate, 4),
        "droppable_tokens": r.droppable_tokens,
        "lang": lang,
        "blocks": [{
            "block": b.block, "category": b.category,
            "tokens": b.tokens, "pct": round(b.pct, 2),
            "verdict": b.verdict, "verdict_label": _vlabel(b.verdict, lang),
            "confidence": b.confidence,
            "evidence": b.evidence, "note": b.note,
        } for b in r.blocks],
        "tool_counts": r.tool_counts,
    }, ensure_ascii=False, indent=2)


RENDERERS = {
    "text": render_text,
    "md": render_markdown,
    "json": render_json,
}
