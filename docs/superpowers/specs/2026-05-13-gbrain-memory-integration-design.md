# GBrain Memory Integration Design

## Summary

将 GBrain (GitNexus) 作为长期记忆节点集成到 Sherpa 的 fuzz 工作流中，使每次 fuzz 会话的决策、crash 分析、策略经验沉淀为可检索复用的长期记忆。GBrain 作为独立 MCP Server 运行，Sherpa 通过 MemoryAdapter（Python MCP client）进行读写。

## Architecture

```
┌─────────────────────────────────────────┐
│              Sherpa                      │
│  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│  │ FastAPI   │  │ Workflow │  │Memory  │ │
│  │ 控制面    │  │ Graph    │  │Adapter │ │
│  └──────────┘  └──────────┘  └───┬────┘ │
│                                  │       │
│  ┌──────────────────────────────┐│       │
│  │  Postgres (Sherpa)            ││       │
│  └──────────────────────────────┘│       │
└──────────────────────────────────┼───────┘
                                   │ MCP stdio
┌──────────────────────────────────┼───────┐
│              GBrain (GitNexus)    │       │
│  ┌──────────────────────────────┐│       │
│  │  MCP Server (30+ tools)       ││       │
│  └──────────────┬───────────────┘│       │
│  ┌──────────────┴───────────────┐│       │
│  │  BrainEngine                  ││       │
│  └──────────────┬───────────────┘│       │
│  ┌──────────────┴───────────────┐│       │
│  │  Postgres + pgvector (GBrain) ││       │
│  └──────────────────────────────┘│       │
└──────────────────────────────────┘       │
```

- **开发环境**: GBrain 作为 Sherpa 的 stdio 子进程，使用 PGLite 嵌入式数据库
- **生产环境**: GBrain 作为 K8s Sidecar 容器，使用独立 Postgres + pgvector

## Workflow Integration

### 新增节点: memory-summarize

在整个 fuzz 会话结束后独立运行，负责:
1. 聚合所有阶段结果
2. 提炼有效策略模式
3. 归档崩溃结论
4. 更新目标仓库画像
5. 建立跨页面知识图谱

### 读写策略

| 时机 | 阶段 | 写入内容 | 方式 |
|------|------|----------|------|
| 实时同步 | crash-triage, crash-analysis | 崩溃分诊/分析结论 | MCP put_page 同步调用 |
| 批量异步 | plan, synthesize, build, run, coverage-analysis | 策略决策、harness、覆盖率 | 攒批后写入，失败可重试 |

### 经验建议机制

以下节点进入时，MemoryAdapter 主动查询 GBrain 并呈现结构化建议:
- **plan** — 查询同类仓库 fuzz 策略
- **crash-triage** — 查询相似崩溃分类
- **crash-analysis** — 查询相似漏洞根因
- **coverage-analysis** — 查询历史覆盖率改进路径

其余节点（init/synthesize/build/run/improve-harness/fix-harness）不触发建议。

## GBrain Page Data Model

### 五种 Page 类型

#### 1. fuzz/target-repo — 目标仓库画像

```yaml
slug: fuzz/targets/<owner>-<repo>
type: fuzz/target-repo
tags: [fuzz, target, <language>]
frontmatter:
  repo_url: string
  repo_language: string
  first_fuzzed_at: datetime
  last_fuzzed_at: datetime
  total_sessions: int
  total_crashes_found: int
  true_vulns_found: int
  cve_ids: list[string]
  attack_surfaces:
    - module: string
      functions: list[string]
      risk_level: high|medium|low
  recommended_strategies: list[string]
  top_coverage: float
```

#### 2. fuzz/session — 会话总结

```yaml
slug: fuzz/sessions/<repo>-<timestamp>
type: fuzz/session
tags: [fuzz, session, <repo>]
frontmatter:
  repo: string         # slug of fuzz/target-repo
  session_id: string
  started_at: datetime
  ended_at: datetime
  duration_seconds: int
  stages_completed: list[string]
  total_harnesses: int
  total_crashes: int
  coverage_start: float
  coverage_end: float
```

#### 3. fuzz/crash — 崩溃分析

```yaml
slug: fuzz/crashes/<repo>-<crash-id>
type: fuzz/crash
tags: [crash, <crash_type>, <repo>]
frontmatter:
  repo: string               # slug of fuzz/target-repo
  session: string            # slug of fuzz/session
  crash_signature: string    # e.g. "SIGSEGV / xmlParseElement+0x1a4"
  crash_type: string         # heap-use-after-free, stack-buffer-overflow, etc.
  verdict: true_positive | false_positive | inconclusive
  severity: critical | high | medium | low
  cve_id: string | null
  asan_report: string
  related_crashes: list[string]  # slugs of similar crashes
  discovered_at: datetime
```

#### 4. fuzz/strategy — 策略经验

```yaml
slug: fuzz/strategies/<descriptive-name>
type: fuzz/strategy
tags: [strategy, <language>, <pattern>]
frontmatter:
  strategy_type: harness_pattern | seed_selection | build_config
  target_language: string
  effective_for_repos: list[string]
  harness_pattern: string
  seed_families: list[string]
  build_flags: list[string]
  success_rate: float       # 0.0 - 1.0
  avg_coverage_gain: float  # percentage points
  validated_sessions: int
```

