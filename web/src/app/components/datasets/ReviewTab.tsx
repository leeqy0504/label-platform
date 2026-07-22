import { useState, useEffect, useCallback, useRef } from 'react';
import { ExternalLink, Plus, RefreshCw, Wifi, WifiOff, Loader2, CheckCircle2, AlertTriangle, Trash2 } from 'lucide-react';
import {
  listReviewSessions,
  createReviewSession,
  deleteReviewSession,
  finalizeReviewSession,
  checkLabelStudioConnection,
  syncReviewSession,
  retryReviewSession,
  getJob,
} from '../../../services/api';
import type { Dataset, ReviewSession } from '../../../types';
import { StatusBadge } from '../shared/StatusBadge';
import { EmptyState, PageLoading } from '../shared/EmptyState';
import { ConfirmDialog } from '../shared/ConfirmDialog';
import { CopyButton } from '../shared/CopyButton';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { Progress } from '../ui/progress';

const JOB_STAGE_LABEL: Record<string, string> = {
  pending: '等待后台任务',
  creating_project: '创建 Label Studio 项目',
  configuring_project: '配置标签与存储',
  importing_tasks: '导入审核任务',
  exporting: '导出 Label Studio 标注',
  converting: '转换并校验标注',
  publishing: '发布不可变版本',
};

interface CreateSessionDialogProps {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  dataset: Dataset;
  onCreated: () => void;
}

