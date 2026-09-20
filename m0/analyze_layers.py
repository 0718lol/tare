"""
tare M0 — 上下文分层精算
从 generation span 的 toolInput 中逐块还原真实请求结构，
回答：tools / system / messages 各占多少 token，skill 如何注入。
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

TRACE_ROOT = Path(os.path.expanduser("~/.workbuddy-ai/traces"))
OUT = Path(__file__).parent / "layer_result.json"

# <agent_skills> 区块里的 skill 条目样式
SKILL_LINE = re.compile(r"^-\s+([a-z0-9_\-]+):\s*(.+)$", re.MULTILINE)


def iter_generations(traces):
    for d in traces:
        for s in d.get("spans", []):
            if s.get("type") == "generation":
                yield d, s


def parse_blocks(span):
    raw = span.get("toolInput")
    if not raw:
        return None
    try:
        blocks = json.loads(raw)
    except Exception:
        return None
    return blocks if isinstance(blocks, list) else None


def classify_block(b):
    """判定一个 content block 属于哪一层"""
    if not isinstance(b, dict):
        return "unknown", 0
    role = b.get("role")
    content = b.get("content")
    if isinstance(content, list):
        text = "".join(c.get("text", "") for c in content if isinstance(c, dict))
    else:
        text = content or ""
    n = len(text)
    if role == "system":
        return "system", n
    if role == "user":
        return "messages.user", n
    if role == "assistant":
        return "messages.assistant", n
    if role in ("tool", "tool_result"):
        return "messages.tool_result", n
    return f"other:{role}", n


def main():
    print("=" * 72)
    print("tare M0 — 上下文分层精算")
    print("=" * 72)

    traces = []
    for p in sorted(TRACE_ROOT.rglob("trace_*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            if "trace" in d:
                traces.append(d)
        except Exception:
            pass

    # 找 token 最大的那次 generation 做详细拆解
    cands = []
    for d, s in iter_generations(traces):
        blocks = parse_blocks(s)
        if not blocks:
            continue
        total_chars = 0
        for b in blocks:
            c = b.get("content")
            if isinstance(c, list):
                total_chars += sum(len(x.get("text", "")) for x in c if isinstance(x, dict))
            elif isinstance(c, str):
                total_chars += len(c)
        cands.append((total_chars, d, s, blocks))

    cands.sort(key=lambda x: -x[0])
    print(f"\n可解析的 generation span: {len(cands)} 个")

    if not cands:
        print("无可用数据")
        return

    print(f"\n[1] 最大请求的分层拆解 (top 5)")
    print("-" * 72)
    layer_totals = defaultdict(int)
    for chars, d, s, blocks in cands[:5]:
        tiers = Counter()
        for b in blocks:
            tier, n = classify_block(b)
            tiers[tier] += n
        print(f"\n  trace={d['trace'].get('traceId')[:20]} span={s.get('spanId')}")
        print(f"  总 {chars:,} chars ≈ {chars//4:,} tok，{len(blocks)} 个 block")
        for t, n in tiers.most_common():
            pct = n / chars * 100 if chars else 0
            print(f"    {t:24s} {n:>8,} chars  {pct:>5.1f}%  ≈{n//4:>7,} tok")
            layer_totals[t] += n

    print(f"\n[2] 全部 generation 的层占比汇总")
    print("-" * 72)
    grand = sum(layer_totals.values())
    for t, n in sorted(layer_totals.items(), key=lambda x: -x[1]):
        print(f"  {t:24s} {n:>12,} chars  {n/grand*100:>5.1f}%  ≈{n//4:>10,} tok")

    # --- skill 注入方式：这是 M0 最关键的问题 ---
    print(f"\n[3] ★ skill 注入方式判定（决定消融策略）")
    print("-" * 72)
    skill_evidence = []
    for chars, d, s, blocks in cands[:10]:
        for b in blocks:
            c = b.get("content")
            if isinstance(c, list):
                text = "".join(x.get("text", "") for x in c if isinstance(x, dict))
            else:
                text = c or ""
            m = re.search(r"<agent_skills>(.*?)</agent_skills>", text, re.DOTALL)
            if m:
                body = m.group(1)
                skills = SKILL_LINE.findall(body)
                skill_evidence.append({
                    "traceId": d["trace"].get("traceId"),
                    "role": b.get("role"),
                    "agent_skills_chars": len(body),
                    "skill_entries": len(skills),
                    "sample": [(n, desc[:70]) for n, desc in skills[:8]],
                })
                break
        if skill_evidence:
            break

    if skill_evidence:
        e = skill_evidence[0]
        print(f"  找到 <agent_skills> 区块")
        print(f"  所在层          : {e['role']}  ← 关键！")
        print(f"  该区块大小      : {e['agent_skills_chars']:,} chars ≈ {e['agent_skills_chars']//4:,} tok")
        print(f"  列出的 skill 数 : {e['skill_entries']}")
        print(f"  样例:")
        for n, desc in e["sample"]:
            print(f"    - {n}: {desc}")
        print()
        if e["role"] == "system":
            print("  判定: ❌ skill 清单注入 **system** 层")
            print("        → 消融 skill 会击穿 system + messages 缓存（🟡 代价）")
        else:
            print("  判定: ✅ skill 清单注入 **messages** 层")
            print("        → 消融 skill 几乎零缓存代价（🟢）")
        print()
        print("  但需同时确认: skill 的 **正文(body)** 是")
        print("    (a) 一开始全量注入 → 🟡 代价高")
        print("    (b) 只注入 name/description，正文按需加载 → 🟢 代价低")
    else:
        print("  未找到 <agent_skills> 区块（可能该 session 无 skill 注入）")

    # --- 统计各 prompt 的分节规模 ---
    print(f"\n[4] system prompt 的顶层区块规模 (取最大那次)")
    print("-" * 72)
    chars, d, s, blocks = cands[0]
    for b in blocks:
        if b.get("role") != "system":
            continue
        c = b.get("content")
        text = "".join(x.get("text", "") for x in c if isinstance(x, dict)) if isinstance(c, list) else (c or "")
        # 按最深一层 xml 标签或 md 标题切分
        parts = re.split(r"(?=^<[a-z_]{3,40}>)", text, flags=re.MULTILINE)
        sizes = []
        for p in parts:
            m = re.match(r"^<([a-z_]{3,40})>", p)
            label = m.group(1) if m else "(preamble)"
            sizes.append((len(p), label))
        sizes.sort(reverse=True)
        print(f"  system 层共 {len(text):,} chars ≈ {len(text)//4:,} tok")
        print(f"  切出 {len(sizes)} 个区块，最大的 15 个:")
        for n, label in sizes[:15]:
            print(f"    {label:32s} {n:>7,} chars ≈{n//4:>6,} tok")
        break

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({
            "layer_totals": dict(layer_totals),
            "skill_evidence": skill_evidence,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n结果已写入: {OUT}")


if __name__ == "__main__":
    main()
