"""
tare.rules — 区块探针规则

探针是一条「可验证证据」的定义：给定 harness 的运行记录，
如何客观判断某个区块**是否被消费**。

三种探针类型：
  span  — 需要某工具被调用（最常用）
  path  — 需要某路径存在且非空（结构性死重探测）
  none  — 无探针，标记为需人工判断
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Probe:
    kind: str                      # "span" | "path" | "none"
    needles: List[str] = field(default_factory=list)   # span: 工具/span 名片段; path: 路径模板
    rationale: str = ""            # 为什么这个探针有效
    confidence: str = "中"         # 探针可靠性：高 / 中 / 低


@dataclass
class Rule:
    block: str                     # 区块名（对应 system prompt 中的标签/标题）
    category: str                  # 策略 / 行为 / 输出 / 工具 / 技能 / 记忆 / 运行时
    probe: Probe
    note: str = ""                 # 人读说明


# ---------------------------------------------------------------- 规则表
RULES: List[Rule] = [
    # ---- 工具/机制类：有明确的行为探针 ----
    Rule("instructions_for_visualizer", "工具",
         Probe("span", ["read_me", "show_widget"],
               "区块描述 Visualizer 用法；若从不调用 read_me/show_widget 则未被消费", "高"),
         "描述可视化工具的使用方式"),
    Rule("visualizer_examples", "工具",
         Probe("span", ["read_me", "show_widget"],
               "跟随 instructions_for_visualizer；同一组证据", "高"),
         "可视化的示例集"),
    Rule("result_presentation", "输出",
         Probe("span", ["present_files"],
               "要求用 present_files 交付；无则该约束未生效", "高"),
         "交付物呈现规范"),
    Rule("sharing_files", "输出",
         Probe("span", ["present_files"],
               "同上，通常与 result_presentation 同时失效", "中"),
         "文件分享规范"),
    Rule("office_skill_routing", "技能",
         Probe("span", ["Skill"],
               "指向 Word/PPT/Excel 技能路由；观察 Skill 是否触发", "中"),
         "Office 技能路由表"),
    Rule("plugin_recommendation", "技能",
         Probe("span", ["search_plugins", "suggest_plugin_install"],
               "要求推荐 Connector/Expert；无调用则未被消费", "高"),
         "插件/连接器推荐机制"),
    Rule("expert_management", "技能",
         Probe("span", ["expert-manager"],
               "仅在编辑专家包时适用", "高"),
         "专家包管理流程"),
    Rule("mcp_configuration", "工具",
         Probe("span", ["mcp__", "ToolSearch"],
               "仅在安装/配置 MCP 时适用", "中"),
         "MCP 配置流程"),
    Rule("automations", "工具",
         Probe("span", ["automation_update"],
               "仅在创建定时任务时适用", "高"),
         "定时任务机制"),
    Rule("task_management", "行为",
         Probe("span", ["TaskCreate", "TaskUpdate", "TaskList"],
               "要求复杂任务用 Task 工具；观察是否使用", "高"),
         "任务管理工具使用规范"),
    Rule("asking_questions", "行为",
         Probe("span", ["AskUserQuestion"],
               "要求澄清时用 AskUserQuestion", "高"),
         "澄清提问规范"),
    Rule("agent_skills", "技能",
         Probe("span", ["Skill"],
               "Skill 机制的元指令；观察 Skill 工具是否被调用", "中"),
         "技能机制的说明"),
    Rule("memory_system", "记忆",
         Probe("span", ["conversation_search"],
               "记忆三层机制；观察是否用到检索", "低"),
         "三层记忆系统说明"),

    # ---- 策略/规范类：无行为探针 ----
    Rule("content_policy", "策略", Probe("none", [], "策略类，无法用行为探针判定", "低")),
    Rule("personal_files_safety", "策略", Probe("none", [], "策略类", "低")),
    Rule("capability_constraints", "策略", Probe("none", [], "策略类", "低")),
    Rule("response_language", "策略", Probe("none", [], "策略类", "低")),
    Rule("final_answer_instructions", "输出", Probe("none", [], "输出规范，难以客观判定", "低")),
    Rule("agent_loop", "行为", Probe("none", [], "核心行为定义", "低")),
    Rule("tool_use", "行为", Probe("none", [], "核心行为定义", "低")),
    Rule("working_modes", "行为", Probe("none", [], "核心行为定义", "低")),
    Rule("tool_usage_policy", "行为", Probe("none", [], "未定义探针", "低")),

    # ---- 路径类：结构性死重探测 ----
    Rule("binary_context", "运行时",
         Probe("path", ["binaries/python", "binaries/node"],
               "声称的 Python/Node 路径是否真实存在", "高"),
         "运行时二进制说明"),
]


# 区块名 → 规范化（容忍 trace 中的变体写法）
ALIASES = {
    "Layer 1 — Cloud Memory": "memory_system",
    "Layer 2 — User-level Local Memory (read/write)": "memory_system",
    "Layer 3 — Workspace Memory (read/write)": "memory_system",
    "# Available Runtimes": "binary_context",
    "Available Runtimes": "binary_context",
    "## Python": "binary_context",
    "## Node": "binary_context",
    "Runtime Selection Rules": "binary_context",
    "Runtime Isolation Rules": "binary_context",
    "Explicit triggers": "instructions_for_visualizer",
    "Proactive triggers (no explicit ask needed)": "instructions_for_visualizer",
    "Specification triggers (no verb needed)": "instructions_for_visualizer",
    "Multi-visualization responses": "instructions_for_visualizer",
    "Design guidance": "instructions_for_visualizer",
    "examples": "agent_skills",
}


def lookup(block: str) -> Optional[Rule]:
    """按区块名查规则（支持别名归一）"""
    key = ALIASES.get(block, block)
    for r in RULES:
        if r.block == key:
            return r
    return None
