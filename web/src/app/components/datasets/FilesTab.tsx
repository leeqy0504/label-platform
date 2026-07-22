import { useState, useEffect, useCallback } from 'react';
import { Search, LayoutGrid, List, X, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { listMediaFiles } from '../../../services/api';
import type { Dataset, MediaFile } from '../../../types';
import { EmptyState, LoadingRows } from '../shared/EmptyState';
import { Pagination } from '../shared/Pagination';
import { CopyButton } from '../shared/CopyButton';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select';
import { cn } from '../ui/utils';

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function AnnotationBadge({ status }: { status: MediaFile['annotationStatus'] }) {
  const cfg = {
    annotated: 'text-green-700 bg-green-50',
    unannotated: 'text-gray-500 bg-gray-100',
    partial: 'text-amber-700 bg-amber-50',
  }[status];
  const label = { annotated: '已标注', unannotated: '未标注', partial: '部分' }[status];
  return <span className={cn('text-xs px-1.5 py-0.5 rounded', cfg)}>{label}</span>;
}

const BBOX_COLORS = [
  '#ef4444',
  '#22c55e',
  '#3b82f6',
  '#f59e0b',
  '#a855f7',
  '#06b6d4',
  '#ec4899',
  '#84cc16',
];

function bboxColor(categoryId: number) {
  const index = ((categoryId - 1) % BBOX_COLORS.length + BBOX_COLORS.length) % BBOX_COLORS.length;
  return BBOX_COLORS[index];
}

export function AnnotatedImage({
  file,
  loading,
}: {
  file: MediaFile;
  loading?: 'eager' | 'lazy';
}) {
  const canRenderOverlay = file.width > 0 && file.height > 0 && file.annotations.length > 0;

  return (
    <div className="relative flex size-full items-center justify-center overflow-hidden">
      <img
        src={file.thumbnailUrl}
        alt={file.filename}
        className="size-full object-contain"
        loading={loading}
        onError={event => { (event.currentTarget as HTMLImageElement).style.display = 'none'; }}
      />
      {canRenderOverlay && (
        <svg
          data-testid={`bbox-overlay-${file.id}`}
          viewBox={`0 0 ${file.width} ${file.height}`}
          preserveAspectRatio="xMidYMid meet"
          className="pointer-events-none absolute inset-0 size-full"
          aria-hidden="true"
        >
          {file.annotations.map((annotation, index) => (
            <rect
              key={`${annotation.categoryId}-${annotation.bbox.join('-')}-${index}`}
              x={annotation.bbox[0]}
              y={annotation.bbox[1]}
              width={annotation.bbox[2]}
              height={annotation.bbox[3]}
              fill="none"
              stroke={bboxColor(annotation.categoryId)}
              strokeWidth="2"
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </svg>
      )}
    </div>
  );
}

function FileInspector({ file, onClose }: { file: MediaFile; onClose: () => void }) {
  return (
    <div className="absolute inset-0 z-20 w-full shrink-0 border-l border-gray-200 bg-white flex flex-col sm:static sm:w-72">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <span className="text-xs font-medium text-gray-700 truncate">{file.filename}</span>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-700">
          <X className="size-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <div className="aspect-video bg-gray-100 rounded overflow-hidden flex items-center justify-center">
          <AnnotatedImage file={file} loading="eager" />
        </div>
        <div className="space-y-2 text-xs">
          {[
            ['尺寸', `${file.width} × ${file.height}`],
            ['文件大小', formatBytes(file.size)],
            ['Split', file.split],
            ['标注状态', ''],
            ['标注数', file.annotationCount],
          ].map(([k, v]) => (
            <div key={k as string} className="flex items-center gap-1">
              <span className="text-gray-500 w-16 shrink-0">{k}</span>
              {k === '标注状态'
                ? <AnnotationBadge status={file.annotationStatus} />
                : <span className="text-gray-800">{v}</span>}
            </div>
          ))}
          <div>
            <span className="text-gray-500">标注类型</span>
            <div className="flex gap-2 mt-1">
              {file.hasBbox && <span className="text-xs px-1.5 py-0.5 bg-blue-50 text-blue-700 rounded">bbox</span>}
              {file.hasMask && <span className="text-xs px-1.5 py-0.5 bg-purple-50 text-purple-700 rounded">mask</span>}
            </div>
          </div>
          <div className="pt-1">
            <p className="text-gray-500 mb-1">文件路径</p>
            <div className="flex items-start gap-1">
              <code className="text-[10px] text-gray-600 font-mono break-all">{file.path}</code>
              <CopyButton text={file.path} />
            </div>
          </div>
          <div>
            <p className="text-gray-500 mb-1">Checksum</p>
            <div className="flex items-start gap-1">
              <code className="text-[10px] text-gray-600 font-mono break-all">{file.checksum}</code>
              <CopyButton text={file.checksum} />
            </div>
          </div>
          {file.hasAnomaly && (
            <div className="flex items-center gap-1.5 p-2 bg-amber-50 border border-amber-200 rounded">
              <AlertTriangle className="size-3.5 text-amber-600 shrink-0" />
              <span className="text-amber-700">发现格式异常</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function FilesTab({ dataset }: { dataset: Dataset }) {
  const [view, setView] = useState<'table' | 'grid'>('table');
  const [search, setSearch] = useState('');
  const [split, setSplit] = useState('');
  const [annotationStatus, setAnnotationStatus] = useState('');
  const [page, setPage] = useState(1);
  const [files, setFiles] = useState<MediaFile[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<MediaFile | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await listMediaFiles(dataset.id, {
        search, split, annotationStatus, page, pageSize: view === 'grid' ? 24 : 20,
      });
      setFiles(result.data);
      setTotal(result.meta.total);
    } catch {
      setFiles([]);
      setTotal(0);
      setError('文件列表加载失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }, [dataset.id, search, split, annotationStatus, page, view]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(1); }, [search, split, annotationStatus]);

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-4 md:px-5 py-3 border-b border-gray-100 bg-white shrink-0 flex-wrap">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-gray-400" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="文件名..."
            className="pl-8 pr-3 py-1.5 text-sm bg-gray-50 border border-gray-200 rounded outline-none focus:border-blue-400 w-48"
          />
        </div>
        <Select value={split || '__all__'} onValueChange={v => setSplit(v === '__all__' ? '' : v)}>
          <SelectTrigger className="w-24 h-8 text-sm">
            <SelectValue placeholder="Split" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">全部</SelectItem>
            <SelectItem value="train">train</SelectItem>
            <SelectItem value="val">val</SelectItem>
            <SelectItem value="test">test</SelectItem>
          </SelectContent>
        </Select>
        <Select value={annotationStatus || '__all__'} onValueChange={v => setAnnotationStatus(v === '__all__' ? '' : v)}>
          <SelectTrigger className="w-28 h-8 text-sm">
            <SelectValue placeholder="标注状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">全部状态</SelectItem>
            <SelectItem value="annotated">已标注</SelectItem>
            <SelectItem value="unannotated">未标注</SelectItem>
            <SelectItem value="partial">部分标注</SelectItem>
          </SelectContent>
        </Select>
        <span className="flex-1" />
        <span className="text-xs text-gray-500">{total} 个文件</span>
        <div className="flex border border-gray-200 rounded overflow-hidden">
          <button
            onClick={() => setView('table')}
            aria-label="表格视图"
            className={cn('px-2.5 py-1.5 transition-colors', view === 'table' ? 'bg-gray-100 text-gray-800' : 'text-gray-500 hover:bg-gray-50')}
          >
            <List className="size-4" />
          </button>
          <button
            onClick={() => setView('grid')}
            aria-label="网格视图"
            className={cn('px-2.5 py-1.5 transition-colors', view === 'grid' ? 'bg-gray-100 text-gray-800' : 'text-gray-500 hover:bg-gray-50')}
          >
            <LayoutGrid className="size-4" />
          </button>
        </div>
      </div>

      <div className="relative flex flex-1 overflow-hidden">
        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {view === 'table' ? (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-gray-50 border-b border-gray-200 z-10">
                <tr>
                  <th className="text-left px-5 py-2.5 text-xs font-medium text-gray-500">文件名</th>
                  <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-14">Split</th>
                  <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-20">尺寸</th>
                  <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-20">标注状态</th>
                  <th className="text-right px-3 py-2.5 text-xs font-medium text-gray-500 w-16">标注数</th>
                  <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-24">类型</th>
                  <th className="w-8" />
                </tr>
              </thead>
              <tbody>
                {loading && <LoadingRows rows={8} cols={7} />}
                {!loading && error && (
                  <tr><td colSpan={7}><EmptyState type="error" title="加载失败" description={error} action={
                    <button onClick={load} className="text-sm text-blue-600 hover:underline">重试</button>
                  } /></td></tr>
                )}
                {!loading && !error && files.length === 0 && (
                  <tr><td colSpan={7}><EmptyState type="no-results" title="无匹配文件" /></td></tr>
                )}
                {!loading && files.map(f => (
                  <tr
                    key={f.id}
                    className={cn(
                      'border-b border-gray-100 hover:bg-gray-50 cursor-pointer transition-colors',
                      selected?.id === f.id && 'bg-blue-50'
                    )}
                    onClick={() => setSelected(s => s?.id === f.id ? null : f)}
                  >
                    <td className="px-5 py-2">
                      <div className="flex items-center gap-2">
                        {f.hasAnomaly && <AlertTriangle className="size-3.5 text-amber-500 shrink-0" />}
                        {!f.hasAnomaly && f.annotationStatus === 'annotated' && <CheckCircle2 className="size-3.5 text-green-500 shrink-0" />}
                        <span className="font-mono text-xs text-gray-700">{f.filename}</span>
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <span className="text-xs text-gray-500 font-mono">{f.split}</span>
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-600">{f.width}×{f.height}</td>
                    <td className="px-3 py-2"><AnnotationBadge status={f.annotationStatus} /></td>
                    <td className="px-3 py-2 text-right text-xs tabular-nums text-gray-700">{f.annotationCount}</td>
                    <td className="px-3 py-2">
                      <div className="flex gap-1">
                        {f.hasBbox && <span className="text-[10px] px-1 py-0.5 bg-blue-50 text-blue-700 rounded">bbox</span>}
                        {f.hasMask && <span className="text-[10px] px-1 py-0.5 bg-purple-50 text-purple-700 rounded">mask</span>}
                      </div>
                    </td>
                    <td className="px-3 py-2" />
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="p-4 md:p-5 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-3">
              {loading && Array.from({ length: 24 }, (_, i) => (
                <div key={i} className="aspect-square bg-gray-100 rounded animate-pulse" />
              ))}
              {!loading && error && (
                <div className="col-span-full">
                  <EmptyState type="error" title="加载失败" description={error} action={
                    <button onClick={load} className="text-sm text-blue-600 hover:underline">重试</button>
                  } />
                </div>
              )}
              {!loading && !error && files.map(f => (
                <div
                  key={f.id}
                  onClick={() => setSelected(s => s?.id === f.id ? null : f)}
                  className={cn(
                    'relative rounded overflow-hidden cursor-pointer border-2 transition-all',
                    selected?.id === f.id ? 'border-blue-500' : 'border-transparent hover:border-gray-300'
                  )}
                >
                  <div className="aspect-square bg-gray-100">
                    <AnnotatedImage file={f} loading="lazy" />
                  </div>
                  {f.hasAnomaly && (
                    <div className="absolute top-1 right-1">
                      <AlertTriangle className="size-3.5 text-amber-500" />
                    </div>
                  )}
                  <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/60 px-1.5 py-1">
                    <p className="text-[9px] text-white truncate">{f.filename}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
          <Pagination page={page} pageSize={view === 'grid' ? 24 : 20} total={total} onChange={setPage} />
        </div>

        {/* Inspector */}
        {selected && <FileInspector file={selected} onClose={() => setSelected(null)} />}
      </div>
    </div>
  );
}
