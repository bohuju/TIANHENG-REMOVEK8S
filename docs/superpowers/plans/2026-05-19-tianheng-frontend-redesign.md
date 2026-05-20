# TIANHENG 前端全面重构 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Sherpa 前端重构为 TIANHENG 控制台，以暗色主题 + 工作流阶段管线可视化为核心，面向安全研究员的多任务并行监控。

**Architecture:** 单页应用，四区垂直布局（TopBar → MetricsRow → TaskTable → PipelineView + StageDetail）。Tailwind CSS + shadcn/ui 替换 MUI，自绘 SVG 风格管线组件（flexbox + CSS 伪元素实现连线）。数据流沿用现有 React Query hooks，新增 `lib/workflow/stageMapping.ts` 从 `TaskDetail.result` 推断当前阶段。

**Tech Stack:** Next.js 14 App Router, Tailwind CSS 4, shadcn/ui, TanStack Query, Zustand, Vitest + React Testing Library

---

## File Structure

```
frontend-next/
├── app/
│   ├── layout.tsx              # MODIFY — title → "TIANHENG"
│   ├── providers.tsx            # MODIFY — remove MUI, keep QueryClientProvider
│   ├── globals.css              # MODIFY — Tailwind + dark theme vars
│   └── page.tsx                 # MODIFY — new layout assembly
├── components/
│   ├── ui/                      # CREATE — shadcn/ui primitives (via CLI)
│   │   ├── button.tsx
│   │   ├── card.tsx
│   │   ├── dialog.tsx
│   │   ├── input.tsx
│   │   ├── select.tsx
│   │   ├── badge.tsx
│   │   ├── tooltip.tsx
│   │   ├── scroll-area.tsx
│   │   ├── progress.tsx
│   │   ├── switch.tsx
│   │   └── separator.tsx
│   ├── TopBar.tsx               # CREATE
│   ├── MetricsRow.tsx           # CREATE
│   ├── TaskTable.tsx            # CREATE
│   ├── PipelineView.tsx         # CREATE
│   ├── StageNode.tsx            # CREATE
│   ├── StageDetail.tsx          # CREATE
│   ├── LogViewer.tsx            # CREATE (enhanced replacement for LogPanel)
│   ├── CreateTaskDialog.tsx     # CREATE (replacement for inline ConfigPanel form)
│   └── logUtils.ts              # KEEP — no changes
├── lib/
│   ├── api/
│   │   ├── client.ts            # KEEP — no changes
│   │   ├── hooks.ts             # KEEP — no changes
│   │   └── schemas.ts           # KEEP — no changes
│   ├── utils.ts                 # CREATE — shadcn cn() helper
│   └── workflow/
│       └── stageMapping.ts      # CREATE — stage inference logic
├── store/
│   └── useUiStore.ts            # MODIFY — extend state
├── components.json              # CREATE — shadcn config
├── tailwind.config.ts           # CREATE
├── postcss.config.mjs           # CREATE
├── package.json                 # MODIFY — deps
└── vitest.config.ts             # KEEP — no changes
```

---

### Task 1: 依赖替换 — 安装 Tailwind + shadcn/ui，移除 MUI

**Files:**
- Modify: `package.json`

- [ ] **Step 1: 卸载 MUI 相关包**

```bash
cd /home/bohuju/TIanHeng_project/Sherpa/frontend-next
npm uninstall @mui/material @mui/icons-material @emotion/react @emotion/styled
```

Expected: packages removed from node_modules and package.json

- [ ] **Step 2: 安装 Tailwind CSS + PostCSS**

```bash
npm install -D tailwindcss @tailwindcss/postcss postcss
```

Expected: tailwindcss, @tailwindcss/postcss, postcss added to devDependencies

- [ ] **Step 3: 安装 shadcn/ui 依赖**

```bash
npm install class-variance-authority clsx tailwind-merge lucide-react
npm install -D tailwindcss-animate
```

Expected: packages added

- [ ] **Step 4: 提交**

```bash
git add frontend-next/package.json frontend-next/package-lock.json
git commit -m "feat: replace MUI with Tailwind CSS + shadcn/ui dependencies"
```

---

### Task 2: Tailwind + PostCSS 配置

**Files:**
- Create: `frontend-next/postcss.config.mjs`
- Create: `frontend-next/tailwind.config.ts`

- [ ] **Step 1: 创建 postcss.config.mjs**

```javascript
const config = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};

export default config;
```

- [ ] **Step 2: 创建 tailwind.config.ts**

```typescript
import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#0b0f14",
        panel: "#141a22",
        border: "#1e2733",
        "text-primary": "#e2e8f0",
        "text-secondary": "#7c8a9e",
        running: "#f0a020",
        success: "#22c55e",
        error: "#ef4444",
        pending: "#3e4a5c",
        info: "#3b82f6",
        crash: "#f97316",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
        sans: ["PingFang SC", "Microsoft YaHei", "sans-serif"],
        display: ["DM Mono", "PingFang SC", "monospace"],
      },
      keyframes: {
        "pulse-node": {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(240, 160, 32, 0.4)" },
          "50%": { boxShadow: "0 0 0 6px rgba(240, 160, 32, 0)" },
        },
        "flash-crash": {
          "0%": { backgroundColor: "#ef4444" },
          "100%": { backgroundColor: "#f97316" },
        },
      },
      animation: {
        "pulse-node": "pulse-node 1.5s ease-in-out infinite",
        "flash-crash": "flash-crash 0.5s ease-out",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
```

- [ ] **Step 3: 提交**

```bash
git add frontend-next/postcss.config.mjs frontend-next/tailwind.config.ts
git commit -m "feat: add Tailwind CSS + PostCSS configuration with TIANHENG dark theme"
```

---

### Task 3: shadcn/ui 初始化

**Files:**
- Create: `frontend-next/lib/utils.ts`
- Create: `frontend-next/components.json`

- [ ] **Step 1: 创建 lib/utils.ts**

```typescript
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 2: 创建 components.json**

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "default",
  "rsc": true,
  "tsx": true,
  "tailwind": {
    "config": "tailwind.config.ts",
    "css": "app/globals.css",
    "baseColor": "slate",
    "cssVariables": true,
    "prefix": ""
  },
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  }
}
```

- [ ] **Step 3: 安装 shadcn/ui 组件**

