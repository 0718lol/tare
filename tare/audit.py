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

# Display labels per language. The internal verdict values stay Chinese so
# that existing JSON consumers and the M0/M1 methodology scripts keep working;
# only the rendered output is translated.
VERDICT_LABELS: Dict[str, Dict[str, str]] = {
    "zh": {VERDICT_KEEP: "保留", VERDICT_DROP: "删除候选", VERDICT_MANUAL: "需人工判断"},
    "en": {VERDICT_KEEP: "keep", VERDICT_DROP: "drop", VERDICT_MANUAL: "review"},
}

# Category labels. Rule tables store the Chinese category so that the M0/M1
# methodology scripts keep matching; display layer translates.
CATEGORY_LABELS: Dict[str, str] = {
    "策略": "policy",
    "行为": "behavior",
    "输出": "output",
    "工具": "tooling",
    "技能": "skills",
    "记忆": "memory",
    "运行时": "runtime",
}

# Text produced by the probe/audit layer also needs translating.
I18N: Dict[str, Dict[str, str]] = {
    "zh": {
        "no_rule": "无对应规则",
        "no_probe": "无行为探针",
        "never_seen": "从未出现",
    },
    "en": {
        "no_rule": "no matching rule",
        "no_probe": "no behavior probe",
        "never_seen": "never observed",
    },
}


def _t(lang: str, key: str) -> str:
    return I18N.get(lang, I18N["en"]).get(key, key)


CONFIDENCE_LABELS: Dict[str, str] = {"高": "high", "中": "medium", "低": "low"}


def _cat(category: str, lang: str) -> str:
    """Translate a category label for display."""
    if lang == "zh" or not category:
        return category
    return CATEGORY_LABELS.get(category, category)


def _conf(confidence: str, lang: str) -> str:
    if lang == "zh" or not confidence:
        return confidence
    return CONFIDENCE_LABELS.get(confidence, confidence)


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


def audit(traces: List[Trace], home: Optional[str] = None,
          lang: str = "en") -> AuditResult:
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
            verdict, evidence, conf, cat, note = (
                VERDICT_MANUAL, _t(lang, "no_rule"), "低", "", "")
        elif rule.probe.kind == "span":
            fired, ev = run_span_probe(rule.probe.needles, span_names, tool_names)
            if fired:
                verdict, evidence = VERDICT_KEEP, ev
            else:
                verdict = VERDICT_DROP
                # The rationale string lives in the rule table and is Chinese.
                # For English output, fall back to the English note (which
                # already says what the block is for) instead of leaking it.
                evidence = _t(lang, "never_seen")
                if lang == "en":
                    if rule.note_en:
                        evidence += f" — {rule.note_en}"
                else:
                    evidence += f" — {rule.probe.rationale}"
            conf, cat, note = rule.probe.confidence, rule.category, rule.note
        elif rule.probe.kind == "path":
            ok, ev = run_path_probe(rule.probe.needles, home)
            evidence = ev
            verdict = VERDICT_MANUAL if ok is None else (
                VERDICT_KEEP if ok else VERDICT_DROP)
            conf, cat, note = rule.probe.confidence, rule.category, rule.note
        else:
            verdict, evidence, conf, cat, note = (
                VERDICT_MANUAL, _t(lang, "no_probe"),
                rule.probe.confidence, rule.category, rule.note)

        disp_note = (rule.note_en or rule.note) if (rule and lang == "en") else note

        blocks.append(BlockResult(
            block=label, chars=n, tokens=n // 4,
            pct=n / total * 100 if total else 0,
            verdict=verdict, evidence=evidence,
            confidence=_conf(conf, lang), category=_cat(cat, lang),
            note=disp_note,
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
