"""
tare.audit — 静默审计引擎

核心流程：
  1. 加载 harness 运行记录（Trace）
  2. 从 system prompt 切出区块
  3. 对每个区块跑探针，判定是否被消费
  4. 归类为 保留 / 删除候选 / 需人工
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .adapters import Trace
from . import rules


VERDICT_KEEP = "保留"
VERDICT_DROP = "删除候选"
VERDICT_MANUAL = "需人工判断"

# 切分 system prompt 的顶层标记
SPLIT_RE = re.compile(r"^(<([a-z_]{3,45})>|#{1,2}\s+(.+))", re.MULTILINE)


@dataclass
class BlockResult:
    block: str
    chars: int
    tokens: int
    pct: float
    verdict: str
    evidence: str
    confidence: str
    category: str = ""
    note: str = ""


@dataclass
class AuditResult:
    blocks: List[BlockResult] = field(default_factory=list)
    trace_count: int = 0
    system_chars: int = 0
    model: Optional[str] = None
    total_input: int = 0
    total_cached: int = 0
    tool_counts: Dict[str, int] = field(default_factory=dict)

    @property
    def system_tokens(self) -> int:
        return self.system_chars // 4

    @property
    def hit_rate(self) -> float:
        return self.total_cached / self.total_input if self.total_input else 0.0

    def by_verdict(self, v: str) -> List[BlockResult]:
        return [b for b in self.blocks if b.verdict == v]

    @property
    def droppable_tokens(self) -> int:
        return sum(b.tokens for b in self.by_verdict(VERDICT_DROP))


def split_blocks(text: str) -> List[Tuple[str, str]]:
    """把 system prompt 切成 (标签, 内容) 列表"""
    marks = [(m.start(), m.group(2) or m.group(3)) for m in SPLIT_RE.finditer(text)]
    if not marks:
        return [("(preamble)", text)]
    out: List[Tuple[str, str]] = []
    if marks[0][0] > 0:
        out.append(("(preamble)", text[: marks[0][0]]))
    for i, (pos, label) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        out.append((label, text[pos:end]))
    return out


def collect_evidence(traces: List[Trace]) -> Tuple[Dict[str, int], Dict[str, int]]:
    """汇总所有 trace 的 span / tool 证据"""
    span_names: Dict[str, int] = {}
    tool_names: Dict[str, int] = {}
    import json
    for t in traces:
        for s in t.spans:
            span_names[s.name] = span_names.get(s.name, 0) + 1
            if s.type == "function" and s.tool_name:
                tool_names[s.tool_name] = tool_names.get(s.tool_name, 0) + 1
            # Skill 工具的真实技能名藏在参数里
            if s.name == "Skill" and s.tool_input:
                try:
                    ti = json.loads(s.tool_input)
                    if isinstance(ti, dict) and ti.get("skill"):
                        k = ti["skill"]
                        tool_names[k] = tool_names.get(k, 0) + 1
                except Exception:
                    pass
    return span_names, tool_names


def run_span_probe(needles: List[str],
                   span_names: Dict[str, int],
                   tool_names: Dict[str, int]) -> Tuple[bool, str]:
    for n in needles:
        nl = n.lower()
        for name, cnt in span_names.items():
            if nl in name.lower():
                return True, f"{name} ×{cnt}"
        for name, cnt in tool_names.items():
            if nl in name.lower():
                return True, f"{name} ×{cnt}"
    return False, "从未出现"


def run_path_probe(paths: List[str], home: Optional[str]) -> Tuple[Optional[bool], str]:
    import os
    from pathlib import Path
    if not home:
        return None, "无法定位 harness 根目录"
    notes = []
    any_exist = False
    for rel in paths:
        p = Path(home) / rel
        if not p.exists():
            notes.append(f"✗ {rel}")
        else:
            n = 0
            try:
                n = sum(1 for _ in p.rglob("*") if _.is_file())
            except Exception:
                pass
            if n:
                any_exist = True
                notes.append(f"✓ {rel}({n})")
            else:
                notes.append(f"⚠ {rel}(空)")
    # 全部为空或不存在 → 视为死重信号
    return any_exist, "; ".join(notes)


def audit(traces: List[Trace], home: Optional[str] = None) -> AuditResult:
    """执行静默审计"""
    if not traces:
        return AuditResult()

    span_names, tool_names = collect_evidence(traces)

    # 取最长的 system prompt 作为区块清单基准
    base = max(traces, key=lambda t: len(t.system_prompt))
    system = base.system_prompt
    if not system:
        return AuditResult(trace_count=len(traces))

    sections = split_blocks(system)
    total = len(system)

    blocks: List[BlockResult] = []
    for label, text in sections:
        n = len(text)
        rule = rules.lookup(label)

        if rule is None:
            verdict, evidence, conf, cat, note = VERDICT_MANUAL, "无对应规则", "低", "", ""
        elif rule.probe.kind == "span":
            fired, ev = run_span_probe(rule.probe.needles, span_names, tool_names)
            verdict = VERDICT_KEEP if fired else VERDICT_DROP
            evidence = f"{ev} — {rule.probe.rationale}" if not fired else ev
            conf, cat, note = rule.probe.confidence, rule.category, rule.note
        elif rule.probe.kind == "path":
            ok, ev = run_path_probe(rule.probe.needles, home)
            evidence = ev
            verdict = VERDICT_MANUAL if ok is None else (
                VERDICT_KEEP if ok else VERDICT_DROP)
            conf, cat, note = rule.probe.confidence, rule.category, rule.note
        else:
            verdict, evidence, conf, cat, note = (
                VERDICT_MANUAL, "无行为探针", rule.probe.confidence, rule.category, rule.note)

        blocks.append(BlockResult(
            block=label, chars=n, tokens=n // 4,
            pct=n / total * 100 if total else 0,
            verdict=verdict, evidence=evidence,
            confidence=conf, category=cat, note=note,
        ))

    blocks.sort(key=lambda b: -b.tokens)

    return AuditResult(
        blocks=blocks,
        trace_count=len(traces),
        system_chars=total,
        model=base.model,
        total_input=sum(t.input_tokens for t in traces),
        total_cached=sum(t.cached_tokens for t in traces),
        tool_counts=tool_names,
    )
