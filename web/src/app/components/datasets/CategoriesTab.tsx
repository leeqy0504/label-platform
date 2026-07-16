import type { Dataset } from '../../../types';
import { EmptyState } from '../shared/EmptyState';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';

export function CategoriesTab({ dataset }: { dataset: Dataset }) {
  if (dataset.categories.length === 0) {
    return <EmptyState type="empty" title="暂无类别数据" description="数据集扫描完成后将显示类别信息" className="py-20" />;
  }

  const sorted = [...dataset.categories].sort((a, b) => b.count - a.count);
  const total = dataset.categories.reduce((s, c) => s + c.count, 0);

  return (
    <div className="p-4 md:p-5 space-y-5 overflow-y-auto">
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <h3 className="text-xs font-medium text-gray-600 mb-4">标注数量分布</h3>
        {total === 0 ? (
          <p className="text-xs text-gray-400 py-10 text-center">当前版本暂无标注</p>
        ) : <ResponsiveContainer width="100%" height={200}>
          <BarChart data={sorted} margin={{ top: 0, right: 16, bottom: 32, left: 8 }}>
            <XAxis
              dataKey="name"
              tick={{ fontSize: 11, fill: '#6B7280' }}
              angle={-25}
              textAnchor="end"
            />
            <YAxis tick={{ fontSize: 11, fill: '#6B7280' }} />
            <Tooltip
              formatter={(v: number) => [v.toLocaleString(), '标注数']}
              contentStyle={{ fontSize: 12 }}
            />
            <Bar dataKey="count" radius={[3, 3, 0, 0]}>
              {sorted.map(entry => (
                <Cell key={entry.name} fill={entry.color ?? '#6B7280'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>}
      </div>

      <div className="bg-white border border-gray-200 rounded-lg overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="border-b border-gray-200 bg-gray-50">
            <tr>
              <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">类别名称</th>
              <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500">超类别</th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-gray-500">标注数</th>
              <th className="text-right px-3 py-2.5 text-xs font-medium text-gray-500 w-24">占比</th>
              <th className="px-4 py-2.5 w-48" />
            </tr>
          </thead>
          <tbody>
            {sorted.map(cat => {
              const pct = total > 0 ? (cat.count / total) * 100 : 0;
              return (
                <tr key={cat.id} className="border-b border-gray-100">
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-2">
                      <span className="size-2.5 rounded-sm shrink-0" style={{ backgroundColor: cat.color ?? '#6B7280' }} />
                      <span className="font-mono text-xs text-gray-800">{cat.name}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-xs text-gray-500">{cat.supercategory}</td>
                  <td className="px-3 py-2.5 text-right text-xs tabular-nums font-medium text-gray-800">
                    {cat.count.toLocaleString()}
                  </td>
                  <td className="px-3 py-2.5 text-right text-xs tabular-nums text-gray-500">
                    {pct.toFixed(1)}%
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${pct}%`, backgroundColor: cat.color ?? '#6B7280' }}
                      />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
