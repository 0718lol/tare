"""
tare M1 — 任务集定义与判定器

每个任务包含：
  - id / block（被测区块）/ prompt（发给 agent 的指令）
  - judge(spans) -> {"pass": bool, "reason": str}

判定完全基于 trace span，零 LLM 主观判断。
"""
import json
import re
from typing import Callable, Dict, List


def _get_tool_calls(spans, tool_name=None):
    out = []
    for s in spans:
        if s.get("type") != "function":
            continue
        if tool_name and s.get("toolName") != tool_name:
            continue
        out.append(s)
    return out


def _parse_input(span):
    try:
        return json.loads(span.get("toolInput") or "{}")
    except Exception:
        return {}


def _has_any_tool(spans, names):
    """任意一个工具被调用"""
    for s in spans:
        if s.get("type") != "function":
            continue
        tn = s.get("toolName") or ""
        nm = s.get("name") or ""
        for n in names:
            if n.lower() in tn.lower() or n.lower() in nm.lower():
                return True, tn or nm
    return False, None


def _skill_invoked(spans, skill_pat):
    """检查 Skill 工具是否被调用，且参数匹配某 skill"""
    for s in _get_tool_calls(spans, "Skill"):
        ti = _parse_input(s)
        blob = json.dumps(ti, ensure_ascii=False)
        if re.search(skill_pat, blob, re.IGNORECASE):
            return True, blob[:120]
    # 有些实现把 skill 名放在 toolName 上
    for s in spans:
        if s.get("type") == "function" and re.search(skill_pat, s.get("toolName") or "", re.I):
            return True, s.get("toolName")
    return False, None


# ------------------------------------------------------------------ 判定器
def judge_automation_create(spans):
    calls = _get_tool_calls(spans, "automation_update")
    if not calls:
        return {"pass": False, "reason": "未调用 automation_update（未创建定时任务）"}
    ti = _parse_input(calls[0])
    if ti.get("mode") != "create":
        return {"pass": False, "reason": f"mode={ti.get('mode')}，期望 create"}
    return {"pass": True, "reason": "已创建定时任务"}


def judge_automation_rrule(freq_expect):
    def j(spans):
        calls = _get_tool_calls(spans, "automation_update")
        if not calls:
            return {"pass": False, "reason": "未调用 automation_update"}
        ti = _parse_input(calls[0])
        rrule = json.dumps(ti, ensure_ascii=False)
        for frag in freq_expect:
            if frag not in rrule:
                return {"pass": False, "reason": f"rrule 缺少 {frag}"}
        return {"pass": True, "reason": "rrule 正确"}
    return j


def judge_task_tool(spans):
    ok, name = _has_any_tool(spans, ["TaskCreate", "TaskUpdate", "TaskList"])
    if ok:
        return {"pass": True, "reason": f"使用了 {name}"}
    return {"pass": False, "reason": "未使用任务管理工具"}


def judge_skill(pattern):
    def j(spans):
        ok, ev = _skill_invoked(spans, pattern)
        if ok:
            return {"pass": True, "reason": f"调用了匹配 {pattern} 的技能"}
        return {"pass": False, "reason": f"未调用匹配 {pattern} 的技能"}
    return j


def judge_ask(spans):
    ok, name = _has_any_tool(spans, ["AskUserQuestion"])
    if ok:
        return {"pass": True, "reason": "主动澄清了歧义"}
    return {"pass": False, "reason": "未澄清歧义，直接执行"}


def judge_present(spans):
    ok, name = _has_any_tool(spans, ["present_files"])
    if ok:
        return {"pass": True, "reason": "交付物已呈现"}
    return {"pass": False, "reason": "未呈现交付物"}


def judge_visualize(spans):
    ok1, _ = _has_any_tool(spans, ["read_me"])
    ok2, _ = _has_any_tool(spans, ["show_widget"])
    if ok1 and ok2:
        return {"pass": True, "reason": "使用了可视化（read_me + show_widget）"}
    if ok1 or ok2:
        return {"pass": False, "reason": f"部分使用（read_me={ok1}, show_widget={ok2}）"}
    return {"pass": False, "reason": "未使用可视化"}


# ------------------------------------------------------------------ 任务集
TASKS: List[Dict] = [
    # 族 A — automations (800 tok, 🔥 零触发)
    {"id": "A1", "block": "automations",
     "prompt": "每天早上9点提醒我检查服务器日志",
     "judge": judge_automation_create},
    {"id": "A2", "block": "automations",
     "prompt": "每周一给我发一份上周的销售汇总",
     "judge": judge_automation_rrule(["WEEKLY", "BYDAY=MO"])},
    {"id": "A3", "block": "automations",
     "prompt": "每月1号和15号提醒我交报表",
     "judge": judge_automation_rrule(["MONTHLY", "BYMONTHDAY=1,15"])},

    # 族 B — task_management (215 tok, 🔥 零触发)
    {"id": "B1", "block": "task_management",
     "prompt": "分析当前目录下所有 py 文件，统计行数并按大小排序，最后生成一份报告文件",
     "judge": judge_task_tool},
    {"id": "B2", "block": "task_management",
     "prompt": "帮我重构这三个模块：先分析依赖，再逐个改造，最后跑测试验证。分步骤做。",
     "judge": judge_task_tool},

    # 族 C — agent_skills (1584 tok, ✅ 被消费)
    {"id": "C1", "block": "agent_skills",
     "prompt": "帮我创建一个 Excel 表格，记录这5个产品的销量：A=100, B=250, C=80, D=400, E=150",
     "judge": judge_skill(r"excel|xlsx|sheet")},
    {"id": "C2", "block": "agent_skills",
     "prompt": "把「2026年Q3总结：营收增长20%，用户数翻倍」做成一个PPT",
     "judge": judge_skill(r"pptx|ppt|slide")},

    # 族 D — asking_questions (136 tok, ✅ 被消费)
    {"id": "D1", "block": "asking_questions",
     "prompt": "帮我改一下那个东西",
     "judge": judge_ask},
    {"id": "D2", "block": "asking_questions",
     "prompt": "把文件处理一下",
     "judge": judge_ask},

    # 族 E — result_presentation + sharing_files (626 tok, ✅ 被消费)
    {"id": "E1", "block": "result_presentation",
     "prompt": "给我写一份项目总结报告，保存成文件",
     "judge": judge_present},
    {"id": "E2", "block": "sharing_files",
     "prompt": "分析一下当前工作区有哪些文件，做成一份清单给我",
     "judge": judge_present},

    # 族 F — visualizer (383 tok, ✅ 被消费)
    {"id": "F1", "block": "instructions_for_visualizer",
     "prompt": "解释一下 TCP 三次握手的过程",
     "judge": judge_visualize},
    {"id": "F2", "block": "visualizer_examples",
     "prompt": "给我画一个流程图，说明用户注册到登录的完整流程",
     "judge": judge_visualize},
]


def get_tasks_by_block(block: str):
    return [t for t in TASKS if t["block"] == block]


def all_blocks():
    seen = []
    for t in TASKS:
        if t["block"] not in seen:
            seen.append(t["block"])
    return seen


if __name__ == "__main__":
    print(f"任务集: {len(TASKS)} 个任务")
    print(f"覆盖区块: {len(all_blocks())} 个")
    print()
    for b in all_blocks():
        ts = get_tasks_by_block(b)
        print(f"  {b:<32} {len(ts)} 个任务: {[t['id'] for t in ts]}")
    print()
    print("示例任务:")
    for t in TASKS[:3]:
        print(f"  [{t['id']}] {t['prompt']}")
