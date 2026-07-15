import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router';
import { Search, ExternalLink, RefreshCw } from 'lucide-react';
import { listReviewSessions } from '../../services/api';
import type { ReviewSession } from '../../types';
import { StatusBadge } from '../components/shared/StatusBadge';
import { EmptyState, LoadingRows } from '../components/shared/EmptyState';
import { Pagination } from '../components/shared/Pagination';
import { Progress } from '../components/ui/progress';
import { CopyButton } from '../components/shared/CopyButton';

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export default function ReviewPage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [sessions, setSessions] = useState<ReviewSession[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await listReviewSessions({ page, pageSize: 20 });
      let data = result.data;
      if (search) {
        const q = search.toLowerCase();
        data = data.filter(s => s.datasetName.toLowerCase().includes(q));
      }
      setSessions(data);
      setTotal(result.meta.total);
    } catch {
      setError('加载失败');
    } finally {
      setLoading(false);
    }
  }, [search, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(1); }, [search]);

  return (
    <div className="p-6 max-w-screen-xl mx-auto">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <h1 className="text-base font-semibold text-gray-900">审核任务</h1>
          <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded">{total} 个</span>
        </div>
        <a
          href="http://label-studio.internal"
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-1.5 px-3 py-1.5 border border-gray-200 text-gray-700 text-sm hover:bg-gray-50 rounded transition-colors"
        >
          <ExternalLink className="size-3.5" />
          打开 Label Studio
        </a>
      </div>

      <div className="flex items-center gap-2 mb-4">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-gray-400" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="搜索数据集名称..."
            className="w-full pl-8 pr-3 py-1.5 text-sm bg-white border border-gray-200 rounded outline-none focus:border-blue-400"
          />
        </div>
        <button onClick={load} title="刷新" className="size-8 flex items-center justify-center text-gray-500 hover:bg-gray-100 rounded border border-gray-200">
          <RefreshCw className="size-3.5" />
        </button>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50">
              <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">数据集 / 版本</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-32">Project ID</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-48">审核进度</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-20">状态</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-16">创建人</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-28">开始时间</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-20">输出版本</th>
              <th className="w-36" />
            </tr>
          </thead>
          <tbody>
            {loading && <LoadingRows rows={6} cols={8} />}
            {!loading && error && (
              <tr><td colSpan={8}><EmptyState type="error" title="加载失败" description={error} /></td></tr>
            )}
            {!loading && !error && sessions.length === 0 && (
              <tr><td colSpan={8}>
                {search
                  ? <EmptyState type="no-results" title="无匹配审核任务" />
                  : <EmptyState type="empty" title="暂无审核任务" description="在数据集详情页创建审核任务" />
                }
              </td></tr>
            )}
            {!loading && !error && sessions.map(session => {
              const pct = Math.round((session.completedTasks / session.totalTasks) * 100);
              return (
                <tr
                  key={session.id}
                  onClick={() => navigate(`/datasets/${session.datasetId}?tab=review`)}
                  className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-2.5">
                    <div className="text-sm text-gray-800 font-medium">{session.datasetName}</div>
                    <div className="text-xs text-gray-400 font-mono">{session.inputVersion}</div>
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-1">
                      <code className="text-xs font-mono text-gray-700">{session.labelStudioProjectId}</code>
                      <CopyButton text={String(session.labelStudioProjectId)} />
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <Progress value={pct} className="h-1.5 w-24" />
                      <span className="text-xs text-gray-600 tabular-nums">
                        {session.completedTasks.toLocaleString()} / {session.totalTasks.toLocaleString()}
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2.5"><StatusBadge status={session.status} /></td>
                  <td className="px-3 py-2.5 text-xs text-gray-600">{session.createdBy}</td>
                  <td className="px-3 py-2.5 text-xs text-gray-500">{formatDate(session.startedAt)}</td>
                  <td className="px-3 py-2.5 text-xs font-mono text-gray-600">{session.outputVersion ?? '—'}</td>
                  <td className="px-3 py-2.5" onClick={e => e.stopPropagation()}>
                    <a
                      href={session.labelStudioProjectUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center gap-1 text-xs text-blue-600 hover:underline"
                    >
                      <ExternalLink className="size-3" />在 Label Studio 中打开
                    </a>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <Pagination page={page} pageSize={20} total={total} onChange={setPage} />
      </div>
    </div>
  );
}
