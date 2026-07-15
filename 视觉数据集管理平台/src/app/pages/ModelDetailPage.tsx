import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router';
import { ChevronLeft, ExternalLink, ImageIcon } from 'lucide-react';
import { getModel } from '../../services/api';
import type { Model } from '../../types';
import { CopyButton } from '../components/shared/CopyButton';
import { PageLoading, EmptyState } from '../components/shared/EmptyState';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell,
} from 'recharts';

function MetricCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className="text-xl font-semibold font-mono text-gray-900">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}

export default function ModelDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [model, setModel] = useState<Model | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    getModel(id)
      .then(setModel)
      .catch(() => setError('模型不存在或加载失败'))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="p-6"><PageLoading /></div>;
  if (error || !model) return (
    <div className="p-6">
      <EmptyState type="error" title="加载失败" description={error ?? '未知错误'} action={
        <Link to="/models" className="text-sm text-blue-600 hover:underline">返回模型列表</Link>
      } />
    </div>
  );

  const apData = model.categoryAP.map(c => ({
    name: c.category,
    ap50: Number(c.ap50.toFixed(3)),
    ap5095: Number(c.ap5095.toFixed(3)),
  }));

  return (
    <div className="p-6 max-w-screen-xl mx-auto space-y-5">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <button onClick={() => navigate('/models')} className="text-gray-400 hover:text-gray-700">
            <ChevronLeft className="size-4" />
          </button>
          <span className="text-xs text-gray-500">模型</span>
          <span className="text-xs text-gray-400">/</span>
          <span className="text-xs text-gray-700 font-mono">{model.name}</span>
        </div>
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-base font-semibold text-gray-900 font-mono mb-1">{model.name}</h2>
            <div className="flex items-center gap-3 text-xs text-gray-500">
              <span>{model.datasetName} <code className="font-mono text-gray-700">{model.datasetVersion}</code></span>
              <span>{model.taskType === 'detection' ? 'Detection' : 'Instance Segmentation'}</span>
              <span>创建人: {model.createdBy}</span>
              <span>{new Date(model.createdAt).toLocaleString('zh-CN')}</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Link
              to={`/training/${model.trainingRunId}`}
              className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-gray-200 text-gray-700 hover:bg-gray-50 rounded"
            >
              <ExternalLink className="size-3.5" />查看训练详情
            </Link>
          </div>
        </div>
      </div>

      {/* Summary metrics */}
      <div className="grid grid-cols-4 gap-3">
        <MetricCard label="mAP50" value={model.mAP50.toFixed(3)} />
        <MetricCard label="mAP50-95" value={model.mAP5095.toFixed(3)} />
        <MetricCard label="Precision" value={model.precision.toFixed(3)} />
        <MetricCard label="Recall" value={model.recall.toFixed(3)} />
      </div>

      <div className="grid grid-cols-3 gap-5">
        {/* Category AP */}
        <div className="col-span-2 bg-white border border-gray-200 rounded-lg p-4">
          <h3 className="text-xs font-medium text-gray-600 mb-3">各类别 AP</h3>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={apData} layout="vertical" margin={{ top: 0, right: 60, bottom: 0, left: 80 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#F3F4F6" />
                <XAxis type="number" domain={[0, 1]} tick={{ fontSize: 11, fill: '#9CA3AF' }} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: '#6B7280' }} width={80} />
                <Tooltip
                  contentStyle={{ fontSize: 12, padding: '4px 8px' }}
                  formatter={(v: number) => [v.toFixed(3)]}
                />
                <Bar dataKey="ap50" name="AP50" fill="#3B82F6" radius={[0, 3, 3, 0]} barSize={10} />
                <Bar dataKey="ap5095" name="AP50-95" fill="#93C5FD" radius={[0, 3, 3, 0]} barSize={10} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Model file & meta */}
        <div className="space-y-4">
          {/* Confusion matrix placeholder */}
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <h3 className="text-xs font-medium text-gray-600 mb-2">混淆矩阵</h3>
            <div className="h-28 bg-gray-50 border border-gray-100 rounded flex flex-col items-center justify-center gap-1.5">
              <ImageIcon className="size-6 text-gray-300" />
              <p className="text-xs text-gray-400">在 UnitTrain 中查看</p>
              <a href={`http://unittrain.internal/models/${model.id}`} target="_blank" rel="noreferrer"
                className="text-xs text-blue-600 hover:underline flex items-center gap-1">
                <ExternalLink className="size-3" />打开
              </a>
            </div>
          </div>

          {/* Model file */}
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <h3 className="text-xs font-medium text-gray-600 mb-2">模型文件</h3>
            <div className="space-y-2 text-xs">
              <div>
                <p className="text-gray-500 mb-0.5">文件路径</p>
                <div className="flex items-start gap-1">
                  <code className="text-gray-700 font-mono text-[10px] break-all">{model.filePath}</code>
                  <CopyButton text={model.filePath} />
                </div>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-500">文件大小</span>
                <span className="text-gray-700">{model.fileSize} MB</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-500">类别数</span>
                <span className="text-gray-700">{model.categories.length}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Category AP table */}
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
          <h3 className="text-xs font-medium text-gray-600">类别详细指标</h3>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200">
              <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">类别</th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-gray-500">AP50</th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-gray-500">AP50-95</th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-gray-500">样本数</th>
              <th className="px-4 py-2.5 w-40" />
            </tr>
          </thead>
          <tbody>
            {model.categoryAP.map(cat => (
              <tr key={cat.category} className="border-b border-gray-100">
                <td className="px-4 py-2 font-mono text-xs text-gray-800">{cat.category}</td>
                <td className="px-3 py-2 text-right font-mono text-xs font-medium text-gray-800 tabular-nums">
                  {Math.max(0, cat.ap50).toFixed(3)}
                </td>
                <td className="px-3 py-2 text-right font-mono text-xs text-gray-600 tabular-nums">
                  {Math.max(0, cat.ap5095).toFixed(3)}
                </td>
                <td className="px-3 py-2 text-right text-xs text-gray-500 tabular-nums">
                  {cat.count.toLocaleString()}
                </td>
                <td className="px-4 py-2">
                  <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-blue-400 rounded-full"
                      style={{ width: `${Math.max(0, cat.ap50) * 100}%` }}
                    />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
