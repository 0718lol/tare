"""
tare.report — 报告生成器

输出格式：
  md     — Markdown 报告（默认）
  text   — 终端彩色表格
  json   — 结构化结果
"""
import json
from datetime import datetime
from typing import Dict, List

from .audit import AuditResult, VERDICT_KEEP, VERDICT_DROP, VERDICT_MANUAL

# ANSI
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"


def _verdict_color(v: str) -> str:
    return {VERDICT_KEEP: GREEN, VERDICT_DROP: RED, VERDICT_MANUAL: YELLOW}.get(v, "")


def render_text(r: AuditResult, color: bool = True) -> str:
    C = (lambda s, c: f"{c}{s}{RESET}") if color else (lambda s, c: s)
    L: List[str] = []
    A = L.append

    A(C("═" * 72, DIM))
    A(C("tare — 静默审计", BOLD))
    A(C("═" * 72, DIM))
    if r.model:
        A(f"  模型        : {r.model}")
    A(f"  trace 数    : {r.trace_count}")
    A(f"  system 规模 : {r.system_chars:,} chars ≈ {r.system_tokens:,} tok")
    if r.total_input:
        A(f"  缓存命中率  : {r.hit_rate*100:.1f}%")
    A("")

    A(C(f"  {'区块':<34}{'tok':>7}{'占比':>7}  {'判定':<12}证据", BOLD))
    A("  " + "─" * 74)
    for b in r.blocks:
        col = _verdict_color(b.verdict)
        A(f"  {b.block[:33]:<34}{b.tokens:>7,}{b.pct:>6.1f}%  "
          f"{C(f'{b.verdict:<12}', col)}{b.evidence[:36]}")

    A("")
    A(C("─" * 72, DIM))
    A(C("  分类汇总", BOLD))
    A(C("─" * 72, DIM))
    for v, col in [(VERDICT_DROP, RED), (VERDICT_KEEP, GREEN), (VERDICT_MANUAL, YELLOW)]:
        items = r.by_verdict(v)
        tok = sum(b.tokens for b in items)
        pct = tok / r.system_tokens * 100 if r.system_tokens else 0
        A(f"  {C(f'{v:<12}', col)} {len(items):>2} 区块  {tok:>7,} tok  ({pct:.1f}%)")
    A("")
    if r.droppable_tokens:
        A(C(f"  ⚠ 潜在可回收: {r.droppable_tokens:,} tok "
            f"({r.droppable_tokens/r.system_tokens*100:.1f}% of system)", YELLOW))
    A("")
    A(C("  注意：'从未出现' 不等于 '无用'。这是假设生成器，不是判决书。", DIM))
    A(C("  因果结论需要主动消融实验。", DIM))
    return "\n".join(L)


def render_markdown(r: AuditResult) -> str:
    L: List[str] = []
    A = L.append

    A("# tare 静默审计报告")
    A("")
    A(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    A(f"> 数据源：{r.trace_count} 条 trace")
    if r.model:
        A(f"> 模型：{r.model}")
    A(f"> 审计对象：system prompt 的 {len(r.blocks)} 个区块，"
      f"合计 {r.system_chars:,} chars ≈ {r.system_tokens:,} tok")
    A("")
    A("---")
    A("")
    A("## 0. 核心结论")
    A("")
    A("| 分类 | 区块数 | token | 占 system |")
    A("|---|---:|---:|---:|")
    for v in [VERDICT_DROP, VERDICT_KEEP, VERDICT_MANUAL]:
        items = r.by_verdict(v)
        tok = sum(b.tokens for b in items)
        pct = tok / r.system_tokens * 100 if r.system_tokens else 0
        A(f"| {v} | {len(items)} | {tok:,} | {pct:.1f}% |")
    A("")
    if r.droppable_tokens:
        A(f"**潜在可回收：{r.droppable_tokens:,} tok "
          f"（{r.droppable_tokens/r.system_tokens*100:.1f}% 的 system prompt）**")
        A("")
    if r.total_input:
        A(f"缓存命中率：**{r.hit_rate*100:.1f}%** "
          f"（{r.total_cached:,} / {r.total_input:,}）")
        A("")
    A("---")
    A("")
    A("## 1. 区块明细")
    A("")
    A("| 区块 | 类别 | tokens | 占比 | 判定 | 置信度 | 证据 |")
    A("|---|---|---:|---:|---|---|---|")
    for b in r.blocks:
        A(f"| `{b.block}` | {b.category or '—'} | {b.tokens:,} | {b.pct:.1f}% | "
          f"{b.verdict} | {b.confidence} | {b.evidence} |")
    A("")
    A("---")
    A("")
    A("## 2. 删除候选明细")
    A("")
    drops = r.by_verdict(VERDICT_DROP)
    if not drops:
        A("无。")
    else:
        for b in drops:
            A(f"### `{b.block}` — {b.tokens:,} tok ({b.pct:.1f}%)")
            A("")
            A(f"- **置信度**：{b.confidence}")
            A(f"- **证据**：{b.evidence}")
            if b.note:
                A(f"- **说明**：{b.note}")
            A("")
    A("---")
    A("")
    A("## 3. 工具调用证据")
    A("")
    if r.tool_counts:
        A("| 工具 | 调用次数 |")
        A("|---|---:|")
        for k, v in sorted(r.tool_counts.items(), key=lambda x: -x[1]):
            A(f"| `{k}` | {v} |")
    A("")
    A("---")
    A("")
    A("## 4. 方法与局限")
    A("")
    A("### 判定方法")
    A("")
    A("采用**行为探针**：对每个区块，检查它所描述的机制是否被实际调用。")
    A("")
    A("### 局限（重要）")
    A("")
    A("1. **「未观察到」≠「无用」**。样本可能未覆盖该场景。")
    A("2. **无行为探针的区块占比可能很高** —— 策略类/输出规范类的价值")
    A("   无法用「是否被调用」衡量。")
    A("3. **触发 ≠ 有效**。区块被消费不代表它产生正收益 ——")
    A("   这需要**主动消融实验**才能确定。")
    A("")
    A("> 静默审计**不是结论，是假设生成器**。它把候选集从「所有区块」")
    A("> 缩小到「少数几个值得做消融实验的目标」，成本几乎为零。")
    A("")
    return "\n".join(L)


def render_json(r: AuditResult) -> str:
    return json.dumps({
        "trace_count": r.trace_count,
        "model": r.model,
        "system_chars": r.system_chars,
        "system_tokens": r.system_tokens,
        "cache_hit_rate": round(r.hit_rate, 4),
        "droppable_tokens": r.droppable_tokens,
        "blocks": [{
            "block": b.block, "category": b.category,
            "tokens": b.tokens, "pct": round(b.pct, 2),
            "verdict": b.verdict, "confidence": b.confidence,
            "evidence": b.evidence, "note": b.note,
        } for b in r.blocks],
        "tool_counts": r.tool_counts,
    }, ensure_ascii=False, indent=2)


RENDERERS = {"text": render_text, "md": render_markdown, "json": render_json}
