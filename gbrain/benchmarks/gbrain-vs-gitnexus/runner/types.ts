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
  gbrainBinary?: string;
  needsCodeImport?: boolean;
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
  mcpCompliant?: boolean;
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
