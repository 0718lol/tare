"""
tare.adapters — harness 适配层

把不同 harness 的运行记录归一化成 tare 能理解的统一结构：

    Trace:
      id, status, model, tokens, calls
      spans: [Span(name, type, tool_name, tool_input, status)]
      system_prompt: str
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Span:
    name: str
    type: str
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None
    status: str = "ok"
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Trace:
    id: str
    status: str = "unknown"
    model: Optional[str] = None
    calls: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    spans: List[Span] = field(default_factory=list)
    system_prompt: str = ""

    # ---- 派生指标 ----
    @property
    def hit_rate(self) -> float:
        return self.cached_tokens / self.input_tokens if self.input_tokens else 0.0

    @property
    def success(self) -> int:
        return 1 if self.status == "ok" else 0

    @property
    def tool_calls(self) -> List[Span]:
        return [s for s in self.spans if s.type == "function"]

    @property
    def tool_error_rate(self) -> float:
        fn = self.tool_calls
        if not fn:
            return 0.0
        return sum(1 for s in fn if s.status == "error") / len(fn)

    @property
    def tool_repeat_rate(self) -> float:
        seq = [s.tool_name for s in self.tool_calls if s.tool_name]
        if len(seq) < 2:
            return 0.0
        return sum(1 for i in range(1, len(seq)) if seq[i] == seq[i - 1]) / len(seq)


class Adapter:
    """适配器基类"""

    name = "base"

    def discover(self) -> List[str]:
        """返回可用 trace 的标识列表"""
        raise NotImplementedError

    def load(self, ident: str) -> Trace:
        raise NotImplementedError

    def home(self) -> Optional[str]:
        return None


class WorkBuddyAdapter(Adapter):
    """
    WorkBuddy 适配器

    读取 ~/.workbuddy-ai/traces/**/trace_*.json
    结构：
      { "trace": {traceId, status, modelInfo:{models,totalInputTokens,...}},
        "spans": [{name, type, toolName, toolInput, status}] }
    """
    name = "workbuddy"

    def __init__(self, root: str):
        import os
        from pathlib import Path
        p = Path(os.path.expanduser(root))
        self.root = p
        self.model_home = p.parent

    def discover(self) -> List[str]:
        if not self.root.exists():
            return []
        return sorted(str(p) for p in self.root.rglob("trace_*.json"))

    def load(self, ident: str) -> Trace:
        import json
        from pathlib import Path
        with open(Path(ident), encoding="utf-8") as f:
            d = json.load(f)
        t = d.get("trace", {})
        mi = t.get("modelInfo") or {}
        models = mi.get("models") or []
        spans = [
            Span(
                name=s.get("name") or "",
                type=s.get("type") or "",
                tool_name=s.get("toolName"),
                tool_input=s.get("toolInput"),
                status=s.get("status") or "ok",
                raw=s,
            )
            for s in d.get("spans", [])
        ]
        return Trace(
            id=t.get("traceId") or ident,
            status=t.get("status") or "unknown",
            model=models[0] if models else None,
            calls=mi.get("callCount", 0),
            input_tokens=mi.get("totalInputTokens", 0),
            cached_tokens=mi.get("totalCachedTokens", 0),
            output_tokens=mi.get("totalOutputTokens", 0),
            duration_ms=t.get("duration", 0),
            spans=spans,
            system_prompt=extract_system_prompt(spans),
        )

    def home(self) -> Optional[str]:
        return str(self.model_home)


class GenericJSONAdapter(Adapter):
    """
    通用适配器：接受一个目录，内含符合 tare schema 的 json。
    schema:
      {"trace": {"traceId":..., "status":..., "modelInfo":{...}},
       "spans": [{"name":..., "type":..., "toolName":..., "toolInput":...}]}
    与 WorkBuddy 结构一致，便于接入其它 harness。
    """
    name = "generic"

    def __init__(self, root: str):
        from pathlib import Path
        import os
        self.root = Path(os.path.expanduser(root))

    def discover(self) -> List[str]:
        if not self.root.exists():
            return []
        return sorted(str(p) for p in self.root.rglob("*.json"))

    def load(self, ident: str) -> Trace:
        return WorkBuddyAdapter(self.root).load(ident)


def extract_system_prompt(spans: List[Span]) -> str:
    """从 generation span 里提取最长的 system prompt"""
    import json
    best = ""
    for s in spans:
        if s.type != "generation" or not s.tool_input:
            continue
        try:
            blocks = json.loads(s.tool_input)
        except Exception:
            continue
        if not isinstance(blocks, list):
            continue
        for b in blocks:
            if not isinstance(b, dict) or b.get("role") != "system":
                continue
            c = b.get("content")
            if isinstance(c, list):
                text = "".join(x.get("text", "") for x in c if isinstance(x, dict))
            else:
                text = c or ""
            if len(text) > len(best):
                best = text
    return best


def get_adapter(name: str, root: str) -> Adapter:
    if name == "workbuddy":
        return WorkBuddyAdapter(root)
    if name == "generic":
        return GenericJSONAdapter(root)
    raise ValueError(f"未知适配器: {name}")
