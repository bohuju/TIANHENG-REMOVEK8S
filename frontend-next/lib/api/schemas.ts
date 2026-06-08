import { z } from 'zod';

const normalizedErrorSchema = z
  .unknown()
  .transform((v) => {
    if (v == null) return '';
    if (typeof v === 'string') return v;
    if (typeof v === 'object') {
      const obj = v as Record<string, unknown>;
      const detail = obj?.detail;
      if (typeof detail === 'string' && detail.trim()) return detail.trim();
      const message = obj?.message;
      if (typeof message === 'string' && message.trim()) return message.trim();
      if (Object.keys(obj).length === 0) return '';
      try {
        return JSON.stringify(obj);
      } catch {
        return String(v);
      }
    }
    return String(v);
  })
  .default('');

export const opencodeProviderSchema = z.object({
  name: z.string().default(''),
  enabled: z.boolean().default(true),
  base_url: z.string().default(''),
  api_key: z.string().optional().default(''),
  api_key_set: z.boolean().optional(),
  clear_api_key: z.boolean().optional().default(false),
  models: z.array(z.string()).default([]),
  headers: z.record(z.string(), z.string()).default({}),
  options: z.record(z.string(), z.any()).default({}),
});

export const configSchema = z.object({
  openai_api_key: z.string().optional().default(''),
  openai_api_key_set: z.boolean().optional(),
  openai_base_url: z.string().optional().default(''),
  openai_model: z.string().optional().default(''),
  opencode_model: z.string().optional().default(''),
  opencode_providers: z.array(opencodeProviderSchema).default([]),
  openrouter_api_key: z.string().optional().default(''),
  openrouter_base_url: z.string().optional().default(''),
  openrouter_model: z.string().optional().default(''),
  fuzz_time_budget: z.number().int().nonnegative().default(900),
  sherpa_run_unlimited_round_budget_sec: z.number().int().nonnegative().default(7200),
  sherpa_run_plateau_idle_growth_sec: z.number().int().min(30).max(86400).default(600),
  fuzz_use_docker: z.boolean().default(true),
  fuzz_docker_image: z.string().default('auto'),
  sherpa_git_mirrors: z.string().default(''),
  sherpa_docker_http_proxy: z.string().default(''),
  sherpa_docker_https_proxy: z.string().default(''),
  sherpa_docker_no_proxy: z.string().default(''),
  sherpa_docker_proxy_host: z.string().default('host.docker.internal'),
  version: z.number().int().default(1),
});

export const childStatusSchema = z.object({
  total: z.number().int().default(0),
  queued: z.number().int().default(0),
  running: z.number().int().default(0),
  success: z.number().int().default(0),
  error: z.number().int().default(0),
});

export const taskSummarySchema = z.object({
  job_id: z.string(),
  status: z.string(),
  repo: z.string().nullable().optional(),
  updated_at_iso: z.string().nullable().optional(),
  created_at_iso: z.string().nullable().optional(),
  children_status: childStatusSchema.default({ total: 0, queued: 0, running: 0, success: 0, error: 0 }),
  child_count: z.number().int().default(0),
  active_child_id: z.string().nullable().optional(),
  active_child_status: z.string().nullable().optional(),
  error: normalizedErrorSchema.optional(),
  result: z.string().nullable().optional(),
});

export const taskListSchema = z.object({
  items: z.array(taskSummarySchema),
});

export const childJobSchema = z.object({
  job_id: z.string(),
  status: z.string(),
  repo: z.string().nullable().optional(),
  error: normalizedErrorSchema.optional(),
  result: z.any().optional(),
  log: z.string().optional().default(''),
  updated_at: z.number().optional(),
  started_at: z.number().nullable().optional(),
  finished_at: z.number().nullable().optional(),
});

export const taskDetailSchema = z.object({
  job_id: z.string(),
  status: z.string(),
  repo: z.string().nullable().optional(),
  error: normalizedErrorSchema.optional(),
  result: z.any().optional(),
  children_status: childStatusSchema.optional(),
  children: z.array(childJobSchema).optional().default([]),
});

export const systemSchema = z.object({
  ok: z.boolean().default(false),
  server_time_iso: z.string().optional(),
  uptime_sec: z.number().optional(),
  jobs: z
    .object({
      total: z.number().int().default(0),
      queued: z.number().int().default(0),
      running: z.number().int().default(0),
      success: z.number().int().default(0),
      error: z.number().int().default(0),
    })
    .default({ total: 0, queued: 0, running: 0, success: 0, error: 0 }),
  active_jobs: z.array(z.any()).optional().default([]),
  workers: z.object({ max: z.number().int().default(0) }).optional(),
});

export type WebConfig = z.infer<typeof configSchema>;
export type OpencodeProvider = z.infer<typeof opencodeProviderSchema>;
export type TaskSummary = z.infer<typeof taskSummarySchema>;
export type TaskDetail = z.infer<typeof taskDetailSchema>;
export type SystemStatus = z.infer<typeof systemSchema>;

// ── Memory ──

export const memoryResultSchema = z.object({
  slug: z.string(),
  type: z.string(),
  title: z.string(),
  score: z.number().default(0),
  snippet: z.string().default(''),
});

export const memorySearchResponseSchema = z.object({
  enabled: z.boolean().default(false),
  healthy: z.boolean().optional(),
  status: z.any().optional(),
  results: z.array(memoryResultSchema).default([]),
  total: z.number().int().default(0),
  error: z.string().optional(),
});

export const memoryPagesResponseSchema = z.object({
  enabled: z.boolean().default(false),
  healthy: z.boolean().optional(),
  status: z.any().optional(),
  results: z.array(memoryResultSchema).default([]),
  total: z.number().int().default(0),
  error: z.string().optional(),
});

export const memoryPageResponseSchema = z.object({
  enabled: z.boolean().default(true),
  page: z.any(),
});

export const memoryUpdateResponseSchema = z.object({
  ok: z.boolean(),
  slug: z.string(),
});

export const memoryDeleteResponseSchema = z.object({
  ok: z.boolean(),
  slug: z.string(),
});

export const memoryStatsResponseSchema = z.object({
  enabled: z.boolean().default(false),
  healthy: z.boolean().default(false),
  total: z.number().int().default(0),
  by_type: z.record(z.string(), z.number().int()).default({}),
  error: z.string().optional(),
});

export const memoryBatchDeleteResponseSchema = z.object({
  ok: z.number().int().default(0),
  failed: z.number().int().default(0),
  errors: z.record(z.string(), z.string()).default({}),
});

export const memoryBatchRetypeResponseSchema = z.object({
  ok: z.number().int().default(0),
  failed: z.number().int().default(0),
  errors: z.record(z.string(), z.string()).default({}),
});

export type MemoryResult = z.infer<typeof memoryResultSchema>;
export type MemorySearchResponse = z.infer<typeof memorySearchResponseSchema>;
export type MemoryPagesResponse = z.infer<typeof memoryPagesResponseSchema>;
export type MemoryPageResponse = z.infer<typeof memoryPageResponseSchema>;
export type MemoryStatsResponse = z.infer<typeof memoryStatsResponseSchema>;
export type MemoryBatchDeleteResponse = z.infer<typeof memoryBatchDeleteResponseSchema>;
export type MemoryBatchRetypeResponse = z.infer<typeof memoryBatchRetypeResponseSchema>;
