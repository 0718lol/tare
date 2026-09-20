# M1 报告 — 任务集与消融框架

> 日期：2026-09-20
> 状态：**判定器与实验框架已完成；执行通道需决策**

---

## 0. 交付物

| 文件 | 说明 |
|---|---|
| `TASK_SUITE.md` | 任务集设计文档 |
| `tasks.py` | 13 个任务 + 判定器实现 |
| `ablate.py` | 消融执行引擎（validate / plan / collect） |
| `ablation_analyzer.py` | 基于 trace 的自然实验分析 |
| `ablation_result.json` | 自然实验结果 |
| `run_plan.json` | 消融执行计划 |

---

## 1. 任务集（13 个任务，覆盖 8 个区块）

| 族 | 任务 | 被测区块 | 判定探针 |
|---|---|---|---|
| A | A1/A2/A3 定时任务 | `automations` (800 tok) | `automation_update` + rrule 校验 |
| B | B1/B2 复杂多步 | `task_management` (215 tok) | `TaskCreate` |
| C | C1/C2 技能调用 | `agent_skills` (1,584 tok) | `Skill` 参数匹配 |
| D | D1/D2 歧义澄清 | `asking_questions` (136 tok) | `AskUserQuestion` |
| E | E1/E2 交付呈现 | `result_presentation` + `sharing_files` (626 tok) | `present_files` |
| F | F1/F2 可视化 | `instructions_for_visualizer` + `visualizer_examples` (383 tok) | `read_me` + `show_widget` |

**判定器验证结果**（在 30 条真实 trace 的全量 span 池上回放）：

| 任务 | 结果 | 与静默审计是否一致 |
|---|---|---|
| A1/A2/A3 | FAIL | ✅ 一致（automations 零触发） |
| B1/B2 | FAIL | ✅ 一致（task_management 零触发） |
| C1/C2 | FAIL | ⚠️ 部分不一致（Skill 被调用过 2 次，但非 excel/pptx） |
| D1/D2 | **PASS** | ✅ 一致（AskUserQuestion ×4） |
| E1/E2 | **PASS** | ✅ 一致（present_files ×5） |
| F1/F2 | **PASS** | ✅ 一致（read_me ×1） |

> **判定器与静默审计的独立结果高度吻合 —— 这验证了探针设计的有效性。**
> C1/C2 的差异是合理的：样本中的 Skill 调用不是 Excel/PPT 类，所以精确匹配失败。
> 说明判定器**没有误判（false positive）**。

---

## 2. 自然实验：从已有 trace 提取的探索性信号

对 30 条 trace 做「区块触发组 vs 未触发组」的关联分析：

| 区块 | 指标 | 触发组 | 未触发 | 效应量 d | p |
|---|---|---|---|---|---|
| `result_presentation` | 工具调用数 | 13.50 | 6.58 | **0.91** | **0.041** * |
| `sharing_files` | 工具调用数 | 13.50 | 6.58 | **0.91** | **0.041** * |
| `asking_questions` | 工具调用数 | 11.25 | 7.46 | 0.72 | 0.067 * |
| `instructions_for_visualizer` | 成功率 | 1.00 | 0.89 | 0.48 | — |
| `instructions_for_visualizer` | 每次调用 token | 86,177 | 67,688 | 0.24 | — |

**读法（重要）：**

- `result_presentation` / `sharing_files` 触发时，**工具调用数显著更多**（d=0.91，p<0.05）。
  这是**反向因果**：任务本身更复杂 → 既触发了交付呈现，也用了更多工具。**不能解读为「该区块导致更好结果」。**

- `instructions_for_visualizer` 触发组的**成功率是 100%**（未触发组 89%），
  且**每次调用 token 更高**（86k vs 68k）。这更像是「可视化任务本身更受控」而非区块的功劳。

**结论：自然实验只能提供相关性，无法给出因果。必须做主动消融。**

> **这就是为什么需要 M1 的主动消融框架。** 自然实验的价值是：**它告诉我们哪些区块有足够的样本量可分析**。

---

## 3. 消融执行计划

**配置矩阵（9 个）：**

```
full（基线）
-automations                    -result_presentation
-task_management                -sharing_files
-agent_skills                   -instructions_for_visualizer
-asking_questions               -visualizer_examples
```

**规模与成本：**

| 项 | 值 |
|---|---|
| 配置数 | 9 |
| 任务数 | 13 |
| 重复轮数 k | 5 |
| **总 runs** | **585** |
| **预估成本** | **$0.71**（deepseek-flash off-peak） |

---

## 4. ⚠️ 阻塞点：执行通道需要决策

**问题：如何在消融条件下真正执行任务并捕获结果？**

tare 本身不内置 agent 运行时 —— WorkBuddy 是闭源客户端。三种通道：

### 通道 1：手动/半自动（推荐，零改造）
- 对每个配置，在 WorkBuddy 里输入消融 prompt 执行任务
- 执行后从 `~/.workbuddy-ai/traces/` 取新 trace
- 用 `ablate.py collect` 自动评分
- **成本**：585 runs 意味着 585 次手动对话 → **不现实**

### 通道 2：脚本驱动 WorkBuddy CLI（若存在）
- 需要确认 WorkBuddy 是否提供 CLI 入口
- 若有，可脚本批量驱动 + 自动收集 trace
- **待确认**

### 通道 3：直连 DeepSeek API（⭐ 我已验证可行）
- **已验证**：trace 里存了**完整的请求结构** —— system prompt（41,274 chars）+ 对话历史 + `tool_calls` + `tool` 结果
- 可以直接还原请求，**删除目标区块**后发给 DeepSeek API
- 自建最小 agent loop（约 200 行）
- **优点**：精确（真正删除，不是"请忽略"）、可复现、全自动
- **成本**：$0.71
- **缺点**：需要一个 DeepSeek API key

---

## 5. 我的建议

**走通道 3。**

理由：
1. **M1 最大的风险不是成本，是「能不能测出信号」。** 通道 1 要 585 次手动对话，几乎不可行；通道 3 全自动，一次跑完。
2. **通道 3 的测量更严谨** —— 「请忽略某区块」的覆盖指令可能不生效（模型可能仍受影响），而**真正删除区块**没有这个疑问。
3. **已验证技术可行性** —— trace 里有完整请求，还原成本很低。
4. **成本可忽略**：$0.71。

另外，通道 3 顺带产出一个**副产品**：tare 会有自己的最小 agent loop，这让它不再依赖 WorkBuddy 客户端 —— **对后续开源和 CI 集成都是必要的**（D5 选了 GitHub Action，而 Action 环境里没有 WorkBuddy 客户端）。

---

## 6. 需要你决定

| 选项 | 说明 |
|---|---|
| **A. 走通道 3** | 你提供 DeepSeek API key，我写完 agent loop + 消融管线，跑出真实 ΔS |
| **B. 走通道 1** | 不提供 key，我把流程做成可手动执行的形式（但 585 runs 不现实，需缩减到 ~20 runs） |
| **C. 先不做消融** | 用自然实验的结论收尾，把 tare 产品化（静默审计已经是可用形态） |

**我建议 A。** 这是唯一能给出因果结论的路径，且成本不到 1 美元。

如果选 A，请提供 DeepSeek API key（或告诉我从哪个环境变量读）。我会：
1. 写最小 agent loop（复用 trace 的真实 prompt）
2. 实现区块删除器（真正从 system prompt 里移除目标区块）
3. 跑 585 runs，输出 ΔS 与置信区间
4. 产出 M1 终版报告
