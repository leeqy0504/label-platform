import { useState, useEffect, useCallback } from 'react';
import { ExternalLink, Plus, RefreshCw, Wifi, WifiOff, Loader2, CheckCircle2, AlertTriangle } from 'lucide-react';
import {
  listReviewSessions,
  createReviewSession,
  finalizeReviewSession,
  checkLabelStudioConnection,
} from '../../../services/api';
import type { Dataset, ReviewSession } from '../../../types';
import { StatusBadge } from '../shared/StatusBadge';
import { EmptyState, PageLoading } from '../shared/EmptyState';
import { ConfirmDialog } from '../shared/ConfirmDialog';
import { CopyButton } from '../shared/CopyButton';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { cn } from '../ui/utils';
import { Progress } from '../ui/progress';

const EXPORT_STAGES = [
  { key: 'exporting', label: '导出 Label Studio 标注' },
  { key: 'extracting', label: '解压数据包' },
  { key: 'converting', label: 'COCO 格式转换' },
  { key: 'validating', label: 'Mask/Bbox 校验' },
  { key: 'publishing', label: '发布不可变版本' },
];

function ExportProgress({ session }: { session: ReviewSession }) {
  const progress = session.exportProgress;
  if (!progress) return null;
  const stageIndex = EXPORT_STAGES.findIndex(s => s.key === progress.stage);

  return (
    <div className="mt-3 p-3 bg-blue-50 border border-blue-200 rounded space-y-2">
      <div className="flex items-center justify-between text-xs">
        <span className="text-blue-700 font-medium">{progress.message}</span>
        <span className="text-blue-600 tabular-nums">{progress.percent}%</span>
      </div>
      <Progress value={progress.percent} className="h-1.5" />
      <div className="flex gap-2 flex-wrap">
        {EXPORT_STAGES.map((s, i) => (
          <span
            key={s.key}
            className={cn(
              'text-xs px-2 py-0.5 rounded border',
              i < stageIndex
                ? 'bg-green-50 text-green-700 border-green-200'
                : i === stageIndex
                  ? 'bg-blue-100 text-blue-700 border-blue-300'
                  : 'bg-white text-gray-400 border-gray-200'
            )}
          >
            {i < stageIndex ? '✓ ' : ''}{s.label}
          </span>
        ))}
      </div>
    </div>
  );
}

interface CreateSessionDialogProps {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  dataset: Dataset;
  onCreated: () => void;
}

