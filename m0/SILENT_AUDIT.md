# tare 静默审计报告

> 生成时间：2026-09-20 01:10
> 数据源：29 条 WorkBuddy trace
> 审计对象：system prompt 的 38 个顶层区块，合计 41,274 chars ≈ 10,318 tok

---

## 0. 核心结论

| 分类 | 区块数 | token | 占 system |
|---|---|---|---|
| 🔥 删除候选 | 5 | 1,729 | 16.8% |
| ✅ 保留 | 7 | 2,885 | 28.0% |
| ❓ 需人工 | 26 | 5,691 | 55.2% |

**潜在可回收：1,729 tok（16.8% 的 system prompt）**

---

## 1. 区块明细

| 区块 | tokens | 占比 | 判定 | 证据 | 说明 |
|---|---:|---:|---|---|---|
| `agent_skills` | 1,584 | 15.4% | 保留 | Skill ×2 | Skill 机制的元指令；观察 Skill 工具是否被调用 |
| `automations` | 800 | 7.8% | 删除候选 | 从未出现 | 仅在创建定时任务时适用 |
| `personal_files_safety` | 571 | 5.5% | 需人工 | 无行为探针 | 策略类 |
| `Layer 3 — Workspace Memory (read/write)` | 558 | 5.4% | 需人工 | 未定义探针 |  |
| `Runtime Isolation Rules` | 441 | 4.3% | 需人工 | 未定义探针 |  |
| `tool_use` | 407 | 4.0% | 需人工 | 无行为探针 | 核心行为定义 |
| `(preamble)` | 406 | 3.9% | 需人工 | 未定义探针 |  |
| `final_answer_instructions` | 359 | 3.5% | 需人工 | 无行为探针 | 输出规范，难以客观判定 |
| `result_presentation` | 357 | 3.5% | 保留 | present_files ×5 | 要求用 present_files 交付；无则该约束未生效 |
| `plugin_recommendation` | 349 | 3.4% | 删除候选 | 从未出现 | 要求推荐 Connector/Expert；无调用则未被消费 |
| `Design guidance` | 311 | 3.0% | 需人工 | 未定义探针 |  |
| `agent_loop` | 305 | 3.0% | 需人工 | 无行为探针 | 核心行为定义 |
| `tool_usage_policy` | 293 | 2.8% | 需人工 | 未定义探针 |  |
| `mcp_configuration` | 292 | 2.8% | 删除候选 | 从未出现 | 仅在安装 MCP 时适用 |
| `Layer 1 — Cloud Memory` | 278 | 2.7% | 需人工 | 未定义探针 |  |
| `visualizer_examples` | 272 | 2.6% | 保留 | read_me ×1 | 跟随 instructions_for_visualizer；同一组证据 |
| `sharing_files` | 269 | 2.6% | 保留 | present_files ×5 | 同上，通常与 result_presentation 同时失效 |
| `content_policy` | 261 | 2.5% | 需人工 | 无行为探针 | 策略类，无法用行为探针判定 |
| `examples` | 221 | 2.1% | 需人工 | 未定义探针 |  |
| `task_management` | 215 | 2.1% | 删除候选 | 从未出现 | 要求复杂任务用 Task 工具；观察是否使用 |
| `Proactive triggers (no explicit ask needed)` | 190 | 1.8% | 需人工 | 未定义探针 |  |
| `Specification triggers (no verb needed)` | 171 | 1.7% | 需人工 | 未定义探针 |  |
| `working_modes` | 165 | 1.6% | 需人工 | 无行为探针 | 核心行为定义 |
| `office_skill_routing` | 156 | 1.5% | 保留 | Skill ×2 | 指向 Word/PPT/Excel 技能路由；观察是否真的触发 Skill |
| `capability_constraints` | 146 | 1.4% | 需人工 | 无行为探针 | 策略类 |
| `asking_questions` | 136 | 1.3% | 保留 | AskUserQuestion ×4 | 要求澄清时用 AskUserQuestion |
| `Multi-visualization responses` | 133 | 1.3% | 需人工 | 未定义探针 |  |
| `Layer 2 — User-level Local Memory (read/write)` | 121 | 1.2% | 需人工 | 未定义探针 |  |
| `instructions_for_visualizer` | 111 | 1.1% | 保留 | read_me ×1 | 描述 Visualizer 的用法；若从不调用 read_me/show_widget 则未被消费 |
| `response_language` | 82 | 0.8% | 需人工 | 无行为探针 | 策略类 |
| `Runtime Selection Rules` | 77 | 0.7% | 需人工 | 未定义探针 |  |
| `expert_management` | 73 | 0.7% | 删除候选 | 从未出现 | 仅在编辑专家包时适用 |
| `Explicit triggers` | 70 | 0.7% | 需人工 | 未定义探针 |  |
| `Python` | 54 | 0.5% | 需人工 | 未定义探针 |  |
| `Node` | 41 | 0.4% | 需人工 | 未定义探针 |  |
| `binary_context` | 21 | 0.2% | 需人工 | ✅ python: 1917文件; ✅ node: 11990文件 | 声称的 Python/Node 路径是否真实存在 |
| `Available Runtimes` | 5 | 0.1% | 需人工 | 未定义探针 |  |
| `memory_system` | 4 | 0.0% | 需人工 | 无行为探针 | 记忆三层机制说明；需人工判断注入内容是否被遵循 |

