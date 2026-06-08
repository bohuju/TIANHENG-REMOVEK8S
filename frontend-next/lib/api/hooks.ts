'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  getConfig,
  getSystem,
  getTask,
  getTasks,
  putConfig,
  stopTask,
  deleteTask,
  submitTask,
  searchMemory,
  listMemoryPages,
  getMemoryPage,
  updateMemoryPage,
  deleteMemoryPage,
  fetchMemoryStats,
  batchDeleteMemoryPages,
  batchRetypeMemoryPages,
  type SubmitTaskInput,
} from './client';
import type { WebConfig } from './schemas';

export function useSystemQuery() {
  return useQuery({
    queryKey: ['system'],
    queryFn: getSystem,
    refetchInterval: 2000,
  });
}

export function useTasksQuery() {
  return useQuery({
    queryKey: ['tasks'],
    queryFn: getTasks,
    refetchInterval: 3000,
  });
}

export function useTaskDetailQuery(taskId: string | null) {
  return useQuery({
    queryKey: ['task', taskId],
    queryFn: () => getTask(taskId as string),
    enabled: Boolean(taskId),
    refetchInterval: 2000,
  });
}

export function useConfigQuery() {
  return useQuery({
    queryKey: ['config'],
    queryFn: getConfig,
  });
}

export function useSaveConfigMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (cfg: WebConfig) => putConfig(cfg),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['config'] });
      void qc.invalidateQueries({ queryKey: ['system'] });
    },
  });
}

export function useSubmitTaskMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: SubmitTaskInput) => submitTask(input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['tasks'] });
      void qc.invalidateQueries({ queryKey: ['system'] });
    },
  });
}

export function useStopTaskMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) => stopTask(taskId),
    onSuccess: (_out, taskId) => {
      void qc.invalidateQueries({ queryKey: ['tasks'] });
      void qc.invalidateQueries({ queryKey: ['task', taskId] });
      void qc.invalidateQueries({ queryKey: ['system'] });
    },
  });
}

export function useDeleteTaskMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) => deleteTask(taskId),
    onSuccess: (_out, taskId) => {
      void qc.invalidateQueries({ queryKey: ['tasks'] });
      void qc.invalidateQueries({ queryKey: ['task', taskId] });
      void qc.invalidateQueries({ queryKey: ['system'] });
    },
  });
}

// ── Memory ──

export function useMemorySearch(q: string, type: string) {
  return useQuery({
    queryKey: ['memory', 'search', q, type],
    queryFn: () => searchMemory(q, type || undefined),
    enabled: q.length > 0,
    staleTime: 30_000,
  });
}

export function useMemoryPages(type: string) {
  return useQuery({
    queryKey: ['memory', 'pages', type],
    queryFn: () => listMemoryPages(type),
    staleTime: 30_000,
  });
}

export function useMemoryPage(slug: string | null) {
  return useQuery({
    queryKey: ['memory', 'page', slug],
    queryFn: () => getMemoryPage(slug as string),
    enabled: Boolean(slug),
    staleTime: 30_000,
  });
}

export function useUpdateMemoryPageMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ slug, frontmatter }: { slug: string; frontmatter: Record<string, unknown> }) =>
      updateMemoryPage(slug, frontmatter),
    onSuccess: (_data, variables) => {
      void qc.invalidateQueries({ queryKey: ['memory', 'page', variables.slug] });
      void qc.invalidateQueries({ queryKey: ['memory', 'pages'] });
      void qc.invalidateQueries({ queryKey: ['memory', 'search'] });
    },
  });
}

export function useDeleteMemoryPageMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (slug: string) => deleteMemoryPage(slug),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['memory', 'pages'] });
      void qc.invalidateQueries({ queryKey: ['memory', 'search'] });
    },
  });
}

export function useMemoryStatsQuery() {
  return useQuery({
    queryKey: ['memory', 'stats'],
    queryFn: fetchMemoryStats,
    staleTime: 30_000,
  });
}

export function useBatchDeleteMemoryMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (slugs: string[]) => batchDeleteMemoryPages(slugs),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['memory', 'pages'] });
      void qc.invalidateQueries({ queryKey: ['memory', 'search'] });
      void qc.invalidateQueries({ queryKey: ['memory', 'stats'] });
    },
  });
}

export function useBatchRetypeMemoryMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (changes: { slug: string; new_type: string }[]) => batchRetypeMemoryPages(changes),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['memory', 'pages'] });
      void qc.invalidateQueries({ queryKey: ['memory', 'search'] });
      void qc.invalidateQueries({ queryKey: ['memory', 'stats'] });
    },
  });
}
