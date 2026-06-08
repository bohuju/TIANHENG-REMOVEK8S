import {
  configSchema,
  systemSchema,
  taskDetailSchema,
  taskListSchema,
  memorySearchResponseSchema,
  memoryPagesResponseSchema,
  memoryPageResponseSchema,
  memoryUpdateResponseSchema,
  memoryDeleteResponseSchema,
  memoryStatsResponseSchema,
  memoryBatchDeleteResponseSchema,
  memoryBatchRetypeResponseSchema,
  type WebConfig,
  type SystemStatus,
  type TaskDetail,
  type TaskSummary,
  type MemorySearchResponse,
  type MemoryPagesResponse,
  type MemoryPageResponse,
  type MemoryStatsResponse,
} from './schemas';

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || '/api').replace(/\/$/, '');

function extractErrorDetail(status: number, text: string, contentType: string | null): string {
  const trimmed = text.trim();
  if (!trimmed) return `HTTP ${status}`;

  const isJson = (contentType || '').includes('application/json');
  if (isJson) {
    try {
      const data = JSON.parse(trimmed);
      const detail = data?.detail;
      if (typeof detail === 'string' && detail.trim()) {
        return detail.trim();
      }
    } catch {
      // Fall through to plain-text handling.
    }
  }

  return trimmed.slice(0, 300);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
    cache: 'no-store',
  });

  const text = await res.text();
  const contentType = res.headers.get('content-type');

  if (!res.ok) {
    throw new Error(extractErrorDetail(res.status, text, contentType));
  }

  if (!text) {
    return {} as T;
  }

  const isJson = (contentType || '').includes('application/json');
  if (!isJson) {
    throw new Error(`Expected JSON response from ${path}, got ${contentType || 'unknown content type'}`);
  }

  return JSON.parse(text) as T;
}

export async function getConfig(): Promise<WebConfig> {
  const data = await request<unknown>('/config');
  return configSchema.parse(data);
}

export async function putConfig(cfg: WebConfig): Promise<{ ok: boolean }> {
  return request('/config', { method: 'PUT', body: JSON.stringify(cfg) });
}

export async function getSystem(): Promise<SystemStatus> {
  const data = await request<unknown>('/system');
  return systemSchema.parse(data);
}

export async function getTasks(): Promise<TaskSummary[]> {
  const data = await request<unknown>('/tasks');
  return taskListSchema.parse(data).items;
}

export async function getTask(jobId: string): Promise<TaskDetail> {
  const data = await request<unknown>(`/task/${encodeURIComponent(jobId)}`);
  return taskDetailSchema.parse(data);
}

export async function stopTask(jobId: string): Promise<{ accepted: boolean; reason: string; status: string }> {
  return request(`/task/${encodeURIComponent(jobId)}/stop`, { method: 'POST' });
}

export async function deleteTask(jobId: string): Promise<{ ok: boolean; job_id: string }> {
  return request(`/task/${encodeURIComponent(jobId)}`, { method: 'DELETE' });
}

export interface SubmitTaskInput {
  repoUrl: string;
  model?: string;
  totalTimeBudget: number;
  runTimeBudget: number;
  maxTokens: number;
}

export async function submitTask(input: SubmitTaskInput): Promise<{ job_id: string; status: string }> {
  return request('/task', {
    method: 'POST',
    body: JSON.stringify({
      jobs: [
        {
          code_url: input.repoUrl,
          model: input.model || undefined,
          max_tokens: input.maxTokens,
          docker: true,
          docker_image: 'auto',
          time_budget: input.totalTimeBudget,
          total_time_budget: input.totalTimeBudget,
          run_time_budget: input.runTimeBudget,
        },
      ],
      auto_init: true,
      build_images: true,
      force_build: false,
      force_clone: false,
    }),
  });
}

// ── Memory ──

export async function searchMemory(q: string, type?: string): Promise<MemorySearchResponse> {
  const params = new URLSearchParams({ q });
  if (type) params.set('type', type);
  const data = await request<unknown>(`/memory/search?${params.toString()}`);
  return memorySearchResponseSchema.parse(data);
}

export async function listMemoryPages(type: string, limit = 50, offset = 0): Promise<MemoryPagesResponse> {
  const params = new URLSearchParams({ type, limit: String(limit), offset: String(offset) });
  const data = await request<unknown>(`/memory/pages?${params.toString()}`);
  return memoryPagesResponseSchema.parse(data);
}

export async function getMemoryPage(slug: string): Promise<MemoryPageResponse> {
  const data = await request<unknown>(`/memory/page/${encodeURIComponent(slug)}`);
  return memoryPageResponseSchema.parse(data);
}

export async function updateMemoryPage(slug: string, frontmatter: Record<string, unknown>): Promise<{ ok: boolean; slug: string }> {
  const data = await request<unknown>(`/memory/page/${encodeURIComponent(slug)}`, {
    method: 'PUT',
    body: JSON.stringify(frontmatter),
  });
  return memoryUpdateResponseSchema.parse(data);
}

export async function deleteMemoryPage(slug: string): Promise<{ ok: boolean; slug: string }> {
  const data = await request<unknown>(`/memory/page/${encodeURIComponent(slug)}`, {
    method: 'DELETE',
  });
  return memoryDeleteResponseSchema.parse(data);
}

export async function fetchMemoryStats(): Promise<MemoryStatsResponse> {
  const data = await request<unknown>('/memory/stats');
  return memoryStatsResponseSchema.parse(data);
}

export async function batchDeleteMemoryPages(slugs: string[]): Promise<{ ok: number; failed: number; errors: Record<string, string> }> {
  const data = await request<unknown>('/memory/batch-delete', {
    method: 'POST',
    body: JSON.stringify({ slugs }),
  });
  return memoryBatchDeleteResponseSchema.parse(data);
}

export async function batchRetypeMemoryPages(changes: { slug: string; new_type: string }[]): Promise<{ ok: number; failed: number; errors: Record<string, string> }> {
  const data = await request<unknown>('/memory/batch-retype', {
    method: 'POST',
    body: JSON.stringify({ changes }),
  });
  return memoryBatchRetypeResponseSchema.parse(data);
}