---

## 2. 🔥 删除候选明细

### `automations` — 800 tok (7.8%)

- **证据**：从未出现
- **说明**：仅在创建定时任务时适用
- **置信度**：中

### `plugin_recommendation` — 349 tok (3.4%)

- **证据**：从未出现
- **说明**：要求推荐 Connector/Expert；无调用则未被消费
- **置信度**：中

### `mcp_configuration` — 292 tok (2.8%)

- **证据**：从未出现
- **说明**：仅在安装 MCP 时适用
- **置信度**：中

### `task_management` — 215 tok (2.1%)

- **证据**：从未出现
- **说明**：要求复杂任务用 Task 工具；观察是否使用
- **置信度**：中

### `expert_management` — 73 tok (0.7%)

- **证据**：从未出现
- **说明**：仅在编辑专家包时适用
- **置信度**：中

---

## 3. 工具调用证据

| 工具 | 调用次数 |
|---|---:|
| `Bash` | 115 |
| `Read` | 27 |
| `PowerShell` | 22 |
| `Write` | 20 |
| `WebFetch` | 11 |
| `Edit` | 11 |
| `WebSearch` | 7 |
| `present_files` | 5 |
| `AskUserQuestion` | 4 |
| `TaskOutput` | 4 |
| `Skill` | 2 |
| `read_me` | 1 |
| `show_widget` | 1 |
| `agent-browser` | 1 |
| `browser-automation` | 1 |

---

## 4. 方法与局限

### 判定方法

采用**行为探针**：对每个区块，检查它所描述的机制是否在会话中被实际调用。
例如 `<instructions_for_visualizer>` 描述了 Visualizer 用法，
则探针为「`read_me` / `show_widget` 是否出现」。若从未出现，则该区块未被消费。

### 局限（重要）

1. **「未观察到」≠「无用」**。本审计基于有限的 trace 样本。
   区块可能只是**当前样本未覆盖**该场景，而非真的无用。
2. **无行为探针的区块占了很大比例**（需人工判断类）。
   这些是策略类/输出规范类区块，其价值无法用「是否被调用」衡量。
3. **触发 ≠ 有效**。区块被消费，不代表它产生了正收益 —— 
   那需要**主动消融实验**才能确定。静默审计只能做到「发现从未被触及的死重」。

### 因此，静默审计的定位

> 它**不是**结论，而是**假设生成器**。
> 它低成本地把候选集从「37 个区块」缩小到「少数几个值得做消融实验的目标」。

下一步：对 🔥 象限的区块做主动消融，用可验证任务测 ΔS。
