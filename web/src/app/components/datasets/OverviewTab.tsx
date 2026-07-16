import { CheckCircle2, AlertTriangle, Clock, CircleDashed } from 'lucide-react';
import type { Dataset } from '../../../types';
import { StatusBadge } from '../shared/StatusBadge';
import { CopyButton } from '../shared/CopyButton';
import { PieChart, Pie, Cell, Tooltip } from 'recharts';

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className="text-xl font-semibold text-gray-900 tabular-nums">{typeof value === 'number' ? value.toLocaleString() : value}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}

function IntegrityRow({
  label,
  state,
  detail,
}: {
  label: string;
  state: 'ok' | 'error' | 'pending';
  detail: string;
}) {
  return (
    <div className="flex items-center gap-2.5 py-1.5">
      {state === 'ok' && <CheckCircle2 className="size-4 text-green-500 shrink-0" />}
      {state === 'error' && <AlertTriangle className="size-4 text-amber-500 shrink-0" />}
      {state === 'pending' && <CircleDashed className="size-4 text-gray-400 shrink-0" />}
      <span className="text-sm text-gray-700 flex-1">{label}</span>
      <span className="text-xs text-gray-500">{detail}</span>
    </div>
  );
}

export function OverviewTab({ dataset }: { dataset: Dataset }) {
  const totalSize = dataset.totalSize >= 1024
    ? `${(dataset.totalSize / 1024).toFixed(1)} GB`
    : `${dataset.totalSize.toFixed(dataset.totalSize >= 10 ? 0 : 1)} MB`;

  const pieData = dataset.categories.slice(0, 8).map(c => ({
    name: c.name,
    value: c.count,
    color: c.color ?? '#6B7280',
  }));

  const validationErrors = dataset.validationResult.errors ?? [];
  const validationState = dataset.validationResult.valid === true
    ? 'ok'
    : dataset.validationResult.valid === false
      ? 'error'
      : 'pending';
  const validationDetail = validationState === 'ok'
    ? '通过'
    : validationState === 'error'
      ? `${validationErrors.length} 个错误`
      : '等待校验';

  return (
    <div className="p-4 md:p-5 space-y-5 overflow-y-auto">
      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        <StatCard label="媒体文件" value={dataset.mediaCount} sub={`训练 ${dataset.trainCount} · 验证 ${dataset.valCount} · 测试 ${dataset.testCount}`} />
        <StatCard label="标注数量" value={dataset.annotationCount} sub={`${dataset.categoryCount} 个类别`} />
        <StatCard label="当前版本" value={dataset.currentVersion || '—'} />
        <StatCard label="数据体积" value={totalSize} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* Category distribution */}
        <div className="xl:col-span-2 bg-white border border-gray-200 rounded-lg p-4">
          <h3 className="text-xs font-medium text-gray-600 mb-3">类别分布</h3>
          {pieData.length === 0 ? (
            <p className="text-xs text-gray-400 py-4 text-center">暂无类别数据</p>
          ) : (
            <div className="flex items-center gap-4">
              <PieChart width={140} height={140}>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={40}
                    outerRadius={65}
                    paddingAngle={2}
                    dataKey="value"
                  >
                    {pieData.map(entry => (
                      <Cell key={entry.name} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(v: number) => [v.toLocaleString(), '数量']}
                    contentStyle={{ fontSize: 12, padding: '4px 8px' }}
                  />
              </PieChart>
              <div className="flex-1 space-y-1">
                {pieData.map(d => (
                  <div key={d.name} className="flex items-center gap-2 text-xs">
                    <span className="size-2.5 rounded-sm shrink-0" style={{ backgroundColor: d.color }} />
                    <span className="text-gray-600 flex-1 truncate">{d.name}</span>
                    <span className="tabular-nums text-gray-800 font-medium">{d.value.toLocaleString()}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* File integrity & meta */}
        <div className="space-y-3">
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <h3 className="text-xs font-medium text-gray-600 mb-2">文件完整性</h3>
            <div className="divide-y divide-gray-100">
              <IntegrityRow label="规范格式校验" state={validationState} detail={validationDetail} />
              <IntegrityRow
                label="图片文件完整"
                state={dataset.mediaCount > 0 ? validationState : 'pending'}
                detail={dataset.mediaCount > 0 ? `${dataset.mediaCount} 张` : '未发布'}
              />
              <IntegrityRow
                label={dataset.taskType === 'instance_segmentation' ? 'Mask 与边界框校验' : '边界框校验'}
                state={dataset.annotationCount === 0 ? 'ok' : validationState}
                detail={dataset.annotationCount === 0 ? '无标注' : validationDetail}
              />
            </div>
            {validationErrors.length > 0 && (
              <div className="mt-2 pt-2 border-t border-gray-100 space-y-1">
                {validationErrors.slice(0, 3).map((error, index) => (
                  <p key={`${error.code}-${index}`} className="text-[11px] text-amber-700 truncate" title={error.message}>
                    {error.code}: {error.message}
                  </p>
                ))}
              </div>
            )}
          </div>

          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <h3 className="text-xs font-medium text-gray-600 mb-2">基本信息</h3>
            <div className="space-y-2 text-xs">
              <div className="flex items-center gap-1">
                <span className="text-gray-500 w-14 shrink-0">状态</span>
                <StatusBadge status={dataset.status} />
              </div>
              <div className="flex items-center gap-1">
                <span className="text-gray-500 w-14 shrink-0">创建人</span>
                <span className="text-gray-700">{dataset.createdBy}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-gray-500 w-14 shrink-0">数据路径</span>
                <span className="text-gray-700 truncate font-mono text-[11px]">{dataset.rootPath}</span>
                <CopyButton text={dataset.rootPath} />
              </div>
              <div className="flex items-start gap-1">
                <span className="text-gray-500 w-14 shrink-0 flex items-center gap-1 pt-0.5">
                  <Clock className="size-3" />创建于
                </span>
                <span className="text-gray-700">{new Date(dataset.createdAt).toLocaleDateString('zh-CN')}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
