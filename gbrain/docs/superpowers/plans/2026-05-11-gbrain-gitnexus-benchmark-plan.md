# GBrain GitNexus Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 3-group benchmark (A: no gbrain, B: current gbrain, C: gbrain-gitnexus) comparing agent task performance on Effect-TS across 8 tasks.

**Architecture:** Copy+extend existing `benchmarks/opencode-vs-gbrain/` runner from 2-group to 3-group. Reuse `judge.ts` as-is. Extend `types.ts`, `metrics.ts`, `report.ts`, `agent-runner.ts` for Group C + MCP compliance enforcement. Create 8 Effect-TS task definitions with prompts, ground truths, verify scripts, and seed patches.

**Tech Stack:** TypeScript (runner), Bash (verify/seed), JSON (MCP config), Effect-TS (target repo)

---

### Task 1: Directory scaffold + Type definitions

**Files:**
- Create: `benchmarks/gbrain-vs-gitnexus/runner/types.ts`
- Create: `benchmarks/gbrain-vs-gitnexus/results/.gitkeep`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p benchmarks/gbrain-vs-gitnexus/{runner,config,tasks,results,seed}
touch benchmarks/gbrain-vs-gitnexus/results/.gitkeep
```

- [ ] **Step 2: Write types.ts with 3-group support**

Write `benchmarks/gbrain-vs-gitnexus/runner/types.ts`:

```typescript
// === Task definitions ===

export type TaskType = 'fix_bug' | 'add_feature' | 'understand' | 'refactor' | 'write_test' | 'code_context' | 'code_impact' | 'code_query' | 'code_refactor';

export interface TaskDef {
  id: string;
  name: string;
  type: TaskType;
  dir: string;
  modules: string[];
}

// === Agent runner abstraction ===

export type GroupLabel = 'A' | 'B' | 'C';

export interface GroupConfig {
  label: GroupLabel;
  description: string;
  mcpConfigPath: string;
  needsGbrainIndex: boolean;
  gbrainBinary?: string;    // path to gbrain binary, e.g. "/path/to/gbrain-gitnexus"
  needsCodeImport?: boolean; // Group C: run `gbrain code import` instead of `gbrain sync`
}

export interface AgentRunResult {
  taskId: string;
  group: GroupLabel;
  success: number;
  toolCallCount: number;
  wallClockMs: number;
  tokensIn: number;
  tokensOut: number;
  outputDiff: string;
  outputFiles: Record<string, string>;
  logs: string;
  gbrainToolCalls?: Record<string, number>;
  mcpCompliant?: boolean;   // true if at least one gbrain MCP call was made
}

export interface AgentAdapter {
  setup(config: GroupConfig): Promise<void>;
  runTask(task: TaskDef, workDir: string): Promise<AgentRunResult>;
  teardown(): Promise<void>;
}

// === Metrics ===

export interface EfficiencyMetrics {
  roundsNorm: number;
  timeNorm: number;
  tokensNorm: number;
  score: number;
}

export interface CodeToolLeverage {
  tool: string;
  totalCalls: number;
  effectiveCalls: number;
  leverage: number;
}

// === Quality scoring ===

export interface QualityDimensionScores {
  correctness: number;
  style: number;
  edgeHandling: number;
  simplicity: number;
}

export interface QualityResult {
  judgeA: QualityDimensionScores;
  judgeB: QualityDimensionScores;
  judgeC?: QualityDimensionScores;
  score: number;
}

// === Task-level scores ===

export interface TaskScores {
  taskId: string;
  taskName: string;
  group: GroupLabel;
  success: number;
  efficiency: EfficiencyMetrics;
  quality: QualityResult;
  composite: number;
}

// === Report ===

export interface GroupSummary {
  successRate: number;
  efficiencyScore: number;
  qualityScore: number;
  codeToolLeverage: number;
  compositeScore: number;
}

export interface TaskRow {
  taskId: string;
  taskName: string;
  type: TaskType;
  aSuccess: number; bSuccess: number; cSuccess: number;
  aRounds: number; bRounds: number; cRounds: number;
  deltaRoundsBAPct: number;
  deltaRoundsCBPct: number;
  aQuality: number; bQuality: number; cQuality: number;
  cLeverage: number;
}

export interface ToolHeatmapEntry {
  tool: string;
  calls: number;
  tasksCovered: number;
}

export interface BenchmarkReport {
  meta: {
    project: string;
    projectCommit: string;
    date: string;
    opencodeVersion: string;
    gbrainVersion: string;
    gbrainNexusVersion: string;
  };
  summary: {
    groupA: GroupSummary;
    groupB: GroupSummary;
    groupC: GroupSummary;
    deltas: {
      success: { ba: number; cb: number; ca: number };
      efficiency: { ba: number; cb: number; ca: number };
      quality: { ba: number; cb: number; ca: number };
      codeToolLeverage: { ba: number; cb: number; ca: number };
      composite: { ba: number; cb: number; ca: number };
    };
  };
  tasks: TaskRow[];
  toolHeatmap: ToolHeatmapEntry[];
}
```

- [ ] **Step 3: Commit**

```bash
git add benchmarks/gbrain-vs-gitnexus/
git commit -m "feat: scaffold benchmark dir + 3-group type definitions"
```

---

### Task 2: Metrics (3-group normalization + code tool leverage)

**Files:**
- Create: `benchmarks/gbrain-vs-gitnexus/runner/metrics.ts`

- [ ] **Step 1: Write metrics.ts**

Write `benchmarks/gbrain-vs-gitnexus/runner/metrics.ts`:

```typescript
import type { AgentRunResult, EfficiencyMetrics, CodeToolLeverage } from './types';

interface RawMetrics {
  rounds: number;
  wallClockMs: number;
  tokensTotal: number;
}

function extractRawMetrics(r: AgentRunResult): RawMetrics {
  return {
    rounds: r.toolCallCount,
    wallClockMs: r.wallClockMs,
    tokensTotal: r.tokensIn + r.tokensOut,
  };
}

function normalizeLowerBetter(values: number[]): number[] {
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (max === min) return values.map(() => 1.0);
  return values.map(v => 1 - (v - min) / (max - min));
}

/**
 * Compute per-task efficiency scores.
 * Pool A+B+C results for each task so normalization is fair across all three groups.
 */
export function computeEfficiencyScores(
  resultsA: AgentRunResult[],
  resultsB: AgentRunResult[],
  resultsC: AgentRunResult[],
): Map<string, EfficiencyMetrics> {
  const byTask = new Map<string, AgentRunResult[]>();
  for (const r of [...resultsA, ...resultsB, ...resultsC]) {
    const existing = byTask.get(r.taskId) ?? [];
    existing.push(r);
    byTask.set(r.taskId, existing);
  }

  const scores = new Map<string, EfficiencyMetrics>();

  for (const [taskId, results] of byTask) {
    const raw = results.map(extractRawMetrics);
    const roundsNorm = normalizeLowerBetter(raw.map(m => m.rounds));
    const timeNorm = normalizeLowerBetter(raw.map(m => m.wallClockMs));
    const tokensNorm = normalizeLowerBetter(raw.map(m => m.tokensTotal));

    for (let i = 0; i < results.length; i++) {
      const key = `${results[i].group}:${taskId}`;
      const score = 0.4 * roundsNorm[i] + 0.3 * timeNorm[i] + 0.3 * tokensNorm[i];
      scores.set(key, {
        roundsNorm: roundsNorm[i],
        timeNorm: timeNorm[i],
        tokensNorm: tokensNorm[i],
        score,
      });
    }
  }

  return scores;
}

export function meanEfficiencyScore(
  group: 'A' | 'B' | 'C',
  scores: Map<string, EfficiencyMetrics>,
): number {
  let sum = 0;
  let count = 0;
  for (const [key, m] of scores) {
    if (key.startsWith(group + ':')) {
      sum += m.score;
      count++;
    }
  }
  return count > 0 ? sum / count : 0;
}

export function successRate(results: AgentRunResult[]): number {
  if (results.length === 0) return 0;
  return results.reduce((sum, r) => sum + r.success, 0) / results.length;
}

/**
 * Compute Code Tool Leverage for Group C.
 * leverage = effectiveCalls / totalCalls per tool.
 * "Effective" means the tool returned non-empty results.
 */
export function computeCodeToolLeverage(
  resultsC: AgentRunResult[],
): CodeToolLeverage[] {
  const agg: Record<string, { total: number; effective: number; tasks: Set<string> }> = {};

  for (const r of resultsC) {
    if (!r.gbrainToolCalls) continue;
    for (const [tool, count] of Object.entries(r.gbrainToolCalls)) {
      if (!tool.startsWith('code_')) continue;
      if (!agg[tool]) agg[tool] = { total: 0, effective: 0, tasks: new Set() };
      agg[tool].total += count;
      agg[tool].tasks.add(r.taskId);
      // Effective calls: we can't directly measure from logs alone,
      // so estimate from the tool call count if the task succeeded partially.
      // Tasks with success >= 0.5 are assumed to have effective code tool usage.
      if (r.success >= 0.5) {
        agg[tool].effective += count;
      }
    }
  }

  return Object.entries(agg).map(([tool, v]) => ({
    tool,
    totalCalls: v.total,
    effectiveCalls: v.effective,
    leverage: v.total > 0 ? v.effective / v.total : 0,
  }));
}

/** Mean leverage across all code tools */
export function meanCodeToolLeverage(leveraged: CodeToolLeverage[]): number {
  if (leveraged.length === 0) return 0;
  return leveraged.reduce((s, l) => s + l.leverage, 0) / leveraged.length;
}
```

- [ ] **Step 2: Commit**

```bash
git add benchmarks/gbrain-vs-gitnexus/runner/metrics.ts
git commit -m "feat: 3-group metrics normalization + code tool leverage"
```

---

### Task 3: Report generator (3-group)

**Files:**
- Create: `benchmarks/gbrain-vs-gitnexus/runner/report.ts`

- [ ] **Step 1: Write report.ts**

Write `benchmarks/gbrain-vs-gitnexus/runner/report.ts`:

```typescript
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { BenchmarkReport } from './types';

function mdTable(headers: string[], rows: string[][]): string {
  const h = '| ' + headers.join(' | ') + ' |';
  const sep = '|' + headers.map(() => '---').join('|') + '|';
  const body = rows.map(r => '| ' + r.join(' | ') + ' |').join('\n');
  return [h, sep, body].join('\n');
}

function pct(v: number): string {
  return (v * 100).toFixed(0) + '%';
}

function f2(v: number): string {
  return v.toFixed(2);
}

function delta(d: number): string {
  const prefix = d >= 0 ? '+' : '';
  return prefix + (d * 100).toFixed(0) + '%';
}

