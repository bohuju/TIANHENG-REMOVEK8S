import { describe, it, expect } from 'bun:test';
import { computeEfficiencyScores, meanEfficiencyScore, successRate, computeCodeToolLeverage, meanCodeToolLeverage, computeCompositeScore } from './metrics';
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

describe('successRate', () => {
  it('computes correctly with mixed results', () => {
    const results = [
      makeResult({ success: 1.0 }),
      makeResult({ success: 0.0 }),
      makeResult({ success: 1.0 }),
    ];
    expect(successRate(results)).toBeCloseTo(2 / 3);
  });

  it('returns 0 for empty array', () => {
    expect(successRate([])).toBe(0);
  });
});

describe('computeEfficiencyScores', () => {
  it('normalizes 3 groups per task — fastest gets highest score', () => {
    const resultsA = [makeResult({ taskId: 'T1', group: 'A', toolCallCount: 10, wallClockMs: 50000, tokensIn: 8000, tokensOut: 3000 })];
    const resultsB = [makeResult({ taskId: 'T1', group: 'B', toolCallCount: 5, wallClockMs: 30000, tokensIn: 5000, tokensOut: 2000 })];
    const resultsC = [makeResult({ taskId: 'T1', group: 'C', toolCallCount: 3, wallClockMs: 20000, tokensIn: 4000, tokensOut: 1500 })];

    const scores = computeEfficiencyScores(resultsA, resultsB, resultsC);
    expect(scores.has('A:T1')).toBe(true);
    expect(scores.has('B:T1')).toBe(true);
    expect(scores.has('C:T1')).toBe(true);

    const scoreA = scores.get('A:T1')!.score;
    const scoreB = scores.get('B:T1')!.score;
    const scoreC = scores.get('C:T1')!.score;
    // C has lowest rounds/time/tokens, so gets highest normalized score
    expect(scoreC).toBeGreaterThanOrEqual(scoreB);
    expect(scoreB).toBeGreaterThanOrEqual(scoreA);
  });

  it('handles all-equal results gracefully', () => {
    const r = [makeResult({ taskId: 'T1', group: 'A', toolCallCount: 5, wallClockMs: 30000, tokensIn: 5000, tokensOut: 2000 })];
    const scores = computeEfficiencyScores(r, [], []);
    expect(scores.get('A:T1')!.score).toBe(1.0);
  });

  it('handles multiple tasks across groups', () => {
    const a = [makeResult({ taskId: 'T1', group: 'A', toolCallCount: 10 })];
    const b = [makeResult({ taskId: 'T1', group: 'B', toolCallCount: 5 })];
    const c = [makeResult({ taskId: 'T2', group: 'C', toolCallCount: 3 })];
    const scores = computeEfficiencyScores(a, b, c);
    // T1 has A+B pooled, T2 has only C
    expect(scores.get('A:T1')).toBeDefined();
    expect(scores.get('B:T1')).toBeDefined();
    expect(scores.get('C:T2')).toBeDefined();
  });
});

describe('meanEfficiencyScore', () => {
  it('averages per group across tasks', () => {
    // T1: B is faster; T2: A is faster -- both groups get non-zero means
    const resultsA = [
      makeResult({ taskId: 'T1', group: 'A', toolCallCount: 10, wallClockMs: 1000, tokensIn: 100, tokensOut: 100 }),
      makeResult({ taskId: 'T2', group: 'A', toolCallCount: 5, wallClockMs: 500, tokensIn: 50, tokensOut: 50 }),
    ];
    const resultsB = [
      makeResult({ taskId: 'T1', group: 'B', toolCallCount: 5, wallClockMs: 500, tokensIn: 50, tokensOut: 50 }),
      makeResult({ taskId: 'T2', group: 'B', toolCallCount: 20, wallClockMs: 2000, tokensIn: 200, tokensOut: 200 }),
    ];

    const scores = computeEfficiencyScores(resultsA, resultsB, []);
    const meanA = meanEfficiencyScore('A', scores);
    const meanB = meanEfficiencyScore('B', scores);
    expect(meanA).toBeGreaterThan(0);
    expect(meanB).toBeGreaterThan(0);
  });

  it('returns 0 for group with no results', () => {
    const scores = computeEfficiencyScores([], [], []);
    expect(meanEfficiencyScore('C', scores)).toBe(0);
  });
});

