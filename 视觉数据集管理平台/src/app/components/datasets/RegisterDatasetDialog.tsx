import { useState, useEffect } from 'react';
import { ChevronRight, ChevronDown, Folder, FolderOpen, AlertTriangle, Loader2, CheckCircle2 } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../ui/dialog';
import { listAllowedRoots, getFileTree, scanDirectory, registerDataset } from '../../../services/api';
import type { AllowedRoot, FileTreeNode, ScanPreview } from '../../../types';
import { cn } from '../ui/utils';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
}

type Step = 'select' | 'preview' | 'fill' | 'submitting' | 'done';

function FileTree({
  nodes,
  selectedPath,
  onSelect,
}: {
  nodes: FileTreeNode[];
  selectedPath: string;
  onSelect: (path: string) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (path: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  function renderNode(node: FileTreeNode, depth = 0) {
    const isExpanded = expanded.has(node.path);
    const isSelected = selectedPath === node.path;
    const hasChildren = node.children && node.children.length > 0;

    return (
      <div key={node.path}>
        <div
          className={cn(
            'flex items-center gap-1.5 px-2 py-1 rounded cursor-pointer text-sm transition-colors',
            isSelected ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-100 text-gray-700'
          )}
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
          onClick={() => {
            if (node.type === 'dir') {
              onSelect(node.path);
              if (hasChildren) toggle(node.path);
            }
          }}
        >
          {hasChildren ? (
            <button
              onClick={e => { e.stopPropagation(); toggle(node.path); }}
              className="size-4 flex items-center justify-center"
            >
              {isExpanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
            </button>
          ) : (
            <span className="size-4" />
          )}
          {isExpanded ? <FolderOpen className="size-4 shrink-0 text-amber-500" /> : <Folder className="size-4 shrink-0 text-amber-400" />}
          <span className="truncate flex-1">{node.name}</span>
          {node.fileCount !== undefined && node.fileCount > 0 && (
            <span className="text-xs text-gray-400 shrink-0">{node.fileCount}</span>
          )}
        </div>
        {isExpanded && node.children?.map(child => renderNode(child, depth + 1))}
      </div>
    );
  }

  return <div>{nodes.map(n => renderNode(n))}</div>;
}

export function RegisterDatasetDialog({ open, onOpenChange, onSuccess }: Props) {
  const [step, setStep] = useState<Step>('select');
  const [roots, setRoots] = useState<AllowedRoot[]>([]);
  const [selectedRoot, setSelectedRoot] = useState<string>('');
  const [treeNodes, setTreeNodes] = useState<FileTreeNode[]>([]);
  const [treeLoading, setTreeLoading] = useState(false);
  const [selectedPath, setSelectedPath] = useState<string>('');
  const [scan, setScan] = useState<ScanPreview | null>(null);
  const [scanLoading, setScanLoading] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [categoriesText, setCategoriesText] = useState('');
  const [submitProgress, setSubmitProgress] = useState(0);
  const [submitMsg, setSubmitMsg] = useState('');
  const [nameError, setNameError] = useState('');

  useEffect(() => {
    if (open) {
      setStep('select');
      setSelectedRoot('');
      setSelectedPath('');
      setScan(null);
      setName('');
      setDescription('');
      setCategoriesText('');
      setNameError('');
      listAllowedRoots().then(setRoots);
    }
  }, [open]);

  useEffect(() => {
    if (!selectedRoot) return;
    setTreeLoading(true);
    setTreeNodes([]);
    setSelectedPath('');
    getFileTree(selectedRoot).then(nodes => {
      setTreeNodes(nodes);
      setTreeLoading(false);
    });
  }, [selectedRoot]);

  const handleScan = async () => {
    if (!selectedPath) return;
    setScanLoading(true);
    setScan(null);
    setStep('preview');
    const result = await scanDirectory(selectedPath);
    setScan(result);
    setScanLoading(false);
  };

  const handleSubmit = async () => {
    if (!name.trim()) { setNameError('请填写数据集名称'); return; }
    setStep('submitting');
    const stages = [
      [20, '正在扫描目录结构...'],
      [40, '正在扫描 340 / 680 文件...'],
      [60, '正在扫描 680 / 680 文件...'],
      [80, '正在注册数据集...'],
      [100, '登记完成'],
    ] as const;
    for (const [progress, msg] of stages) {
      setSubmitProgress(progress);
      setSubmitMsg(msg);
      await new Promise(r => setTimeout(r, 600));
    }
    await registerDataset({
      name: name.trim(),
      description,
      rootPath: selectedPath,
      categories: categoriesText.split(',').map(s => s.trim()).filter(Boolean),
    });
    setStep('done');
  };

  const canProceedToFill = !!selectedPath && scan && !scanLoading;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>登记服务器数据集</DialogTitle>
        </DialogHeader>

        {/* Step: select + preview */}
        {(step === 'select' || step === 'preview') && (
          <div className="space-y-4">
            {/* Root selector */}
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1.5">允许访问的根目录</label>
              <div className="flex gap-2">
                {roots.map(r => (
                  <button
                    key={r.id}
                    onClick={() => setSelectedRoot(r.path)}
                    className={cn(
                      'px-3 py-1.5 rounded border text-sm transition-colors',
                      selectedRoot === r.path
                        ? 'border-blue-400 bg-blue-50 text-blue-700'
                        : 'border-gray-200 text-gray-600 hover:bg-gray-50'
                    )}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
            </div>

            {/* File tree */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1.5">选择目录</label>
                <div className="border border-gray-200 rounded h-56 overflow-y-auto p-1 bg-white">
                  {!selectedRoot && (
                    <p className="text-xs text-gray-400 px-2 py-4 text-center">请先选择根目录</p>
                  )}
                  {selectedRoot && treeLoading && (
                    <div className="flex items-center justify-center h-full">
                      <Loader2 className="size-5 animate-spin text-gray-400" />
                    </div>
                  )}
                  {selectedRoot && !treeLoading && (
                    <FileTree nodes={treeNodes} selectedPath={selectedPath} onSelect={setSelectedPath} />
                  )}
                </div>
                {selectedPath && (
                  <div className="mt-1.5 flex items-center gap-1.5">
                    <span className="text-xs text-gray-500 truncate">{selectedPath}</span>
                    <button
                      onClick={handleScan}
                      className="shrink-0 text-xs text-blue-600 hover:underline"
                    >
                      扫描预览
                    </button>
                  </div>
                )}
              </div>

              {/* Scan preview */}
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1.5">扫描预览</label>
                <div className="border border-gray-200 rounded h-56 p-3 bg-white">
                  {!scan && !scanLoading && (
                    <p className="text-xs text-gray-400 text-center pt-8">选择目录后点击「扫描预览」</p>
                  )}
                  {scanLoading && (
                    <div className="flex flex-col items-center justify-center h-full gap-2">
                      <Loader2 className="size-6 animate-spin text-blue-400" />
                      <p className="text-xs text-gray-500">正在扫描...</p>
                    </div>
                  )}
                  {scan && !scanLoading && (
                    <div className="space-y-2">
                      <div className="grid grid-cols-2 gap-y-1.5 text-xs">
                        <span className="text-gray-500">图片数量</span>
                        <span className="font-medium text-gray-800 tabular-nums">{scan.imageCount.toLocaleString()}</span>
                        <span className="text-gray-500">视频数量</span>
                        <span className="font-medium text-gray-800">{scan.videoCount}</span>
                        <span className="text-gray-500">COCO 文件</span>
                        <span className="font-medium text-gray-800">{scan.cocoFiles.length > 0 ? scan.cocoFiles.join(', ') : '无'}</span>
                        <span className="text-gray-500">总大小</span>
                        <span className="font-medium text-gray-800">{scan.totalSizeMB >= 1024 ? `${(scan.totalSizeMB / 1024).toFixed(1)} GB` : `${scan.totalSizeMB} MB`}</span>
                      </div>
                      {scan.anomalies.length > 0 && (
                        <div className="mt-2 p-2 bg-amber-50 border border-amber-200 rounded">
                          <div className="flex items-start gap-1.5">
                            <AlertTriangle className="size-3.5 text-amber-600 shrink-0 mt-0.5" />
                            <div className="text-xs text-amber-700 space-y-0.5">
                              {scan.anomalies.map((a, i) => <p key={i}>{a}</p>)}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>

            <DialogFooter>
              <button onClick={() => onOpenChange(false)} className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded">取消</button>
              <button
                onClick={() => setStep('fill')}
                disabled={!canProceedToFill}
                className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded disabled:opacity-40 transition-colors"
              >
                下一步
              </button>
            </DialogFooter>
          </div>
        )}

        {/* Step: fill info */}
        {step === 'fill' && (
          <div className="space-y-4">
            <div className="p-2.5 bg-gray-50 border border-gray-200 rounded text-xs text-gray-600">
              <span className="font-medium">路径：</span>{selectedPath}
              {scan && <span className="ml-3 text-gray-500">{scan.imageCount} 张图片 · {scan.totalSizeMB >= 1024 ? `${(scan.totalSizeMB / 1024).toFixed(1)} GB` : `${scan.totalSizeMB} MB`}</span>}
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">数据集名称 <span className="text-red-500">*</span></label>
              <input
                value={name}
                onChange={e => { setName(e.target.value); setNameError(''); }}
                placeholder="例如：warehouse-cargo-v4"
                className={cn(
                  'w-full px-3 py-1.5 text-sm border rounded outline-none focus:ring-1',
                  nameError ? 'border-red-400 focus:ring-red-100' : 'border-gray-200 focus:border-blue-400 focus:ring-blue-100'
                )}
              />
              {nameError && <p className="text-xs text-red-500 mt-1">{nameError}</p>}
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">描述</label>
              <textarea
                value={description}
                onChange={e => setDescription(e.target.value)}
                rows={2}
                placeholder="数据集用途、来源说明..."
                className="w-full px-3 py-1.5 text-sm border border-gray-200 rounded outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-100 resize-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">初始类别（逗号分隔）</label>
              <input
                value={categoriesText}
                onChange={e => setCategoriesText(e.target.value)}
                placeholder="cargo_box, pallet, forklift, person"
                className="w-full px-3 py-1.5 text-sm border border-gray-200 rounded outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-100"
              />
              <p className="text-xs text-gray-400 mt-1">可后续在类别页面编辑</p>
            </div>
            <DialogFooter>
              <button onClick={() => setStep('select')} className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded">上一步</button>
              <button
                onClick={handleSubmit}
                className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors"
              >
                登记数据集
              </button>
            </DialogFooter>
          </div>
        )}

        {/* Step: submitting */}
        {step === 'submitting' && (
          <div className="py-8 flex flex-col items-center gap-4">
            <Loader2 className="size-10 animate-spin text-blue-500" />
            <div className="text-center">
              <p className="text-sm font-medium text-gray-800">{submitMsg}</p>
              <div className="mt-3 w-64 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-500 rounded-full transition-all duration-500"
                  style={{ width: `${submitProgress}%` }}
                />
              </div>
            </div>
          </div>
        )}

        {/* Step: done */}
        {step === 'done' && (
          <div className="py-8 flex flex-col items-center gap-4">
            <CheckCircle2 className="size-10 text-green-500" />
            <div className="text-center">
              <p className="text-sm font-medium text-gray-900">数据集登记成功</p>
              <p className="text-xs text-gray-500 mt-1">「{name}」已添加到数据集列表，正在后台扫描中</p>
            </div>
            <button
              onClick={onSuccess}
              className="px-4 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors"
            >
              完成
            </button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