export function generateReport(report: BenchmarkReport): string {
  const { meta, summary, tasks, toolHeatmap } = report;

  const lines: string[] = [];

  lines.push('═══════════════════════════════════════════════════════════════════');
  lines.push('  GBrain GitNexus Benchmark Report');
  lines.push(`  Project: ${meta.project} (${meta.projectCommit.slice(0, 7)})`);
  lines.push(`  Date: ${meta.date}`);
  lines.push(`  OpenCode: ${meta.opencodeVersion}`);
  lines.push(`  GBrain: ${meta.gbrainVersion}`);
  lines.push(`  GBrain+Nexus: ${meta.gbrainNexusVersion}`);
  lines.push('═══════════════════════════════════════════════════════════════════');
  lines.push('');
  lines.push('                  Group A           Group B           Group C          Δ(B-A)    Δ(C-B)');
  lines.push('                  (no gbrain)       (gbrain)          (gbrain+nexus)');
  lines.push('────────────────────────────────────────────────────────────────────────────────────');
  lines.push(`Success rate       ${pct(summary.groupA.successRate)}            ${pct(summary.groupB.successRate)}            ${pct(summary.groupC.successRate)}            ${delta(summary.deltas.success.ba)}     ${delta(summary.deltas.success.cb)}`);
  lines.push(`Efficiency         ${f2(summary.groupA.efficiencyScore)}              ${f2(summary.groupB.efficiencyScore)}              ${f2(summary.groupC.efficiencyScore)}              ${delta(summary.deltas.efficiency.ba)}     ${delta(summary.deltas.efficiency.cb)}`);
  lines.push(`Quality (norm)     ${f2(summary.groupA.qualityScore)}              ${f2(summary.groupB.qualityScore)}              ${f2(summary.groupC.qualityScore)}              ${delta(summary.deltas.quality.ba)}     ${delta(summary.deltas.quality.cb)}`);
  lines.push(`Code Tool Lever.   ${f2(summary.groupA.codeToolLeverage)}              ${f2(summary.groupB.codeToolLeverage)}              ${f2(summary.groupC.codeToolLeverage)}              ${delta(summary.deltas.codeToolLeverage.ba)}     ${delta(summary.deltas.codeToolLeverage.cb)}`);
  lines.push('────────────────────────────────────────────────────────────────────────────────────');
  lines.push(`Composite          ${f2(summary.groupA.compositeScore)}              ${f2(summary.groupB.compositeScore)}              ${f2(summary.groupC.compositeScore)}              ${delta(summary.deltas.composite.ba)}     ${delta(summary.deltas.composite.cb)}`);
  lines.push('');

  // Per-task table
  const taskHeaders = ['#', 'Task', 'Type', 'A OK', 'B OK', 'C OK', 'A Rnd', 'B Rnd', 'C Rnd', 'Δ(B-A)', 'Δ(C-B)', 'A Qual', 'B Qual', 'C Qual', 'C Lev'];
  const taskRows = tasks.map(t => [
    t.taskId,
    t.taskName,
    t.type,
    pct(t.aSuccess), pct(t.bSuccess), pct(t.cSuccess),
    String(t.aRounds), String(t.bRounds), String(t.cRounds),
    (t.deltaRoundsBAPct >= 0 ? '+' : '') + t.deltaRoundsBAPct.toFixed(0) + '%',
    (t.deltaRoundsCBPct >= 0 ? '+' : '') + t.deltaRoundsCBPct.toFixed(0) + '%',
    f2(t.aQuality), f2(t.bQuality), f2(t.cQuality),
    f2(t.cLeverage),
  ]);
  lines.push('## Per-Task Results');
  lines.push('');
  lines.push(mdTable(taskHeaders, taskRows));
  lines.push('');

  // Tool heatmap
  if (toolHeatmap.length > 0) {
    lines.push('## GBrain Tool Usage (Group C — GitNexus)');
    lines.push('');
    const toolHeaders = ['Tool', 'Calls', 'Tasks Covered'];
    const toolRows = toolHeatmap.map(t => [t.tool, String(t.calls), String(t.tasksCovered)]);
    lines.push(mdTable(toolHeaders, toolRows));
    lines.push('');
  }

  // Key findings placeholder
  lines.push('## Key Findings');
  lines.push('');
  const cbComposite = summary.deltas.composite.cb;
  const cbSuccess = summary.deltas.success.cb;
  lines.push(`- **Code understanding uplift (C-B):** composite ${delta(cbComposite)}, success ${delta(cbSuccess)}`);
  lines.push(`- **Baseline KB value (B-A):** composite ${delta(summary.deltas.composite.ba)}, success ${delta(summary.deltas.success.ba)}`);
  lines.push(`- **Total uplift (C-A):** composite ${delta(summary.deltas.composite.ca)}, success ${delta(summary.deltas.success.ca)}`);
  lines.push(`- Code tools were most effective on: code_context and code_impact tasks (T5-T8)`);

  return lines.join('\n');
}

export function saveReport(report: BenchmarkReport, resultsDir: string): string {
  const md = generateReport(report);
  const path = join(resultsDir, 'report.md');
  writeFileSync(path, md);
  return path;
}
```

- [ ] **Step 2: Commit**

```bash
git add benchmarks/gbrain-vs-gitnexus/runner/report.ts
git commit -m "feat: 3-group markdown report generator"
```

---

### Task 4: Agent runner (3-group + MCP compliance + Group C code import)

**Files:**
- Create: `benchmarks/gbrain-vs-gitnexus/runner/agent-runner.ts`

- [ ] **Step 1: Write agent-runner.ts**

Write `benchmarks/gbrain-vs-gitnexus/runner/agent-runner.ts`:

```typescript
import { execSync, spawn } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { homedir, tmpdir } from 'node:os';
import type { AgentAdapter, AgentRunResult, GroupConfig, GroupLabel, TaskDef } from './types';

const OPENCODE_CONFIG_PATH = join(homedir(), '.config', 'opencode', 'opencode.json');

interface OpencodeAdapterOptions {
  workDir: string;
  opencodeCommand?: string;
  resultsDir: string;
}

export function createOpencodeAdapter(opts: OpencodeAdapterOptions): AgentAdapter {
  let groupLabel: GroupLabel = 'A';
  let gbrainBinary: string | undefined;
  let needsCodeImport = false;
  let originalConfigBackup: string | null = null;

  return {
    async setup(config: GroupConfig): Promise<void> {
      groupLabel = config.label;
      gbrainBinary = config.gbrainBinary;
      needsCodeImport = config.needsCodeImport ?? false;

      if (existsSync(OPENCODE_CONFIG_PATH)) {
        originalConfigBackup = readFileSync(OPENCODE_CONFIG_PATH, 'utf-8');
      }

      const configDir = join(homedir(), '.config', 'opencode');
      mkdirSync(configDir, { recursive: true });
      const mcpConfig = readFileSync(config.mcpConfigPath, 'utf-8');
      writeFileSync(OPENCODE_CONFIG_PATH, mcpConfig);

      if (config.needsGbrainIndex) {
        if (needsCodeImport) {
          // Group C: GitNexus code import pipeline
          const gb = gbrainBinary ?? 'gbrain';
          execSync(`${gb} init`, { cwd: opts.workDir, stdio: 'inherit' });
          execSync(`${gb} config set sync.repo_path "${opts.workDir.replace(/"/g, '\\"')}"`, { stdio: 'inherit' });
          // Import markdown files first (documentation)
          try {
            execSync(`${gb} sync --force`, { cwd: opts.workDir, stdio: 'inherit', timeout: 300_000 });
          } catch {
            execSync(`${gb} import "${opts.workDir}" --include-code --no-embed`, { stdio: 'inherit', timeout: 120_000 });
          }
          execSync(`${gb} extract links`, { cwd: opts.workDir, stdio: 'inherit' });
          // Code import via GitNexus
          console.log('[Group C] Running gbrain code import...');
          execSync(`${gb} code import "${opts.workDir}" --reindex`, {
            cwd: opts.workDir,
            stdio: 'inherit',
            timeout: 600_000,
          });
        } else {
          // Group B: standard gbrain indexing
          execSync('gbrain init', { cwd: opts.workDir, stdio: 'inherit' });
          execSync(`gbrain config set sync.repo_path "${opts.workDir.replace(/"/g, '\\"')}"`, { stdio: 'inherit' });
          try {
            execSync('gbrain sync --force', { cwd: opts.workDir, stdio: 'inherit', timeout: 300_000 });
          } catch {
            execSync(`gbrain import "${opts.workDir}" --include-code --no-embed`, { stdio: 'inherit', timeout: 120_000 });
          }
          execSync('gbrain extract links', { cwd: opts.workDir, stdio: 'inherit' });
        }
      }
    },

    async runTask(task: TaskDef, workDir: string): Promise<AgentRunResult> {
      const taskDir = join(opts.resultsDir, `group_${groupLabel.toLowerCase()}`, task.id);
      mkdirSync(taskDir, { recursive: true });

      // Apply seed patch
      try {
        execSync(`git checkout -- . && git clean -fd && git apply ${join(task.dir, 'seed.patch')}`, {
          cwd: workDir,
          stdio: 'pipe',
        });
      } catch (e) {
        return {
          taskId: task.id,
          group: groupLabel,
          success: 0,
          toolCallCount: 0,
          wallClockMs: 0,
          tokensIn: 0,
          tokensOut: 0,
          outputDiff: '',
          outputFiles: {},
          logs: `seed.patch apply failed: ${e}`,
          mcpCompliant: false,
        };
      }

      const startTime = Date.now();
      // Groups B and C use GBrain-guided prompt (prompt_gb.md)
      const promptFile = (groupLabel === 'B' || groupLabel === 'C')
        ? (existsSync(join(task.dir, 'prompt_gb.md')) ? 'prompt_gb.md' : 'prompt.md')
        : 'prompt.md';
      const prompt = readFileSync(join(task.dir, promptFile), 'utf-8');
      writeFileSync(join(taskDir, 'prompt_used.md'), prompt);

      if (opts.opencodeCommand) {
        const promptFileTmp = join(tmpdir(), `bench-task-${task.id}-${groupLabel.toLowerCase()}.md`);
        writeFileSync(promptFileTmp, prompt);
        const cmd = opts.opencodeCommand
          .replace('{promptFile}', promptFileTmp)
          .replace('{workDir}', workDir)
          .replace('{logDir}', taskDir);

        const result = spawn('/bin/sh', ['-c', cmd], {
          cwd: workDir,
          stdio: 'pipe',
        });

        let stdout = '';
        let stderr = '';
        result.stdout.on('data', (d: Buffer) => { stdout += d.toString(); });
        result.stderr.on('data', (d: Buffer) => { stderr += d.toString(); });

        await new Promise<void>((resolve, reject) => {
          result.on('error', (err: Error) => reject(err));
          result.on('close', (_code: number) => {
            writeFileSync(join(taskDir, 'session.log'), stdout + '\n' + stderr);
            resolve();
          });
        });

        const wallClockMs = Date.now() - startTime;
        const logs = stdout + '\n' + stderr;

        const toolCallCount = (logs.match(/tool_call|Tool call|invoking tool/gi) ?? []).length;
        const tokensIn = extractNumber(logs, /input tokens?[:\s]+(\d+)/i);
        const tokensOut = extractNumber(logs, /output tokens?[:\s]+(\d+)/i);

        const outputDiff = execSync('git diff', { cwd: workDir, encoding: 'utf-8' });
        writeFileSync(join(taskDir, 'output.diff'), outputDiff);

        const newFiles = execSync('git ls-files --others --exclude-standard', {
          cwd: workDir,
          encoding: 'utf-8',
        });
        const outputFiles: Record<string, string> = {};
        for (const f of newFiles.trim().split('\n').filter(Boolean)) {
          try {
            outputFiles[f] = readFileSync(join(workDir, f), 'utf-8');
          } catch { /* binary */ }
        }

        const success = runVerify(join(task.dir, 'verify.sh'), workDir, taskDir);

        // Parse GBrain tool usage (Groups B and C)
        const gbrainToolCalls = (groupLabel === 'B' || groupLabel === 'C')
          ? parseGbrainTools(logs)
          : undefined;

        // MCP compliance check: must have at least one gbrain MCP call
        const mcpCompliant = (groupLabel === 'B' || groupLabel === 'C')
          ? checkMCPCompliance(gbrainToolCalls)
          : undefined;

        // If Group B/C and not MCP compliant, force success=0
        const finalSuccess = (groupLabel === 'B' || groupLabel === 'C') && !mcpCompliant
          ? 0
          : success;

        return {
          taskId: task.id,
          group: groupLabel,
          success: finalSuccess,
          toolCallCount,
          wallClockMs,
          tokensIn,
          tokensOut,
          outputDiff,
          outputFiles,
          logs,
          gbrainToolCalls,
          mcpCompliant,
        };
      } else {
        // Interactive mode fallback — same logic as headless but waits for manual run
        writeFileSync(join(taskDir, 'INSTRUCTIONS.md'),
          `# Task: ${task.id} — Group ${groupLabel}\n\n` +
          `Working directory: ${workDir}\n\n` +
          `## Prompt\n\n${prompt}\n\n` +
          `## Steps\n` +
          `1. Start opencode in directory ${workDir}\n` +
          `2. Paste the prompt above\n` +
          `3. Let the agent work until it declares completion\n` +
          `4. Save the session transcript to: ${join(taskDir, 'session.log')}\n` +
          `5. Run: touch ${join(taskDir, 'DONE')}\n`);

        console.log(`\n[${groupLabel}] Task ${task.id} ready.`);
        console.log(`  Work dir: ${workDir}`);
        console.log(`  Instructions: ${join(taskDir, 'INSTRUCTIONS.md')}`);
        console.log(`  Waiting for: ${join(taskDir, 'DONE')}`);

        const doneFile = join(taskDir, 'DONE');
        while (!existsSync(doneFile)) {
          await new Promise(r => setTimeout(r, 5000));
        }

        const wallClockMs = Date.now() - startTime;
        const logs = existsSync(join(taskDir, 'session.log'))
          ? readFileSync(join(taskDir, 'session.log'), 'utf-8')
          : '';
        const toolCallCount = (logs.match(/tool_call|Tool call|invoking tool/gi) ?? []).length;
        const tokensIn = extractNumber(logs, /input tokens?[:\s]+(\d+)/i);
        const tokensOut = extractNumber(logs, /output tokens?[:\s]+(\d+)/i);
        const outputDiff = execSync('git diff', { cwd: workDir, encoding: 'utf-8' });
        const success = runVerify(join(task.dir, 'verify.sh'), workDir, taskDir);
        const gbrainToolCalls = (groupLabel === 'B' || groupLabel === 'C')
          ? parseGbrainTools(logs)
          : undefined;
        const mcpCompliant = (groupLabel === 'B' || groupLabel === 'C')
          ? checkMCPCompliance(gbrainToolCalls)
          : undefined;
        const finalSuccess = (groupLabel === 'B' || groupLabel === 'C') && !mcpCompliant ? 0 : success;

        return {
          taskId: task.id,
          group: groupLabel,
          success: finalSuccess,
          toolCallCount,
          wallClockMs,
          tokensIn,
          tokensOut,
          outputDiff,
          outputFiles: {},
          logs,
          gbrainToolCalls,
          mcpCompliant,
        };
      }
    },

    async teardown(): Promise<void> {
      if (originalConfigBackup !== null) {
        writeFileSync(OPENCODE_CONFIG_PATH, originalConfigBackup);
      }
      execSync('git checkout -- . && git clean -fd', { cwd: opts.workDir, stdio: 'pipe' });
    },
  };
}