#### 5. fuzz/harness — Harness 模式

```yaml
slug: fuzz/harnesses/<repo>-<harness-id>
type: fuzz/harness
tags: [harness, <repo>]
frontmatter:
  repo: string
  session: string
  target_function: string
  build_status: success | failed
  fuzz_result: running | coverage_gain | plateau | crash_found
  coverage_achieved: float
```

### 七种关系边

| link_type | from | to | 含义 |
|-----------|------|----|------|
| source | session | target-repo | 会话记录了哪个目标仓库 |
| discovered_in | crash | session | 崩溃在哪个会话中被发现 |
| found_in_repo | crash | target-repo | 崩溃属于哪个目标仓库 |
| generated_in | harness | session | harness 在哪个会话中生成 |
| follows_pattern | harness | strategy | harness 遵循哪个策略 |
| applied_to | strategy | target-repo | 策略应用于哪个目标仓库 |
| similar_to | crash | crash | 崩溃相似 |

### Page 内容结构

每个 page 遵循 GBrain 的 `compiled_truth` + `timeline` 结构:
- **compiled_truth**: 当前最佳结论，可随新证据更新
- **timeline**: 只追加的证据链，保留完整审计轨迹

## MemoryAdapter Interface

### 核心方法

```python
class MemoryAdapter:
    # 查询
    async def query_experience(query: str, context: dict) -> list[MemoryHit]
    async def get_page(slug: str) -> Page | None
    async def get_target_profile(repo_url: str) -> Page | None
    async def find_similar_crashes(signature: str, limit: int = 5) -> list[Page]
    async def suggest_strategies(language: str, module: str) -> list[Page]

    # 写入
    async def write_page(slug: str, frontmatter: dict, compiled_truth: str, timeline: list[str]) -> bool
    async def add_timeline(slug: str, entry: str) -> bool
    async def add_link(from_slug: str, to_slug: str, link_type: str, source: str = "sherpa") -> bool

    # 批量
    async def batch_write(ops: list[WriteOp]) -> BatchResult

    # 建议
    async def get_suggestions(node: str, ctx: dict) -> Suggestion | None

    # 总结
    async def summarize_session(session: SessionData) -> str
```

### MCP Tool Mapping

| MemoryAdapter 方法 | GBrain MCP 工具 |
|---------------------|-----------------|
| query_experience | query / search |
| get_page | get_page |
| find_similar_crashes | search + traverse_graph |
| suggest_strategies | query |
| write_page | put_page |
| add_timeline | add_timeline_entry |
| add_link | add_link |
| batch_write | put_page × N + add_link × N |
| get_suggestions | query + traverse_graph |
| summarize_session | 全部写入类工具 |

## Fault Tolerance

| 场景 | 策略 |
|------|------|
| MCP Server 未启动 | MemoryAdapter init 时自动 `gbrain serve` 拉起子进程 |
| 查询超时 (> 5s) | 返回空结果 + log warning，不阻塞节点 |
| 写入失败（关键阶段） | 重试 3 次，仍失败则写入本地 recovery log |
| 批量写入部分失败 | 成功的保留，失败的进入 recovery log，下次重试 |
| GBrain 数据库损坏 | Sherpa 不受影响，GBrain 侧 `gbrain doctor` 修复 |

核心原则: **写入失败不阻断 fuzz 主流程**。

## Implementation Phases

### Phase 1 — 核心读写通路
- MemoryAdapter 基础实现（MCP client + 核心方法）
- crash-triage / crash-analysis 节点实时写入
- plan 节点查询（get_target_profile）
- 开发环境 PGLite + stdio 子进程
- 验证: 一次完整 fuzz 会话后 GBrain 中有 session + crash 记录

### Phase 2 — 经验总结节点 + 批量写入
- memory-summarize 工作流节点实现
- batch_write 攒批 + 重试逻辑
- coverage-analysis / build / run 阶段批量写入
- session 级 page 间 link 关系建立
- 验证: 多次 fuzz 后 GBrain 图谱可遍历 session→crash→target

### Phase 3 — 主动建议机制
- get_suggestions 实现（组合查询 + 建议生成）
- 建议采纳/忽略的 timeline 记录
- 搜索阈值调优
- GitNexus code_query 集成
- 验证: 第二次 fuzz 同一仓库时收到有效策略建议

### Phase 4 — 生产化
- K8s Sidecar + Postgres 迁移
- 跨仓库知识迁移
- 策略效果自动评估
- GBrain doctor 定期维护集成

## File Structure

```
Sherpa 仓库中新增:
harness_generator/src/langchain_agent/
├── memory_adapter.py          # MemoryAdapter 核心类
├── memory/
│   ├── __init__.py
│   ├── schemas.py             # Page frontmatter dataclass
│   ├── slug_resolver.py       # repo_url → slug 转换
│   └── suggestion_builder.py  # 查询结果 → 结构化建议
└── nodes/
    └── memory_summarize.py    # memory-summarize 工作流节点

修改:
harness_generator/src/langchain_agent/
├── workflow_graph.py          # 新增 memory-summarize 节点 + 建议钩子
└── opencode_skills/
    ├── plan/                  # 加入 get_suggestions 调用
    ├── crash_triage/          # 加入 find_similar + 实时写入
    └── crash_analysis/        # 加入 find_similar + 实时写入
```
