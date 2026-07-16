import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router';
import { Plus, ChevronRight, Loader2, RefreshCw, Wifi, WifiOff } from 'lucide-react';
import { listTrainingRuns, createTrainingRun, checkUnitTrainConnection } from '../../../services/api';
import type { Dataset, TrainingRun } from '../../../types';
import { StatusBadge } from '../shared/StatusBadge';
import { EmptyState, PageLoading } from '../shared/EmptyState';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { useAuth } from '../../auth/AuthProvider';

function formatDuration(seconds: number): string {
  if (seconds === 0) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function CreateTrainingDialog({
  open, onOpenChange, dataset, onCreated,
}: { open: boolean; onOpenChange: (o: boolean) => void; dataset: Dataset; onCreated: () => void }) {
  const immutableVersions = dataset.versions.filter(v => v.isImmutable);
  const [versionId, setVersionId] = useState(
    dataset.currentVersionId ?? immutableVersions[0]?.id ?? '',
  );
  const taskType = dataset.taskType;
  const [model, setModel] = useState(
    taskType === 'detection' ? 'yolo11n' : 'yolo11n-seg',
  );
  const [batchSize, setBatchSize] = useState('16');
  const [epochs, setEpochs] = useState('100');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedVersion = immutableVersions.find(version => version.id === versionId);
  const runName = `${dataset.name}-${taskType === 'detection' ? 'det' : 'inst'}-${selectedVersion?.version ?? 'version'}-run${Date.now().toString().slice(-4)}`;

  const handleCreate = async () => {
    setLoading(true);
    setError(null);
    try {
      await createTrainingRun({
        name: runName,
        datasetId: dataset.id,
        datasetVersionId: versionId,
        config: {
          framework: 'ultralytics',
          model,
          batch_size: Number(batchSize),
          epochs: Number(epochs),
        },
      });
      onCreated();
      onOpenChange(false);
    } catch {
      setError('训练任务提交失败，请检查 UnitTrain 连接和参数');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>提交训练任务</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1.5">数据集版本（不可变）</label>
            <Select value={versionId} onValueChange={setVersionId}>
              <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
              <SelectContent>
                {immutableVersions.map(v => (
                  <SelectItem key={v.id} value={v.id}>
                    {v.version} — {v.imageCount} 张 / {v.annotationCount.toLocaleString()} 标注
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1.5">任务类型</label>
            <div className="h-9 flex items-center px-3 border border-gray-200 rounded bg-gray-50 text-sm text-gray-700">
              {taskType === 'detection' ? 'Detection' : 'Instance Segmentation'}
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1.5">模型</label>
              <Select value={model} onValueChange={setModel}>
                <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {taskType === 'detection'
                    ? ['yolo11n', 'yolo11s', 'yolo11m', 'yolo11l', 'yolo11x'].map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)
                    : ['yolo11n-seg', 'yolo11s-seg', 'yolo11m-seg', 'yolo11l-seg', 'yolo11x-seg'].map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)
                  }
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1.5">Batch Size</label>
              <input
                value={batchSize}
                onChange={e => setBatchSize(e.target.value)}
                type="number"
                className="w-full h-8 px-2.5 text-sm border border-gray-200 rounded outline-none focus:border-blue-400"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1.5">Epochs</label>
              <input
                value={epochs}
                onChange={e => setEpochs(e.target.value)}
                type="number"
                className="w-full h-8 px-2.5 text-sm border border-gray-200 rounded outline-none focus:border-blue-400"
              />
            </div>
          </div>
          <div className="p-2.5 bg-gray-50 border border-gray-100 rounded">
            <p className="text-xs text-gray-500">任务名称</p>
            <code className="text-xs text-gray-700 font-mono">{runName}</code>
          </div>
          {error && <p className="text-xs text-red-600" role="alert">{error}</p>}
        </div>
        <DialogFooter>
          <button onClick={() => onOpenChange(false)} className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded">取消</button>
          <button
            onClick={handleCreate}
            disabled={loading || !versionId}
            className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded disabled:opacity-40"
          >
            {loading ? '提交中...' : '提交训练'}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function DatasetTrainingTab({ dataset }: { dataset: Dataset }) {
  const { user } = useAuth();
  const canOperate = user?.role === 'admin' || user?.role === 'data_engineer';
  const navigate = useNavigate();
  const [runs, setRuns] = useState<TrainingRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [serviceStatus, setServiceStatus] = useState<'checking' | 'online' | 'offline'>('checking');

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const result = await listTrainingRuns({ datasetId: dataset.id });
      setRuns(result.data);
    } catch {
      setRuns([]);
      setLoadError('训练服务尚不可用，请确认平台训练 API 已启动');
    } finally {
      setLoading(false);
    }
  }, [dataset.id]);

  const checkService = useCallback(async () => {
    setServiceStatus('checking');
    try {
      const result = await checkUnitTrainConnection();
      setServiceStatus(result.status);
    } catch {
      setServiceStatus('offline');
    }
  }, []);

  useEffect(() => {
    load();
    checkService();
  }, [load, checkService]);

  const canTrain = serviceStatus === 'online'
    && canOperate
    && dataset.status === 'trainable'
    && dataset.versions.some(v => v.isImmutable);

  return (
    <div className="p-4 md:p-5 overflow-y-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-gray-600">UnitTrain 连接</span>
          {serviceStatus === 'checking' && <Loader2 className="size-3.5 text-gray-400 animate-spin" />}
          {serviceStatus === 'online' && <span className="flex items-center gap-1 text-xs text-green-600"><Wifi className="size-3.5" />在线</span>}
          {serviceStatus === 'offline' && <span className="flex items-center gap-1 text-xs text-red-600"><WifiOff className="size-3.5" />离线</span>}
          <button onClick={checkService} className="text-xs text-blue-600 hover:underline flex items-center gap-1">
            <RefreshCw className="size-3" />重新检测
          </button>
        </div>
        <button
          onClick={() => setCreateOpen(true)}
          disabled={!canTrain}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded disabled:opacity-40 transition-colors"
          title={!canTrain ? 'UnitTrain 须在线，且数据集状态须为「可训练」' : undefined}
        >
          <Plus className="size-4" />提交训练任务
        </button>
      </div>

      {serviceStatus === 'offline' && (
        <div className="mb-4 flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded text-sm">
          <WifiOff className="size-4 text-red-500 shrink-0" />
          <span className="text-red-700">UnitTrain 离线，暂时无法提交训练任务。</span>
        </div>
      )}

      {loading ? (
        <PageLoading />
      ) : loadError ? (
        <EmptyState type="error" title="训练服务不可用" description={loadError} action={
          <button onClick={load} className="text-sm text-blue-600 hover:underline">重试</button>
        } />
      ) : runs.length === 0 ? (
        <EmptyState type="empty" title="暂无训练任务" description="选择不可变数据集版本后可提交训练" />
      ) : (
        <div className="bg-white border border-gray-200 rounded-lg overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="border-b border-gray-200 bg-gray-50">
              <tr>
                <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">任务名称</th>
                <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-16">版本</th>
                <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-24">类型</th>
                <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-20">状态</th>
                <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-20">进度</th>
                <th className="text-right px-3 py-2.5 text-xs font-medium text-gray-500 w-20">mAP50</th>
                <th className="text-right px-3 py-2.5 text-xs font-medium text-gray-500 w-20">耗时</th>
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {runs.map(run => (
                <tr
                  key={run.id}
                  className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer transition-colors"
                  onClick={() => navigate(`/training/${run.id}`)}
                >
                  <td className="px-4 py-2.5">
                    <div className="font-mono text-xs text-gray-700 truncate max-w-52">{run.name}</div>
                  </td>
                  <td className="px-3 py-2.5 text-xs font-mono text-gray-600">{run.datasetVersion}</td>
                  <td className="px-3 py-2.5 text-xs text-gray-600">
                    {run.taskType === 'detection' ? 'Detection' : 'Inst. Seg.'}
                  </td>
                  <td className="px-3 py-2.5"><StatusBadge status={run.status} /></td>
                  <td className="px-3 py-2.5 text-xs text-gray-600 tabular-nums">
                    {run.currentEpoch}/{run.totalEpochs}
                  </td>
                  <td className="px-3 py-2.5 text-right text-xs tabular-nums font-medium text-gray-800">
                    {run.primaryMetric > 0 ? run.primaryMetric.toFixed(3) : '—'}
                  </td>
                  <td className="px-3 py-2.5 text-right text-xs text-gray-500">
                    {formatDuration(run.durationSeconds)}
                  </td>
                  <td className="px-3 py-2.5">
                    <ChevronRight className="size-4 text-gray-400" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <CreateTrainingDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        dataset={dataset}
        onCreated={load}
      />
    </div>
  );
}