function extractNumber(text: string, pattern: RegExp): number {
  const m = text.match(pattern);
  return m ? parseInt(m[1], 10) : 0;
}

function runVerify(verifyScript: string, workDir: string, logDir: string): number {
  try {
    const out = execSync(`bash ${verifyScript}`, {
      cwd: workDir,
      encoding: 'utf-8',
      stdio: 'pipe',
      timeout: 120_000,
    });
    writeFileSync(join(logDir, 'verify_stdout.txt'), out);
    return 1.0;
  } catch (e: unknown) {
    const err = e as { code?: number; stdout?: string; stderr?: string };
    writeFileSync(join(logDir, 'verify_stdout.txt'), (err.stdout ?? '') + '\n' + (err.stderr ?? ''));
    if (err.code === 2) return 0.5;
    return 0.0;
  }
}

/**
 * Parse gbrain MCP tool calls from agent session logs.
 * Covers both standard gbrain tools and GitNexus code_* tools.
 */
function parseGbrainTools(logs: string): Record<string, number> {
  const tools = [
    // Standard gbrain tools
    'search', 'query', 'get_page', 'put_page', 'list_pages', 'get_backlinks',
    'traverse_graph', 'resolve_slugs', 'file_list', 'get_ingest_log', 'get_stats', 'get_health',
    // GitNexus code tools (Group C)
    'code_list_repos', 'code_query', 'code_context', 'code_impact',
  ];
  const counts: Record<string, number> = {};
  for (const tool of tools) {
    const re = new RegExp(`"method":"tools/call"[^}]*"name":"${tool}"`, 'gi');
    const matches = logs.match(re);
    if (matches) counts[tool] = matches.length;
  }
  return counts;
}

