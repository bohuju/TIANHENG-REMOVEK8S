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
      // Replace placeholder with actual binary path for Group C
      const resolvedConfig = mcpConfig.replace('__GBRAIN_NEXUS_BIN__', gbrainBinary ?? 'gbrain');
      writeFileSync(OPENCODE_CONFIG_PATH, resolvedConfig);

      if (config.needsGbrainIndex) {
        const gb = gbrainBinary ?? 'gbrain';
        // Use --migrate-only to apply schema against existing postgres config (no PGLite)
        execSync(`${gb} init --migrate-only`, { cwd: opts.workDir, stdio: 'inherit' });
        execSync(`${gb} config set sync.repo_path "${opts.workDir.replace(/"/g, '\\"')}"`, { stdio: 'inherit' });
        // Sync docs first (both groups)
        try {
          execSync(`${gb} sync --force`, { cwd: opts.workDir, stdio: 'inherit', timeout: 1200_000 });
        } catch {
          execSync(`${gb} import "${opts.workDir}" --include-code --no-embed`, { stdio: 'inherit', timeout: 120_000 });
        }
        execSync(`${gb} extract links`, { cwd: opts.workDir, stdio: 'inherit' });

        if (needsCodeImport) {
          console.log('[Group C] Running gbrain code import...');
          try {
            execSync(`${gb} code import "${opts.workDir}" --reindex`, {
              cwd: opts.workDir,
              stdio: 'inherit',
              timeout: 600_000,
            });
          } catch (e) {
            console.error('[Group C] code import failed (non-fatal):', e instanceof Error ? e.message : e);
          }
        }
      }
    },

    async runTask(task: TaskDef, workDir: string): Promise<AgentRunResult> {
      const taskDir = join(opts.resultsDir, `group_${groupLabel.toLowerCase()}`, task.id);
      mkdirSync(taskDir, { recursive: true });

      // Reset working directory and apply seed patch (skip if patch is empty/missing)
      execSync('git checkout -- . && git clean -fd', { cwd: workDir, stdio: 'pipe' });
      const seedPath = join(task.dir, 'seed.patch');
      if (existsSync(seedPath)) {
        const seedContent = readFileSync(seedPath, 'utf-8');
        // Only apply if the patch contains actual diff content (not just comments)
        if (/^diff --git/m.test(seedContent)) {
          try {
            execSync(`git apply ${seedPath}`, { cwd: workDir, stdio: 'pipe' });
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
        }
      }

      const startTime = Date.now();
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

        let resolved = false;
        await new Promise<void>((resolve, reject) => {
          const timer = setTimeout(() => {
            try { process.kill(-result.pid!, 'SIGTERM'); } catch {}
            // Give it 5 more seconds to die gracefully, then force-kill process group and force-resolve
            setTimeout(() => {
              try { process.kill(-result.pid!, 'SIGKILL'); } catch {}
              if (!resolved) {
                resolved = true;
                writeFileSync(join(taskDir, 'session.log'), stdout + '\n' + stderr + '\n[bench] killed after 20min timeout');
                resolve();
              }
            }, 5000);
          }, 1200_000);

          result.on('error', (err: Error) => {
            if (!resolved) { resolved = true; reject(err); }
          });
          result.on('close', (code: number) => {
            clearTimeout(timer);
            if (resolved) return;
            resolved = true;
            if (code !== 0) {
              stderr += `\n[bench] opencode exited with code ${code}`;
            }
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

        const gbrainToolCalls = (groupLabel === 'B' || groupLabel === 'C')
          ? parseGbrainTools(logs)
          : undefined;

        const mcpCompliant = (groupLabel === 'B' || groupLabel === 'C')
          ? checkMCPCompliance(gbrainToolCalls)
          : undefined;

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
        // Interactive mode fallback
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
        const maxWaitMs = 1200_000; // 30 minutes
        const pollStart = Date.now();
        while (!existsSync(doneFile)) {
          if (Date.now() - pollStart > maxWaitMs) {
            console.error(`[${groupLabel}] Task ${task.id} timed out waiting for DONE file`);
            break;
          }
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
          outputFiles,
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

function parseGbrainTools(logs: string): Record<string, number> {
  const tools = [
    'search', 'query', 'get_page', 'put_page', 'list_pages', 'get_backlinks',
    'traverse_graph', 'resolve_slugs', 'file_list', 'get_ingest_log', 'get_stats', 'get_health',
    'code_list_repos', 'code_query', 'code_context', 'code_impact',
  ];
  const counts: Record<string, number> = {};
  for (const tool of tools) {
    const re = new RegExp(`"method":"tools/call"[\\s\\S]*?"name":"${tool}"`, 'gi');
    const matches = logs.match(re);
    if (matches) counts[tool] = matches.length;
  }
  return counts;
}

function checkMCPCompliance(toolCalls: Record<string, number> | undefined): boolean {
  if (!toolCalls) return false;
  return Object.values(toolCalls).some(count => count > 0);
}
