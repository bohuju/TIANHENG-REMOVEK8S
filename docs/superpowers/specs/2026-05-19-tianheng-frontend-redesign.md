# TIANHENG 前端全面重构设计

## 概述

将 Sherpa 前端全面重构为 TIANHENG 控制台，以工作流阶段管线可视化为核心，面向安全研究员的多任务并行监控场景。

## 目标用户

安全研究员/模糊测试工程师 — 同时跑多个仓库的 fuzz 任务，最关心：
- 哪个阶段卡住了
- crash 有没有产生
- 覆盖率有没有涨
- 修复回路是否在收敛

## 技术决策

| 层 | 选择 | 原因 |
|---|---|---|
| 框架 | Next.js 14 App Router | 保留，已配置稳定 |
| 数据 | TanStack Query (React Query) | 保留，2s/3s 轮询完美匹配监控场景 |
| 状态 | Zustand | 保留，轻量 UI 状态管理 |
| 样式 | Tailwind CSS + shadcn/ui | 替换 MUI — 管线自定义布局需要灵活的工具，暗色主题更匹配安全工具调性 |
| 管线 | 自绘 SVG + CSS 动画 | 不用 React Flow 等重库，12 个固定节点手写即可 |
| 字体 | JetBrains Mono (代码) + PingFang SC/微软雅黑 (中文UI) | DM Mono 用于数字/英文标题 tabular figures |

## 页面架构

单页应用，从上到下四区布局：

```
TOP BAR       — TIANHENG 控制台 + 系统状态指示 + 快捷操作
METRICS ROW   — 活跃任务数 | Crash 数 | 覆盖率趋势 | 构建成功率 | 运行时长
TASK TABLE    — compact 多任务列表，支持选中切换
PIPELINE VIEW — 选中任务的所有子任务阶段管线展开
  └─ STAGE DETAIL — 点击阶段节点展开详情面板（日志、产物、错误签名）
```

### 页面拆分

从当前单一 `app/page.tsx` 拆为 8 个组件：

| 文件 | 职责 |
|---|---|
| `app/page.tsx` | 布局组装 |
| `components/TopBar.tsx` | 标题、系统状态、操作按钮 |
| `components/MetricsRow.tsx` | 顶部指标卡片 |
| `components/TaskTable.tsx` | 任务列表 compact rows |
| `components/PipelineView.tsx` | 子任务阶段管线 |
| `components/StageNode.tsx` | 单个阶段圆点+连线 |
| `components/StageDetail.tsx` | 阶段详情抽屉面板 |
| `components/LogViewer.tsx` | 日志查看器（保留增强） |
| `components/CreateTaskDialog.tsx` | 新建任务对话框（替代内嵌表单） |

## 工作流管线可视化

### 阶段精简

9 个主流程节点 + 修复回路：

```
init → analysis → plan → synthesize → build → run
                                                  ├─ crash → crash-triage → crash-analysis
                                                  └─ ok → coverage → improve → re-build → re-run

build 失败 → fix-build ─→ build (重试)
run 异常 → fix-harness → re-build → re-run
```

### 视觉编码

- **已完成**：实心绿点 `#22c55e` + 实线
- **进行中**：脉冲动画琥珀黄圆点 `#f0a020` + 虚线
- **失败/错误**：红色圆点 `#ef4444` + 红色连线
- **待执行**：灰色空心圆 `#3e4a5c`
- **修复回路**：弧形回退箭头，标注重试次数
- **Crash 发现**：橙色 `#f97316`（区别于普通错误）

### 交互

- 鼠标悬停节点 → tooltip：阶段耗时、关键产物摘要
- 点击节点 → StageDetail 面板展开：完整日志、产物路径、错误签名
- 新 crash 出现 → 节点闪烁一次红色再稳定为橙色
- 任务完成 → 整行管线短暂全绿

### 阶段状态派生

API 当前不直接返回 "当前阶段" 字段，从 `result` 对象推断：

```
推断优先级：run > crash-analysis > crash-triage > coverage > re-run > re-build
           > improve > build > fix-build > synthesize > plan > analysis > init
```

## 配色方案

暗色底 + 高对比度状态色 + 低饱和度工业蓝灰：

```
背景底：    #0b0f14
面板/卡片： #141a22
边框：      #1e2733
文字主：    #e2e8f0
文字次：    #7c8a9e
运行中：    #f0a020 (琥珀黄)
成功：      #22c55e (翠绿)
失败：      #ef4444 (警示红)
等待：      #3e4a5c (深钢灰)
信息：      #3b82f6 (冷蓝)
Crash：     #f97316 (橙)
```

## 数据流

不变，沿用现有 React Query hooks：
- `useSystemQuery()` → MetricsRow
- `useTasksQuery()` → TaskTable
- `useTaskDetailQuery(activeTaskId)` → PipelineView + StageDetail
- `useConfigQuery()` → CreateTaskDialog

## 实施步骤

1. **Tailwind + shadcn 初始化** — 安装配置 Tailwind，移除 MUI 依赖，设置暗色主题 CSS 变量
2. **TopBar + MetricsRow** — 顶部栏和指标卡片
3. **TaskTable** — 任务列表，替换原 SessionPanel
4. **PipelineView + StageNode** — 核心管线组件（SVG 自绘）
5. **StageDetail + LogViewer** — 阶段详情面板和日志查看器
6. **CreateTaskDialog** — 新建任务对话框
7. **page.tsx 组装** — 连接所有组件，移除旧代码
8. **清理** — 删除旧 MUI 组件，确认样式一致

## 不涉及

- 后端 API 改动
- 数据库 schema 改动
- Docker 配置改动