function CreateSessionDialog({ open, onOpenChange, dataset, onCreated }: CreateSessionDialogProps) {
  const [versionId, setVersionId] = useState(dataset.currentVersionId ?? '');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCreate = async () => {
    setLoading(true);
    setError(null);
    try {
      await createReviewSession({ datasetId: dataset.id, inputVersionId: versionId });
      onCreated();
      onOpenChange(false);
    } catch {
      setError('审核任务创建失败，请检查 Label Studio 连接后重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>创建审核任务</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1.5">输入数据集版本</label>
            <Select value={versionId} onValueChange={setVersionId}>
              <SelectTrigger className="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {dataset.versions
                  .filter(v => v.isImmutable)
                  .map(v => (
                    <SelectItem key={v.id} value={v.id}>
                      {v.version} — {v.imageCount} 张图片
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
          <p className="text-xs text-gray-500 tabular-nums">
            {dataset.versions.find(v => v.id === versionId)?.imageCount ?? 0} 个任务
          </p>
          {error && <p className="text-xs text-red-600" role="alert">{error}</p>}
        </div>
        <DialogFooter>
          <button onClick={() => onOpenChange(false)} className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded">取消</button>
          <button
            onClick={handleCreate}
            disabled={loading || !versionId || dataset.versions.filter(v => v.isImmutable).length === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded disabled:opacity-40"
          >
            {loading && <Loader2 className="size-3.5 animate-spin" />}
            创建审核任务
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ReviewTab({ dataset, onDeleted }: { dataset: Dataset; onDeleted?: () => Promise<void> }) {
  const mounted = useRef(true);
  const [sessions, setSessions] = useState<ReviewSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [lsStatus, setLsStatus] = useState<'checking' | 'online' | 'offline'>('checking');
  const [createOpen, setCreateOpen] = useState(false);
  const [finalizeTarget, setFinalizeTarget] = useState<ReviewSession | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ReviewSession | null>(null);
  const [finalizing, setFinalizing] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);

  const loadSessions = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    setLoadError(null);
    try {
      const result = await listReviewSessions({ datasetId: dataset.id });
      const active = result.data.filter(session => ['ready', 'in_review'].includes(session.status));
      const synchronized = await Promise.all(
        result.data.map(session => (
          active.some(candidate => candidate.id === session.id)
            ? syncReviewSession(session.id).catch(() => session)
            : session
        )),
      );
      const withJobs = await Promise.all(synchronized.map(async session => {
        if (!session.jobId || !['creating', 'importing', 'exporting'].includes(session.status)) {
          return session;
        }
        try {
          const job = await getJob(session.jobId);
          return {
            ...session,
            jobStage: job.stage,
            jobProcessed: job.processed_count,
            jobTotal: job.total_count,
          };
        } catch {
          return session;
        }
      }));
      if (!mounted.current) return;
      setSessions(withJobs);
    } catch {
      if (mounted.current) {
        setSessions([]);
        setLoadError('审核服务尚不可用，请确认平台审核 API 已启动');
      }
    } finally {
      if (showLoading && mounted.current) setLoading(false);
    }
  }, [dataset.id]);

  const checkLs = useCallback(async () => {
    setLsStatus('checking');
    try {
      const res = await checkLabelStudioConnection();
      setLsStatus(res.status);
    } catch {
      setLsStatus('offline');
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    loadSessions();
    checkLs();
    return () => { mounted.current = false; };
  }, [loadSessions, checkLs]);

  useEffect(() => {
    const hasTransientSession = sessions.some(session => (
      ['creating', 'importing', 'exporting'].includes(session.status)
    ));
    if (!hasTransientSession) return undefined;
    const timer = window.setTimeout(() => { void loadSessions(false); }, 2000);
    return () => window.clearTimeout(timer);
  }, [sessions, loadSessions]);

  const handleFinalize = async () => {
    if (!finalizeTarget) return;
    setFinalizing(true);
    const target = finalizeTarget;
    setFinalizeTarget(null);
    setActionError(null);
    try {
      await finalizeReviewSession(target.id);
      await loadSessions();
    } catch {
      setActionError('审核导出未能启动，请检查任务状态后重试');
    } finally {
      setFinalizing(false);
    }
  };

  const handleRetry = async (sessionId: string) => {
    setRetryingId(sessionId);
    setActionError(null);
    try {
      await retryReviewSession(sessionId);
      await loadSessions(false);
    } catch {
      setActionError('审核任务重试失败，请检查 Label Studio 连接');
    } finally {
      setRetryingId(null);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    const target = deleteTarget;
    setDeleteTarget(null);
    setDeletingId(target.id);
    setActionError(null);
    try {
      await deleteReviewSession(target.id);
      await Promise.all([loadSessions(false), onDeleted?.()]);
    } catch {
      setActionError('审核任务删除失败，请确认任务状态和 Label Studio 连接');
    } finally {
      setDeletingId(null);
    }
  };

  const formatDate = (iso: string | null) =>
    iso ? new Date(iso).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—';

  return (
    <div className="p-4 md:p-5 overflow-y-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-gray-600">Label Studio 连接</span>
          {lsStatus === 'checking' && <Loader2 className="size-3.5 text-gray-400 animate-spin" />}
          {lsStatus === 'online' && (
            <span className="flex items-center gap-1 text-xs text-green-600">
              <Wifi className="size-3.5" />在线
            </span>
          )}
          {lsStatus === 'offline' && (
            <span className="flex items-center gap-1 text-xs text-red-600">
              <WifiOff className="size-3.5" />离线
            </span>
          )}
          <button onClick={checkLs} className="text-xs text-blue-600 hover:underline flex items-center gap-1">
            <RefreshCw className="size-3" />重新检测
          </button>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => { void loadSessions(); }} className="size-7 flex items-center justify-center text-gray-500 hover:bg-gray-100 rounded" title="刷新">
            <RefreshCw className="size-3.5" />
          </button>
          <button
            onClick={() => setCreateOpen(true)}
            disabled={lsStatus !== 'online' || dataset.status === 'archived' || !dataset.versions.some(version => version.isImmutable)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded disabled:opacity-40 transition-colors"
          >
            <Plus className="size-4" />创建审核任务
          </button>
        </div>
      </div>

      {lsStatus === 'offline' && (
        <div className="mb-4 flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded text-sm">
          <WifiOff className="size-4 text-red-500 shrink-0" />
          <span className="text-red-700">Label Studio 离线，无法创建新审核任务。请联系管理员检查服务状态。</span>
        </div>
      )}
      {actionError && (
        <div className="mb-4 flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded text-sm" role="alert">
          <AlertTriangle className="size-4 text-red-500 shrink-0" />
          <span className="text-red-700">{actionError}</span>
        </div>
      )}

      {/* Sessions */}
      {loading ? (
        <PageLoading />
      ) : loadError ? (
        <EmptyState type="error" title="审核服务不可用" description={loadError} action={
          <button onClick={() => { void loadSessions(); }} className="text-sm text-blue-600 hover:underline">重试</button>
        } />
      ) : sessions.length === 0 ? (
        <EmptyState type="empty" title="暂无审核任务" description="点击「创建审核任务」开始审核流程" />
      ) : (
        <div className="space-y-3">
          {sessions.map(session => (
            <div key={session.id} className="bg-white border border-gray-200 rounded-lg p-4">
              <div className="flex flex-col lg:flex-row items-start justify-between gap-3 mb-3">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-900">
                      {session.datasetName} {session.inputVersion} 审核
                    </span>
                    <StatusBadge status={session.status} />
                    {session.outputVersion && (
                      <span className="text-xs text-green-600">→ {session.outputVersion}</span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-gray-500">
                    {session.labelStudioProjectId !== null && <span className="flex items-center gap-1">
                      Project ID: <code className="font-mono text-gray-700">{session.labelStudioProjectId}</code>
                      <CopyButton text={String(session.labelStudioProjectId)} />
                    </span>}
                    <span>开始: {formatDate(session.startedAt)}</span>
                    {session.completedAt && <span>完成: {formatDate(session.completedAt)}</span>}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {['ready', 'in_review'].includes(session.status) && (
                    <button
                      onClick={() => setDeleteTarget(session)}
                      disabled={deletingId === session.id}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-red-200 text-red-600 hover:bg-red-50 rounded transition-colors disabled:opacity-40"
                    >
                      {deletingId === session.id
                        ? <Loader2 className="size-3.5 animate-spin" />
                        : <Trash2 className="size-3.5" />}
                      删除审核任务
                    </button>
                  )}
                  {session.labelStudioProjectUrl && session.status !== 'completed' && <a
                    href={session.labelStudioProjectUrl}
                    target="_blank"
                    rel="noreferrer"
                    onClick={e => e.stopPropagation()}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-gray-200 text-gray-700 hover:bg-gray-50 rounded transition-colors"
                  >
                    <ExternalLink className="size-3.5" />
                    在 Label Studio 中打开
                  </a>}
                  {['ready', 'in_review'].includes(session.status) && (
                    <button
                      onClick={() => setFinalizeTarget(session)}
                      disabled={finalizing}
                      className="px-2.5 py-1.5 text-xs bg-green-600 hover:bg-green-700 text-white rounded disabled:opacity-40"
                    >
                      结束审核并生成版本
                    </button>
                  )}
                </div>
              </div>

              {/* Progress */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-gray-500">
                    完成 <span className="font-medium text-gray-800 tabular-nums">{session.completedTasks.toLocaleString()}</span>
                    {' / '}
                    <span className="tabular-nums">{session.totalTasks.toLocaleString()}</span>
                    {session.skippedTasks > 0 && <span className="text-amber-500 ml-1">（跳过 {session.skippedTasks}）</span>}
                  </span>
                  <span className="text-gray-500 tabular-nums">
                    {session.totalTasks > 0 ? Math.round((session.completedTasks / session.totalTasks) * 100) : 0}%
                  </span>
                </div>
                <Progress
                  value={session.totalTasks > 0 ? (session.completedTasks / session.totalTasks) * 100 : 0}
                  className="h-1.5"
                />
              </div>

              {session.jobStage && ['creating', 'importing', 'exporting'].includes(session.status) && (
                <div className="mt-3 p-3 bg-blue-50 border border-blue-200 rounded space-y-2">
                  <div className="flex items-center justify-between text-xs text-blue-700">
                    <span>{JOB_STAGE_LABEL[session.jobStage] ?? session.jobStage}</span>
                    <span className="tabular-nums">
                      {(session.jobProcessed ?? 0).toLocaleString()} / {(session.jobTotal ?? 0).toLocaleString()}
                    </span>
                  </div>
                  <Progress
                    value={(session.jobTotal ?? 0) > 0
                      ? ((session.jobProcessed ?? 0) / (session.jobTotal ?? 1)) * 100
                      : 0}
                    className="h-1.5"
                  />
                </div>
              )}

              {session.status === 'failed' && (
                <div className="mt-3 flex items-center gap-2 p-2.5 bg-red-50 border border-red-200 rounded text-xs">
                  <AlertTriangle className="size-3.5 text-red-500 shrink-0" />
                  <span className="text-red-700">
                    {session.errorSummary.message ?? '审核任务失败，请检查任务状态后重试'}
                  </span>
                  <button
                    onClick={() => { void handleRetry(session.id); }}
                    disabled={retryingId === session.id}
                    className="ml-auto text-red-700 underline disabled:opacity-50"
                  >
                    {retryingId === session.id ? '重试中...' : '重试'}
                  </button>
                </div>
              )}

              {session.status === 'completed' && session.outputVersion && (
                <div className="mt-3 flex items-center gap-2 p-2.5 bg-green-50 border border-green-200 rounded text-xs">
                  <CheckCircle2 className="size-3.5 text-green-600 shrink-0" />
                  <span className="text-green-700">已生成不可变版本 {session.outputVersion}</span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <CreateSessionDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        dataset={dataset}
        onCreated={loadSessions}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={o => !o && setDeleteTarget(null)}
        title="删除审核任务"
        description="删除后无法恢复。"
        confirmLabel="确认删除"
        variant="destructive"
        onConfirm={handleDelete}
      >
        <ul className="text-xs text-gray-600 space-y-1">
          {deleteTarget?.labelStudioProjectId != null && (
            <li>删除 Label Studio 项目 {deleteTarget?.labelStudioProjectId}</li>
          )}
          <li>删除平台中的审核任务记录</li>
          <li>不会删除原始数据集及其版本</li>
        </ul>
      </ConfirmDialog>

      <ConfirmDialog
        open={!!finalizeTarget}
        onOpenChange={o => !o && setFinalizeTarget(null)}
        title="结束审核并生成版本"
        description="以下操作将不可撤销："
        confirmLabel="确认结束并生成版本"
        onConfirm={handleFinalize}
      >
        <ul className="text-xs text-gray-600 space-y-1">
          <li>• 从 Label Studio 导出所有已完成标注</li>
          <li>• 执行 COCO 格式校验（mask polygon + bbox 合规性）</li>
          <li>• 生成新的<strong>不可修改</strong>版本</li>
        </ul>
        {finalizeTarget && finalizeTarget.completedTasks < finalizeTarget.totalTasks && (
          <div className="mt-2 flex items-center gap-1.5 p-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-700">
            <AlertTriangle className="size-3.5 shrink-0" />
            注意：仍有 {finalizeTarget.totalTasks - finalizeTarget.completedTasks} 个任务未完成
          </div>
        )}
      </ConfirmDialog>
    </div>
  );
}
