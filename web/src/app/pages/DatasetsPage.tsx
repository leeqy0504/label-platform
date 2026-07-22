import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router';
import {
  Search,
  Plus,
  MoreHorizontal,
  Eye,
  ClipboardCheck,
  Play,
  Archive,
  RefreshCw,
} from 'lucide-react';
import { listDatasets, archiveDataset } from '../../services/api';
import type { Dataset, DatasetStatus } from '../../types';
import { StatusBadge } from '../components/shared/StatusBadge';
import { EmptyState, LoadingRows } from '../components/shared/EmptyState';
import { Pagination } from '../components/shared/Pagination';
import { ConfirmDialog } from '../components/shared/ConfirmDialog';
import { RegisterDatasetDialog } from '../components/datasets/RegisterDatasetDialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';

const STATUS_OPTIONS: { value: DatasetStatus | ''; label: string }[] = [
  { value: '', label: '全部状态' },
  { value: 'scanning', label: '扫描中' },
  { value: 'pending_annotation', label: '待标注' },
  { value: 'reviewing', label: '审核中' },
  { value: 'trainable', label: '可训练' },
  { value: 'validation_failed', label: '校验失败' },
  { value: 'archived', label: '已归档' },
];

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function formatSize(mb: number) {
  if (mb === 0) return '—';
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`;
}

export default function DatasetsPage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<DatasetStatus | ''>('');
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<{ data: Dataset[]; meta: { page: number; pageSize: number; total: number } } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [registerOpen, setRegisterOpen] = useState(false);
  const [archiveTarget, setArchiveTarget] = useState<Dataset | null>(null);
  const [archiving, setArchiving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listDatasets({ search, status, page, pageSize: 20 });
      setResult(data);
    } catch {
      setError('加载失败，请检查网络连接后重试');
    } finally {
      setLoading(false);
    }
  }, [search, status, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(1); }, [search, status]);

  const handleArchive = async () => {
    if (!archiveTarget) return;
    setArchiving(true);
    try {
      await archiveDataset(archiveTarget.id);
      setArchiveTarget(null);
      load();
    } finally {
      setArchiving(false);
    }
  };

  return (
    <div className="p-4 md:p-6 max-w-screen-xl mx-auto">
      {/* Page header */}
      <div className="flex items-center justify-between gap-3 mb-5">
        <div className="flex items-center gap-3">
          <h1 className="text-base font-semibold text-gray-900">数据集</h1>
          {result && (
            <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded">
              {result.meta.total} 个
            </span>
          )}
        </div>
        <button
          onClick={() => setRegisterOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded transition-colors shrink-0"
        >
          <Plus className="size-4" />
          登记服务器数据集
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-gray-400" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="搜索数据集名称..."
            className="w-full pl-8 pr-3 py-1.5 text-sm bg-white border border-gray-200 rounded outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-100"
          />
        </div>
        <Select value={status || '__all__'} onValueChange={v => setStatus(v === '__all__' ? '' : v as DatasetStatus)}>
          <SelectTrigger className="w-32 h-8 text-sm">
            <SelectValue placeholder="全部状态" />
          </SelectTrigger>
          <SelectContent>
            {STATUS_OPTIONS.map(opt => (
              <SelectItem key={opt.value || '__all__'} value={opt.value || '__all__'}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <button
          onClick={load}
          title="刷新"
          className="size-8 flex items-center justify-center text-gray-500 hover:bg-gray-100 rounded transition-colors border border-gray-200"
        >
          <RefreshCw className="size-3.5" />
        </button>
      </div>

      {/* Table */}
      <div className="bg-white border border-gray-200 rounded-lg overflow-x-auto">
        <table className="w-full min-w-[960px] text-sm">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50">
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-48">名称</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-16">版本</th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-gray-500 w-20">媒体数</th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-gray-500 w-16">类别数</th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-gray-500 w-24">标注数</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-24">状态</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-28">更新时间</th>
              <th className="w-8" />
            </tr>
          </thead>
          <tbody>
            {loading && <LoadingRows rows={6} cols={9} />}
            {!loading && error && (
              <tr>
                <td colSpan={9}>
                  <EmptyState type="error" title="加载失败" description={error} action={
                    <button onClick={load} className="text-sm text-blue-600 hover:underline">重试</button>
                  } />
                </td>
              </tr>
            )}
            {!loading && !error && result?.data.length === 0 && (
              <tr>
                <td colSpan={9}>
                  {search || status ? (
                    <EmptyState type="no-results" title="无匹配数据集" description="尝试调整搜索条件或清除筛选器" />
                  ) : (
                    <EmptyState type="empty" title="暂无数据集" description="点击右上角按钮登记第一个数据集" />
                  )}
                </td>
              </tr>
            )}
            {!loading && !error && result?.data.map(ds => (
              <tr
                key={ds.id}
                onClick={() => navigate(`/datasets/${ds.id}`)}
                className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer group transition-colors"
              >
                <td className="px-3 py-2.5">
                  <div className="font-medium text-gray-900 text-sm truncate max-w-44">{ds.name}</div>
                  <div className="text-xs text-gray-400 truncate max-w-44">{ds.description}</div>
                </td>
                <td className="px-3 py-2.5 text-xs font-mono text-gray-600">{ds.currentVersion || '—'}</td>
                <td className="px-3 py-2.5 text-right text-xs text-gray-700 tabular-nums">
                  {ds.mediaCount.toLocaleString()}
                </td>
                <td className="px-3 py-2.5 text-right text-xs text-gray-700 tabular-nums">
                  {ds.categoryCount || '—'}
                </td>
                <td className="px-3 py-2.5 text-right text-xs text-gray-700 tabular-nums">
                  {ds.annotationCount ? ds.annotationCount.toLocaleString() : '—'}
                </td>
                <td className="px-3 py-2.5">
                  <StatusBadge status={ds.status} />
                </td>
                <td className="px-3 py-2.5 text-xs text-gray-500">{formatDate(ds.updatedAt)}</td>
                <td className="px-3 py-2.5" onClick={e => e.stopPropagation()}>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button className="size-6 flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded opacity-0 group-hover:opacity-100 transition-opacity">
                        <MoreHorizontal className="size-4" />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-40">
                      <DropdownMenuItem onClick={() => navigate(`/datasets/${ds.id}`)}>
                        <Eye className="size-3.5 mr-2" />查看详情
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onClick={() => navigate(`/datasets/${ds.id}?tab=review`)}
                        disabled={!['trainable', 'reviewing', 'pending_annotation'].includes(ds.status)}
                      >
                        <ClipboardCheck className="size-3.5 mr-2" />创建审核任务
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onClick={() => navigate(`/datasets/${ds.id}?tab=training`)}
                        disabled={ds.status !== 'trainable'}
                      >
                        <Play className="size-3.5 mr-2" />提交训练
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        onClick={() => setArchiveTarget(ds)}
                        disabled={ds.status === 'archived'}
                        className="text-amber-700"
                      >
                        <Archive className="size-3.5 mr-2" />归档
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {result && (
          <Pagination
            page={page}
            pageSize={20}
            total={result.meta.total}
            onChange={setPage}
          />
        )}
      </div>

      <RegisterDatasetDialog
        open={registerOpen}
        onOpenChange={setRegisterOpen}
        onSuccess={() => { setRegisterOpen(false); load(); }}
      />

      <ConfirmDialog
        open={!!archiveTarget}
        onOpenChange={open => !open && setArchiveTarget(null)}
        title="归档数据集"
        description={`确认归档「${archiveTarget?.name}」？归档后数据集将只读，无法创建新的审核任务或训练任务。`}
        confirmLabel={archiving ? '归档中...' : '确认归档'}
        variant="destructive"
        onConfirm={handleArchive}
      />
    </div>
  );
}