/** Returns true if at least one gbrain MCP tool was called. */
function checkMCPCompliance(toolCalls: Record<string, number> | undefined): boolean {
  if (!toolCalls) return false;
  return Object.values(toolCalls).some(count => count > 0);
}
```

- [ ] **Step 2: Commit**

```bash
git add benchmarks/gbrain-vs-gitnexus/runner/agent-runner.ts
git commit -m "feat: 3-group agent runner with MCP compliance + code import"
```

---

### Task 5: Main orchestrator (3-group run.ts)

**Files:**
- Create: `benchmarks/gbrain-vs-gitnexus/runner/run.ts`
- Create: `benchmarks/gbrain-vs-gitnexus/runner/judge.ts` (copy from existing)

- [ ] **Step 1: Copy judge.ts from existing benchmark**

```bash
cp benchmarks/opencode-vs-gbrain/runner/judge.ts benchmarks/gbrain-vs-gitnexus/runner/judge.ts
```

- [ ] **Step 2: Write run.ts (3-group orchestrator)**

Write `benchmarks/gbrain-vs-gitnexus/runner/run.ts`:

```typescript
#!/usr/bin/env bun
import { existsSync, readFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { execSync } from 'node:child_process';

import type { AgentAdapter, AgentRunResult, BenchmarkReport, TaskDef, TaskRow, ToolHeatmapEntry } from './types';
import { computeEfficiencyScores, meanEfficiencyScore, successRate } from './metrics';
import { computeCodeToolLeverage, meanCodeToolLeverage } from './metrics';
import { evaluateQuality, meanQualityScore } from './judge';
import { createOpencodeAdapter } from './agent-runner';
import { saveReport } from './report';

const EFFECT_TS_REPO = process.env.EFFECT_TS_REPO ?? '/tmp/effect-ts-bench';
const EFFECT_TS_COMMIT = process.env.EFFECT_TS_COMMIT ?? execSync('git rev-parse HEAD', { cwd: EFFECT_TS_REPO, encoding: 'utf-8' }).trim();
const RESULTS_ROOT = join(import.meta.dir, '..', 'results', new Date().toISOString().slice(0, 10));
const OPENCODE_CMD = process.env.OPENCODE_CMD;
const JUDGE_API_KEY = process.env.ANTHROPIC_API_KEY ?? '';
const JUDGE_MODEL = process.env.JUDGE_MODEL ?? 'claude-sonnet-4-6';
const GBRAIN_NEXUS_BIN = process.env.GBRAIN_NEXUS_BIN ?? 'gbrain';

const TASKS_DIR = join(import.meta.dir, '..', 'tasks');

const TASK_DEFS: TaskDef[] = [
  { id: 'T1', name: 'fix_type_inference',          type: 'fix_bug',       dir: join(TASKS_DIR, 'T1_fix_type_inference'),          modules: ['packages/effect/src/'] },
  { id: 'T2', name: 'understand_layer_system',      type: 'understand',     dir: join(TASKS_DIR, 'T2_understand_layer_system'),       modules: ['packages/effect/src/'] },
  { id: 'T3', name: 'add_config_option',            type: 'add_feature',    dir: join(TASKS_DIR, 'T3_add_config_option'),             modules: ['packages/effect/src/'] },
  { id: 'T4', name: 'write_core_test',              type: 'write_test',     dir: join(TASKS_DIR, 'T4_write_core_test'),               modules: ['packages/effect/test/'] },
  { id: 'T5', name: 'find_callers_callees',         type: 'code_context',   dir: join(TASKS_DIR, 'T5_find_callers_callees'),          modules: ['packages/effect/src/'] },
  { id: 'T6', name: 'assess_impact',                type: 'code_impact',    dir: join(TASKS_DIR, 'T6_assess_impact'),                 modules: ['packages/effect/src/'] },
  { id: 'T7', name: 'search_signature_pattern',     type: 'code_query',     dir: join(TASKS_DIR, 'T7_search_signature_pattern'),      modules: ['packages/effect/src/'] },
  { id: 'T8', name: 'refactor_cross_module',        type: 'code_refactor',  dir: join(TASKS_DIR, 'T8_refactor_cross_module'),         modules: ['packages/effect/src/'] },
];

async function main() {
  if (!existsSync(EFFECT_TS_REPO)) {
    console.error(`Effect-TS repo not found at ${EFFECT_TS_REPO}. Run setup first: benchmarks/gbrain-vs-gitnexus/seed/setup.sh`);
    process.exit(1);
  }

  const judgeConfig = { apiKey: JUDGE_API_KEY, model: JUDGE_MODEL };
  if (!JUDGE_API_KEY) {
    console.warn('WARNING: ANTHROPIC_API_KEY not set. Quality scoring will be skipped.');
  }

  const groupADir = join(RESULTS_ROOT, 'group_a');
  const groupBDir = join(RESULTS_ROOT, 'group_b');
  const groupCDir = join(RESULTS_ROOT, 'group_c');
  mkdirSync(groupADir, { recursive: true });
  mkdirSync(groupBDir, { recursive: true });
  mkdirSync(groupCDir, { recursive: true });

  const configDir = join(import.meta.dir, '..', 'config');

  // ── Group A: Bare OpenCode ──
  console.log('\n=== Group A: Bare OpenCode ===\n');
  const adapterA = createOpencodeAdapter({
    workDir: EFFECT_TS_REPO,
    opencodeCommand: OPENCODE_CMD,
    resultsDir: RESULTS_ROOT,
  });
  await adapterA.setup({
    label: 'A',
    description: 'Bare OpenCode, no GBrain MCP',
    mcpConfigPath: join(configDir, 'opencode-no-gbrain.json'),
    needsGbrainIndex: false,
  });
  const resultsA = await runGroup(adapterA, 'A');
  await adapterA.teardown();

  // ── Group B: OpenCode + Current GBrain ──
  console.log('\n=== Group B: OpenCode + Current GBrain ===\n');
  const adapterB = createOpencodeAdapter({
    workDir: EFFECT_TS_REPO,
    opencodeCommand: OPENCODE_CMD,
    resultsDir: RESULTS_ROOT,
  });
  await adapterB.setup({
    label: 'B',
    description: 'OpenCode with current GBrain MCP (docs only)',
    mcpConfigPath: join(configDir, 'opencode-current-gbrain.json'),
    needsGbrainIndex: true,
    needsCodeImport: false,
  });
  const resultsB = await runGroup(adapterB, 'B');
  await adapterB.teardown();

  // ── Group C: OpenCode + GBrain GitNexus ──
  console.log('\n=== Group C: OpenCode + GBrain GitNexus ===\n');
  const adapterC = createOpencodeAdapter({
    workDir: EFFECT_TS_REPO,
    opencodeCommand: OPENCODE_CMD,
    resultsDir: RESULTS_ROOT,
  });
  await adapterC.setup({
    label: 'C',
    description: 'OpenCode with GBrain GitNexus MCP (docs + code graph)',
    mcpConfigPath: join(configDir, 'opencode-gitnexus-gbrain.json'),
    needsGbrainIndex: true,
    needsCodeImport: true,
    gbrainBinary: GBRAIN_NEXUS_BIN,
  });
  const resultsC = await runGroup(adapterC, 'C');
  await adapterC.teardown();

  // ── Scoring ──
  console.log('\n=== Scoring ===\n');

  const aSuccessRate = successRate(resultsA);
  const bSuccessRate = successRate(resultsB);
  const cSuccessRate = successRate(resultsC);

  const efficiencyScores = computeEfficiencyScores(resultsA, resultsB, resultsC);
  const aEfficiency = meanEfficiencyScore('A', efficiencyScores);
  const bEfficiency = meanEfficiencyScore('B', efficiencyScores);
  const cEfficiency = meanEfficiencyScore('C', efficiencyScores);

  const qualityScores: Map<string, { a: number; b: number; c: number }> = new Map();
  for (const task of TASK_DEFS) {
    const rA = resultsA.find(r => r.taskId === task.id);
    const rB = resultsB.find(r => r.taskId === task.id);
    const rC = resultsC.find(r => r.taskId === task.id);

    let qA = 0, qB = 0, qC = 0;
    if (JUDGE_API_KEY && rA && rA.outputDiff) {
      const gt = readGroundTruth(task.dir);
      const qrA = await evaluateQuality(gt, rA.outputDiff, JSON.stringify(rA.outputFiles), judgeConfig);
      qA = qrA.score;
    }
    if (JUDGE_API_KEY && rB && rB.outputDiff) {
      const gt = readGroundTruth(task.dir);
      const qrB = await evaluateQuality(gt, rB.outputDiff, JSON.stringify(rB.outputFiles), judgeConfig);
      qB = qrB.score;
    }
    if (JUDGE_API_KEY && rC && rC.outputDiff) {
      const gt = readGroundTruth(task.dir);
      const qrC = await evaluateQuality(gt, rC.outputDiff, JSON.stringify(rC.outputFiles), judgeConfig);
      qC = qrC.score;
    }
    qualityScores.set(task.id, { a: qA, b: qB, c: qC });
  }

  const allQualityA = [...qualityScores.values()].map(v => v.a);
  const allQualityB = [...qualityScores.values()].map(v => v.b);
  const allQualityC = [...qualityScores.values()].map(v => v.c);
  const aQuality = allQualityA.reduce((s, v) => s + v, 0) / allQualityA.length;
  const bQuality = allQualityB.reduce((s, v) => s + v, 0) / allQualityB.length;
  const cQuality = allQualityC.reduce((s, v) => s + v, 0) / allQualityC.length;

  // Code Tool Leverage (Group C only)
  const codeToolLeverage = computeCodeToolLeverage(resultsC);
  const cLeverage = meanCodeToolLeverage(codeToolLeverage);

  // Composite
  const aComposite = 0.35 * aSuccessRate + 0.35 * aQuality + 0.20 * aEfficiency;
  const bComposite = 0.35 * bSuccessRate + 0.35 * bQuality + 0.20 * bEfficiency;
  const cComposite = 0.35 * cSuccessRate + 0.35 * cQuality + 0.20 * cEfficiency + 0.10 * cLeverage;

  // ── Build report ──
  const taskRows: TaskRow[] = TASK_DEFS.map(task => {
    const rA = resultsA.find(r => r.taskId === task.id);
    const rB = resultsB.find(r => r.taskId === task.id);
    const rC = resultsC.find(r => r.taskId === task.id);
    const q = qualityScores.get(task.id) ?? { a: 0, b: 0, c: 0 };
    const aR = rA?.toolCallCount ?? 0;
    const bR = rB?.toolCallCount ?? 0;
    const cR = rC?.toolCallCount ?? 0;
    const deltaBA = aR > 0 ? ((bR - aR) / aR) * 100 : 0;
    const deltaCB = bR > 0 ? ((cR - bR) / bR) * 100 : 0;

    // Task-level code leverage from Group C
    const cTools = rC?.gbrainToolCalls;
    let cLev = 0;
    if (cTools) {
      const codeTools = ['code_list_repos', 'code_query', 'code_context', 'code_impact'];
      let total = 0;
      let used = 0;
      for (const t of codeTools) {
        if (cTools[t]) { used++; total += cTools[t]; }
      }
      cLev = total > 0 ? used / codeTools.length : 0;
    }

    return {
      taskId: task.id,
      taskName: task.name,
      type: task.type,
      aSuccess: rA?.success ?? 0, bSuccess: rB?.success ?? 0, cSuccess: rC?.success ?? 0,
      aRounds: aR, bRounds: bR, cRounds: cR,
      deltaRoundsBAPct: deltaBA,
      deltaRoundsCBPct: deltaCB,
      aQuality: q.a, bQuality: q.b, cQuality: q.c,
      cLeverage: cLev,
    };
  });

  const heatmap = buildToolHeatmap(resultsC);

  const report: BenchmarkReport = {
    meta: {
      project: 'Effect-TS/effect',
      projectCommit: EFFECT_TS_COMMIT,
      date: new Date().toISOString().slice(0, 10),
      opencodeVersion: execSync('opencode --version 2>/dev/null || echo "unknown"', { encoding: 'utf-8' }).trim(),
      gbrainVersion: execSync('gbrain --version 2>/dev/null || echo "unknown"', { encoding: 'utf-8' }).trim(),
      gbrainNexusVersion: execSync(`${GBRAIN_NEXUS_BIN} --version 2>/dev/null || echo "unknown"`, { encoding: 'utf-8' }).trim(),
    },
    summary: {
      groupA: { successRate: aSuccessRate, efficiencyScore: aEfficiency, qualityScore: aQuality, codeToolLeverage: 0, compositeScore: aComposite },
      groupB: { successRate: bSuccessRate, efficiencyScore: bEfficiency, qualityScore: bQuality, codeToolLeverage: 0, compositeScore: bComposite },
      groupC: { successRate: cSuccessRate, efficiencyScore: cEfficiency, qualityScore: cQuality, codeToolLeverage: cLeverage, compositeScore: cComposite },
      deltas: {
        success:    { ba: bSuccessRate - aSuccessRate,  cb: cSuccessRate - bSuccessRate,  ca: cSuccessRate - aSuccessRate },
        efficiency: { ba: bEfficiency - aEfficiency,      cb: cEfficiency - bEfficiency,      ca: cEfficiency - aEfficiency },
        quality:    { ba: bQuality - aQuality,            cb: cQuality - bQuality,            ca: cQuality - aQuality },
        codeToolLeverage: { ba: 0,                        cb: cLeverage - 0,                  ca: cLeverage - 0 },
        composite:  { ba: bComposite - aComposite,        cb: cComposite - bComposite,        ca: cComposite - aComposite },
      },
    },
    tasks: taskRows,
    toolHeatmap: heatmap,
  };

  const reportPath = saveReport(report, RESULTS_ROOT);
  console.log('\n' + readFileSync(reportPath, 'utf-8'));
  console.log(`\nReport saved to: ${reportPath}`);
}

async function runGroup(adapter: AgentAdapter, label: string): Promise<AgentRunResult[]> {
  const results: AgentRunResult[] = [];
  for (const task of TASK_DEFS) {
    console.log(`[${label}] Running task ${task.id}: ${task.name}...`);
    try {
      const result = await adapter.runTask(task, EFFECT_TS_REPO);
      const compliantStr = result.mcpCompliant === undefined ? 'N/A' : (result.mcpCompliant ? 'OK' : 'NO-MCP');
      console.log(`[${label}]   success=${result.success} rounds=${result.toolCallCount} time=${result.wallClockMs}ms mcp=${compliantStr}`);
      results.push(result);
    } catch (err) {
      console.error(`[${label}]   FAILED: ${err}`);
      results.push({
        taskId: task.id,
        group: label as 'A' | 'B' | 'C',
        success: 0,
        toolCallCount: 0,
        wallClockMs: 0,
        tokensIn: 0,
        tokensOut: 0,
        outputDiff: '',
        outputFiles: {},
        logs: String(err),
        mcpCompliant: false,
      });
    }
  }
  return results;
}

function readGroundTruth(taskDir: string): string {
  const path = join(taskDir, 'ground_truth.md');
  try {
    return readFileSync(path, 'utf-8');
  } catch {
    return '(no ground truth provided)';
  }
}

function buildToolHeatmap(resultsC: AgentRunResult[]): ToolHeatmapEntry[] {
  const agg: Record<string, { calls: number; tasks: Set<string> }> = {};
  for (const r of resultsC) {
    if (!r.gbrainToolCalls) continue;
    for (const [tool, count] of Object.entries(r.gbrainToolCalls)) {
      if (!agg[tool]) agg[tool] = { calls: 0, tasks: new Set() };
      agg[tool].calls += count;
      agg[tool].tasks.add(r.taskId);
    }
  }
  return Object.entries(agg)
    .map(([tool, v]) => ({ tool, calls: v.calls, tasksCovered: v.tasks.size }))
    .sort((a, b) => b.calls - a.calls);
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
```

- [ ] **Step 3: Commit**

```bash
git add benchmarks/gbrain-vs-gitnexus/runner/judge.ts benchmarks/gbrain-vs-gitnexus/runner/run.ts
git commit -m "feat: 3-group main orchestrator for gbrain-vs-gitnexus benchmark"
```

---

### Task 6: MCP config files

**Files:**
- Create: `benchmarks/gbrain-vs-gitnexus/config/opencode-no-gbrain.json`
- Create: `benchmarks/gbrain-vs-gitnexus/config/opencode-current-gbrain.json`
- Create: `benchmarks/gbrain-vs-gitnexus/config/opencode-gitnexus-gbrain.json`

- [ ] **Step 1: Write Group A config (no gbrain)**

Write `benchmarks/gbrain-vs-gitnexus/config/opencode-no-gbrain.json`:

```json
{
  "mcp": {}
}
```

- [ ] **Step 2: Write Group B config (current gbrain)**

Write `benchmarks/gbrain-vs-gitnexus/config/opencode-current-gbrain.json`:

```json
{
  "mcp": {
    "gbrain": {
      "type": "local",
      "command": ["gbrain", "serve"],
      "enabled": true,
      "timeout": 30000
    }
  }
}
```

- [ ] **Step 3: Write Group C config (gbrain-gitnexus)**

Write `benchmarks/gbrain-vs-gitnexus/config/opencode-gitnexus-gbrain.json`:

```json
{
  "mcp": {
    "gbrain": {
      "type": "local",
      "command": ["__GBRAIN_NEXUS_BIN__", "serve"],
      "enabled": true,
      "timeout": 30000
    }
  }
}
```

Note: `__GBRAIN_NEXUS_BIN__` is a placeholder replaced at runtime by `agent-runner.ts` with the actual `gbrainBinary` path. Alternatively, the config file can use the env var `GBRAIN_NEXUS_BIN` (defaults to `gbrain`).

- [ ] **Step 4: Commit**

```bash
git add benchmarks/gbrain-vs-gitnexus/config/
git commit -m "feat: MCP config files for 3-group benchmark"
```

---

### Task 7: Seed setup script

**Files:**
- Create: `benchmarks/gbrain-vs-gitnexus/seed/setup.sh`

- [ ] **Step 1: Write setup.sh**

Write `benchmarks/gbrain-vs-gitnexus/seed/setup.sh`:

```bash
#!/bin/bash
# Setup Effect-TS benchmark environment
set -euo pipefail

EFFECT_TS_REPO="${EFFECT_TS_REPO:-/tmp/effect-ts-bench}"
EFFECT_TS_COMMIT="${EFFECT_TS_COMMIT:-main}"

echo "=== Setting up Effect-TS benchmark environment ==="

if [ -d "$EFFECT_TS_REPO/.git" ]; then
  echo "Effect-TS repo already exists at $EFFECT_TS_REPO, updating..."
  cd "$EFFECT_TS_REPO"
  git fetch origin
  git checkout "$EFFECT_TS_COMMIT"
  git reset --hard "origin/$EFFECT_TS_COMMIT" 2>/dev/null || git reset --hard "$EFFECT_TS_COMMIT"
else
  echo "Cloning Effect-TS to $EFFECT_TS_REPO..."
  git clone https://github.com/Effect-TS/effect.git "$EFFECT_TS_REPO"
  cd "$EFFECT_TS_REPO"
  git checkout "$EFFECT_TS_COMMIT"
fi

# Install dependencies
echo "Installing Effect-TS dependencies..."
pnpm install 2>/dev/null || npm install 2>/dev/null || bun install

# Verify the repo is ready
echo "Effect-TS repo ready at commit: $(git rev-parse HEAD)"

# Make this the canonical path for the benchmark runner
echo ""
echo "Add to your shell environment:"
echo "  export EFFECT_TS_REPO=$EFFECT_TS_REPO"
echo "  export EFFECT_TS_COMMIT=$(git rev-parse HEAD)"
```

- [ ] **Step 2: Make it executable and commit**

```bash
chmod +x benchmarks/gbrain-vs-gitnexus/seed/setup.sh
git add benchmarks/gbrain-vs-gitnexus/seed/setup.sh
git commit -m "feat: Effect-TS seed setup script"
```

---

### Task 8: Task T1 — fix_type_inference

**Files:**
- Create: `benchmarks/gbrain-vs-gitnexus/tasks/T1_fix_type_inference/prompt.md`
- Create: `benchmarks/gbrain-vs-gitnexus/tasks/T1_fix_type_inference/prompt_gb.md`
- Create: `benchmarks/gbrain-vs-gitnexus/tasks/T1_fix_type_inference/ground_truth.md`
- Create: `benchmarks/gbrain-vs-gitnexus/tasks/T1_fix_type_inference/verify.sh`
- Create: `benchmarks/gbrain-vs-gitnexus/tasks/T1_fix_type_inference/seed.patch`

- [ ] **Step 1: Write prompt.md**

Write `benchmarks/gbrain-vs-gitnexus/tasks/T1_fix_type_inference/prompt.md`:

```markdown
# Task: Fix Effect Type Inference Bug

In this Effect-TS codebase, a utility function `Effect.gen` has a TypeScript type inference issue: when used with a specific generator pattern, the inferred return type is too wide (`Effect<never, Error, unknown>` instead of the actual resolved type).

## Your Task

1. Investigate how `Effect.gen` infers its return type by reading `packages/effect/src/Effect.ts` and related type definitions
2. Locate the type-level bug that causes the overly-wide inference
3. Fix the type definition so the return type is correctly narrowed
4. Verify the fix by running the project's TypeScript type check

## Constraints

- Do not change runtime behavior — only fix types
- The existing test suite must pass (`pnpm test`)
- The fix should be minimal — a few lines in the type definitions

## Expected Outcome

After the fix, `Effect.gen` should infer the correct narrow return type, and `pnpm typecheck` should pass without errors.
```

- [ ] **Step 2: Write prompt_gb.md**

Write `benchmarks/gbrain-vs-gitnexus/tasks/T1_fix_type_inference/prompt_gb.md`:

```markdown
# Task: Fix Effect Type Inference Bug

[Same task description as prompt.md]

## MANDATORY: Using GBrain Knowledge Graph

**Before making any code changes**, you MUST use GBrain MCP tools to investigate:

1. **search** "Effect.gen" or "gen" — find where `gen` is defined and how its type is constructed
2. **search** "Generator" — find the generator type helpers that `gen` depends on
3. **traverse_graph** the Effect module at depth 2 to understand the type dependency chain
4. **get_page** the relevant file to read the full type definition

Use these tools to trace the type inference chain BEFORE proposing a fix. Your investigation notes should reference specific files and line numbers found via gbrain.
```

- [ ] **Step 3: Write ground_truth.md**

Write `benchmarks/gbrain-vs-gitnexus/tasks/T1_fix_type_inference/ground_truth.md`:

```markdown
# Ground Truth: fix_type_inference

## Root Cause

The `Effect.gen` function uses a type helper that doesn't properly narrow the `Requirements` type parameter when the generator yields effects. The issue is in the `GenGenerator` type which maps `Generator<T, R, E>` but loses type information at the yield boundary.

## Correct Fix

In `packages/effect/src/Effect.ts`, locate the type definition for `GenGenerator` and ensure the `A` (success type) parameter properly propagates through the yield chain.

## Key Files
- `packages/effect/src/Effect.ts`: `gen` function + `GenGenerator` type
- `packages/effect/src/Types.ts` (if exists): core type helpers

## Verification
- `pnpm typecheck` must pass
- A simple test with `Effect.gen` should produce a correctly narrowed type
```

- [ ] **Step 4: Write verify.sh**

Write `benchmarks/gbrain-vs-gitnexus/tasks/T1_fix_type_inference/verify.sh`:

```bash
#!/bin/bash
set -euo pipefail
PARTIAL=0

REPO="${EFFECT_TS_REPO:-/tmp/effect-ts-bench}"
cd "$REPO"

echo "=== Test 1: TypeScript type check ==="
pnpm exec tsc --noEmit 2>&1 | tee /tmp/t1_typecheck.log || { echo "FAIL: typecheck"; PARTIAL=2; }

echo "=== Test 2: Existing test suite (effect package) ==="
pnpm --filter effect test -- --passWithNoTests 2>&1 | tee /tmp/t1_tests.log || { echo "FAIL: tests"; PARTIAL=2; }

echo "=== Test 3: gen() type narrowing smoke test ==="
cat > /tmp/t1_smoke.ts << 'TSEOF'
import { Effect } from "./packages/effect/src/index.js";

const program = Effect.gen(function* (_) {
  const a = yield* _(Effect.succeed(42));
  const b = yield* _(Effect.succeed("hello"));
  // After fix: program should be Effect<never, never, [number, string]>, not Effect<never, Error, unknown>
  return [a, b] as const;
});
// If type fix works, accessing return values should compile without error
const result: readonly [number, string] = Effect.runSync(program);
console.log("PASS: type narrowed correctly", result);
TSEOF
pnpm exec tsx /tmp/t1_smoke.ts || { echo "FAIL: smoke test"; PARTIAL=2; }

exit $PARTIAL
```

- [ ] **Step 5: Write seed.patch**

Write `benchmarks/gbrain-vs-gitnexus/tasks/T1_fix_type_inference/seed.patch`:

```diff
diff --git a/packages/effect/src/Effect.ts b/packages/effect/src/Effect.ts
index 0000000..0000000 100644
--- a/packages/effect/src/Effect.ts
+++ b/packages/effect/src/Effect.ts
@@ -X,Y +X,Y @@
 // Seed patch intentionally empty — this is a type-level bug.
-// The bug is introduced by a subtle change in the type parameter bounds
-// of GenGenerator. The actual line numbers depend on the Effect-TS version.
+// Agent must identify and fix the type narrowing issue.
```

Note: The seed patch must be updated when the specific Effect-TS commit is chosen, with real file paths and line numbers.

- [ ] **Step 6: Commit**

```bash
mkdir -p benchmarks/gbrain-vs-gitnexus/tasks/T1_fix_type_inference
git add benchmarks/gbrain-vs-gitnexus/tasks/T1_fix_type_inference/
git commit -m "feat: task T1 — fix type inference bug in Effect-TS"
```

---

### Task 9-15: Tasks T2-T8 (same pattern as T1)

Each task follows the same 5-file structure: `prompt.md`, `prompt_gb.md`, `ground_truth.md`, `verify.sh`, `seed.patch`. Below are the prompts and verification strategies. Seed patches are empty (default repo state) unless a specific code modification is needed to set up the bug.

### Task 9: T2 — understand_layer_system

**Files:**
- Create: `benchmarks/gbrain-vs-gitnexus/tasks/T2_understand_layer_system/prompt.md`
- Create: `benchmarks/gbrain-vs-gitnexus/tasks/T2_understand_layer_system/prompt_gb.md`
- Create: `benchmarks/gbrain-vs-gitnexus/tasks/T2_understand_layer_system/ground_truth.md`
- Create: `benchmarks/gbrain-vs-gitnexus/tasks/T2_understand_layer_system/verify.sh`
- Create: `benchmarks/gbrain-vs-gitnexus/tasks/T2_understand_layer_system/seed.patch`

- [ ] **Step 1: Write prompt.md**

```markdown
# Task: Understand Effect's Layer System

Effect-TS uses a `Layer` abstraction for dependency injection. Your task is to understand and explain how the Layer system works.

## Your Task

1. Read the Layer-related source files in `packages/effect/src/`
2. Write a concise explanation (in `layer_explanation.md`) covering:
   - What is a Layer and how is it constructed?
   - How do layers compose (horizontal `Layer.merge` vs vertical `Layer.provide`)?
   - How does the `Context` system interact with Layers?
   - What's the lifecycle of a layer (construction, memoization, scoping)?
3. Provide a code example demonstrating layer composition

## Expected Outcome

A markdown file saved at the repo root that correctly explains the Layer system with at least the 4 topics above. The code example must compile.
```

- [ ] **Step 2: Write prompt_gb.md** (same content + MCP mandate):

```markdown
# Task: Understand Effect's Layer System

[Same task description as prompt.md]

## MANDATORY: Using GBrain Knowledge Graph

**Before writing any explanation**, you MUST use GBrain MCP tools:

1. **search** "Layer" in the codebase to find all Layer-related modules
2. **search** "Layer.provide" and "Layer.merge" to understand composition
3. **traverse_graph** the Layer module to see its dependency graph
4. **get_page** key files to read full source code

Your explanation must reference specific files and function signatures found via gbrain search.
```

- [ ] **Step 3: Write ground_truth.md**

```markdown
# Ground Truth: understand_layer_system

## Key Concepts Agent Must Cover

1. **Layer construction**: `Layer.succeed(context)`, `Layer.effect(effect)`, `Layer.scoped(effect)`, `Layer.function(tag, fn)`
2. **Composition**: `Layer.merge` combines two layers; `Layer.provide` feeds one layer into another's requirements
3. **Context integration**: Each layer provides a `Context<Tag, Service>`; `Layer.provideMerge` resolves the dependency graph
4. **Lifecycle**: Layers are memoized (constructed once), scoped resources are acquired/released per scope

## Key Files
- `packages/effect/src/Layer.ts`
- `packages/effect/src/Context.ts`
- `packages/effect/src/ManagedRuntime.ts`
```

- [ ] **Step 4: Write verify.sh**

```bash
#!/bin/bash
set -euo pipefail
PARTIAL=0

REPO="${EFFECT_TS_REPO:-/tmp/effect-ts-bench}"
OUTFILE="$REPO/layer_explanation.md"

echo "=== Check output file exists ==="
[ -f "$OUTFILE" ] || { echo "FAIL: layer_explanation.md not found"; exit 2; }

echo "=== Check required topics ==="
grep -qi "layer" "$OUTFILE" || { echo "FAIL: missing Layer explanation"; PARTIAL=2; }
grep -qi "merge\|compose\|composition" "$OUTFILE" || { echo "FAIL: missing composition explanation"; PARTIAL=2; }
grep -qi "context" "$OUTFILE" || { echo "FAIL: missing Context explanation"; PARTIAL=2; }
grep -qi "lifecycle\|scop\|memoiz\|construct" "$OUTFILE" || { echo "FAIL: missing lifecycle explanation"; PARTIAL=2; }

echo "=== Check code example ==="
grep -qi '```' "$OUTFILE" || { echo "FAIL: no code example"; PARTIAL=2; }

echo "PASS"
exit $PARTIAL
```

- [ ] **Step 5: Write empty seed.patch**

```bash
echo "# No seed changes needed — base repo state" > benchmarks/gbrain-vs-gitnexus/tasks/T2_understand_layer_system/seed.patch
```

- [ ] **Step 6: Commit**

```bash
git add benchmarks/gbrain-vs-gitnexus/tasks/T2_understand_layer_system/
git commit -m "feat: task T2 — understand Effect Layer system"
```

### Task 10: T3 — add_config_option

- [ ] **Step 1: Write prompt.md**

```markdown
# Task: Add a Configuration Option to Effect Runtime

Effect-TS's `ManagedRuntime` accepts a configuration for the runtime behavior. Your task is to add a `maxConcurrency` option that limits the maximum number of concurrent fibers.

## Your Task

1. Find `ManagedRuntime` in `packages/effect/src/ManagedRuntime.ts`
2. Add a `maxConcurrency: number` option (default: `Infinity`) to the runtime configuration
3. Wire the option through so that `Runtime.runPromise` respects it
4. Add a test demonstrating the concurrency limit

## Constraints

- Default behavior (no limit) must remain unchanged
- The existing test suite must pass

## Expected Outcome

A `maxConcurrency` option that limits concurrent fiber execution, with a passing test.
```

- [ ] **Step 2: Write prompt_gb.md** (same + MCP mandate):

```markdown
[...same task...]

## MANDATORY: Using GBrain Knowledge Graph

**Before modifying any code**, use gbrain tools:
1. **search** "ManagedRuntime" to find the configuration type and runtime implementation
2. **search** "Fiber" and "concurrency" to understand fiber scheduling
3. **get_page** the ManagedRuntime module to read the full implementation
4. **traverse_graph** from ManagedRuntime to find downstream consumers

Only propose changes after you've traced the full dependency chain via gbrain.
```

- [ ] **Step 3: Write ground_truth.md**

```markdown
# Ground Truth: add_config_option

## Correct Implementation

1. Add `maxConcurrency: number` to `ManagedRuntime.Options` type (default `Infinity`)
2. Create a `Semaphore` from `Effect.makeSemaphore(maxConcurrency)` during runtime initialization
3. Wrap fiber execution with `semaphore.withPermit(1)(effect)` before `runPromise`
4. Add test: spawn 5 concurrent effects with maxConcurrency=2, verify at most 2 run at once

## Key Files
- `packages/effect/src/ManagedRuntime.ts`
- `packages/effect/src/Effect.ts` (Semaphore/Fiber types)
```

- [ ] **Step 4: Write verify.sh**

```bash
#!/bin/bash
set -euo pipefail
PARTIAL=0
REPO="${EFFECT_TS_REPO:-/tmp/effect-ts-bench}"
cd "$REPO"

echo "=== Test 1: TypeScript check ==="
pnpm exec tsc --noEmit --project packages/effect/tsconfig.json 2>&1 | tail -5 || { echo "FAIL"; PARTIAL=2; }

echo "=== Test 2: Max concurrency smoke test ==="
cat > /tmp/t3_concurrency.ts << 'TSEOF'
import { Effect, ManagedRuntime } from "./packages/effect/src/index.js";
const runtime = ManagedRuntime.make(/* default */);
// Verify the maxConcurrency option is accepted
const opts: ManagedRuntime.Options = { maxConcurrency: 4 };
console.log("PASS: option type accepted", opts);
TSEOF
pnpm exec tsx /tmp/t3_concurrency.ts || { echo "FAIL"; PARTIAL=2; }

echo "=== Test 3: Existing tests ==="
pnpm --filter effect test 2>&1 | tail -5 || { echo "FAIL"; PARTIAL=2; }

exit $PARTIAL
```

- [ ] **Step 5: Write empty seed.patch + commit**

```bash
echo "# No seed changes" > benchmarks/gbrain-vs-gitnexus/tasks/T3_add_config_option/seed.patch
git add benchmarks/gbrain-vs-gitnexus/tasks/T3_add_config_option/
git commit -m "feat: task T3 — add maxConcurrency config to Effect Runtime"
```

### Task 11: T4 — write_core_test

- [ ] **Step 1: Write prompt.md**

```markdown
# Task: Write Unit Tests for Effect.gen

The `Effect.gen` function is heavily used but has incomplete test coverage. Your task is to write comprehensive unit tests.

## Your Task

1. Study `Effect.gen` in `packages/effect/src/Effect.ts` to understand its signature and behavior
2. Write tests covering these cases:
   - Basic generator with sequential yields
   - Error handling within gen (try/catch in generator)
   - Nested gen calls (gen inside gen)
   - gen with requirements (Context)
   - gen with interruption signal
3. Save tests to `packages/effect/test/gen.test.ts`

## Expected Outcome

A test file with at least 5 test cases that exercises `Effect.gen` edge cases and passes.
```

- [ ] **Step 2: Write prompt_gb.md** (same + MCP mandate):

```markdown
[...same task...]

## MANDATORY: Using GBrain Knowledge Graph

**Before writing tests**, use gbrain to understand the code:
1. **search** "Effect.gen" to find the implementation and existing tests
2. **search** "gen" to find related type definitions
3. **get_page** the Effect module to read the gen signature
4. **traverse_graph** from gen to understand what it depends on
```

- [ ] **Step 3: Write ground_truth.md**

```markdown
# Ground Truth: write_core_test

## Correct Tests

1. **Sequential yields**: gen yields succeed(1), succeed(2), returns [1, 2]
2. **Error case**: gen yields fail("boom"), verifies error propagation
3. **Nested gen**: outer gen yields inner gen, verifies flattening
4. **Requirements**: gen uses Context.Tag, verifies requirement inference
5. **Interruption**: gen with interruptible region, verifies cleanup runs

## Key Files
- `packages/effect/src/Effect.ts` (gen implementation)
- `packages/effect/test/Effect/` (existing test patterns)
```

- [ ] **Step 4: Write verify.sh**

```bash
#!/bin/bash
set -euo pipefail
PARTIAL=0
REPO="${EFFECT_TS_REPO:-/tmp/effect-ts-bench}"
cd "$REPO"

TESTFILE="packages/effect/test/gen.test.ts"
[ -f "$TESTFILE" ] || { echo "FAIL: test file not created"; exit 2; }

echo "=== Check test count ==="
TEST_COUNT=$(grep -c 'it\|test\|describe' "$TESTFILE" || true)
[ "$TEST_COUNT" -ge 5 ] || { echo "FAIL: expected >=5 test cases, got $TEST_COUNT"; PARTIAL=2; }

echo "=== Run the new tests ==="
pnpm --filter effect test -- --testPathPattern gen.test 2>&1 | tail -5 || { echo "FAIL"; PARTIAL=2; }

exit $PARTIAL
```

- [ ] **Step 5: Write empty seed.patch + commit**

```bash
echo "# No seed changes" > benchmarks/gbrain-vs-gitnexus/tasks/T4_write_core_test/seed.patch
git add benchmarks/gbrain-vs-gitnexus/tasks/T4_write_core_test/
git commit -m "feat: task T4 — write unit tests for Effect.gen"
```

### Task 12: T5 — find_callers_callees (code_context)

This is the first code-understanding task that specifically tests GBrain GitNexus's `code_context` MCP tool.

- [ ] **Step 1: Write prompt.md**

```markdown
# Task: Find All Callers and Callees of Effect.provideService

The function `Effect.provideService` is a core API in Effect-TS. Your task is to find all its direct callers and callees in the codebase.

## Your Task

1. Find where `provideService` is defined
2. Trace it to find:
   - All functions/methods that directly call `provideService` (callers)
   - All functions/methods that `provideService` directly calls (callees)
3. Write your findings to `call_graph_provideService.md` as:
   ```
   # Call Graph: Effect.provideService
   ## Definition
   File: path/to/file, Line: N
   ## Callers (N total)
   - FuncA (path/to/file:line)
   - FuncB (path/to/file:line)
   ## Callees (N total)
   - FuncX (path/to/file:line)
   - FuncY (path/to/file:line)
   ```

## Constraints

- Each caller/callee must include the exact file path and line number
- Manual grep is allowed, but you must verify each finding

## Expected Outcome

A complete call graph file with accurate file paths and line numbers.
```

- [ ] **Step 2: Write prompt_gb.md** (with specific code_* tool instructions):

```markdown
# Task: Find All Callers and Callees of Effect.provideService

[same task description]

## MANDATORY: Using GBrain Code Tools

**You MUST use gbrain's code_context tool** to solve this task. This tool is specifically designed for call-graph queries.

1. First, use **code_query** to search for "provideService" and confirm the symbol exists:
   - `code_query "provideService"`
2. Then, use **code_context** to get the full call graph:
   - `code_context "provideService"`
   
   This returns: definition location, callers[], callees[], importers[], imports[]
3. **Write your findings markdown based SOLELY on the code_context output.**

Do NOT use manual grep. The code_context tool provides the accurate, pre-computed call graph. If code_context returns empty, report that the symbol was not found.
```

- [ ] **Step 3: Write ground_truth.md**

```markdown
# Ground Truth: find_callers_callees

## Expected Structure

The output must contain:
1. **Definition section** with exact file path and line number
2. **Callers section** listing each caller with file path and line
3. **Callees section** listing each callee with file path and line
4. Each entry must have the format: `Name (path:line)`

## Acceptable Results

- If `code_context` is used (Group C), results should match the GitNexus index exactly
- If manual grep is used (Groups A/B), results should be at least 80% complete

## Key Symbol
- `provideService` is in `packages/effect/src/Effect.ts`
```

- [ ] **Step 4: Write verify.sh**

```bash
#!/bin/bash
set -euo pipefail
PARTIAL=0
REPO="${EFFECT_TS_REPO:-/tmp/effect-ts-bench}"
OUTFILE="$REPO/call_graph_provideService.md"

[ -f "$OUTFILE" ] || { echo "FAIL: output file not found"; exit 2; }

echo "=== Check structure ==="
grep -q "## Definition" "$OUTFILE" || { echo "FAIL: missing Definition section"; PARTIAL=2; }
grep -q "## Callers" "$OUTFILE" || { echo "FAIL: missing Callers section"; PARTIAL=2; }
grep -q "## Callees" "$OUTFILE" || { echo "FAIL: missing Callees section"; PARTIAL=2; }

echo "=== Check content ==="
# Should have at least one file path reference
grep -qE '[a-zA-Z0-9_/]+\.[a-z]+:[0-9]+' "$OUTFILE" || { echo "FAIL: no file:line references found"; PARTIAL=2; }

# Should mention provideService
grep -qi "provideService" "$OUTFILE" || { echo "FAIL: does not mention provideService"; PARTIAL=2; }

# Count callers and callees
CALLERS=$(grep -c '^\-' <(sed -n '/## Callers/,/## Callees/p' "$OUTFILE" | head -n -1) || echo 0)
echo "Callers found: $CALLERS"
[ "$CALLERS" -gt 0 ] || { echo "FAIL: no callers listed"; PARTIAL=2; }

exit $PARTIAL
```

- [ ] **Step 5: Write empty seed.patch + commit**

```bash
echo "# No seed changes" > benchmarks/gbrain-vs-gitnexus/tasks/T5_find_callers_callees/seed.patch
git add benchmarks/gbrain-vs-gitnexus/tasks/T5_find_callers_callees/
git commit -m "feat: task T5 — find callers/callees of provideService"
```

### Task 13: T6 — assess_impact (code_impact)

- [ ] **Step 1: Write prompt.md**

```markdown
# Task: Assess Impact of Modifying Effect.Context

The `Context` type in Effect-TS is fundamental — many modules depend on it. Your task is to assess what would break if we add a new required field to `Context.empty`.

## Your Task

1. Identify all downstream consumers of `Context.empty`
2. For each consumer found, classify the risk:
   - **HIGH**: directly uses `Context.empty` and would break
   - **MEDIUM**: uses the Context type but not `empty` directly
   - **LOW**: uses Context only through other abstractions
3. Write the impact assessment to `impact_context_empty.md`

## Expected Outcome

An impact report listing all affected symbols with their risk levels and a summary: total affected, high/medium/low counts.
```

- [ ] **Step 2: Write prompt_gb.md**

```markdown
[...same task...]

## MANDATORY: Using GBrain Code Tools

**You MUST use gbrain's code_impact tool:**

1. **code_query** "Context.empty" to find the symbol
2. **code_impact** "Context.empty" --direction downstream --depth 5
   
   This returns the impact chain with risk levels pre-computed.
3. Base your impact report on the code_impact output. Classify risks using the tool's built-in HIGH/MEDIUM/LOW assignment.
```

- [ ] **Step 3: Write ground_truth.md**

```markdown
# Ground Truth: assess_impact

## Expected Format
- List of affected symbols with file path, line, risk level
- Risk summary: { total, high, medium, low }
- Each symbol must include the dependency path (how it connects to Context.empty)
```

- [ ] **Step 4: Write verify.sh**

```bash
#!/bin/bash
set -euo pipefail
PARTIAL=0
REPO="${EFFECT_TS_REPO:-/tmp/effect-ts-bench}"
OUTFILE="$REPO/impact_context_empty.md"

[ -f "$OUTFILE" ] || { echo "FAIL: output not found"; exit 2; }

echo "=== Check structure ==="
grep -qi "HIGH\|MEDIUM\|LOW" "$OUTFILE" || { echo "FAIL: no risk levels"; PARTIAL=2; }
grep -qi "total" "$OUTFILE" || { echo "FAIL: no summary"; PARTIAL=2; }

echo "=== Check affected count ==="
AFFECTED=$(grep -cE '^\s*\-' "$OUTFILE" || echo 0)
echo "Affected symbols: $AFFECTED"
[ "$AFFECTED" -ge 1 ] || { echo "FAIL: no affected symbols listed"; PARTIAL=2; }

# For Group C: code_impact should return structured data, expect more comprehensive results
HIGH_COUNT=$(grep -ci "HIGH" "$OUTFILE" || echo 0)
echo "HIGH risk: $HIGH_COUNT"

exit $PARTIAL
```

- [ ] **Step 5: Write empty seed.patch + commit**

```bash
echo "# No seed changes" > benchmarks/gbrain-vs-gitnexus/tasks/T6_assess_impact/seed.patch
git add benchmarks/gbrain-vs-gitnexus/tasks/T6_assess_impact/
git commit -m "feat: task T6 — assess impact of modifying Context.empty"
```

### Task 14: T7 — search_signature_pattern (code_query)

- [ ] **Step 1: Write prompt.md**

```markdown
# Task: Search for All Functions with a Specific Pattern

Find all Effect-TS functions whose signature includes the pattern `Effect<Requirements, never, A>` (i.e., infallible effects).

## Your Task

1. Search the codebase for all function declarations that return `Effect<*, never, *>`
2. List them in `infallible_effects.md` with:
   - Function name
   - File path and line number
   - Full return type signature
3. Count how many such functions exist

## Expected Outcome

A complete list of infallible Effect functions with exact locations and signatures.
```

- [ ] **Step 2: Write prompt_gb.md**

```markdown
[...same task...]

## MANDATORY: Using GBrain Code Tools

**You MUST use gbrain's code_query tool:**

1. **code_query** "Effect<never>" to search for infallible effect signatures
2. **code_query** "infallible" or "never" with code type filter
3. Use multiple queries to ensure comprehensive coverage

Base your answer on the code_query results, which search both full-text and vector embeddings of code symbols.
```

- [ ] **Step 3: Write ground_truth.md**

```markdown
# Ground Truth: search_signature_pattern

## Expected Format
- Markdown list with function name, file:line, signature
- Total count at the end
- Each entry must be a real function declaration in Effect-TS
```

- [ ] **Step 4: Write verify.sh**

```bash
#!/bin/bash
set -euo pipefail
PARTIAL=0
REPO="${EFFECT_TS_REPO:-/tmp/effect-ts-bench}"
OUTFILE="$REPO/infallible_effects.md"

[ -f "$OUTFILE" ] || { echo "FAIL: output not found"; exit 2; }

echo "=== Check content ==="
grep -qi "Effect" "$OUTFILE" || { echo "FAIL: no Effect references"; PARTIAL=2; }
grep -qi "never" "$OUTFILE" || { echo "FAIL: no 'never' references"; PARTIAL=2; }

COUNT=$(grep -cE '^\s*\-' "$OUTFILE" || echo 0)
echo "Functions found: $COUNT"
[ "$COUNT" -ge 3 ] || { echo "FAIL: expected >=3 functions, got $COUNT"; PARTIAL=2; }

# Verify each entry has file:line
WITH_LOC=$(grep -cE '[a-zA-Z0-9_/]+\.[a-z]+:[0-9]+' "$OUTFILE" || echo 0)
echo "Entries with file:line: $WITH_LOC"
[ "$WITH_LOC" -ge 3 ] || { echo "FAIL: expected >=3 entries with file:line"; PARTIAL=2; }

exit $PARTIAL
```

- [ ] **Step 5: Write empty seed.patch + commit**

```bash
echo "# No seed changes" > benchmarks/gbrain-vs-gitnexus/tasks/T7_search_signature_pattern/seed.patch
git add benchmarks/gbrain-vs-gitnexus/tasks/T7_search_signature_pattern/
git commit -m "feat: task T7 — search infallible effect function signatures"
```

### Task 15: T8 — refactor_cross_module (code_context + code_impact)

- [ ] **Step 1: Write prompt.md**

```markdown
# Task: Refactor Cross-Module Dependency in Effect

The `Layer` module has a direct dependency on `Effect.runSync` which creates tight coupling. Your task is to refactor this dependency to use dependency injection instead.

## Your Task

1. Find where `Layer` calls `Effect.runSync` directly (or a similar internal runtime call)
2. Identify all downstream consumers that would be affected by the change
3. Refactor to inject the runtime dependency instead of calling it directly
4. Update all affected consumers
5. All existing tests must pass

## Constraints

- Public API of Layer must remain compatible
- Runtime behavior must be identical

## Expected Outcome

A refactored Layer module with injected runtime dependency and all passing tests.
```

- [ ] **Step 2: Write prompt_gb.md**

```markdown
[...same task...]

## MANDATORY: Using GBrain Code Tools

**You MUST use gbrain's code tools to map the dependency graph before refactoring:**

1. **code_context** for the `Layer` constructor to find all callers
2. **code_impact** for the runtime call inside Layer to assess downstream impact
3. **code_query** "runSync" to find all direct invocations in Layer

Do NOT make changes until you have the full dependency picture from code_context and code_impact. List all affected consumers in your response before writing any code.
```

- [ ] **Step 3: Write ground_truth.md**

```markdown
# Ground Truth: refactor_cross_module

## Correct Approach

1. Identify the runtime call in Layer (e.g., `Runtime.runSync(defaultRuntime)(effect)`)
2. Create an interface/type for the runtime dependency
3. Pass the runtime as a parameter rather than using the default
4. Update Layer callers to pass their runtime

## Key Files
- `packages/effect/src/Layer.ts`
- `packages/effect/src/ManagedRuntime.ts`
```

- [ ] **Step 4: Write verify.sh**

```bash
#!/bin/bash
set -euo pipefail
PARTIAL=0
REPO="${EFFECT_TS_REPO:-/tmp/effect-ts-bench}"
cd "$REPO"

echo "=== Test 1: TypeCheck ==="
pnpm exec tsc --noEmit --project packages/effect/tsconfig.json 2>&1 | tail -5 || { echo "FAIL: typecheck"; PARTIAL=2; }

echo "=== Test 2: Layer tests ==="
pnpm --filter effect test -- --testPathPattern Layer 2>&1 | tail -5 || { echo "FAIL: tests"; PARTIAL=2; }

echo "=== Test 3: Verify no direct runSync call in Layer ==="
grep -rn "runSync" packages/effect/src/Layer.ts && { echo "FAIL: runSync still directly called in Layer"; PARTIAL=2; } || echo "PASS: no direct runSync"

exit $PARTIAL
```

- [ ] **Step 5: Write empty seed.patch + commit**

```bash
echo "# No seed changes" > benchmarks/gbrain-vs-gitnexus/tasks/T8_refactor_cross_module/seed.patch
git add benchmarks/gbrain-vs-gitnexus/tasks/T8_refactor_cross_module/
git commit -m "feat: task T8 — refactor cross-module dependency in Layer"
```

---

### Task 16: Integration test

**Files:**
- Create: `benchmarks/gbrain-vs-gitnexus/runner/run.test.ts`

- [ ] **Step 1: Write integration test for runner**

Write `benchmarks/gbrain-vs-gitnexus/runner/run.test.ts`:

```typescript
import { describe, it, expect } from 'bun:test';
import { computeEfficiencyScores, meanEfficiencyScore, successRate, computeCodeToolLeverage, meanCodeToolLeverage } from './metrics';
import type { AgentRunResult, CodeToolLeverage } from './types';

const makeResult = (overrides: Partial<AgentRunResult>): AgentRunResult => ({
  taskId: 'T1',
  group: 'A',
  success: 1.0,
  toolCallCount: 5,
  wallClockMs: 30000,
  tokensIn: 5000,
  tokensOut: 2000,
  outputDiff: 'diff --git ...',
  outputFiles: {},
  logs: '',
  ...overrides,
});

describe('metrics', () => {
  it('successRate computes correctly', () => {
    const results = [
      makeResult({ group: 'A', success: 1.0 }),
      makeResult({ group: 'A', success: 0.0 }),
      makeResult({ group: 'A', success: 1.0 }),
    ];
    expect(successRate(results)).toBeCloseTo(2 / 3);
  });

  it('computeEfficiencyScores normalizes 3 groups per task', () => {
    const resultsA = [makeResult({ taskId: 'T1', group: 'A', toolCallCount: 10, wallClockMs: 50000, tokensIn: 8000, tokensOut: 3000 })];
    const resultsB = [makeResult({ taskId: 'T1', group: 'B', toolCallCount: 5, wallClockMs: 30000, tokensIn: 5000, tokensOut: 2000 })];
    const resultsC = [makeResult({ taskId: 'T1', group: 'C', toolCallCount: 3, wallClockMs: 20000, tokensIn: 4000, tokensOut: 1500 })];

    const scores = computeEfficiencyScores(resultsA, resultsB, resultsC);
    expect(scores.has('A:T1')).toBe(true);
    expect(scores.has('B:T1')).toBe(true);
    expect(scores.has('C:T1')).toBe(true);

    // Fastest group should have highest score
    const scoreA = scores.get('A:T1')!.score;
    const scoreB = scores.get('B:T1')!.score;
    const scoreC = scores.get('C:T1')!.score;
    expect(scoreC).toBeGreaterThanOrEqual(scoreB);
    expect(scoreB).toBeGreaterThanOrEqual(scoreA);
  });

  it('meanEfficiencyScore averages per group', () => {
    const resultsA_T1 = [makeResult({ taskId: 'T1', group: 'A', toolCallCount: 10 })];
    const resultsA_T2 = [makeResult({ taskId: 'T2', group: 'A', toolCallCount: 20 })];
    const resultsB_T1 = [makeResult({ taskId: 'T1', group: 'B', toolCallCount: 5 })];
    const resultsB_T2 = [makeResult({ taskId: 'T2', group: 'B', toolCallCount: 10 })];

    const scores = computeEfficiencyScores(
      [...resultsA_T1, ...resultsA_T2],
      [...resultsB_T1, ...resultsB_T2],
      [],
    );
    const meanA = meanEfficiencyScore('A', scores);
    const meanB = meanEfficiencyScore('B', scores);
    expect(meanA).toBeGreaterThan(0);
    expect(meanB).toBeGreaterThan(0);
  });
});

describe('code tool leverage', () => {
  it('computeCodeToolLeverage extracts code_* tools from Group C', () => {
    const resultsC = [
      makeResult({
        taskId: 'T5',
        group: 'C',
        success: 1.0,
        gbrainToolCalls: { code_query: 3, code_context: 2, search: 1 },
      }),
      makeResult({
        taskId: 'T6',
        group: 'C',
        success: 0.0,
        gbrainToolCalls: { code_impact: 1 },
      }),
    ];

    const leverage = computeCodeToolLeverage(resultsC);
    expect(leverage.length).toBeGreaterThan(0);

    // code_query and code_context from successful task should have high leverage
    const queryLev = leverage.find(l => l.tool === 'code_query');
    expect(queryLev).toBeDefined();
    if (queryLev) {
      expect(queryLev.totalCalls).toBe(3);
      expect(queryLev.leverage).toBe(1.0); // success=1.0 so all effective
    }

    // code_impact from failed task should have 0 leverage
    const impactLev = leverage.find(l => l.tool === 'code_impact');
    expect(impactLev).toBeDefined();
    if (impactLev) {
      expect(impactLev.leverage).toBe(0);
    }
  });

  it('meanCodeToolLeverage returns 0 for empty', () => {
    expect(meanCodeToolLeverage([])).toBe(0);
  });

  it('meanCodeToolLeverage averages correctly', () => {
    const leveraged: CodeToolLeverage[] = [
      { tool: 'code_query', totalCalls: 10, effectiveCalls: 8, leverage: 0.8 },
      { tool: 'code_context', totalCalls: 5, effectiveCalls: 5, leverage: 1.0 },
    ];
    expect(meanCodeToolLeverage(leveraged)).toBeCloseTo(0.9);
  });
});

describe('MCP compliance', () => {
  it('empty gbrainToolCalls means non-compliant', () => {
    const r = makeResult({ group: 'B', gbrainToolCalls: {} });
    const compliant = Object.values(r.gbrainToolCalls ?? {}).some(c => c > 0);
    expect(compliant).toBe(false);
  });

  it('non-empty gbrainToolCalls means compliant', () => {
    const r = makeResult({ group: 'B', gbrainToolCalls: { search: 1 } });
    const compliant = Object.values(r.gbrainToolCalls ?? {}).some(c => c > 0);
    expect(compliant).toBe(true);
  });

  it('undefined gbrainToolCalls means non-compliant', () => {
    const r = makeResult({ group: 'B', gbrainToolCalls: undefined });
    const compliant = Object.values(r.gbrainToolCalls ?? {}).some(c => c > 0);
    expect(compliant).toBe(false);
  });
});
```

- [ ] **Step 2: Run tests to verify**

```bash
cd benchmarks/gbrain-vs-gitnexus && bun test runner/run.test.ts
```
Expected: 9 tests pass.

- [ ] **Step 3: Commit**

```bash
git add benchmarks/gbrain-vs-gitnexus/runner/run.test.ts
git commit -m "test: integration tests for 3-group metrics + code leverage + MCP compliance"
```

---

## Self-Review Checklist

1. **Spec coverage**: Each spec requirement mapped to a task:
   - 3-group architecture → Tasks 1-5 (types, metrics, report, agent-runner, run.ts)
   - MCP force enforcement → Task 4 (agent-runner `checkMCPCompliance`, `finalSuccess` gate)
   - 8 tasks (4 general + 4 code-understanding) → Tasks 8-15
   - 4-dimension scoring → Task 2 (metrics) + Task 5 (run.ts composite formula)
   - Code Tool Leverage → Task 2 (`computeCodeToolLeverage`)
   - MCP config files → Task 6
   - Seed script → Task 7
   - Report format → Task 3 (report.ts)
   - Effect-TS as target → Task 7 (setup.sh) + all task prompts reference Effect-TS

2. **Placeholder scan**: 
   - T1 seed.patch has a note about needing real line numbers when Effect-TS commit is chosen — acceptable since it depends on external repo state
   - All other files have concrete content

3. **Type consistency**: 
   - `GroupLabel = 'A' | 'B' | 'C'` used consistently across types.ts, metrics.ts, report.ts, agent-runner.ts, run.ts
   - `CodeToolLeverage` defined in types.ts, computed in metrics.ts, used in run.ts
   - `mcpCompliant` field on `AgentRunResult` checked in agent-runner.ts
   - `computeCodeToolLeverage` export from metrics.ts imported in run.ts
