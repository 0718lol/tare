"""
tare M1 — 消融分析器 (Ablation Analyzer)

用已有 trace 做「自然实验」：
  WorkBuddy 的 trace 里已经包含了各种真实会话，每个会话实际触发了不同的区块组合。
  通过关联分析「哪些区块被触发 vs 会话的成功指标」，可以得到区块的**相关性信号**。

同时提供主动消融的实验框架（需 API key 时启用）。

产出：
  1. 区块 × 会话的触发矩阵
  2. 区块与成功指标（status / 工具成功率 / 重试率）的关联
  3. 消融实验的 run plan（供 API 执行）
"""
import json
import os
import re
import sys
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

TRACE_ROOT = Path(os.path.expanduser("~/.workbuddy-ai/traces"))
OUT_DIR = Path(__file__).parent

# 区块 → 行为探针（与 silent_audit 一致）
BLOCK_PROBES = {
    "automations": ["automation_update"],
    "plugin_recommendation": ["search_plugins", "suggest_plugin_install"],
    "mcp_configuration": ["mcp__", "ToolSearch"],
    "task_management": ["TaskCreate", "TaskUpdate", "TaskList"],
    "expert_management": ["expert-manager"],
    "agent_skills": ["Skill"],
    "asking_questions": ["AskUserQuestion"],
    "result_presentation": ["present_files"],
    "sharing_files": ["present_files"],
    "instructions_for_visualizer": ["read_me", "show_widget"],
    "visualizer_examples": ["read_me", "show_widget"],
    "office_skill_routing": ["Skill"],
    "memory_system": ["conversation_search"],
}


