#!/usr/bin/env bun
import { existsSync, readFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { execSync } from 'node:child_process';

import type { AgentAdapter, AgentRunResult, BenchmarkReport, TaskDef, TaskRow, ToolHeatmapEntry } from './types';
import { computeEfficiencyScores, meanEfficiencyScore, successRate, computeCodeToolLeverage, meanCodeToolLeverage, computeCompositeScore } from './metrics';
import { evaluateQuality } from './judge';
import { createOpencodeAdapter } from './agent-runner';
import { saveReport } from './report';

const PREACT_REPO = process.env.PREACT_REPO ?? '/tmp/preact-bench';
const PREACT_COMMIT = process.env.PREACT_COMMIT ?? execSync('git rev-parse HEAD', { cwd: PREACT_REPO, encoding: 'utf-8' }).trim();
const RESULTS_ROOT = join(import.meta.dir, '..', 'results', new Date().toISOString().slice(0, 10));
const OPENCODE_CMD = process.env.OPENCODE_CMD;
const JUDGE_API_KEY = process.env.JUDGE_API_KEY ?? process.env.ANTHROPIC_API_KEY ?? '';
const JUDGE_MODEL = process.env.JUDGE_MODEL ?? 'deepseek-chat';
const JUDGE_BASE_URL = process.env.JUDGE_BASE_URL ?? 'https://api.deepseek.com/v1';
const GBRAIN_NEXUS_BIN = process.env.GBRAIN_NEXUS_BIN ?? 'gbrain';

const TASKS_DIR = join(import.meta.dir, '..', 'tasks');

const TASK_DEFS: TaskDef[] = [
  { id: 'P2', name: 'understand_component_lifecycle',  type: 'understand',   dir: join(TASKS_DIR, 'P2_understand_component_lifecycle'),  modules: ['src/'] },
  { id: 'P3', name: 'add_batching_option',             type: 'add_feature',  dir: join(TASKS_DIR, 'P3_add_batching_option'),             modules: ['src/'] },
  { id: 'P5', name: 'find_render_callers',              type: 'code_context', dir: join(TASKS_DIR, 'P5_find_render_callers'),              modules: ['src/'] },
  { id: 'P7', name: 'search_createElement',             type: 'code_query',   dir: join(TASKS_DIR, 'P7_search_createElement'),             modules: ['src/'] },
];

async function main() {
  if (!existsSync(PREACT_REPO)) {
    console.error(`Preact repo not found at ${PREACT_REPO}. Run setup first: benchmarks/gbrain-vs-gitnexus/seed/setup.sh`);
    process.exit(1);
  }

  const judgeConfig = { apiKey: JUDGE_API_KEY, model: JUDGE_MODEL, baseUrl: JUDGE_BASE_URL };
  if (!JUDGE_API_KEY) {
    console.warn('WARNING: JUDGE_API_KEY not set. Quality scoring will be skipped.');
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
    workDir: PREACT_REPO,
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
    workDir: PREACT_REPO,
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
    workDir: PREACT_REPO,
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
  const aQuality = allQualityA.length > 0 ? allQualityA.reduce((s, v) => s + v, 0) / allQualityA.length : 0;
  const bQuality = allQualityB.length > 0 ? allQualityB.reduce((s, v) => s + v, 0) / allQualityB.length : 0;
  const cQuality = allQualityC.length > 0 ? allQualityC.reduce((s, v) => s + v, 0) / allQualityC.length : 0;

  const codeToolLeverage = computeCodeToolLeverage(resultsC);
  const cLeverage = meanCodeToolLeverage(codeToolLeverage);

  const aComposite = computeCompositeScore(aSuccessRate, aQuality, aEfficiency, 0);
  const bComposite = computeCompositeScore(bSuccessRate, bQuality, bEfficiency, 0);
  const cComposite = computeCompositeScore(cSuccessRate, cQuality, cEfficiency, cLeverage);

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

    const cTools = rC?.gbrainToolCalls;
    let cLev = 0;
    if (cTools) {
      const codeTools = ['code_list_repos', 'code_query', 'code_context', 'code_impact'];
      let used = 0;
      for (const t of codeTools) {
        if (cTools[t] && cTools[t] > 0) used++;
      }
      cLev = used / codeTools.length;
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
      project: 'preactjs/preact',
      projectCommit: PREACT_COMMIT,
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
      const result = await adapter.runTask(task, PREACT_REPO);
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
