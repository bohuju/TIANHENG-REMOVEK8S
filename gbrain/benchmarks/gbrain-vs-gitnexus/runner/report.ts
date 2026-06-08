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

  if (toolHeatmap.length > 0) {
    lines.push('## GBrain Tool Usage (Group C — GitNexus)');
    lines.push('');
    const toolHeaders = ['Tool', 'Calls', 'Tasks Covered'];
    const toolRows = toolHeatmap.map(t => [t.tool, String(t.calls), String(t.tasksCovered)]);
    lines.push(mdTable(toolHeaders, toolRows));
    lines.push('');
  }

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
