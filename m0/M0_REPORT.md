# M0 可行性验证报告 — tare

> 日期：2026-09-20
> 状态：**✅ 通过（含 2 项关键策略修正）**
> 数据源：`~/.workbuddy-ai/traces/` 实测日志 28 条

---

## 0. 结论摘要

| 验证项 | 结果 | 影响 |
|---|---|---|
| **A. 缓存命中是否可用** | ✅ 通过，总命中率 **97.1%** | 成本模型成立，且无需额外构造 |
| **B. WorkBuddy 是否可观测** | ✅ **超预期** —— 内置完整 trace | **项目重心需调整（见 §5）** |
| **C. skill 注入层** | ⚠️ **注入 system 层** | 消融代价 🟡，调度策略需修正 |
| **D. 上下文分层比例** | ✅ 已量化 | system 49.8% / user 30.8% / tool_result 18.9% |

---

## 1. 意外发现：WorkBuddy 已有内置遥测系统

**这是 M0 最重要的发现，超出了原计划预期。**

`~/.workbuddy-ai/traces/` 下有 **28 条完整 trace**（26MB），每条包含：

```
trace:
  traceId, sessionId, agentName, status, duration, spanCount
  modelInfo:
    models: ["deepseek-v4.1-flash"]
    totalInputTokens, totalOutputTokens, totalCachedTokens
    lastCallInputTokens, callCount
spans[40]:
  spanId, parentId, name, type, startedAt, endedAt, duration, status
  toolInput   ← 完整 prompt 原文
  toolOutput  ← 完整响应原文
```

**span 类型分布（28 条 trace 汇总）：**

| 类型 | 数量 | 说明 |
|---|---|---|
| `custom` | 678 | 绝大多数是 `mcp_tools` |
| `generation` | 235 | **LLM 调用，含完整 prompt** |
| `function` | 215 | 工具调用 |
| `agent` | 30 | 子 agent |

**这意味着：不需要自己搭评测管线就能拿到真实数据。** 原计划中的「运行引擎」在 M1 阶段可直接复用 trace 数据。

---

## 2. 缓存实测（验证项 A）✅

13 条有效记录，**总缓存命中率 97.1%**：

| 指标 | 值 |
|---|---|
| 合计 input | 12,318,053 |
| 合计 **cached** | **11,962,240** |
| 合计 output | 90,276 |
| **命中率** | **97.1%** |

**逐条明细（按 token 降序）：**

| traceId | calls | input | 命中率 | output | status |
|---|---|---|---|---|---|
| c65c56d0 | 32 | 2,283,055 | 98.9% | 38,624 | ok |
| 581497ee | 9 | 2,205,720 | **99.8%** | 8,041 | ok |
| bc873e46 | 13 | 1,753,372 | 95.6% | 8,469 | ok |
| 576f88b3 | 6 | 1,557,287 | **99.8%** | 2,386 | ok |
| 9e16d826 | 5 | 1,335,356 | 99.8% | 6,981 | error |
| 379fb6da | 8 | 665,508 | 88.7% | 4,245 | ok |
| 39cf8034 | 8 | 652,488 | 99.2% | 8,404 | error |
| cdc1ec32 | 9 | 635,511 | 95.0% | 7,122 | ok |
| 2db4607e | 3 | 114,145 | **64.7%** | 925 | ok |

**关键观察：**
- 稳定状态下命中率稳定在 **95–99.8%**。缓存前缀在真实 WorkBuddy 运行中是**高度稳定**的。
- 唯一低值（64.7%）出现在 callCount=3 的**短会话** —— 前缀尚未建立完整缓存。符合预期。
- **单条 session 可消耗 200 万+ input token**（如 581497ee）。这个量级下，成本优化有实际意义。

**结论：缓存机制可用，成本模型成立。** 改用 DeepSeek 后（$0.003/MTok 命中价），这条 session 的缓存部分成本仅 **$0.0066**。

---

## 3. 上下文分层实测（验证项 C + D）

### 3.1 分层比例（全部 generation 汇总）

| 层 | chars | 占比 | ≈tokens |
|---|---|---|---|
| **`system`** | 167,238 | **49.8%** | 41,809 |
| `messages.user` | 103,281 | 30.8% | 25,820 |
| `messages.tool_result` | 63,366 | 18.9% | 15,841 |
| `messages.assistant` | 1,789 | 0.5% | 447 |

**关键观察：system prompt 占了一半的上下文。** 这正是 tare 要审计的对象。

### 3.2 单次请求的绝对规模

| 请求 | 总 chars | system | tool_result | user |
|---|---|---|---|---|
| 典型多轮 | 71,472 | **41,274** (57.7%) | 18,505 (25.9%) | 10,114 (14.2%) |
| 典型多轮 | 67,735 | 41,274 (60.9%) | 18,505 (27.3%) | 7,889 (11.6%) |
| 典型多轮 | 61,061 | 41,278 (67.6%) | 11,815 (19.3%) | 7,892 (12.9%) |
| 首轮 | 71,635 | 2,138 (3.0%) | 0 | **69,497** (97.0%) |

> **system prompt 稳定在 41,274 chars ≈ 10,318 tok**，跨会话几乎不变（41,274 / 41,278）。这是**理想的稳定前缀**，也是 tare 的主要优化目标。

### 3.3 ⚠️ skill 注入方式判定 —— 策略修正点

实测：`<agent_skills>` 区块位于 **`system` 层**，大小 **7,189 chars ≈ 1,797 tok**。

**但重要的是这个区块的实际内容** —— 它不是 skill 清单，而是**关于 Skill 机制的元指令**：