def load_traces():
    out = []
    for p in sorted(TRACE_ROOT.rglob("trace_*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            if "trace" in d:
                d["_path"] = str(p)
                out.append(d)
        except Exception:
            pass
    return out


def session_metrics(d):
    """从一条 trace 提取会话级质量指标"""
    t = d["trace"]
    spans = d.get("spans", [])
    mi = t.get("modelInfo") or {}

    fn = [s for s in spans if s.get("type") == "function"]
    gen = [s for s in spans if s.get("type") == "generation"]

    err_spans = [s for s in spans if s.get("status") == "error"]
    err_tools = [s for s in fn if s.get("status") == "error"]

    # 重复探测：同一工具被反复调用（探索效率低的信号）
    tool_seq = [s.get("toolName") for s in fn if s.get("toolName")]
    repeats = sum(1 for i in range(1, len(tool_seq)) if tool_seq[i] == tool_seq[i - 1])

    inp = mi.get("totalInputTokens", 0)
    cached = mi.get("totalCachedTokens", 0)
    out_tok = mi.get("totalOutputTokens", 0)

    return {
        "traceId": t.get("traceId"),
        "status": t.get("status"),
        "success": 1 if t.get("status") == "ok" else 0,
        "callCount": mi.get("callCount", 0),
        "input": inp,
        "cached": cached,
        "output": out_tok,
        "hitRate": cached / inp if inp else 0,
        "n_spans": len(spans),
        "n_fn": len(fn),
        "n_gen": len(gen),
        "n_err": len(err_spans),
        "n_err_tool": len(err_tools),
        "tool_error_rate": len(err_tools) / len(fn) if fn else 0,
        "tool_repeat_rate": repeats / len(tool_seq) if len(tool_seq) > 1 else 0,
        "distinct_tools": len(set(tool_seq)),
        "duration": t.get("duration", 0),
        "tokens_per_call": inp / mi.get("callCount", 1) if mi.get("callCount") else 0,
    }


def block_triggered(d, needles):
    """该 trace 是否触发了这些探针"""
    for s in d.get("spans", []):
        name = s.get("name") or ""
        tname = s.get("toolName") or ""
        for n in needles:
            if n.lower() in name.lower() or n.lower() in tname.lower():
                return True
    return False


def bootstrap_ci(vals, n_boot=2000, alpha=0.05):
    import random
    if len(vals) < 3:
        return None
    random.seed(42)
    means = []
    for _ in range(n_boot):
        sample = [random.choice(vals) for _ in vals]
        means.append(sum(sample) / len(sample))
    means.sort()
    lo = means[int(len(means) * alpha / 2)]
    hi = means[int(len(means) * (1 - alpha / 2))]
    return lo, hi


def cohens_d(a, b):
    """效应量"""
    if len(a) < 2 or len(b) < 2:
        return None
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va = sum((x - ma) ** 2 for x in a) / (len(a) - 1)
    vb = sum((x - mb) ** 2 for x in b) / (len(b) - 1)
    sd = math.sqrt((va + vb) / 2)
    if sd == 0:
        return None
    return (ma - mb) / sd


def mann_whitney_p(a, b):
    """近似的 Mann-Whitney U 检验 p 值（正态近似）"""
    n1, n2 = len(a), len(b)
    if n1 < 3 or n2 < 3:
        return None
    combined = [(v, 0) for v in a] + [(v, 1) for v in b]
    combined.sort()
    # 秩
    ranks = {}
    i = 0
    while i < len(combined):
        j = i
        while j + 1 < len(combined) and combined[j + 1][0] == combined[i][0]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[k] = avg_rank
        i = j + 1
    r1 = sum(ranks[k] for k in range(len(combined)) if combined[k][1] == 0)
    u1 = r1 - n1 * (n1 + 1) / 2
    mu = n1 * n2 / 2
    sigma = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    if sigma == 0:
        return None
    z = (u1 - mu) / sigma
    # 双尾 p
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return p


def main():
    print("=" * 78)
    print("tare M1 — 消融分析（基于 trace 的自然实验）")
    print("=" * 78)

    traces = load_traces()
    print(f"trace 数: {len(traces)}\n")
    if not traces:
        return

    metrics = [session_metrics(d) for d in traces]

    # --- 1. 会话质量概览 ---
    print("[1] 会话质量概览")
    print("-" * 78)
    n_ok = sum(m["success"] for m in metrics)
    print(f"  成功会话: {n_ok}/{len(metrics)} ({n_ok/len(metrics)*100:.1f}%)")
    avg = lambda k: sum(m[k] for m in metrics) / len(metrics)
    print(f"  平均 calls     : {avg('callCount'):.1f}")
    print(f"  平均 spans     : {avg('n_spans'):.1f}")
    print(f"  平均工具调用   : {avg('n_fn'):.1f}")
    print(f"  平均工具错误率 : {avg('tool_error_rate')*100:.1f}%")
    print(f"  平均工具重复率 : {avg('tool_repeat_rate')*100:.1f}%")
    print(f"  平均缓存命中率 : {avg('hitRate')*100:.1f}%")

    # --- 2. 区块触发矩阵 ---
    print(f"\n[2] 区块触发矩阵（{len(BLOCK_PROBES)} 个可探针区块）")
    print("-" * 78)
    trig = {}
    for blk, needles in BLOCK_PROBES.items():
        hits = [i for i, d in enumerate(traces) if block_triggered(d, needles)]
        trig[blk] = hits

    print(f"  {'区块':<32}{'触发会话':>8}{'占比':>8}  {'判定'}")
    for blk, hits in sorted(trig.items(), key=lambda x: -len(x[1])):
        pct = len(hits) / len(traces) * 100
        verdict = "✅ 有证据" if hits else "🔥 零触发"
        print(f"  {blk:<32}{len(hits):>8}{pct:>7.1f}%  {verdict}")

    # --- 3. 关联分析：区块触发 vs 会话指标 ---
    print(f"\n[3] 关联分析（触发组 vs 未触发组）")
    print("-" * 78)
    print(f"  说明：样本量小（{len(traces)} 条），以下为**探索性**信号，非结论。\n")

    results = []
    for blk, hits in trig.items():
        if not hits or len(hits) == len(traces):
            continue  # 全有或全无，无法比较
        in_g = [metrics[i] for i in hits]
        out_g = [metrics[i] for i in range(len(traces)) if i not in hits]
        for metric in ["success", "tool_error_rate", "tool_repeat_rate", "n_fn", "tokens_per_call"]:
            a = [m[metric] for m in in_g]
            b = [m[metric] for m in out_g]
            d = cohens_d(a, b)
            p = mann_whitney_p(a, b)
            if d is None:
                continue
            results.append({
                "block": blk,
                "metric": metric,
                "n_in": len(a),
                "n_out": len(b),
                "mean_in": sum(a) / len(a),
                "mean_out": sum(b) / len(b),
                "d": d,
                "p": p,
            })

    results.sort(key=lambda r: -abs(r["d"]))
    print(f"  {'区块':<28}{'指标':<20}{'触发组':>10}{'未触发':>10}{'d':>8}{'p':>8}")
    print("  " + "-" * 82)
    for r in results[:20]:
        star = "*" if (r["p"] is not None and r["p"] < 0.1) else " "
        print(f"  {r['block']:<28}{r['metric']:<20}"
              f"{r['mean_in']:>10.4f}{r['mean_out']:>10.4f}"
              f"{r['d']:>8.2f}{(r['p'] if r['p'] is not None else -1):>8.3f}{star}")

    # --- 4. 生成 run plan ---
    print(f"\n[4] 主动消融 run plan")
    print("-" * 78)
    targets = [b for b, h in trig.items()]
    tasks_per_block = 3
    k = 5
    n_runs = (1 + len(targets)) * tasks_per_block * k
    print(f"  待测区块      : {len(targets)}")
    print(f"  每区块任务数  : {tasks_per_block}")
    print(f"  重复轮数 k    : {k}")
    print(f"  总 runs       : {n_runs}")
    print(f"  预估成本      : ${n_runs * 0.00122:.2f} (deepseek-flash off-peak)")

    run_plan = {
        "targets": targets,
        "tasks_per_block": tasks_per_block,
        "k": k,
        "total_runs": n_runs,
        "est_cost_usd": round(n_runs * 0.00122, 4),
        "configs": [{"name": "full", "ablate": []}] +
                   [{"name": f"-{b}", "ablate": [b]} for b in targets],
    }

    with open(OUT_DIR / "ablation_result.json", "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "n_traces": len(traces),
            "metrics": metrics,
            "triggers": {k: v for k, v in trig.items()},
            "associations": results,
            "run_plan": run_plan,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n结果已写入: {OUT_DIR/'ablation_result.json'}")
    return metrics, trig, results, run_plan


if __name__ == "__main__":
    main()
