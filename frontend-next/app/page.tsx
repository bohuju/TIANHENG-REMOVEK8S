'use client';

import { useEffect, useMemo, useState } from 'react';
import { Alert, Box, Button, Stack, Typography } from '@mui/material';
import PsychologyIcon from '@mui/icons-material/Psychology';
import { MemoryDrawer } from '@/components/MemoryDrawer';
import { ConfigPanel } from '@/components/ConfigPanel';
import { LogPanel } from '@/components/LogPanel';
import { SessionPanel } from '@/components/SessionPanel';
import { SystemOverviewCard } from '@/components/SystemOverviewCard';
import { TaskProgressPanel } from '@/components/TaskProgressPanel';
import { useDeleteTaskMutation, useStopTaskMutation, useSystemQuery, useTaskDetailQuery, useTasksQuery } from '@/lib/api/hooks';
import { useUiStore } from '@/store/useUiStore';

export default function HomePage() {
  const activeTaskId = useUiStore((s) => s.activeTaskId);
  const hydrate = useUiStore((s) => s.hydrate);
  const hydrated = useUiStore((s) => s.hydrated);
  const setActiveTaskId = useUiStore((s) => s.setActiveTaskId);

  const system = useSystemQuery();
  const tasks = useTasksQuery();
  const detail = useTaskDetailQuery(activeTaskId || null);
  const stopTask = useStopTaskMutation();
  const deleteTask = useDeleteTaskMutation();

  useEffect(() => {
    if (!hydrated) hydrate();
  }, [hydrate, hydrated]);

  useEffect(() => {
    if (!tasks.data?.length) return;
    if (activeTaskId) {
      const exists = tasks.data.some((t) => t.job_id === activeTaskId);
      if (!exists) setActiveTaskId(tasks.data[0].job_id);
      return;
    }
    setActiveTaskId(tasks.data[0].job_id);
  }, [tasks.data, activeTaskId, setActiveTaskId]);

  const [memoryOpen, setMemoryOpen] = useState(false);

  const activeSummary = useMemo(
    () => tasks.data?.find((t) => t.job_id === activeTaskId),
    [tasks.data, activeTaskId],
  );

  const activeStatus = detail.data?.status || activeSummary?.status || '';
  const canStopTask = ['queued', 'running', 'resuming', 'recoverable'].includes(String(activeStatus).toLowerCase());

  const handleStopTask = async () => {
    if (!activeTaskId) return;
    await stopTask.mutateAsync(activeTaskId);
  };

  const handleDeleteTask = async () => {
    if (!activeTaskId) return;
    if (!window.confirm(`确定删除任务 ${activeTaskId.slice(0, 8)}... 吗？此操作不可恢复。`)) return;
    await deleteTask.mutateAsync(activeTaskId);
    setActiveTaskId('');
  };

  return (
    <Box sx={{ maxWidth: 1600, mx: 'auto', px: 2.5, py: 2.5 }}>
      <Stack spacing={2}>
        <Stack direction="row" alignItems="center" justifyContent="space-between">
          <Box>
            <Typography variant="h4" fontWeight={700}>TianHeng 控制台</Typography>
            <Typography variant="body2" color="text.secondary">
              重点视图：任务进度、子任务状态、日志与错误摘要。
            </Typography>
          </Box>
          <Button
            variant="outlined"
            startIcon={<PsychologyIcon />}
            onClick={() => setMemoryOpen(true)}
            size="small"
          >
            记忆查看
          </Button>
        </Stack>

        <SystemOverviewCard
          data={system.data}
          error={system.isError ? (system.error as Error).message : undefined}
        />

        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems="stretch">
          <Box sx={{ width: { xs: '100%', md: 360, lg: 420 }, flexShrink: 0 }}>
            <Stack spacing={2}>
              <ConfigPanel />
              <SessionPanel tasks={tasks.data || []} />
            </Stack>
          </Box>

          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Stack spacing={2}>
              {tasks.isError ? <Alert severity="warning">任务列表加载失败</Alert> : null}
              {activeSummary?.error ? <Alert severity="error">{activeSummary.error}</Alert> : null}
              {stopTask.isError ? (
                <Alert severity="error">停止任务失败：{(stopTask.error as Error).message}</Alert>
              ) : null}
              {deleteTask.isError ? (
                <Alert severity="error">删除任务失败：{(deleteTask.error as Error).message}</Alert>
              ) : null}
              <TaskProgressPanel
                detail={detail.data}
                onStopTask={handleStopTask}
                stopDisabled={!activeTaskId || !canStopTask}
                stopLoading={stopTask.isPending}
                onDeleteTask={handleDeleteTask}
                deleteDisabled={!activeTaskId}
                deleteLoading={deleteTask.isPending}
              />
              <LogPanel detail={detail.data} />
            </Stack>
          </Box>
        </Stack>
        <MemoryDrawer open={memoryOpen} onClose={() => setMemoryOpen(false)} />
      </Stack>
    </Box>
  );
}