```bash
cd /home/bohuju/TIanHeng_project/Sherpa/frontend-next
npx shadcn@latest add button card dialog input select badge tooltip scroll-area progress switch separator --yes
```

Expected: components created in `components/ui/`

- [ ] **Step 4: 提交**

```bash
git add frontend-next/lib/utils.ts frontend-next/components.json frontend-next/components/ui/
git commit -m "feat: initialize shadcn/ui with base components"
```

---

### Task 4: globals.css 重写 + 暗色主题 CSS 变量

**Files:**
- Modify: `frontend-next/app/globals.css`

- [ ] **Step 1: 重写 globals.css**

```css
@import "tailwindcss";

@theme inline {
  --color-background: #0b0f14;
  --color-panel: #141a22;
  --color-border: #1e2733;
  --color-text-primary: #e2e8f0;
  --color-text-secondary: #7c8a9e;
  --color-running: #f0a020;
  --color-success: #22c55e;
  --color-error: #ef4444;
  --color-pending: #3e4a5c;
  --color-info: #3b82f6;
  --color-crash: #f97316;
  --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, monospace;
  --font-sans: "PingFang SC", "Microsoft YaHei", sans-serif;
  --font-display: "DM Mono", "PingFang SC", monospace;
}

* {
  box-sizing: border-box;
}

html,
body {
  margin: 0;
  padding: 0;
  min-height: 100%;
  background-color: var(--color-background);
  color: var(--color-text-primary);
  font-family: var(--font-sans);
}

/* Scrollbar styling */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
::-webkit-scrollbar-track {
  background: var(--color-background);
}
::-webkit-scrollbar-thumb {
  background: var(--color-border);
  border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
  background: var(--color-text-secondary);
}
```

- [ ] **Step 2: 验证构建**

```bash
cd /home/bohuju/TIanHeng_project/Sherpa/frontend-next
npm run build 2>&1 | tail -20
```

