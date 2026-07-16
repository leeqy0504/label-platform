import { useState, useEffect } from 'react';
import { useParams, useSearchParams, Link } from 'react-router';
import { ChevronLeft, RefreshCw } from 'lucide-react';
import { getDataset } from '../../services/api';
import type { Dataset } from '../../types';
import { StatusBadge } from '../components/shared/StatusBadge';
import { PageLoading, EmptyState } from '../components/shared/EmptyState';
import { OverviewTab } from '../components/datasets/OverviewTab';
import { FilesTab } from '../components/datasets/FilesTab';
import { VersionsTab } from '../components/datasets/VersionsTab';
import { ReviewTab } from '../components/datasets/ReviewTab';
import { DatasetTrainingTab } from '../components/datasets/DatasetTrainingTab';
import { CategoriesTab } from '../components/datasets/CategoriesTab';
import { FormatSplitsTab } from '../components/datasets/FormatSplitsTab';
import { cn } from '../components/ui/utils';

const TABS = [
  { key: 'overview', label: '概览' },
  { key: 'files', label: '文件' },
  { key: 'format', label: '格式与划分' },
  { key: 'categories', label: '类别' },
  { key: 'versions', label: '版本' },
  { key: 'review', label: 'Label Studio 审核' },
  { key: 'training', label: 'UnitTrain 训练' },
];

export default function DatasetDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get('tab') ?? 'overview';
  const activeTab = TABS.some(tab => tab.key === requestedTab) ? requestedTab : 'overview';

  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const ds = await getDataset(id);
      setDataset(ds);
    } catch {
      setError('数据集不存在或加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [id]);

  const setTab = (tab: string) => {
    setSearchParams(prev => { prev.set('tab', tab); return prev; });
  };

  if (loading) return <div className="p-6"><PageLoading /></div>;
  if (error || !dataset) {
    return (
      <div className="p-6">
        <EmptyState type="error" title="加载失败" description={error ?? '未知错误'} action={
          <Link to="/datasets" className="text-sm text-blue-600 hover:underline flex items-center gap-1">
            <ChevronLeft className="size-4" />返回数据集列表
          </Link>
        } />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Detail header */}
      <div className="bg-white border-b border-gray-200 px-4 md:px-6 py-4 shrink-0">
        <div className="flex items-center gap-2 mb-3">
          <Link to="/datasets" className="text-gray-400 hover:text-gray-700 transition-colors">
            <ChevronLeft className="size-4" />
          </Link>
          <span className="text-xs text-gray-500">数据集</span>
          <span className="text-xs text-gray-400">/</span>
          <span className="text-xs text-gray-700 font-medium">{dataset.name}</span>
        </div>
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2 md:gap-3 min-w-0 flex-wrap">
            <h2 className="text-base font-semibold text-gray-900 font-mono">{dataset.name}</h2>
            <StatusBadge status={dataset.status} />
            {dataset.currentVersion && (
              <span className="text-xs text-gray-500 font-mono bg-gray-100 px-1.5 py-0.5 rounded">
                {dataset.currentVersion}
              </span>
            )}
          </div>
          <button onClick={load} title="刷新" className="size-7 flex items-center justify-center text-gray-400 hover:bg-gray-100 rounded transition-colors">
            <RefreshCw className="size-3.5" />
          </button>
        </div>
        {dataset.description && (
          <p className="text-xs text-gray-500 mt-1">{dataset.description}</p>
        )}
      </div>

      {/* Tabs */}
      <div className="bg-white border-b border-gray-200 px-2 md:px-6 shrink-0 overflow-x-auto">
        <div className="flex gap-0 min-w-max">
          {TABS.map(tab => (
            <button
              key={tab.key}
              onClick={() => setTab(tab.key)}
              className={cn(
                'px-4 py-3 text-sm border-b-2 transition-colors',
                activeTab === tab.key
                  ? 'border-blue-600 text-blue-700 font-medium'
                  : 'border-transparent text-gray-600 hover:text-gray-900'
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-hidden flex flex-col">
        {activeTab === 'overview' && <OverviewTab dataset={dataset} />}
        {activeTab === 'files' && <FilesTab dataset={dataset} />}
        {activeTab === 'format' && <FormatSplitsTab dataset={dataset} />}
        {activeTab === 'categories' && <CategoriesTab dataset={dataset} />}
        {activeTab === 'versions' && <VersionsTab dataset={dataset} />}
        {activeTab === 'review' && <ReviewTab dataset={dataset} />}
        {activeTab === 'training' && <DatasetTrainingTab dataset={dataset} />}
      </div>
    </div>
  );
}