function CreateSessionDialog({ open, onOpenChange, dataset, onCreated }: CreateSessionDialogProps) {
  const [version, setVersion] = useState(dataset.currentVersion);
  const [loading, setLoading] = useState(false);

  const handleCreate = async () => {
    setLoading(true);
    try {
      await createReviewSession({ datasetId: dataset.id, inputVersion: version });
      onCreated();
      onOpenChange(false);
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
            <Select value={version} onValueChange={setVersion}>
              <SelectTrigger className="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {dataset.versions
                  .filter(v => v.isImmutable)
                  .map(v => (
                    <SelectItem key={v.version} value={v.version}>
                      {v.version} — {v.imageCount} 张图片
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
          <div className="p-3 bg-gray-50 border border-gray-200 rounded text-xs text-gray-600 space-y-1">
            <p>• 将在 Label Studio 创建新项目并导入图片</p>
            <p>• 任务数量：{dataset.versions.find(v => v.version === version)?.imageCount ?? 0} 个</p>
            <p>• 审核员完成后，手动点击「结束审核」生成不可变版本</p>
          </div>
        </div>
        <DialogFooter>
          <button onClick={() => onOpenChange(false)} className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded">取消</button>
          <button
            onClick={handleCreate}
            disabled={loading || dataset.versions.filter(v => v.isImmutable).length === 0}
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

export function ReviewTab({ dataset }: { dataset: Dataset }) {
  const [sessions, setSessions] = useState<ReviewSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [lsStatus, setLsStatus] = useState<'checking' | 'online' | 'offline'>('checking');
  const [createOpen, setCreateOpen] = useState(false);
  const [finalizeTarget, setFinalizeTarget] = useState<ReviewSession | null>(null);
  const [finalizing, setFinalizing] = useState(false);

  const loadSessions = useCallback(async () => {
    setLoading(true);
    try {
      const result = await listReviewSessions({ datasetId: dataset.id });
      setSessions(result.data);
    } finally {
      setLoading(false);
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
    loadSessions();
    checkLs();
  }, [loadSessions, checkLs]);

  const handleFinalize = async () => {
    if (!finalizeTarget) return;
    setFinalizing(true);
    const target = finalizeTarget;
    setFinalizeTarget(null);

    // simulate export progress
    const stages: Array<[ReviewSession['exportProgress'], number]> = [
      [{ stage: 'exporting', percent: 20, message: '正在导出 Label Studio 标注...' }, 800],
      [{ stage: 'extracting', percent: 40, message: '正在解压数据包...' }, 600],
      [{ stage: 'converting', percent: 60, message: '正在执行 COCO 格式转换...' }, 800],
      [{ stage: 'validating', percent: 80, message: '正在校验 mask/bbox 格式...' }, 700],
      [{ stage: 'publishing', percent: 95, message: '正在发布不可变版本...' }, 600],
    ];

    for (const [progress, ms] of stages) {
      setSessions(prev =>
        prev.map(s => s.id === target.id ? { ...s, status: 'exporting', exportProgress: progress } : s)
      );
      await new Promise(r => setTimeout(r, ms));
    }

    await finalizeReviewSession(target.id);
    setSessions(prev =>
      prev.map(s =>
        s.id === target.id
          ? { ...s, status: 'completed', exportProgress: undefined, completedAt: new Date().toISOString(), outputVersion: 'v-new' }
          : s
      )
    );
    setFinalizing(false);
  };

  const formatDate = (iso: string | null) =>
    iso ? new Date(iso).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—';

  return (
    <div className="p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
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
          <button onClick={loadSessions} className="size-7 flex items-center justify-center text-gray-500 hover:bg-gray-100 rounded" title="刷新">
            <RefreshCw className="size-3.5" />
          </button>
          <button
            onClick={() => setCreateOpen(true)}
            disabled={lsStatus === 'offline'}
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

      {/* Sessions */}
      {loading ? (
        <PageLoading />
      ) : sessions.length === 0 ? (
        <EmptyState type="empty" title="暂无审核任务" description="点击「创建审核任务」开始审核流程" />
      ) : (
        <div className="space-y-3">
          {sessions.map(session => (
            <div key={session.id} className="bg-white border border-gray-200 rounded-lg p-4">
              <div className="flex items-start justify-between mb-3">
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
                    <span className="flex items-center gap-1">
                      Project ID: <code className="font-mono text-gray-700">{session.labelStudioProjectId}</code>
                      <CopyButton text={String(session.labelStudioProjectId)} />
                    </span>
                    <span>创建人: {session.createdBy}</span>
                    <span>开始: {formatDate(session.startedAt)}</span>
                    {session.completedAt && <span>完成: {formatDate(session.completedAt)}</span>}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <a
                    href={session.labelStudioProjectUrl}
                    target="_blank"
                    rel="noreferrer"
                    onClick={e => e.stopPropagation()}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-gray-200 text-gray-700 hover:bg-gray-50 rounded transition-colors"
                  >
                    <ExternalLink className="size-3.5" />
                    在 Label Studio 中打开
                  </a>
                  {session.status === 'active' && (
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
                    {Math.round((session.completedTasks / session.totalTasks) * 100)}%
                  </span>
                </div>
                <Progress
                  value={(session.completedTasks / session.totalTasks) * 100}
                  className="h-1.5"
                />
              </div>

              {session.status === 'exporting' && <ExportProgress session={session} />}

              {session.status === 'failed' && (
                <div className="mt-3 flex items-center gap-2 p-2.5 bg-red-50 border border-red-200 rounded text-xs">
                  <AlertTriangle className="size-3.5 text-red-500 shrink-0" />
                  <span className="text-red-700">导出失败：COCO 格式校验错误，请检查标注数据后重试</span>
                </div>
              )}

              {session.status === 'completed' && session.outputVersion && (
                <div className="mt-3 flex items-center gap-2 p-2.5 bg-green-50 border border-green-200 rounded text-xs">
                  <CheckCircle2 className="size-3.5 text-green-600 shrink-0" />
                  <span className="text-green-700">已生成不可变版本 {session.outputVersion}，数据集状态已更新为「可训练」</span>
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
          <li>• 数据集状态切换为「可训练」</li>
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
