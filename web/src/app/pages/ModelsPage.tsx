import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router';
import { Search, RefreshCw } from 'lucide-react';
import { listModels } from '../../services/api';
import { ApiError } from '../../services/http';
import type { Model } from '../../types';
import { EmptyState, LoadingRows } from '../components/shared/EmptyState';
import { Pagination } from '../components/shared/Pagination';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';

function formatBytes(mb: number): string {
  if (mb < 1) return `${Math.max(1, Math.round(mb * 1024))} KB`;
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`;
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', year: '2-digit' });
}

function MetricBadge({ value }: { value: number }) {
  const color = value >= 0.85 ? 'text-green-700' : value >= 0.7 ? 'text-amber-700' : 'text-gray-600';
  return <span className={`text-xs font-semibold font-mono tabular-nums ${color}`}>{value.toFixed(3)}</span>;
}

export default function ModelsPage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [taskType, setTaskType] = useState('');
  const [page, setPage] = useState(1);
  const [models, setModels] = useState<Model[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{
    type: 'error' | 'offline';
    title: string;
    description: string;
  } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await listModels({ search, taskType, page, pageSize: 20 });
      setModels(result.data);
      setTotal(result.meta.total);
    } catch (cause) {
      if (cause instanceof ApiError && (cause.status === 502 || cause.status === 503)) {
        setError({
          type: 'offline',
          title: 'UnitTrain 服务不可用',
          description: '模型数据暂时无法同步，请稍后重试。',
        });
      } else {
        setError({
          type: 'error',
          title: '模型加载失败',
          description: '请检查网络连接后重试。',
        });
      }
    } finally {
      setLoading(false);
    }
  }, [search, taskType, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(1); }, [search, taskType]);

  return (
    <div className="p-4 md:p-6 max-w-screen-xl mx-auto">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <h1 className="text-base font-semibold text-gray-900">模型</h1>
          <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded">{total} 个</span>
        </div>
      </div>

      <div className="flex items-center gap-2 mb-4">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-gray-400" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="搜索模型名称..."
            className="w-full pl-8 pr-3 py-1.5 text-sm bg-white border border-gray-200 rounded outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-100"
          />
        </div>
        <Select value={taskType || '__all__'} onValueChange={v => setTaskType(v === '__all__' ? '' : v)}>
          <SelectTrigger className="w-36 h-8 text-sm">
            <SelectValue placeholder="全部类型" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">全部类型</SelectItem>
            <SelectItem value="detection">Detection</SelectItem>
            <SelectItem value="instance_segmentation">Instance Segmentation</SelectItem>
          </SelectContent>
        </Select>
        <button onClick={load} title="刷新" className="size-8 flex items-center justify-center text-gray-500 hover:bg-gray-100 rounded border border-gray-200">
          <RefreshCw className="size-3.5" />
        </button>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg overflow-x-auto">
        <table className="w-full min-w-[900px] text-sm">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50">
              <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">模型名称</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-36">来源训练任务</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-32">数据集版本</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-32">任务类型</th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-gray-500 w-20">mAP50</th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-gray-500 w-24">mAP50-95</th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-gray-500 w-20">文件大小</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-24">创建时间</th>
            </tr>
          </thead>
          <tbody>
            {loading && <LoadingRows rows={4} cols={8} />}
            {!loading && error && (
              <tr><td colSpan={8}>
                <EmptyState type={error.type} title={error.title} description={error.description} />
              </td></tr>
            )}
            {!loading && !error && models.length === 0 && (
              <tr><td colSpan={8}>
                {search || taskType
                  ? <EmptyState type="no-results" title="无匹配模型" />
                  : <EmptyState type="empty" title="暂无模型" description="训练任务完成后将自动生成模型" />
                }
              </td></tr>
            )}
            {!loading && !error && models.map(model => (
              <tr
                key={model.id}
                onClick={() => navigate(`/models/${model.id}`)}
                className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer transition-colors"
              >
                <td className="px-4 py-2.5">
                  <div className="font-mono text-xs text-gray-800 truncate max-w-48">{model.name}</div>
                  <div className="text-xs text-gray-400 mt-0.5">{model.categories.length} 个类别</div>
                </td>
                <td className="px-3 py-2.5 text-xs font-mono text-gray-600 truncate max-w-32">{model.trainingRunId}</td>
                <td className="px-3 py-2.5">
                  <div className="text-xs text-gray-700 truncate">{model.datasetName}</div>
                  <div className="text-xs text-gray-400 font-mono">{model.datasetVersion}</div>
                </td>
                <td className="px-3 py-2.5 text-xs text-gray-600">
                  {model.taskType === 'detection' ? 'Detection' : 'Instance Segmentation'}
                </td>
                <td className="px-3 py-2.5 text-right"><MetricBadge value={model.mAP50} /></td>
                <td className="px-3 py-2.5 text-right"><MetricBadge value={model.mAP5095} /></td>
                <td className="px-3 py-2.5 text-right text-xs text-gray-600">{formatBytes(model.fileSize)}</td>
                <td className="px-3 py-2.5 text-xs text-gray-500">{formatDate(model.createdAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pagination page={page} pageSize={20} total={total} onChange={setPage} />
      </div>
    </div>
  );
}