Expected: build succeeds (page will be broken visually since we haven't updated components yet, but no compile errors)

- [ ] **Step 3: 提交**

```bash
git add frontend-next/app/globals.css
git commit -m "feat: rewrite globals.css with Tailwind directives and TIANHENG dark theme"
```

---

### Task 5: 阶段状态推断逻辑 + 测试

**Files:**
- Create: `frontend-next/lib/workflow/stageMapping.ts`
- Create: `frontend-next/lib/workflow/stageMapping.test.ts`

- [ ] **Step 1: 编写测试**

```typescript
import { describe, expect, it } from "vitest";
import { inferStage, STAGE_LABELS, type WorkflowStage } from "./stageMapping";

describe("stageMapping", () => {
  it("returns 'init' for empty result", () => {
    expect(inferStage("queued", null)).toBe("init");
  });

  it("returns 'init' for result without known stage fields", () => {
    expect(inferStage("running", { some_unknown: true })).toBe("init");
  });

  it("detects crash-analysis stage", () => {
    expect(
      inferStage("running", { crash_analysis_done: true })
    ).toBe("crash-analysis");
    expect(
      inferStage("running", { crash_analysis_verdict: "true_positive" })
    ).toBe("crash-analysis");
  });

  it("detects crash-triage stage", () => {
    expect(
      inferStage("running", { crash_triage_done: true })
    ).toBe("crash-triage");
    expect(
      inferStage("running", { crash_triage_label: "security" })
    ).toBe("crash-triage");
  });

  it("detects coverage-analysis stage", () => {
    expect(
      inferStage("running", { coverage_history: [] })
    ).toBe("coverage-analysis");
    expect(
      inferStage("running", { coverage_target_name: "foo" })
    ).toBe("coverage-analysis");
  });

  it("detects run stage", () => {
    expect(inferStage("running", { run_rc: 0 })).toBe("run");
    expect(inferStage("running", { run_details: [] })).toBe("run");
  });

  it("detects build stage", () => {
    expect(inferStage("running", { build_rc: 0 })).toBe("build");
    expect(inferStage("running", { build_error_signature: "..." })).toBe(
      "build"
    );
  });

  it("detects fix-build stage", () => {
    expect(
      inferStage("running", { fix_build_attempts: 1, build_error_signature_before: "x" })
    ).toBe("fix-build");
  });

  it("detects synthesize stage", () => {
    expect(
      inferStage("running", { synthesize_selected_target_name: "foo" })
    ).toBe("synthesize");
  });

  it("detects plan stage", () => {
    expect(
      inferStage("running", { execution_plan_path: "/tmp/plan" })
    ).toBe("plan");
  });

  it("detects analysis stage", () => {
    expect(
      inferStage("running", { analysis_done: true })
    ).toBe("analysis");
  });

  it("returns 'init' when status is queued", () => {
    expect(inferStage("queued", null)).toBe("init");
  });

  it("returns 'done' when status is success", () => {
    expect(inferStage("success", null)).toBe("done");
  });

  it("all stages have labels", () => {
    const stages: WorkflowStage[] = [
      "init", "analysis", "plan", "synthesize", "build", "fix-build",
      "run", "crash-triage", "crash-analysis", "coverage-analysis",
      "improve-harness", "re-build", "re-run", "fix-harness", "done",
    ];
    for (const s of stages) {
      expect(STAGE_LABELS[s]).toBeDefined();
    }
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/bohuju/TIanHeng_project/Sherpa/frontend-next
npx vitest run lib/workflow/stageMapping.test.ts
```

Expected: FAIL — module not found

- [ ] **Step 3: 实现 stageMapping.ts**

```typescript
export type WorkflowStage =
  | "init"
  | "analysis"
  | "plan"
  | "synthesize"
  | "build"
  | "fix-build"
  | "run"
  | "crash-triage"
  | "crash-analysis"
  | "coverage-analysis"
  | "improve-harness"
  | "re-build"
  | "re-run"
  | "fix-harness"
  | "done";

export const STAGE_LABELS: Record<WorkflowStage, string> = {
  "init": "初始化",
  "analysis": "分析",
  "plan": "规划",
  "synthesize": "生成",
  "build": "构建",
  "fix-build": "修复构建",
  "run": "运行",
  "crash-triage": "Crash 分类",
  "crash-analysis": "Crash 分析",
  "coverage-analysis": "覆盖率分析",
  "improve-harness": "改进 Harness",
  "re-build": "重新构建",
  "re-run": "重新运行",
  "fix-harness": "修复 Harness",
  "done": "完成",
};

export const MAINLINE_STAGES: WorkflowStage[] = [
  "init",
  "analysis",
  "plan",
  "synthesize",
  "build",
  "run",
];

/**
 * Infer the current workflow stage from a child job's status and result object.
 * Priority order (highest to lowest):
 *   run > crash-analysis > crash-triage > coverage-analysis > improve-harness
 *   > re-run > re-build > fix-harness > build > fix-build > synthesize
 *   > plan > analysis > init
 *
 * Returns 'done' for terminal success, 'init' for queued/unstarted.
 */
export function inferStage(
  status: string,
  result: Record<string, unknown> | null | undefined,
): WorkflowStage {
  const s = (status || "").toLowerCase();

  if (s === "success") return "done";

  if (!result || Object.keys(result).length === 0) {
    return s === "queued" ? "init" : "init";
  }

  // Run stage indicators (highest priority — once we're running, we're past build)
  if ("run_rc" in result || "run_details" in result || "run_error_kind" in result) {
    // Check if after run we went into crash or coverage paths
    if ("crash_analysis_done" in result || "crash_analysis_verdict" in result) {
      return "crash-analysis";
    }
    if ("crash_triage_done" in result || "crash_triage_label" in result) {
      return "crash-triage";
    }
    if ("coverage_history" in result || "coverage_target_name" in result || "coverage_plateau_streak" in result) {
      return "coverage-analysis";
    }
    if ("improve_harness" in result || "coverage_improve_mode" in result) {
      return "improve-harness";
    }
    if ("re_run_done" in result || "re_run_ok" in result) {
      return "re-run";
    }
    if ("re_build_done" in result || "re_build_ok" in result) {
      return "re-build";
    }
    if ("fix_harness_attempts" in result) {
      return "fix-harness";
    }
    return "run";
  }

  // Build stage indicators
  if ("build_rc" in result || "build_error_signature" in result || "build_stdout_tail" in result) {
    if ("fix_build_attempts" in result && Number(result.fix_build_attempts) > 0) {
      return "fix-build";
    }
    return "build";
  }

  // Synthesize stage indicators
  if (
    "synthesize_selected_target_name" in result ||
    "synthesize_selected_target_api" in result ||
    "synthesize_target_drifted" in result
  ) {
    return "synthesize";
  }

  // Plan stage indicators
  if ("execution_plan_path" in result || "selected_targets_path" in result || "harness_index_path" in result) {
    return "plan";
  }

  // Analysis stage indicators
  if ("analysis_done" in result || "analysis_report_path" in result || "analysis_error" in result) {
    return "analysis";
  }

  return "init";
}

/** Determine the visual state of a stage node. */
export type StageState = "completed" | "active" | "error" | "pending";

export function getStageState(
  currentStage: WorkflowStage,
  stageIndex: number,
  hasError: boolean,
): StageState {
  const allStages = MAINLINE_STAGES;
  const currentIdx = allStages.indexOf(currentStage);

  // If the job has an error, mark the current stage as error
  if (hasError && allStages[stageIndex] === currentStage) return "error";

  if (stageIndex < currentIdx) return "completed";
  if (stageIndex === currentIdx) {
    // If we're past the main line (in repair or crash path), show previous stages as completed
    if (currentIdx === -1) return "completed";
    return "active";
  }
  return "pending";
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/bohuju/TIanHeng_project/Sherpa/frontend-next
npx vitest run lib/workflow/stageMapping.test.ts
```

Expected: all tests PASS

- [ ] **Step 5: 提交**

```bash
git add frontend-next/lib/workflow/
git commit -m "feat: add workflow stage inference logic with tests"
```

---

### Task 6: Zustand store 扩展

**Files:**
- Modify: `frontend-next/store/useUiStore.ts`

- [ ] **Step 1: 更新 useUiStore.ts**

Replace the entire file:

```typescript
import { create } from "zustand";

const ACTIVE_TASK_KEY = "sherpa_active_task_id";

function readActiveTask(): string {
  if (typeof window === "undefined") return "";
  try {
    return localStorage.getItem(ACTIVE_TASK_KEY) || "";
  } catch {
    return "";
  }
}

function writeActiveTask(taskId: string) {
  if (typeof window === "undefined") return;
  try {
    if (taskId) localStorage.setItem(ACTIVE_TASK_KEY, taskId);
    else localStorage.removeItem(ACTIVE_TASK_KEY);
  } catch {
    // noop
  }
}

interface UiState {
  activeTaskId: string;
  logFilter: "all" | "warn" | "error";
  logKeyword: string;
  autoScrollEnabled: boolean;
  selectedChildId: string | null;
  selectedStage: string | null;
  detailPanelOpen: boolean;
  createDialogOpen: boolean;
  hydrated: boolean;
  hydrate: () => void;
  setActiveTaskId: (taskId: string) => void;
  setLogFilter: (filter: "all" | "warn" | "error") => void;
  setLogKeyword: (keyword: string) => void;
  setAutoScrollEnabled: (enabled: boolean) => void;
  setSelectedChildId: (childId: string | null) => void;
  setSelectedStage: (stage: string | null) => void;
  setDetailPanelOpen: (open: boolean) => void;
  setCreateDialogOpen: (open: boolean) => void;
}

export const useUiStore = create<UiState>((set) => ({
  activeTaskId: "",
  logFilter: "all",
  logKeyword: "",
  autoScrollEnabled: true,
  selectedChildId: null,
  selectedStage: null,
  detailPanelOpen: false,
  createDialogOpen: false,
  hydrated: false,
  hydrate: () => {
    set({ activeTaskId: readActiveTask(), hydrated: true });
  },
  setActiveTaskId: (taskId: string) => {
    writeActiveTask(taskId);
    set({
      activeTaskId: taskId,
      autoScrollEnabled: true,
      selectedChildId: null,
      selectedStage: null,
      detailPanelOpen: false,
    });
  },
  setLogFilter: (filter) => set({ logFilter: filter }),
  setLogKeyword: (keyword) => set({ logKeyword: keyword }),
  setAutoScrollEnabled: (enabled) => set({ autoScrollEnabled: enabled }),
  setSelectedChildId: (childId) => set({ selectedChildId: childId }),
  setSelectedStage: (stage) =>
    set({ selectedStage: stage, detailPanelOpen: stage !== null }),
  setDetailPanelOpen: (open) => set({ detailPanelOpen: open }),
  setCreateDialogOpen: (open) => set({ createDialogOpen: open }),
}));
```

- [ ] **Step 2: 提交**

```bash
git add frontend-next/store/useUiStore.ts
git commit -m "feat: extend Zustand store with stage selection and dialog state"
```

---

### Task 7: providers.tsx 重构

**Files:**
- Modify: `frontend-next/app/providers.tsx`

- [ ] **Step 1: 移除 MUI ThemeProvider，保留 QueryClientProvider**

```typescript
"use client";

import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 1_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend-next/app/providers.tsx
git commit -m "refactor: remove MUI ThemeProvider from providers, keep QueryClientProvider"
```

---

### Task 8: layout.tsx 更新

**Files:**
- Modify: `frontend-next/app/layout.tsx`

- [ ] **Step 1: 更新 metadata**

```typescript
import type { Metadata } from "next";
import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "TIANHENG 控制台",
  description: "TIANHENG fuzz orchestration console",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className="dark">
      <body className="min-h-screen bg-background text-text-primary antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend-next/app/layout.tsx
git commit -m "feat: update layout metadata to TIANHENG branding"
```

---

### Task 9: TopBar 组件

**Files:**
- Create: `frontend-next/components/TopBar.tsx`

- [ ] **Step 1: 创建 TopBar.tsx**

```typescript
"use client";

import { Plus, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useUiStore } from "@/store/useUiStore";
import { useSystemQuery } from "@/lib/api/hooks";

export function TopBar() {
  const setCreateDialogOpen = useUiStore((s) => s.setCreateDialogOpen);
  const system = useSystemQuery();

  return (
    <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <div className="flex h-14 items-center justify-between px-4">
        <div className="flex items-center gap-3">
          <h1 className="font-display text-lg font-bold tracking-tight text-text-primary">
            TIANHENG
          </h1>
          <span className="text-xs text-text-secondary font-mono">控制台</span>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs text-text-secondary">
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                system.data?.ok ? "bg-success" : "bg-error"
              }`}
            />
            {system.data?.ok ? "系统正常" : "系统离线"}
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={() => setCreateDialogOpen(true)}
            className="h-8 gap-1.5 border-border text-text-secondary hover:text-text-primary"
          >
            <Plus className="h-3.5 w-3.5" />
            新建任务
          </Button>
        </div>
      </div>
    </header>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend-next/components/TopBar.tsx
