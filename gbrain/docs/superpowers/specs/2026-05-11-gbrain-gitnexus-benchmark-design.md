# GBrain GitNexus Benchmark Design

## 目标

对比测试两个版本 gbrain 在 agent 编程任务中的表现差异：
- **当前 gbrain** (v0.16.x)：只有文档/笔记知识库 + MiniMax embedding
- **gbrain-gitnexus**：含完整 GitNexus 代码导入管道 + code_query / code_context / code_impact MCP 工具

测试 OpenCode 作为 agent 调用不同版本 gbrain 完成任务的效果，量化"代码理解能力"带来的边际提升。

## 三组对比架构

| 组 | Agent | GBrain 版本 | 说明 |
|---|---|---|---|
| A | OpenCode | 无 | 纯 baseline，无任何知识库辅助 |
| B | OpenCode | 当前 gbrain (0.16.x) | 有文档/笔记知识但不含代码理解 |
| C | OpenCode | gbrain-gitnexus | 文档知识 + 代码理解能力 |

- C vs B 的差距 = 代码理解能力的边际贡献（核心指标）
- B vs A 的差距 = 知识库本身的基础价值
- C vs A 的差距 = 代码理解能力的总提升

## 测试项目

**Effect-TS** (~200K+ LOC TypeScript)，函数式编程风格，模块间依赖密集。

选择理由：
- 规模足够大，code_context / code_impact 有用武之地
- 类型系统复杂，依赖图丰富
- 跨模块调用/继承关系密集，适合测试代码图遍历

## MCP 强制调用约束

**B/C 组的 prompt 必须显式要求 agent 在动手前先调用 gbrain MCP 工具获取信息**，不能依赖 agent 自行决定。这是 benchmark 有效性的关键保障。

具体方式：
- 每个 task 的 `prompt_gb.md` 开头包含强制性指令，例如："在修改任何代码之前，你必须先调用 gbrain 的 search 工具搜索相关页面"
- T5-T8（代码理解 task）的 `prompt_gb.md` 明确指定要调用的 code_* 工具，例如："使用 gbrain 的 code_context 工具查询 X 的调用者和被调用者，基于返回结果作答"
- runner 在 task 完成后检查 MCP 调用日志，如果 B/C 组完全没有调用 gbrain MCP，该 task 标记为"未遵循协议"，success 直接计为 0
- 组 A 的 `prompt.md` 不含任何 gbrain 调用指令

## Task 设计（8 个）

### 通用 task（T1-T4）：两组 gbrain 均可参与

| ID | 类型 | 名称 | 说明 |
|---|---|---|---|
| T1 | fix_bug | 修复 Effect 模块的类型推导错误 | 定位 bug 来源，修改类型定义 |
| T2 | understand | 理解 Effect 的 Layer 系统设计 | 跨文件阅读，提取架构知识 |
| T3 | add_feature | 为 Effect 模块添加配置项 | 理解现有模式后扩展 |
| T4 | write_test | 为核心函数写单元测试 | 理解函数签名和行为 |

### 代码理解 task（T5-T8）：gbrain-gitnexus 优势项

| ID | 类型 | 名称 | 核心能力 |
|---|---|---|---|
| T5 | code_context | 找出某 Effect 的调用者和被调用者 | code_context |
| T6 | code_impact | 评估修改核心类型的影响范围 | code_impact |
| T7 | code_query | 搜索含特定模式的函数签名 | code_query |
| T8 | code_refactor | 重构跨模块依赖，保证不破坏下游 | code_context + code_impact |

## Runner 架构

```
benchmarks/gbrain-vs-gitnexus/
├── runner/
│   ├── run.ts           # 三组编排调度器
│   ├── types.ts         # 类型定义（复用+扩展）
│   ├── metrics.ts       # 效率归一化
│   ├── judge.ts         # LLM-as-judge
│   ├── report.ts        # Markdown 报告生成
│   └── agent-runner.ts  # OpenCode adapter
├── config/
│   ├── opencode-no-gbrain.json        # 组A
│   ├── opencode-current-gbrain.json   # 组B
│   └── opencode-gitnexus-gbrain.json  # 组C
├── tasks/
│   ├── T1_fix_type_inference/
│   │   ├── prompt.md
│   │   ├── prompt_gb.md
│   │   ├── ground_truth.md
│   │   ├── verify.sh
│   │   └── seed.patch
│   ├── T2_understand_layer_system/
│   ├── T3_add_config_option/
│   ├── T4_write_core_test/
│   ├── T5_find_callers_callees/
│   ├── T6_assess_impact/
│   ├── T7_search_signature_pattern/
│   └── T8_refactor_cross_module/
├── results/             # 按日期存放报告
└── seed/                # Effect-TS 环境准备脚本
```

