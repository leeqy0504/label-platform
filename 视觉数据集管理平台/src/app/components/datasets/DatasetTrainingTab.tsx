import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router';
import { Plus, ExternalLink, ChevronRight } from 'lucide-react';
import { listTrainingRuns, createTrainingRun } from '../../../services/api';
import type { Dataset, TrainingRun } from '../../../types';
import { StatusBadge } from '../shared/StatusBadge';
import { EmptyState, PageLoading } from '../shared/EmptyState';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';

function formatDuration(seconds: number): string {
  if (seconds === 0) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function CreateTrainingDialog({
  open, onOpenChange, dataset, onCreated,
}: { open: boolean; onOpenChange: (o: boolean) => void; dataset: Dataset; onCreated: () => void }) {
  const [version, setVersion] = useState(dataset.currentVersion);
  const [taskType, setTaskType] = useState<'detection' | 'instance_segmentation'>('detection');
  const [model, setModel] = useState('yolov8l');
  const [batchSize, setBatchSize] = useState('16');
  const [epochs, setEpochs] = useState('100');
  const [loading, setLoading] = useState(false);

  const immutableVersions = dataset.versions.filter(v => v.isImmutable);
  const runName = `${dataset.name}-${taskType === 'detection' ? 'det' : 'inst'}-${version}-run${Date.now().toString().slice(-4)}`;

  const handleCreate = async () => {
    setLoading(true);
    try {
      await createTrainingRun({
        name: runName,
        datasetId: dataset.id,
        datasetVersion: version,
        taskType,
        config: { model, batchSize: Number(batchSize), totalEpochs: Number(epochs) },
      });
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
          <DialogTitle>提交训练任务</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1.5">数据集版本（不可变）</label>
            <Select value={version} onValueChange={setVersion}>
              <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
              <SelectContent>
                {immutableVersions.map(v => (
                  <SelectItem key={v.version} value={v.version}>
                    {v.version} — {v.imageCount} 张 / {v.annotationCount.toLocaleString()} 标注
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1.5">任务类型</label>
            <div className="grid grid-cols-2 gap-2">
              {(['detection', 'instance_segmentation'] as const).map(t => (
                <button
                  key={t}
                  onClick={() => setTaskType(t)}
                  className={`px-3 py-2 rounded border text-sm transition-colors ${taskType === t ? 'border-blue-400 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}
                >
                  {t === 'detection' ? 'Detection' : 'Instance Segmentation'}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1.5">模型</label>
              <Select value={model} onValueChange={setModel}>
                <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {taskType === 'detection'
                    ? ['yolov8n', 'yolov8s', 'yolov8m', 'yolov8l', 'yolov8x'].map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)
                    : ['yolov8n-seg', 'yolov8s-seg', 'yolov8m-seg', 'yolov8l-seg', 'yolov8x-seg'].map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)
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
        </div>
        <DialogFooter>
          <button onClick={() => onOpenChange(false)} className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded">取消</button>
          <button
            onClick={handleCreate}
            disabled={loading || immutableVersions.length === 0}
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
  const navigate = useNavigate();
  const [runs, setRuns] = useState<TrainingRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await listTrainingRuns({ datasetId: dataset.id });
      setRuns(result.data);
    } finally {
      setLoading(false);
    }
  }, [dataset.id]);

  useEffect(() => { load(); }, [load]);

  const canTrain = dataset.status === 'trainable' && dataset.versions.some(v => v.isImmutable);

  return (
    <div className="p-5">
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs text-gray-500">{runs.length} 个训练任务</span>
        <button
          onClick={() => setCreateOpen(true)}
          disabled={!canTrain}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded disabled:opacity-40 transition-colors"
          title={!canTrain ? '数据集状态须为「可训练」' : undefined}
        >
          <Plus className="size-4" />提交训练任务
        </button>
      </div>

      {loading ? (
        <PageLoading />
      ) : runs.length === 0 ? (
        <EmptyState type="empty" title="暂无训练任务" description="选择不可变数据集版本后可提交训练" />
      ) : (
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
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