describe('computeCodeToolLeverage', () => {
  it('extracts code_* tools from Group C only', () => {
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
        gbrainToolCalls: { code_impact: 1, search: 1 },
      }),
    ];

    const leverage = computeCodeToolLeverage(resultsC);
    expect(leverage.length).toBeGreaterThan(0);

    // code_query from successful task: all calls effective
    const queryLev = leverage.find(l => l.tool === 'code_query');
    expect(queryLev).toBeDefined();
    if (queryLev) {
      expect(queryLev.totalCalls).toBe(3);
      expect(queryLev.leverage).toBe(1.0);
    }

    // code_impact from failed task: 0 leverage
    const impactLev = leverage.find(l => l.tool === 'code_impact');
    expect(impactLev).toBeDefined();
    if (impactLev) {
      expect(impactLev.totalCalls).toBe(1);
      expect(impactLev.leverage).toBe(0);
    }
  });

  it('ignores non-code tools', () => {
    const resultsC = [
      makeResult({
        taskId: 'T1',
        group: 'C',
        success: 1.0,
        gbrainToolCalls: { search: 5, get_page: 3 },
      }),
    ];
    const leverage = computeCodeToolLeverage(resultsC);
    expect(leverage.length).toBe(0);
  });

  it('returns empty for Group with no gbrainToolCalls', () => {
    const resultsC = [makeResult({ taskId: 'T1', group: 'C', gbrainToolCalls: undefined })];
    expect(computeCodeToolLeverage(resultsC)).toEqual([]);
  });
});

describe('meanCodeToolLeverage', () => {
  it('returns 0 for empty array', () => {
    expect(meanCodeToolLeverage([])).toBe(0);
  });

  it('averages leverage across tools', () => {
    const leveraged: CodeToolLeverage[] = [
      { tool: 'code_query', totalCalls: 10, effectiveCalls: 8, leverage: 0.8 },
      { tool: 'code_context', totalCalls: 5, effectiveCalls: 5, leverage: 1.0 },
    ];
    expect(meanCodeToolLeverage(leveraged)).toBeCloseTo(0.9);
  });
});

describe('computeCompositeScore', () => {
  it('applies correct weights (0.35, 0.35, 0.20, 0.10)', () => {
    // success=1.0, quality=0.5, efficiency=0.8, leverage=0.6
    const score = computeCompositeScore(1.0, 0.5, 0.8, 0.6);
    // 0.35*1.0 + 0.35*0.5 + 0.20*0.8 + 0.10*0.6 = 0.35 + 0.175 + 0.16 + 0.06 = 0.745
    expect(score).toBeCloseTo(0.745);
  });

  it('handles zero scores', () => {
    expect(computeCompositeScore(0, 0, 0, 0)).toBe(0);
  });

  it('handles perfect scores', () => {
    const score = computeCompositeScore(1.0, 1.0, 1.0, 1.0);
    expect(score).toBeCloseTo(1.0);
  });
});

describe('MCP compliance behavior', () => {
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
    const r = makeResult({ group: 'A', gbrainToolCalls: undefined });
    const compliant = Object.values(r.gbrainToolCalls ?? {}).some(c => c > 0);
    expect(compliant).toBe(false);
  });

  it('Group C with code tools is compliant', () => {
    const r = makeResult({
      group: 'C',
      gbrainToolCalls: { code_query: 2, code_context: 1, code_impact: 3 },
    });
    const compliant = Object.values(r.gbrainToolCalls ?? {}).some(c => c > 0);
    expect(compliant).toBe(true);
  });
});
