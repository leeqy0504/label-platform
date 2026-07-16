import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router';
import { Search, RefreshCw } from 'lucide-react';
import { listTrainingRuns } from '../../services/api';
import type { TrainingRun, TrainingStatus } from '../../types';
import { StatusBadge } from '../components/shared/StatusBadge';
import { EmptyState, LoadingRows } from '../components/shared/EmptyState';
import { Pagination } from '../components/shared/Pagination';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Progress } from '../components/ui/progress';

const STATUS_OPTIONS: { value: TrainingStatus | ''; label: string }[] = [
  { value: '', label: '全部状态' },
  { value: 'queued', label: '排队中' },
  { value: 'running', label: '运行中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'stopped', label: '已停止' },
];

function formatDuration(seconds: number): string {
  if (seconds === 0) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export default function TrainingPage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<TrainingStatus | ''>('');
  const [page, setPage] = useState(1);
  const [runs, setRuns] = useState<TrainingRun[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await listTrainingRuns({ search, status, page, pageSize: 20 });
      setRuns(result.data);
      setTotal(result.meta.total);
    } catch {
      setError('加载失败');
    } finally {
      setLoading(false);
    }
  }, [search, status, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(1); }, [search, status]);

  return (
    <div className="p-4 md:p-6 max-w-screen-xl mx-auto">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <h1 className="text-base font-semibold text-gray-900">训练任务</h1>
          <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded">{total} 个</span>
        </div>
      </div>

      <div className="flex items-center gap-2 mb-4">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-gray-400" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="搜索任务名称..."
            className="w-full pl-8 pr-3 py-1.5 text-sm bg-white border border-gray-200 rounded outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-100"
          />
        </div>
        <Select value={status || '__all__'} onValueChange={v => setStatus(v === '__all__' ? '' : v as TrainingStatus)}>
          <SelectTrigger className="w-28 h-8 text-sm">
            <SelectValue placeholder="全部状态" />
          </SelectTrigger>
          <SelectContent>
            {STATUS_OPTIONS.map(o => (
              <SelectItem key={o.value || '__all__'} value={o.value || '__all__'}>{o.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <button onClick={load} title="刷新" className="size-8 flex items-center justify-center text-gray-500 hover:bg-gray-100 rounded border border-gray-200">
          <RefreshCw className="size-3.5" />
        </button>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg overflow-x-auto">
        <table className="w-full min-w-[980px] text-sm">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50">
              <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">任务名称</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-40">数据集版本</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-32">任务类型</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-20">状态</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-36">进度</th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-gray-500 w-20">mAP50</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-20">启动人</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-28">启动时间</th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-gray-500 w-20">耗时</th>
            </tr>
          </thead>
          <tbody>
            {loading && <LoadingRows rows={5} cols={9} />}
            {!loading && error && (
              <tr><td colSpan={9}><EmptyState type="error" title="加载失败" description={error} /></td></tr>
            )}
            {!loading && !error && runs.length === 0 && (
              <tr><td colSpan={9}>
                {search || status
                  ? <EmptyState type="no-results" title="无匹配任务" />
                  : <EmptyState type="empty" title="暂无训练任务" description="在数据集详情页选择不可变版本提交训练" />
                }
              </td></tr>
            )}
            {!loading && !error && runs.map(run => (
              <tr
                key={run.id}
                onClick={() => navigate(`/training/${run.id}`)}
                className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer transition-colors"
              >
                <td className="px-4 py-2.5">
                  <div className="font-mono text-xs text-gray-800 truncate max-w-52">{run.name}</div>
                  {run.errorMessage && (
                    <div className="text-xs text-red-500 mt-0.5 truncate max-w-52">{run.errorMessage.slice(0, 60)}…</div>
                  )}
                </td>
                <td className="px-3 py-2.5">
                  <div className="text-xs text-gray-700 truncate">{run.datasetName}</div>
                  <div className="text-xs text-gray-400 font-mono">{run.datasetVersion}</div>
                </td>
                <td className="px-3 py-2.5 text-xs text-gray-600">
                  {run.taskType === 'detection' ? 'Detection' : 'Instance Segmentation'}
                </td>
                <td className="px-3 py-2.5"><StatusBadge status={run.status} /></td>
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <Progress
                      value={(run.currentEpoch / Math.max(1, run.totalEpochs)) * 100}
                      className="h-1.5 w-20"
                    />
                    <span className="text-xs tabular-nums text-gray-500">
                      {run.currentEpoch}/{run.totalEpochs}
                    </span>
                  </div>
                </td>
                <td className="px-3 py-2.5 text-right">
                  <span className={`text-xs tabular-nums font-medium ${run.primaryMetric >= 0.8 ? 'text-green-700' : run.primaryMetric >= 0.6 ? 'text-amber-700' : 'text-gray-600'}`}>
                    {run.primaryMetric > 0 ? run.primaryMetric.toFixed(3) : '—'}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-xs text-gray-600">{run.startedBy}</td>
                <td className="px-3 py-2.5 text-xs text-gray-500">{formatDate(run.startedAt)}</td>
                <td className="px-3 py-2.5 text-right text-xs text-gray-500">{formatDuration(run.durationSeconds)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pagination page={page} pageSize={20} total={total} onChange={setPage} />
      </div>
    </div>
  );
}