git commit -m "feat: add TopBar component with system status and create task button"
```

---

### Task 10: MetricsRow 组件

**Files:**
- Create: `frontend-next/components/MetricsRow.tsx`

- [ ] **Step 1: 创建 MetricsRow.tsx**

```typescript
"use client";

import { Bug, Clock, FlaskConical, TrendingUp } from "lucide-react";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import type { SystemStatus } from "@/lib/api/schemas";

function fmtDuration(sec?: number): string {
  if (!Number.isFinite(sec) || (sec as number) < 0) return "--";
  const s = Math.floor(sec as number);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${r}s`;
  return `${r}s`;
}

interface MetricCardProps {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  accent?: string;
}

function MetricCard({ icon, label, value, accent }: MetricCardProps) {
  return (
    <Card className="border-border bg-panel">
      <CardContent className="flex items-center gap-3 p-3">
        <div className={`flex h-9 w-9 items-center justify-center rounded-lg bg-background ${accent || "text-info"}`}>
          {icon}
        </div>
        <div>
          <p className="text-xs text-text-secondary">{label}</p>
          <p className="font-display text-lg font-semibold tabular-nums">{value}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export function MetricsRow({ data }: { data?: SystemStatus }) {
  const jobs = data?.jobs;

  return (
    <div className="grid grid-cols-2 gap-2 px-4 md:grid-cols-4 lg:grid-cols-5">
      <MetricCard
        icon={<FlaskConical className="h-4 w-4" />}
        label="活跃任务"
        value={jobs?.running ?? 0}
        accent="text-running"
      />
      <MetricCard
        icon={<Bug className="h-4 w-4" />}
        label="总任务"
        value={`${jobs?.success ?? 0}/${jobs?.total ?? 0}`}
        accent="text-success"
      />
      <MetricCard
        icon={<TrendingUp className="h-4 w-4" />}
        label="失败"
        value={jobs?.error ?? 0}
        accent="text-error"
      />
      <MetricCard
        icon={<Clock className="h-4 w-4" />}
        label="运行时长"
        value={fmtDuration(data?.uptime_sec)}
        accent="text-text-secondary"
      />
      <MetricCard
        icon={<Clock className="h-4 w-4" />}
        label="排队"
        value={jobs?.queued ?? 0}
        accent="text-info"
      />
    </div>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend-next/components/MetricsRow.tsx
git commit -m "feat: add MetricsRow component with job stat cards"
```

---

### Task 11: TaskTable 组件

**Files:**
- Create: `frontend-next/components/TaskTable.tsx`

- [ ] **Step 1: 创建 TaskTable.tsx**

```typescript
"use client";

import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { TaskSummary } from "@/lib/api/schemas";
import { useUiStore } from "@/store/useUiStore";

function shortId(id: string): string {
  return id.slice(0, 8);
}

function statusVariant(
  status: string,
): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "success":
      return "default";
    case "error":
      return "destructive";
    case "running":
      return "secondary";
    default:
      return "outline";
  }
}

export function TaskTable({ tasks }: { tasks: TaskSummary[] }) {
  const activeTaskId = useUiStore((s) => s.activeTaskId);
  const setActiveTaskId = useUiStore((s) => s.setActiveTaskId);

  if (!tasks.length) {
    return (
      <Card className="border-border bg-panel mx-4">
        <CardContent className="py-8 text-center text-text-secondary text-sm">
          暂无任务 — 点击右上角"新建任务"开始
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="px-4">
      <Card className="border-border bg-panel">
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-text-secondary">
                  <th className="px-3 py-2 text-left font-medium w-28">任务 ID</th>
                  <th className="px-3 py-2 text-left font-medium">仓库</th>
                  <th className="px-3 py-2 text-left font-medium w-20">状态</th>
                  <th className="px-3 py-2 text-left font-medium w-28">子任务</th>
                  <th className="px-3 py-2 text-left font-medium w-36">更新时间</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => {
                  const isActive = task.job_id === activeTaskId;
                  const cs = task.children_status;
                  return (
                    <tr
                      key={task.job_id}
                      onClick={() => setActiveTaskId(task.job_id)}
                      className={`cursor-pointer border-b border-border transition-colors hover:bg-background ${
                        isActive ? "bg-background ring-1 ring-inset ring-info/30" : ""
                      }`}
                    >
                      <td className="px-3 py-2 font-mono text-xs">
                        #{shortId(task.job_id)}
                      </td>
                      <td className="px-3 py-2 max-w-48 truncate text-text-secondary">
                        {task.repo || "--"}
                      </td>
                      <td className="px-3 py-2">
                        <Badge variant={statusVariant(task.status)} className="text-xs">
                          {task.status}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 font-mono text-xs tabular-nums">
                        <span className="text-success">{(cs as any)?.success ?? 0}</span>
                        <span className="text-text-secondary">/</span>
                        <span className="text-error">{(cs as any)?.error ?? 0}</span>
                        <span className="text-text-secondary">/</span>
                        <span className="text-text-primary">{(cs as any)?.total ?? 0}</span>
                      </td>
                      <td className="px-3 py-2 text-xs text-text-secondary">
                        {task.updated_at_iso
                          ? new Date(task.updated_at_iso).toLocaleTimeString("zh-CN", {
                              hour: "2-digit",
                              minute: "2-digit",
                              second: "2-digit",
                            })
                          : "--"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend-next/components/TaskTable.tsx
git commit -m "feat: add TaskTable component replacing SessionPanel"
```

---

### Task 12: StageNode 组件

**Files:**
- Create: `frontend-next/components/StageNode.tsx`

- [ ] **Step 1: 创建 StageNode.tsx**

```typescript
"use client";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { StageState } from "@/lib/workflow/stageMapping";

interface StageNodeProps {
  label: string;
  state: StageState;
  isLast: boolean;
  meta?: string;
  onClick?: () => void;
}

export function StageNode({ label, state, isLast, meta, onClick }: StageNodeProps) {
  return (
    <div className="flex items-center">
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={onClick}
            className={cn(
              "relative flex h-3 w-3 shrink-0 items-center justify-center rounded-full transition-colors",
              state === "completed" && "bg-success",
              state === "active" && "bg-running animate-pulse-node",
              state === "error" && "bg-error",
              state === "pending" && "bg-pending",
            )}
          >
            <span className="absolute -bottom-4 whitespace-nowrap text-[10px] text-text-secondary">
              {label}
            </span>
          </button>
        </TooltipTrigger>
        {meta ? (
          <TooltipContent side="top" className="bg-panel border-border text-text-primary text-xs">
            {meta}
          </TooltipContent>
        ) : null}
      </Tooltip>

      {!isLast && (
        <div
          className={cn(
            "mx-0.5 h-px w-4 shrink-0 transition-colors sm:w-6 md:w-8",
            state === "completed" && "bg-success",
            state === "active" && "bg-running/50",
            state === "error" && "bg-error",
            state === "pending" && "bg-pending",
          )}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend-next/components/StageNode.tsx
git commit -m "feat: add StageNode component for pipeline visualization"
```

---

### Task 13: PipelineView 组件

**Files:**
- Create: `frontend-next/components/PipelineView.tsx`

- [ ] **Step 1: 创建 PipelineView.tsx**

```typescript
"use client";

import { useMemo } from "react";
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { StageNode } from "./StageNode";
import { useUiStore } from "@/store/useUiStore";
import {
  type WorkflowStage,
  MAINLINE_STAGES,
  STAGE_LABELS,
  inferStage,
  getStageState,
} from "@/lib/workflow/stageMapping";
import type { TaskDetail, childJobSchema } from "@/lib/api/schemas";
import type { z } from "zod";

type ChildJob = z.infer<typeof childJobSchema>;

function shortId(id: string): string {
  return id.slice(0, 8);
}

function extractMeta(
  child: ChildJob,
  stage: WorkflowStage,
): string | undefined {
  const r = child.result as Record<string, unknown> | null | undefined;
  if (!r) return undefined;

  switch (stage) {
    case "build":
    case "fix-build": {
      const sig = r.build_error_signature;
      if (sig) return `构建错误: ${String(sig).slice(0, 40)}`;
      return `构建完成 rc=${r.build_rc ?? "?"}`;
    }
    case "run": {
      const kind = r.run_error_kind;
      if (kind) return `运行异常: ${kind}`;
      return `运行 rc=${r.run_rc ?? "?"}`;
    }
    case "crash-triage": {
      const label = r.crash_triage_label;
      return label ? `分类: ${label}` : undefined;
    }
    case "crash-analysis": {
      const verdict = r.crash_analysis_verdict;
      return verdict ? `判定: ${verdict}` : undefined;
    }
    case "coverage-analysis": {
      const cov = r.coverage_last_max_cov;
      return cov !== undefined ? `覆盖率: ${cov}%` : undefined;
    }
    default:
      return undefined;
  }
}

function statusIcon(status: string) {
  switch (status) {
    case "success":
      return <CheckCircle2 className="h-3.5 w-3.5 text-success" />;
    case "error":
      return <AlertTriangle className="h-3.5 w-3.5 text-error" />;
    case "running":
      return <Loader2 className="h-3.5 w-3.5 animate-spin text-running" />;
    default:
      return null;
  }
}

interface PipelineRowProps {
  child: ChildJob;
  onStageClick: (childId: string, stage: WorkflowStage) => void;
}

function PipelineRow({ child, onStageClick }: PipelineRowProps) {
  const result = child.result as Record<string, unknown> | null | undefined;
  const currentStage = inferStage(child.status, result);
  const hasError = child.status === "error";

  // Show extended stages if the job has gone beyond mainline
  const showCrashPath =
    currentStage === "crash-triage" || currentStage === "crash-analysis";
  const showCoveragePath =
    currentStage === "coverage-analysis" ||
    currentStage === "improve-harness" ||
    currentStage === "re-build" ||
    currentStage === "re-run";

  return (
    <div className="flex items-center gap-2 py-1.5 px-2 rounded hover:bg-background/50 transition-colors">
      {/* Child info */}
      <div className="flex items-center gap-1.5 w-48 shrink-0">
        {statusIcon(child.status)}
        <span className="font-mono text-xs text-text-primary">
          #{shortId(child.job_id)}
        </span>
        <Badge variant="outline" className="text-[10px] px-1 py-0 h-4 border-border text-text-secondary">
          {child.status === "running"
            ? "运行中"
            : child.status === "error"
              ? "失败"
              : child.status === "success"
                ? "完成"
                : child.status}
        </Badge>
      </div>

      {/* Mainline pipeline */}
      <div className="flex items-center">
        {MAINLINE_STAGES.map((stage, idx) => {
          const isInMainline = MAINLINE_STAGES.includes(currentStage);
          const state = getStageState(
            isInMainline ? currentStage : "done",
            idx,
            hasError,
          );
          return (
            <StageNode
              key={stage}
              label={STAGE_LABELS[stage]}
              state={state}
              isLast={idx === MAINLINE_STAGES.length - 1 && !showCrashPath && !showCoveragePath}
              meta={extractMeta(child, stage)}
              onClick={() => onStageClick(child.job_id, stage)}
            />
          );
        })}
      </div>

      {/* Crash path extension */}
      {showCrashPath && (
        <div className="flex items-center">
          <div className="mx-0.5 h-px w-3 bg-success" />
          {(["crash-triage", "crash-analysis"] as WorkflowStage[]).map(
            (stage) => {
              const crashStages = ["crash-triage", "crash-analysis"];
              const stageIdx = crashStages.indexOf(stage);
              const currentIdx = crashStages.indexOf(currentStage);

              const s: ReturnType<typeof getStageState> =
                stageIdx === currentIdx
                  ? hasError
                    ? "error"
                    : "active"
                  : stageIdx < currentIdx
                    ? "completed"
                    : "pending";

              return (
                <StageNode
                  key={stage}
                  label={STAGE_LABELS[stage]}
                  state={s}
                  isLast={stage === "crash-analysis"}
                  meta={extractMeta(child, stage)}
                  onClick={() => onStageClick(child.job_id, stage)}
                />
              );
            },
          )}
        </div>
      )}

      {/* Coverage path extension */}
      {showCoveragePath && (
        <div className="flex items-center">
          <div className="mx-0.5 h-px w-3 bg-success" />
          {(["coverage-analysis", "improve-harness", "re-build", "re-run"] as WorkflowStage[]).map(
            (stage, idx, arr) => {
              const s: ReturnType<typeof getStageState> =
                currentStage === stage
                  ? hasError
                    ? "error"
                    : "active"
                  : arr.indexOf(currentStage as any) > arr.indexOf(stage)
                    ? "completed"
                    : "pending";

              return (
                <StageNode
                  key={stage}
                  label={STAGE_LABELS[stage]}
                  state={s}
                  isLast={idx === arr.length - 1}
                  meta={extractMeta(child, stage)}
                  onClick={() => onStageClick(child.job_id, stage)}
                />
              );
            },
          )}
        </div>
      )}
    </div>
  );
}

export function PipelineView({ detail }: { detail?: TaskDetail }) {
  const setSelectedChildId = useUiStore((s) => s.setSelectedChildId);
  const setSelectedStage = useUiStore((s) => s.setSelectedStage);
  const selectedChildId = useUiStore((s) => s.selectedChildId);
  const selectedStage = useUiStore((s) => s.selectedStage);

  const children = detail?.children || [];

  const handleStageClick = (childId: string, stage: WorkflowStage) => {
    setSelectedChildId(childId);
    setSelectedStage(stage);
  };

  if (!children.length) {
    return (
      <Card className="border-border bg-panel mx-4">
        <CardContent className="py-8 text-center text-text-secondary text-sm">
          {detail
            ? "暂无子任务数据"
            : "选择一个任务查看工作流管线"}
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="px-4">
      <Card className="border-border bg-panel">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-text-secondary flex items-center gap-2">
            工作流管线
            <span className="text-xs font-normal text-text-secondary">
              ({children.length} 个子任务)
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <ScrollArea className="max-h-[400px]">
            <div className="p-2 space-y-0.5">
              {children.map((child) => (
                <PipelineRow
                  key={child.job_id}
                  child={child}
                  onStageClick={handleStageClick}
                />
              ))}
            </div>
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend-next/components/PipelineView.tsx
git commit -m "feat: add PipelineView component with per-child stage rows"
```

---

### Task 14: StageDetail 组件

**Files:**
- Create: `frontend-next/components/StageDetail.tsx`

- [ ] **Step 1: 创建 StageDetail.tsx**

```typescript
"use client";

import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useUiStore } from "@/store/useUiStore";
import { STAGE_LABELS } from "@/lib/workflow/stageMapping";
import type { TaskDetail } from "@/lib/api/schemas";
import { LogViewer } from "./LogViewer";

export function StageDetail({ detail }: { detail?: TaskDetail }) {
  const selectedChildId = useUiStore((s) => s.selectedChildId);
  const selectedStage = useUiStore((s) => s.selectedStage);
  const setSelectedStage = useUiStore((s) => s.setSelectedStage);

  if (!selectedStage || !selectedChildId) return null;

  const child = detail?.children?.find((c) => c.job_id === selectedChildId);
  if (!child) return null;

  const result = (child.result || {}) as Record<string, unknown>;

  // Collect all keys from result that are relevant
  const relevantKeys = Object.keys(result).filter(
    (k) =>
      !k.startsWith("_") &&
      k !== "log" &&
      typeof result[k] !== "object",
  );

  return (
    <div className="px-4">
      <Card className="border-border bg-panel">
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium text-text-primary">
            阶段详情: {STAGE_LABELS[selectedStage as keyof typeof STAGE_LABELS] || selectedStage}
            <span className="ml-2 font-mono text-xs text-text-secondary">
              #{selectedChildId.slice(0, 8)}
            </span>
          </CardTitle>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 text-text-secondary hover:text-text-primary"
            onClick={() => setSelectedStage(null)}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {/* Result fields */}
          {relevantKeys.length > 0 && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {relevantKeys.map((key) => (
                <div key={key} className="rounded bg-background px-2 py-1">
                  <p className="text-[10px] text-text-secondary font-mono">{key}</p>
                  <p className="text-xs text-text-primary truncate">
                    {String(result[key])}
                  </p>
                </div>
              ))}
            </div>
          )}

          {/* Child log */}
          <div>
            <p className="text-xs text-text-secondary mb-1">子任务日志</p>
            <LogViewer rawLog={child.log || ""} compact />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend-next/components/StageDetail.tsx
git commit -m "feat: add StageDetail panel for stage-level drill-down"
```

---

### Task 15: LogViewer 组件

**Files:**
- Create: `frontend-next/components/LogViewer.tsx`

- [ ] **Step 1: 创建 LogViewer.tsx**

```typescript
"use client";

import { useEffect, useMemo, useRef } from "react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { useUiStore } from "@/store/useUiStore";
import { filterLogLines } from "./logUtils";

interface LogViewerProps {
  rawLog: string;
  compact?: boolean;
}

export function LogViewer({ rawLog, compact = false }: LogViewerProps) {
  const logFilter = useUiStore((s) => s.logFilter);
  const logKeyword = useUiStore((s) => s.logKeyword);
  const autoScrollEnabled = useUiStore((s) => s.autoScrollEnabled);
  const setLogFilter = useUiStore((s) => s.setLogFilter);
  const setLogKeyword = useUiStore((s) => s.setLogKeyword);
  const setAutoScrollEnabled = useUiStore((s) => s.setAutoScrollEnabled);

  const logRef = useRef<HTMLDivElement | null>(null);

  const filteredLines = useMemo(() => {
    return filterLogLines(rawLog, logFilter, logKeyword);
  }, [rawLog, logFilter, logKeyword]);

  useEffect(() => {
    if (!autoScrollEnabled || !logRef.current) return;
    logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [filteredLines, autoScrollEnabled]);

  const onScroll: React.UIEventHandler<HTMLDivElement> = (e) => {
    const el = e.currentTarget;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    if (!nearBottom && autoScrollEnabled) setAutoScrollEnabled(false);
    if (nearBottom && !autoScrollEnabled) setAutoScrollEnabled(true);
  };

  const maxH = compact ? "max-h-[200px]" : "max-h-[420px]";

  return (
    <div className="space-y-1.5">
      {!compact && (
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Select
              value={logFilter}
              onValueChange={(v) => setLogFilter(v as "all" | "warn" | "error")}
            >
              <SelectTrigger className="h-7 w-[100px] text-xs border-border bg-background text-text-primary">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="border-border bg-panel text-text-primary">
                <SelectItem value="all">全部</SelectItem>
                <SelectItem value="warn">Warn+</SelectItem>
                <SelectItem value="error">Error</SelectItem>
              </SelectContent>
            </Select>
            <Input
              placeholder="关键词"
              value={logKeyword}
              onChange={(e) => setLogKeyword(e.target.value)}
              className="h-7 w-32 text-xs border-border bg-background text-text-primary"
            />
          </div>
          {!autoScrollEnabled && (
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs border-border text-text-secondary"
              onClick={() => setAutoScrollEnabled(true)}
            >
              恢复自动滚动
            </Button>
          )}
        </div>
      )}

      <div
        ref={logRef}
        onScroll={onScroll}
        className={`overflow-auto rounded border border-border bg-background p-2 font-mono text-xs leading-relaxed text-text-primary whitespace-pre-wrap ${maxH}`}
      >
        {filteredLines.length ? filteredLines.join("\n") : "暂无日志输出"}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend-next/components/LogViewer.tsx
git commit -m "feat: add LogViewer component with filter controls"
```

---

### Task 16: CreateTaskDialog 组件

**Files:**
- Create: `frontend-next/components/CreateTaskDialog.tsx`

- [ ] **Step 1: 创建 CreateTaskDialog.tsx**

```typescript
"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { useUiStore } from "@/store/useUiStore";
import { useConfigQuery, useSubmitTaskMutation } from "@/lib/api/hooks";

export function CreateTaskDialog() {
  const open = useUiStore((s) => s.createDialogOpen);
  const setOpen = useUiStore((s) => s.setCreateDialogOpen);
  const setActiveTaskId = useUiStore((s) => s.setActiveTaskId);
  const cfgQuery = useConfigQuery();
  const submitTask = useSubmitTaskMutation();

  const [repoUrl, setRepoUrl] = useState("");
  const [totalBudget, setTotalBudget] = useState("900");
  const [runBudget, setRunBudget] = useState("900");
  const [totalUnlimited, setTotalUnlimited] = useState(false);
  const [runUnlimited, setRunUnlimited] = useState(false);
  const [statusText, setStatusText] = useState("");
  const [statusError, setStatusError] = useState(false);

  useEffect(() => {
    if (!cfgQuery.data) return;
    const b = Number(cfgQuery.data.fuzz_time_budget);
    const isUnlimited = Number.isFinite(b) && b <= 0;
    const v = !isUnlimited && Number.isFinite(b) && b > 0 ? Math.floor(b) : 900;
    setTotalBudget(String(v));
    setRunBudget(String(v));
    setTotalUnlimited(isUnlimited);
    setRunUnlimited(isUnlimited);
  }, [cfgQuery.data]);

  const handleSubmit = async () => {
    const repo = repoUrl.trim();
    if (!repo) {
      setStatusText("仓库 URL 不能为空");
      setStatusError(true);
      return;
    }
    const total = totalUnlimited ? 0 : parseInt(totalBudget, 10) || 900;
    const run = runUnlimited ? 0 : parseInt(runBudget, 10) || total || 900;

    try {
      setStatusText("提交中...");
      setStatusError(false);
      const res = await submitTask.mutateAsync({
        repoUrl: repo,
        totalTimeBudget: total,
        runTimeBudget: run,
        maxTokens: 0,
      });
      setActiveTaskId(res.job_id);
      setStatusText(`任务已提交: ${res.job_id}`);
      setStatusError(false);
      setRepoUrl("");
      setTimeout(() => setOpen(false), 1000);
    } catch (e) {
      setStatusText(e instanceof Error ? e.message : "提交失败");
      setStatusError(true);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="border-border bg-panel text-text-primary max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-text-primary">新建 Fuzz 任务</DialogTitle>
          <DialogDescription className="text-text-secondary">
            输入目标仓库 URL 并配置时间预算
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label className="text-xs text-text-secondary">仓库 URL</Label>
            <Input
              placeholder="https://github.com/madler/zlib.git"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              className="border-border bg-background text-text-primary"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label className="text-xs text-text-secondary">总时长 (秒)</Label>
                <div className="flex items-center gap-1.5">
                  <Label className="text-[10px] text-text-secondary">不限</Label>
                  <Switch
                    checked={totalUnlimited}
                    onCheckedChange={setTotalUnlimited}
                    className="scale-75"
                  />
                </div>
              </div>
              <Input
                type="number"
                value={totalBudget}
                onChange={(e) => setTotalBudget(e.target.value)}
                disabled={totalUnlimited}
                className="border-border bg-background text-text-primary"
              />
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label className="text-xs text-text-secondary">单次时长 (秒)</Label>
                <div className="flex items-center gap-1.5">
                  <Label className="text-[10px] text-text-secondary">不限</Label>
                  <Switch
                    checked={runUnlimited}
                    onCheckedChange={setRunUnlimited}
                    className="scale-75"
                  />
                </div>
              </div>
              <Input
                type="number"
                value={runBudget}
                onChange={(e) => setRunBudget(e.target.value)}
                disabled={runUnlimited}
                className="border-border bg-background text-text-primary"
              />
            </div>
          </div>

          <Button
            onClick={handleSubmit}
            disabled={submitTask.isPending}
            className="w-full"
          >
            {submitTask.isPending ? "提交中..." : "提交任务"}
          </Button>

          {statusText && (
            <p
              className={`text-xs ${statusError ? "text-error" : "text-success"}`}
            >
              {statusText}
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend-next/components/CreateTaskDialog.tsx
git commit -m "feat: add CreateTaskDialog replacing inline ConfigPanel form"
```

---

### Task 17: page.tsx 组装

**Files:**
- Modify: `frontend-next/app/page.tsx`

- [ ] **Step 1: 重写 page.tsx**

```typescript
"use client";

import { useEffect, useMemo } from "react";
import { TopBar } from "@/components/TopBar";
import { MetricsRow } from "@/components/MetricsRow";
import { TaskTable } from "@/components/TaskTable";
import { PipelineView } from "@/components/PipelineView";
import { StageDetail } from "@/components/StageDetail";
import { CreateTaskDialog } from "@/components/CreateTaskDialog";
import { LogViewer } from "@/components/LogViewer";
import { Separator } from "@/components/ui/separator";
import {
  useSystemQuery,
  useTaskDetailQuery,
  useTasksQuery,
  useStopTaskMutation,
} from "@/lib/api/hooks";
import { useUiStore } from "@/store/useUiStore";

export default function HomePage() {
  const activeTaskId = useUiStore((s) => s.activeTaskId);
  const hydrate = useUiStore((s) => s.hydrate);
  const hydrated = useUiStore((s) => s.hydrated);
  const setActiveTaskId = useUiStore((s) => s.setActiveTaskId);

  const system = useSystemQuery();
  const tasks = useTasksQuery();
  const detail = useTaskDetailQuery(activeTaskId || null);

  useEffect(() => {
    if (!hydrated) hydrate();
  }, [hydrate, hydrated]);

  useEffect(() => {
    if (!tasks.data?.length) return;
    if (activeTaskId) {
      const exists = tasks.data.some((t) => t.job_id === activeTaskId);
      if (!exists) setActiveTaskId(tasks.data[0].job_id);
      return;
    }
    setActiveTaskId(tasks.data[0].job_id);
  }, [tasks.data, activeTaskId, setActiveTaskId]);

  const activeTask = useMemo(
    () => tasks.data?.find((t) => t.job_id === activeTaskId),
    [tasks.data, activeTaskId],
  );

  return (
    <div className="min-h-screen bg-background">
      <TopBar />
      <CreateTaskDialog />

      <main className="space-y-3 py-3">
        <MetricsRow data={system.data} />

        <TaskTable tasks={tasks.data || []} />

        {activeTaskId && (
          <>
            <Separator className="bg-border mx-4 w-auto" />
            <PipelineView detail={detail.data} />
          </>
        )}

        <StageDetail detail={detail.data} />
      </main>
    </div>
  );
}
```

- [ ] **Step 2: 验证构建**

```bash
cd /home/bohuju/TIanHeng_project/Sherpa/frontend-next
npm run build 2>&1 | tail -30
```

Expected: build succeeds

- [ ] **Step 3: 提交**

```bash
git add frontend-next/app/page.tsx
git commit -m "feat: assemble TIANHENG console layout with pipeline visualization"
```

---

### Task 18: 清理旧文件 + 最终验证

**Files:**
- Remove: `frontend-next/components/SystemOverviewCard.tsx`
- Remove: `frontend-next/components/ConfigPanel.tsx`
- Remove: `frontend-next/components/SessionPanel.tsx`
- Remove: `frontend-next/components/LogPanel.tsx`
- Remove: `frontend-next/components/TaskProgressPanel.tsx`
- Run: `npm run build`, `npm test`, `npm run lint`

- [ ] **Step 1: 删除旧组件文件**

```bash
cd /home/bohuju/TIanHeng_project/Sherpa/frontend-next
rm components/SystemOverviewCard.tsx
rm components/ConfigPanel.tsx
rm components/SessionPanel.tsx
rm components/LogPanel.tsx
rm components/TaskProgressPanel.tsx
```

Expected: files removed

- [ ] **Step 2: 验证构建**

```bash
cd /home/bohuju/TIanHeng_project/Sherpa/frontend-next
npm run build 2>&1
```

Expected: build succeeds with no errors

- [ ] **Step 3: 运行测试**

```bash
cd /home/bohuju/TIanHeng_project/Sherpa/frontend-next
npm test
```

Expected: all tests pass (existing logUtils.test.ts + client.test.ts + new stageMapping.test.ts)

- [ ] **Step 4: 运行 lint**

```bash
cd /home/bohuju/TIanHeng_project/Sherpa/frontend-next
npm run lint
```

Expected: no lint errors (may have warnings)

- [ ] **Step 5: 删除 Sentry 残留引用**

Check if `@sentry/nextjs` is still in package.json and remove since we removed it from providers.tsx:

```bash
cd /home/bohuju/TIanHeng_project/Sherpa/frontend-next
npm uninstall @sentry/nextjs
```

- [ ] **Step 6: 提交**

```bash
git add frontend-next/components/ frontend-next/app/
git commit -m "chore: remove old MUI components, finalize TIANHENG refactor"
```