## 评分体系

**硬性门禁**：B/C 组每个 task 必须至少调用一次 gbrain MCP。如果 runner 检测到零 gbrain 调用，该 task 的 success 直接计为 0，不计入后续评分维度。此门禁确保 B/C 组的优势（或劣势）确实归因于 gbrain 的使用。

| 维度 | 权重 | 来源 | 说明 |
|---|---|---|---|
| Success Rate | 35% | verify.sh 自动化验证 | 任务是否通过验证脚本 |
| Quality | 35% | LLM-as-judge vs ground_truth | 产出代码/答案质量 |
| Efficiency | 20% | tool call 轮次归一化 | 完成任务消耗的交互轮次 |
| Code Tool Leverage | 10% | MCP tool 调用统计 | code_* 工具的有效使用率 |

### Code Tool Leverage 算法

```
leverage = (有效代码工具调用次数) / (总代码工具调用次数)
```
其中"有效"定义为：code_query 返回非空结果、code_context 返回了符号信息、code_impact 返回了非空影响链。

组 A 和组 B 的 leverage 恒为 0（没有 code_* 工具）。只有组 C 有 leverage 值。C vs B 的 leverage 差值 = C 的 leverage 值，展示代码工具被实际使用的程度。

### 组合分

```
composite = 0.35 × successRate + 0.35 × quality + 0.20 × efficiency + 0.10 × codeToolLeverage
```

## 执行流程

1. **准备 Effect-TS 环境**：clone repo，checkout 指定 commit
2. **组 B 准备**：启动 gbrain 0.16.x，导入 Effect-TS 文档
3. **组 C 准备**：启动 gbrain-gitnexus，执行 `gbrain code import` 导入 Effect-TS 代码图
4. **组 A 执行**：OpenCode 无 MCP，逐 task 执行
5. **组 B 执行**：OpenCode + gbrain 0.16.x MCP，逐 task 执行
6. **组 C 执行**：OpenCode + gbrain-gitnexus MCP，逐 task 执行
7. **评分**：verify.sh + LLM judge + 指标归一化
8. **报告生成**：Markdown 格式，含三组对比表 + tool heatmap + 分析

## 报告格式

```markdown
# GBrain GitNexus Benchmark Report

## Summary
| Metric | Group A (No GBrain) | Group B (GBrain) | Group C (GBrain+Nexus) | Delta (C-B) |
|--------|---------------------|-------------------|------------------------|-------------|
| Success Rate | ... | ... | ... | ... |
| Quality | ... | ... | ... | ... |
| Efficiency | ... | ... | ... | ... |
| Code Tool Leverage | ... | ... | ... | ... |
| Composite | ... | ... | ... | ... |

## Per-Task Breakdown
| Task | Type | A Success | B Success | C Success | A Quality | B Quality | C Quality | A Rounds | B Rounds | C Rounds |
|------|------|-----------|-----------|-----------|-----------|-----------|-----------|----------|----------|----------|

## Code Tool Heatmap (Group C)
| Tool | Calls | Tasks Covered |
|------|-------|---------------|
| code_query | ... | T5,T6,T7,T8 |
| code_context | ... | T5,T8 |
| code_impact | ... | T6,T8 |

## Key Findings
- 代码理解能力的边际提升 = C-B composite delta
- 代码工具在哪些 task 类型中最有价值
- 和纯 baseline (A) 的总体提升对比
```

## 依赖

- OpenCode CLI（agent runner）
- ANTHROPIC_API_KEY（LLM judge）
- gbrain 0.16.x（组 B）
- gbrain-gitnexus（组 C）
- Effect-TS repo（测试目标）
