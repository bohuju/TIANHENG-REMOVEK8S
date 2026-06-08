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

export function meanCodeToolLeverage(leveraged: CodeToolLeverage[]): number {
  if (leveraged.length === 0) return 0;
  return leveraged.reduce((s, l) => s + l.leverage, 0) / leveraged.length;
}

/** Compute composite score using spec-defined weights. */
export function computeCompositeScore(
  successRate: number,
  qualityScore: number,
  efficiencyScore: number,
  codeToolLeverage: number,
): number {
  return 0.35 * successRate + 0.35 * qualityScore + 0.20 * efficiencyScore + 0.10 * codeToolLeverage;
}