```
<agent_skills>
When users ask you to perform tasks, check if any of the available skills
listed in the Skill tool can help complete the task more effectively.
Skills provide specialized capabilities and domain knowledge.
To use a skill, call the Skill tool, the skill's instructions will be
automatically loaded into context.
...
**Skill Levels and Storage**:
- **User-level Skills**: Stored in `~/.workbuddy-ai/skills/`.
- **Project-level Skills**: Stored in `{workspace}/.workbuddy-ai/skills/`.
...
```

**修正后的判定：**

| 对象 | 实际形态 | 消融代价 |
|---|---|---|
| **Skill 元指令块** | 注入 `system`，~1,797 tok | 🟡 击穿 system + messages |
| **Skill 清单（name/description）** | 由 `Skill` **工具**提供（工具 schema 里） | 🔴 击穿全部 |
| **Skill 正文** | **按需加载**（"instructions will be automatically loaded into context"） | 🟢 只影响 messages |

> **✅ 关键结论：WorkBuddy 采用渐进加载（progressive disclosure）。**
> Skill 正文**不在初始 system prompt 里**，只在调用 `Skill` 工具后才注入。
> 这意味着：**消融 skill 正文的代价是 🟢 低**，与上下文分层设计的最佳实践一致。

### 3.4 修正后的消融调度策略

| 组件类型 | 注入层 | 消融代价 | 调度顺序 |
|---|---|---|---|
| Skill 正文 | `messages`（按需） | 🟢 低 | **第 1 批** |
| Hook 注入提醒 | `messages` | 🟢 低 | **第 1 批** |
| system prompt 内的区块（如 `<agent_skills>` 元指令） | `system` | 🟡 中 | 第 2 批（按区块批量测） |
| Skill 清单 / 工具 schema | `tools` | 🔴 高 | 第 3 批（单独处理） |

**验证项 C 判定：⚠️ 部分修正，但不影响可行性。** 原假设（skill 全量注入 system）被证伪 —— 实际情况更好。

---

## 4. system prompt 的可消融区块清单

从实测的 41,274 chars system prompt 中检出 **37 个顶层区块**，即 tare 的审计单元：

| 类别 | 区块 |
|---|---|
| 策略类（xml） | `<content_policy>` `<personal_files_safety>` `<capability_constraints>` `<response_language>` |
| 行为类（xml） | `<working_modes>` `<agent_loop>` `<tool_usage_policy>` `<task_management>` `<asking_questions>` |
| 输出类（xml） | `<result_presentation>` `<sharing_files>` `<final_answer_instructions>` |
| 工具类（xml） | `<tool_use>` `<mcp_configuration>` `<office_skill_routing>` `<automations>` |
| 可视化类（xml） | `<instructions_for_visualizer>` `<visualizer_examples>` + 5 个 md 子节 |
| 技能类（xml） | `<agent_skills>` + `<examples>` + `<expert_management>` + `<plugin_recommendation>` |
| 记忆类（xml） | `<memory_system>` + 3 个 Layer 子节 |
| 运行时类 | `<binary_context>` + 4 个 md 节（Python/Node/Runtime Rules/Isolation） |

**这 37 个区块，每一个都是可以被消融测试的对象。** —— 这就是 M1 的组件清单。

---

## 5. 对项目计划的影响（重要）

### 5.1 需要调整的部分

| 原计划 | 修正 | 原因 |
|---|---|---|
| M1 自建「运行引擎」 | **改为：解析 trace 为主，主动触发为辅** | trace 已含完整 prompt + token + 缓存数据 |
| 缓存安全分叉是核心难点 | **降级为 M3 的优化项** | 实测命中率 97.1%，机制本身工作良好 |
| 组件发现器扫文件系统 | **补一条：从 trace 提取实际注入的区块** | 文件系统 ≠ 实际注入内容 |
| 假设 skill 全量注入 | **修正为渐进加载** | 实测证伪 |

### 5.2 新增的独特能力（这是意外收获）

**trace 数据让 tare 能做一件原计划没有的事：静默审计（Silent Audit）。**

- 不需要主动跑评测，**直接分析用户已有的 session 历史**。
- 可以立刻产出「你的 system prompt 里这 37 个区块，各自被消费了多少次、在什么场景下被触发」。
- 这是一个**零成本、零侵入**的第一版产品形态 —— 可以直接落地。

**建议的 M1 修订：** 先做「静默审计」，再做「主动消融」。

---

## 6. 产出物

| 文件 | 说明 |
|---|---|
| `scan_traces.py` | trace 全量扫描器（缓存/span/分节统计） |
| `analyze_layers.py` | 上下文分层精算 + skill 注入方式判定 |
| `scan_result.json` | 扫描原始结果 |
| `layer_result.json` | 分层原始结果 |
| `M0_REPORT.md` | 本报告 |

---

## 7. M0 验收结论

| 验收项 | 标准 | 结果 |
|---|---|---|
| A. 缓存命中 > 90% | — | ✅ **97.1%** |
| B. 组件映射表确认 | — | ✅ **完成，37 个区块** |
| C. skill 注入层判定 | — | ✅ **渐进加载（优于预期）** |
| D. 成本实测报告 | — | ✅ 见 §2 |

**M0 = PASS，且发现了一条更快的落地路径。**

---

## 8. 下一步（M1 修订版）

1. **静默审计器**（新增，优先）
   解析 trace → 输出「37 个区块 × 触发次数 × token 占用」表格。
   **零成本，一两天可完成。**

2. **区块级消融**
   对 system prompt 的 37 个区块做 leave-one-out，用可验证任务评分。
   按 §3.4 的三批顺序执行。

3. **可验证任务集**
   20 个任务，覆盖至少 3 类区块（如 `<office_skill_routing>`、`<instructions_for_visualizer>`、`<memory_system>`）。

**下一步需要你的确认：是否先做「静默审计器」？**
