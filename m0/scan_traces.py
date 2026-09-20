"""
tare M0 — WorkBuddy trace 解析器
扫描 ~/.workbuddy-ai/traces 下的所有 trace，回答 M0 的核心问题：
  1. 缓存命中率如何？（成本模型基础）
  2. 上下文由哪些层构成？各占多少 token？
  3. skill / rule / hook / tool 分别注入到哪一层？（决定消融调度策略）
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

TRACE_ROOT = Path(os.path.expanduser("~/.workbuddy-ai/traces"))
OUT = Path(__file__).parent / "scan_result.json"


def load_traces():
    traces = []
    for p in sorted(TRACE_ROOT.rglob("trace_*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            if "trace" in d:
                d["_path"] = str(p)
                traces.append(d)
        except Exception as e:
            print(f"  ! skip {p.name}: {e}", file=sys.stderr)
    return traces


def analyze_model_info(traces):
    """缓存成本模型基础数据"""
    rows = []
    for d in traces:
        t = d["trace"]
        mi = t.get("modelInfo") or {}
        inp = mi.get("totalInputTokens", 0)
        cached = mi.get("totalCachedTokens", 0)
        out = mi.get("totalOutputTokens", 0)
        if not inp:
            continue
        rows.append({
            "traceId": t.get("traceId"),
            "sessionId": t.get("sessionId"),
            "models": mi.get("models"),
            "callCount": mi.get("callCount", 0),
            "input": inp,
            "cached": cached,
            "output": out,
            "hitRate": cached / inp if inp else 0,
            "status": t.get("status"),
            "duration": t.get("duration"),
            "spanCount": t.get("spanCount", 0),
            "startedAt": t.get("startedAt"),
        })
    return rows


def analyze_spans(traces):
    """span 名称 / 类型分布"""
    names = Counter()
    types = Counter()
    tools = Counter()
    for d in traces:
        for s in d.get("spans", []):
            names[s.get("name")] += 1
            types[s.get("type")] += 1
            if s.get("type") == "function" and s.get("toolName"):
                tools[s["toolName"]] += 1
    return names, types, tools


SECTION_RE = re.compile(
    r"^[ \t]*(?:#{1,4}[ \t]+|<([a-z_\-]+)>|(\[?[A-Z][A-Za-z \-]{2,60}\]?)[ \t]*$)",
    re.MULTILINE,
)


def extract_prompt_skeleton(traces, max_prompts=3):
    """
    从 generation span 的 toolInput 里提取实际注入的 system prompt，
    识别出顶层分节 —— 这些分节就是可消融的 harness 组件单元。
    """
    results = []
    for d in traces:
        for s in d.get("spans", []):
            if s.get("type") != "generation":
                continue
            raw = s.get("toolInput")
            if not raw:
                continue
            try:
                blocks = json.loads(raw)
            except Exception:
                continue
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                content = b.get("content")
                if not isinstance(content, str) or len(content) < 3000:
                    continue
                # 找出顶层分节标题
                heads = []
                for line in content.split("\n"):
                    ls = line.strip()
                    if not ls:
                        continue
                    if re.match(r"^#{1,4}\s+\S", ls):
                        heads.append(("md_heading", ls[:110]))
                    elif re.match(r"^<[a-z_\-]{2,40}>$", ls):
                        heads.append(("xml_tag", ls))
                results.append({
                    "traceId": d["trace"].get("traceId"),
                    "spanId": s.get("spanId"),
                    "chars": len(content),
                    "est_tokens": len(content) // 4,
                    "sections": heads,
                    "head": content[:200],
                })
                if len(results) >= max_prompts:
                    return results
    return results


def main():
    print("=" * 70)
    print("tare M0 — WorkBuddy trace 扫描")
    print("=" * 70)

    traces = load_traces()
    print(f"\n加载 trace 数: {len(traces)}")
    if not traces:
        print("未找到 trace，请确认路径:", TRACE_ROOT)
        return

    # --- 1. 缓存模型 ---
    rows = analyze_model_info(traces)
    print(f"\n[1] 模型与缓存（{len(rows)} 条有效记录）")
    print("-" * 70)
    if rows:
        tot_in = sum(r["input"] for r in rows)
        tot_cached = sum(r["cached"] for r in rows)
        tot_out = sum(r["output"] for r in rows)
        print(f"  合计 input : {tot_in:,}")
        print(f"  合计 cached: {tot_cached:,}")
        print(f"  合计 output: {tot_out:,}")
        print(f"  ★ 总缓存命中率: {tot_cached/tot_in*100:.1f}%" if tot_in else "")
        print()
        all_models = Counter()
        for r in rows:
            for m in (r["models"] or ["<unknown>"]):
                all_models[m] += 1
        print(f"  使用模型: {dict(all_models)}")
        print()
        print("  逐条明细（按 token 降序）:")
        for r in sorted(rows, key=lambda x: -x["input"])[:12]:
            print(f"    {r['traceId'][:22]} calls={r['callCount']:>3} "
                  f"in={r['input']:>9,} hit={r['hitRate']*100:>5.1f}% "
                  f"out={r['output']:>7,} {r['status']}")

    # --- 2. span 分布 ---
    names, types, tools = analyze_spans(traces)
    print(f"\n[2] Span 分布")
    print("-" * 70)
    print(f"  按类型: {dict(types)}")
    print(f"  按名称 (top 15): {dict(names.most_common(15))}")
    if tools:
        print(f"  工具调用 (top 15): {dict(tools.most_common(15))}")

    # --- 3. 上下文分层 ---
    print(f"\n[3] 注入的 system prompt 结构（M0 核心问题）")
    print("-" * 70)
    sk = extract_prompt_skeleton(traces)
    for i, r in enumerate(sk, 1):
        print(f"\n  --- prompt #{i} ({r['chars']:,} chars ≈ {r['est_tokens']:,} tok) ---")
        print(f"  trace: {r['traceId']}")
        print(f"  开头: {r['head'][:110]!r}")
        print(f"  检出顶层分节 {len(r['sections'])} 个:")
        for kind, txt in r["sections"][:40]:
            print(f"    [{kind:11s}] {txt}")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({
            "trace_count": len(traces),
            "model_info": rows,
            "span_names": dict(names),
            "span_types": dict(types),
            "tools": dict(tools),
            "prompt_skeletons": sk,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n结果已写入: {OUT}")


if __name__ == "__main__":
    main()
