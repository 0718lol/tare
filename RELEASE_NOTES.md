# tare v0.1.0 — 工具化收尾报告

> 日期：2026-09-20
> 里程碑：**M1 静默审计产品化（D-option C）完成**

---

## 1. 交付物

从「一次性脚本」重构为**可分发、可扩展的 Python 包**。

```
tare/
├── pyproject.toml           # 打包配置 + CLI 入口点
├── README.md                # 项目说明（含真实案例与方法论）
├── LICENSE                  # MIT
├── action.yml               # GitHub Action 定义（M3 铺路）
├── .github/workflows/test.yml
├── tare/                    # 核心包
│   ├── __init__.py          # 版本号
│   ├── adapters.py          # harness 适配层（WorkBuddy / Generic）
│   ├── rules.py             # 区块探针规则表（可扩展）
│   ├── audit.py             # 审计引擎
│   ├── report.py            # 三种输出格式
│   └── cli.py               # 命令行
├── tests/test_tare.py       # 10 个单元测试，10/10 通过
├── examples/traces/         # 示例数据
├── m0/                      # M0 方法论文档（保留）
└── m1/                      # M1 报告（保留）
```

---

## 2. 命令行接口

三个子命令，全部工作：

```bash
$ tare info
适配器      : workbuddy
trace 目录  : ~/.workbuddy-ai/traces
harness 根  : ~/.workbuddy-ai
trace 数    : 31
模型        : deepseek-v4.1-flash
总 input    : 17,163,853
总 cached   : 16,779,520  (97.8%)
最大 system : 41,278 chars

$ tare audit                      # 终端彩色表格
$ tare audit --format md -o AUDIT.md
$ tare audit --format json        # 供 CI 消费
$ tare audit --adapter generic --trace-dir ./my-traces
```

---

## 3. 架构改进

| 维度 | 原（脚本） | 现（包） |
|---|---|---|
| 结构 | 单文件硬编码 | 分层：adapters / rules / audit / report / cli |
| harness 支持 | 仅 WorkBuddy 硬编码 | **适配器模式**，支持 generic JSON |
| 规则 | 内联 if-else | **声明式 Rule 表**，可外部扩展 |
| 输出 | 仅 Markdown | text / md / json 三格式 |
| 测试 | 无 | **10 个单元测试，全通过** |
| 依赖 | — | **零外部依赖**（纯标准库） |
| 分发 | 复制文件 | `pip install -e .` + CLI 入口点 |
| CI | 无 | GitHub Actions 矩阵测试（3.9/3.11/3.12） |

### 关键设计：适配器抽象

```python
class Adapter:
    def discover(self) -> List[str]      # 列出可用记录
    def load(self, ident) -> Trace       # 归一化成统一结构
    def home(self) -> Optional[str]      # harness 根目录（用于路径探针）
```

`Trace` 是统一中间表示，派生指标全部是 property：

```python
trace.hit_rate            # 缓存命中率
trace.tool_error_rate     # 工具错误率
trace.tool_repeat_rate    # 工具重复率（低效探索信号）
trace.success             # 会话是否成功
```

**任何 harness 只要提供「system prompt + function spans」，就能被审计。**

---

## 4. 可扩展的规则表

```python
Rule("my_block", "工具",
     Probe("span", ["my_tool"], "该区块描述 my_tool 用法", "高"),
     "自定义区块说明")
```

三种探针类型：

| 类型 | 判定依据 | 适用 |
|---|---|---|
| `span` | 某工具是否被调用 | 机制类区块（最常用） |
| `path` | 某路径是否存在且非空 | 结构性死重探测 |
| `none` | 无探针 | 策略/规范类，标记为需人工 |

**新增 harness 只需加规则，不改引擎。**

---

## 5. 真实数据验证

在 31 条真实 trace 上端到端运行：

| 指标 | 值 |
|---|---|
| system prompt | 10,319 tok / 38 区块 |
| 缓存命中率 | **97.8%** |
| **可回收** | **1,733 tok (16.8%)** |
| 删除候选 | 6 区块 |
| 保留 | 12 区块 |
| 需人工判断 | 20 区块 |

示例数据（`examples/traces/`）用 generic 适配器验证：3 区块 → 正确识别 1 个删除候选（569 tok）。

---

## 6. 为 M3 铺路：action.yml

已写好 GitHub Action 定义，支持：

- 自动写 PR comment（带 `<!-- tare-audit -->` 标记，重复运行会更新而非刷屏）
- 输出 `droppable-tokens` / `droppable-percent` 供后续步骤消费
- **门禁**：死重占比超阈值时检查失败（`fail-on-droppable-percent`）

```yaml
- uses: ./tare
  with:
    fail-on-droppable-percent: "10"
```

---

## 7. 诚实声明：当前能力边界

| 能做 | 不能做 |
|---|---|
| 找出**从未被触及**的区块 | 判断**触发了但无用**的区块 |
| 零成本（纯读已有记录） | 给出因果结论（需主动消融） |
| 跨 harness（适配器） | 自动修复 harness |
| 量化可回收 token | 覆盖策略类区块（占 47.7%） |

**这仍然是「假设生成器」，不是「判决书」。** README 里明确写了这一点 —— 这是可信度的基础。

---

## 8. 当前状态与下一步

**已完成**：M0（可行性验证）→ M1（静默审计器）→ **产品化收尾**

**待办**：
- M2：主动消融实验（需 API key，$0.71）
- M3：GitHub Action 实际接入
- M4：云沙箱 + 冗余检测

**可选立即动作**：
1. `git init` 并推送到 GitHub（README/action.yml 已就绪）
2. 在真实的 ECC 类 harness 上跑一次，作为示范案例
3. 补一份 `CONTRIBUTING.md` 方便外部扩展规则表
