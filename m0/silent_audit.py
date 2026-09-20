"""
tare -- 静默审计器 (Silent Audit)

不跑评测，直接分析已有 session trace，产出：
  1. system prompt 的区块清单 + token 占用
  2. 每个区块的触发判定（是否在会话中被实际消费）
  3. 四象限分类：保留 / 观察 / 高价值 / 删除候选

触发判定启发式（每区块一组探针）：
  - 依赖工具型：区块描述的机制是否真的被调用（如 <instructions_for_visualizer> → show_widget/read_me）
  - 依赖产物型：区块描述的输出是否真的出现（如 <result_presentation> → present_files）
  - 依赖路径型：区块提到的路径/文件是否真实存在（如 skills 目录为空 → 该说明是死重）
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

TRACE_ROOT = Path(os.path.expanduser("~/.workbuddy-ai/traces"))
HOME = Path(os.path.expanduser("~/.workbuddy-ai"))
OUT_DIR = Path(__file__).parent


# ---------------------------------------------------------------- 探针定义
# 每个探针: (区块匹配, 说明, 期望证据, 证据类型)
#   evidence kind: 'span'  = 需要该名称的 span 出现
#                  'path'  = 需要该路径存在且非空
#                  'none'  = 无探针（只能靠人工判断）
PROBES = [
    ("instructions_for_visualizer", "可视化指令",
     ["read_me", "show_widget"], "span",
     "描述 Visualizer 的用法；若从不调用 read_me/show_widget 则未被消费"),
    ("visualizer_examples", "可视化示例",
     ["read_me", "show_widget"], "span",
     "跟随 instructions_for_visualizer；同一组证据"),
    ("result_presentation", "结果呈现",
     ["present_files"], "span",
     "要求用 present_files 交付；无则该约束未生效"),
    ("sharing_files", "文件分享",
     ["present_files"], "span",
     "同上，通常与 result_presentation 同时失效"),
    ("office_skill_routing", "Office 技能路由",
     ["tencent-docs", "Skill"], "span",
     "指向 Word/PPT/Excel 技能路由；观察是否真的触发 Skill"),
    ("plugin_recommendation", "插件推荐",
     ["search_plugins", "suggest_plugin_install"], "span",
     "要求推荐 Connector/Expert；无调用则未被消费"),
    ("expert_management", "专家管理",
     ["expert-manager"], "span",
     "仅在编辑专家包时适用"),
    ("mcp_configuration", "MCP 配置",
     ["mcp__", "ToolSearch"], "span",
     "仅在安装 MCP 时适用"),
    ("automations", "自动化任务",
     ["automation_update"], "span",
     "仅在创建定时任务时适用"),
    ("task_management", "任务管理",
     ["TaskCreate", "TaskUpdate", "TaskList"], "span",
     "要求复杂任务用 Task 工具；观察是否使用"),
    ("asking_questions", "提问澄清",
     ["AskUserQuestion"], "span",
     "要求澄清时用 AskUserQuestion"),
    ("automations_tools", "自动化工具",
     ["automation_update"], "span", ""),
    ("agent_skills", "技能机制",
     ["Skill"], "span",
     "Skill 机制的元指令；观察 Skill 工具是否被调用"),
    ("memory_system", "记忆系统",
     [], "none",
     "记忆三层机制说明；需人工判断注入内容是否被遵循"),
    ("content_policy", "内容策略",
     [], "none", "策略类，无法用行为探针判定"),
    ("personal_files_safety", "个人文件安全",
     [], "none", "策略类"),
    ("capability_constraints", "能力边界",
     [], "none", "策略类"),
    ("response_language", "响应语言",
     [], "none", "策略类"),
    ("binary_context", "运行时上下文",
     [], "path",
     "声称的 Python/Node 路径是否真实存在"),
    ("final_answer_instructions", "最终答复指令",
     [], "none", "输出规范，难以客观判定"),
    ("agent_loop", "代理循环",
     [], "none", "核心行为定义"),
    ("tool_use", "工具使用",
     [], "none", "核心行为定义"),
    ("working_modes", "工作模式",
     [], "none", "核心行为定义"),
]


def load_traces():
    traces = []
    for p in sorted(TRACE_ROOT.rglob("trace_*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            if "trace" in d:
                traces.append(d)
        except Exception:
            pass
    return traces


def block_text(b):
    c = b.get("content")
    if isinstance(c, list):
        return "".join(x.get("text", "") for x in c if isinstance(x, dict))
    return c or ""


def split_system_blocks(text):
    """按顶层 xml 标签 / md 一级标题切分 system prompt"""
    pat = re.compile(r"^(<([a-z_]{3,45})>|#{1,2}\s+(.+))", re.MULTILINE)
    marks = [(m.start(), m.group(2) or m.group(3), m.group(0).strip()) for m in pat.finditer(text)]
    if not marks:
        return [("(preamble)", text)]
    out = []
    if marks[0][0] > 0:
        out.append(("(preamble)", text[:marks[0][0]]))
    for i, (pos, label, raw) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        out.append((label, text[pos:end]))
    return out


def probe_span(needles, span_names, tool_names):
    """检查是否需要探针的 span/tool 出现过"""
    for n in needles:
        for name, cnt in span_names.items():
            if n.lower() in name.lower():
                return True, f"{name} ×{cnt}"
        for name, cnt in tool_names.items():
            if n.lower() in name.lower():
                return True, f"{name} ×{cnt}"
    return False, "从未出现"


def probe_path(label):
    """检查该区块声称的路径是否真实存在且非空（结构性死重探测）"""
    checks = {
        "binary_context": [(HOME / "binaries" / "python", "python"), (HOME / "binaries" / "node", "node")],
        "agent_skills": [(HOME / "skills", "用户技能目录"), (Path.cwd() / ".workbuddy-ai" / "skills", "项目技能目录")],
        "memory_system": [(HOME / "memory", "用户记忆"), (Path.cwd() / ".workbuddy-ai" / "memory", "项目记忆")],
        "automations": [(HOME / "sessions", "会话目录")],
    }
    if label not in checks:
        return None, ""
    notes = []
    for p, desc in checks[label]:
        if not p.exists():
            notes.append(f"❌{desc}不存在")
        else:
            try:
                n = sum(1 for _ in p.rglob("*") if _.is_file())
                notes.append(f"{'✅' if n else '⚠️空'} {desc}: {n}文件")
            except Exception:
                notes.append(f"? {desc}: 无法读取")
    return None, "; ".join(notes)


def main():
    print("=" * 78)
    print("tare — 静默审计 (Silent Audit)")
    print("=" * 78)
    print(f"数据源: {TRACE_ROOT}")

    traces = load_traces()
    print(f"trace 数: {len(traces)}")
    if not traces:
        return

    # --- 收集全量 span / tool 证据 ---
    span_names = Counter()
    tool_names = Counter()
    for d in traces:
        for s in d.get("spans", []):
            span_names[s.get("name")] += 1
            if s.get("type") == "function" and s.get("toolName"):
                tool_names[s["toolName"]] += 1
            if s.get("name") == "Skill" and s.get("toolInput"):
                try:
                    ti = json.loads(s["toolInput"])
                    if isinstance(ti, dict) and ti.get("skill"):
                        tool_names[ti["skill"]] += 1
                except Exception:
                    pass

    # --- 取最大的一次 system prompt 作为区块清单基准 ---
    best_text, best_tid, best_blocks = "", None, []
    for d in traces:
        for s in d.get("spans", []):
            if s.get("type") != "generation":
                continue
            try:
                blocks = json.loads(s.get("toolInput") or "[]")
            except Exception:
                continue
            for b in blocks:
                if b.get("role") != "system":
                    continue
                t = block_text(b)
                if len(t) > len(best_text):
                    best_text, best_tid, best_blocks = t, d["trace"].get("traceId"), blocks
            if best_text:
                break
        if best_text:
            break

    if not best_text:
        print("未找到 system prompt")
        return

    sections = split_system_blocks(best_text)
    total_chars = len(best_text)
    print(f"\nsystem prompt: {total_chars:,} chars ≈ {total_chars//4:,} tok")
    print(f"切出 {len(sections)} 个区块 (trace {best_tid})\n")

    # --- 审计每个区块 ---
    rows = []
    for label, text in sections:
        n = len(text)
        probe = next((p for p in PROBES if p[0] == label), None)
        if probe:
            _, desc, needles, kind, note = probe
            if kind == "span" and needles:
                fired, ev = probe_span(needles, span_names, tool_names)
                evidence = ev
                confidence = "中" if fired else "中"
                verdict = "保留" if fired else "删除候选"
            elif kind == "path":
                _, ev = probe_path(label)
                evidence = ev or "无路径探针"
                verdict = "需人工"
                confidence = "低"
            else:
                evidence = "无行为探针"
                verdict = "需人工"
                confidence = "低"
            purpose = note
        else:
            evidence = "未定义探针"
            verdict = "需人工"
            confidence = "低"
            purpose = ""

        rows.append({
            "block": label,
            "chars": n,
            "tokens": n // 4,
            "pct": n / total_chars * 100,
            "verdict": verdict,
            "evidence": evidence,
            "confidence": confidence,
            "purpose": purpose,
        })

    rows.sort(key=lambda r: -r["tokens"])

    # --- 输出表格 ---
    print(f"{'区块':<34}{'tok':>7}{'占比':>7}  {'判定':<10}{'证据'}")
    print("-" * 78)
    for r in rows:
        print(f"{r['block']:<34}{r['tokens']:>7,}{r['pct']:>6.1f}%  "
              f"{r['verdict']:<10}{r['evidence']}")

    # --- 分类汇总 ---
    print("\n" + "=" * 78)
    print("四象限分类")
    print("=" * 78)
    quad = defaultdict(lambda: {"n": 0, "tok": 0, "items": []})
    for r in rows:
        if r["verdict"] == "删除候选":
            q = "🔥 删除候选（未观察到被消费）"
        elif r["verdict"] == "保留":
            q = "✅ 保留（观察到被消费）"
        else:
            q = "❓ 需人工判断（无行为探针）"
        quad[q]["n"] += 1
        quad[q]["tok"] += r["tokens"]
        quad[q]["items"].append(r["block"])

    for q in ["🔥 删除候选（未观察到被消费）", "✅ 保留（观察到被消费）", "❓ 需人工判断（无行为探针）"]:
        if q not in quad:
            continue
        v = quad[q]
        print(f"\n{q}")
        print(f"  {v['n']} 个区块，合计 {v['tok']:,} tok（占 system {v['tok']/ (total_chars//4) *100:.1f}%）")
        for it in v["items"]:
            print(f"    · {it}")

    # --- 探针命中率 ---
    print("\n" + "=" * 78)
    print("工具调用证据（判定依据）")
    print("=" * 78)
    for k, v in tool_names.most_common(25):
        print(f"  {k:<28} {v}")

    # --- 写报告 ---
    with open(OUT_DIR / "audit_result.json", "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "trace_count": len(traces),
            "system_prompt_chars": total_chars,
            "block_count": len(sections),
            "rows": rows,
            "tool_names": dict(tool_names),
            "span_names": dict(span_names),
        }, f, ensure_ascii=False, indent=2)

    gen_report(rows, quad, total_chars, len(traces), tool_names)
    print(f"\n结果已写入: {OUT_DIR/'audit_result.json'}")
    print(f"报告已写入: {OUT_DIR/'SILENT_AUDIT.md'}")


def gen_report(rows, quad, total_chars, n_traces, tool_names):
    total_tok = total_chars // 4
    L = []
    A = L.append
    A("# tare 静默审计报告")
    A("")
    A(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    A(f"> 数据源：{n_traces} 条 WorkBuddy trace")
    A(f"> 审计对象：system prompt 的 {len(rows)} 个顶层区块，"
      f"合计 {total_chars:,} chars ≈ {total_tok:,} tok")
    A("")
    A("---")
    A("")
    A("## 0. 核心结论")
    A("")
    q_fire = quad.get("🔥 删除候选（未观察到被消费）", {"n": 0, "tok": 0})
    q_keep = quad.get("✅ 保留（观察到被消费）", {"n": 0, "tok": 0})
    q_man = quad.get("❓ 需人工判断（无行为探针）", {"n": 0, "tok": 0})
    A(f"| 分类 | 区块数 | token | 占 system |")
    A(f"|---|---|---|---|")
    A(f"| 🔥 删除候选 | {q_fire['n']} | {q_fire['tok']:,} | {q_fire['tok']/total_tok*100:.1f}% |")
    A(f"| ✅ 保留 | {q_keep['n']} | {q_keep['tok']:,} | {q_keep['tok']/total_tok*100:.1f}% |")
    A(f"| ❓ 需人工 | {q_man['n']} | {q_man['tok']:,} | {q_man['tok']/total_tok*100:.1f}% |")
    A("")
    A(f"**潜在可回收：{q_fire['tok']:,} tok（{q_fire['tok']/total_tok*100:.1f}% 的 system prompt）**")
    A("")
    A("---")
    A("")
    A("## 1. 区块明细")
    A("")
    A("| 区块 | tokens | 占比 | 判定 | 证据 | 说明 |")
    A("|---|---:|---:|---|---|---|")
    for r in rows:
        A(f"| `{r['block']}` | {r['tokens']:,} | {r['pct']:.1f}% | {r['verdict']} | "
          f"{r['evidence']} | {r['purpose']} |")
    A("")
    A("---")
    A("")
    A("## 2. 🔥 删除候选明细")
    A("")
    for name in quad.get("🔥 删除候选（未观察到被消费）", {}).get("items", []):
        r = next(x for x in rows if x["block"] == name)
        A(f"### `{name}` — {r['tokens']:,} tok ({r['pct']:.1f}%)")
        A("")
        A(f"- **证据**：{r['evidence']}")
        A(f"- **说明**：{r['purpose']}")
        A(f"- **置信度**：{r['confidence']}")
        A("")
    A("---")
    A("")
    A("## 3. 工具调用证据")
    A("")
    A("| 工具 | 调用次数 |")
    A("|---|---:|")
    for k, v in sorted(tool_names.items(), key=lambda x: -x[1])[:30]:
        A(f"| `{k}` | {v} |")
    A("")
    A("---")
    A("")
    A("## 4. 方法与局限")
    A("")
    A("### 判定方法")
    A("")
    A("采用**行为探针**：对每个区块，检查它所描述的机制是否在会话中被实际调用。")
    A("例如 `<instructions_for_visualizer>` 描述了 Visualizer 用法，")
    A("则探针为「`read_me` / `show_widget` 是否出现」。若从未出现，则该区块未被消费。")
    A("")
    A("### 局限（重要）")
    A("")
    A("1. **「未观察到」≠「无用」**。本审计基于有限的 trace 样本。")
    A("   区块可能只是**当前样本未覆盖**该场景，而非真的无用。")
    A("2. **无行为探针的区块占了很大比例**（需人工判断类）。")
    A("   这些是策略类/输出规范类区块，其价值无法用「是否被调用」衡量。")
    A("3. **触发 ≠ 有效**。区块被消费，不代表它产生了正收益 —— ")
    A("   那需要**主动消融实验**才能确定。静默审计只能做到「发现从未被触及的死重」。")
    A("")
    A("### 因此，静默审计的定位")
    A("")
    A("> 它**不是**结论，而是**假设生成器**。")
    A("> 它低成本地把候选集从「37 个区块」缩小到「少数几个值得做消融实验的目标」。")
    A("")
    A("下一步：对 🔥 象限的区块做主动消融，用可验证任务测 ΔS。")
    A("")

    with open(OUT_DIR / "SILENT_AUDIT.md", "w", encoding="utf-8") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()
