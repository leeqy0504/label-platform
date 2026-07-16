import { Lock, GitBranch, Tag } from 'lucide-react';
import type { Dataset } from '../../../types';
import { CopyButton } from '../shared/CopyButton';
import { cn } from '../ui/utils';

const SOURCE_LABEL: Record<string, string> = {
  initial_import: '初始导入',
  review_export: 'Label Studio 导出',
  manual: '手动创建',
};

export function VersionsTab({ dataset }: { dataset: Dataset }) {
  if (dataset.versions.length === 0) {
    return (
      <div className="p-8 text-center text-sm text-gray-500">
        暂无版本记录
      </div>
    );
  }

  const sorted = [...dataset.versions].sort((a, b) => b.version.localeCompare(a.version));

  return (
    <div className="p-4 md:p-5 overflow-y-auto">
      <div className="flex items-start">
        {/* Timeline */}
        <div className="flex flex-col items-center mr-4 mt-1">
          {sorted.map((_, i) => (
            <div key={i} className="flex flex-col items-center">
              <div className="size-3 rounded-full bg-gray-300 border-2 border-white ring-1 ring-gray-300" />
              {i < sorted.length - 1 && <div className="w-0.5 h-20 bg-gray-200" />}
            </div>
          ))}
        </div>

        {/* Version cards */}
        <div className="flex-1 space-y-4">
          {sorted.map(ver => (
            <div
              key={ver.id}
              className={cn(
                'border rounded-lg p-4 bg-white',
                ver.version === dataset.currentVersion ? 'border-blue-300' : 'border-gray-200'
              )}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold font-mono text-gray-900">{ver.version}</span>
                  {ver.version === dataset.currentVersion && (
                    <span className="text-xs px-1.5 py-0.5 bg-blue-50 text-blue-700 border border-blue-200 rounded">当前</span>
                  )}
                  {ver.isImmutable && (
                    <span className="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 bg-gray-100 text-gray-600 border border-gray-200 rounded">
                      <Lock className="size-2.5" />不可修改
                    </span>
                  )}
                </div>
                <span className="text-xs text-gray-400">
                  {new Date(ver.createdAt).toLocaleDateString('zh-CN', { year: 'numeric', month: 'short', day: 'numeric' })}
                </span>
              </div>

              <div className="grid grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-2 text-xs mb-3">
                <div>
                  <span className="text-gray-500">来源</span>
                  <p className="text-gray-800 mt-0.5">{SOURCE_LABEL[ver.source] ?? ver.source}</p>
                </div>
                {ver.parentVersion && (
                  <div>
                    <span className="text-gray-500">父版本</span>
                    <p className="text-gray-800 font-mono mt-0.5 flex items-center gap-1">
                      <GitBranch className="size-3 text-gray-400" />
                      {ver.parentVersion}
                    </p>
                  </div>
                )}
                <div>
                  <span className="text-gray-500">创建人</span>
                  <p className="text-gray-800 mt-0.5">{ver.createdBy}</p>
                </div>
                <div>
                  <span className="text-gray-500">图片数</span>
                  <p className="text-gray-900 font-medium tabular-nums mt-0.5">{ver.imageCount.toLocaleString()}</p>
                </div>
                <div>
                  <span className="text-gray-500">标注数</span>
                  <p className="text-gray-900 font-medium tabular-nums mt-0.5">{ver.annotationCount.toLocaleString()}</p>
                </div>
                <div>
                  <span className="text-gray-500">类别数</span>
                  <p className="text-gray-900 font-medium mt-0.5">{ver.categorySchema.length}</p>
                </div>
                <div>
                  <span className="text-gray-500">审核会话</span>
                  <p className="text-gray-800 font-mono mt-0.5 flex items-center gap-1">
                    {ver.reviewSessionId
                      ? <><span>{ver.reviewSessionId}</span><CopyButton text={ver.reviewSessionId} /></>
                      : '—'}
                  </p>
                </div>
                <div>
                  <span className="text-gray-500">训练次数</span>
                  <p className="text-gray-800 mt-0.5">{ver.trainingCount}</p>
                </div>
              </div>

              {/* COCO file path */}
              {ver.cocoFilePath && <div className="flex items-center gap-1.5 p-2 bg-gray-50 border border-gray-100 rounded text-xs">
                <Tag className="size-3.5 text-gray-400 shrink-0" />
                <code className="text-gray-600 truncate font-mono">{ver.cocoFilePath}</code>
                <CopyButton text={ver.cocoFilePath} />
              </div>}

              {ver.notes && (
                <p className="text-xs text-gray-500 mt-2 border-t border-gray-100 pt-2">{ver.notes}</p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
