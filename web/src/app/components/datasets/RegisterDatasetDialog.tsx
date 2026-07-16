import { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  FileJson,
  Folder,
  Loader2,
} from 'lucide-react';
import {
  analyzeDataset,
  getFileTree,
  getJob,
  listAllowedRoots,
  registerDataset,
} from '../../../services/api';
import type {
  AllowedRoot,
  AnalysisResult,
  BackgroundJob,
  FileTreeNode,
  TaskType,
} from '../../../types';
import { addTask, updateTask } from '../../hooks/useBackgroundTasks';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
}

type Phase = 'idle' | 'analyzing' | 'registering' | 'done';

const formatLabels: Record<string, string> = {
  image_directory: 'Image Directory',
  coco_detection: 'COCO Detection',
  coco_instance: 'COCO Instance Segmentation',
  label_studio: 'Label Studio Export',
};

function uniqueId() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

export function RegisterDatasetDialog({ open, onOpenChange, onSuccess }: Props) {
  const [roots, setRoots] = useState<AllowedRoot[]>([]);
  const [rootId, setRootId] = useState('');
  const [relativePath, setRelativePath] = useState('');
  const [entries, setEntries] = useState<FileTreeNode[]>([]);
  const [treeLoading, setTreeLoading] = useState(false);
  const [taskType, setTaskType] = useState<TaskType>('detection');
  const [categoriesText, setCategoriesText] = useState('');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [job, setJob] = useState<BackgroundJob | null>(null);
  const [error, setError] = useState('');
  const pollingControllers = useRef(new Set<AbortController>());

  useEffect(() => () => {
    pollingControllers.current.forEach(controller => controller.abort());
    pollingControllers.current.clear();
  }, []);

  useEffect(() => {
    if (!open) return;
    setRootId('');
    setRelativePath('');
    setEntries([]);
    setTaskType('detection');
    setCategoriesText('');
    setName('');
    setDescription('');
    setAnalysis(null);
    setPhase('idle');
    setJob(null);
    setError('');
    listAllowedRoots().then(setRoots).catch(() => setError('允许目录加载失败'));
  }, [open]);

  const categories = categoriesText.split(',').map(value => value.trim()).filter(Boolean);
  const selection = () => ({
    source_root_id: rootId,
    relative_path: relativePath,
    categories,
    task_type: taskType,
    split: { train: 0.8, val: 0.2, test: 0, seed: 42 },
  });

  const invalidateAnalysis = () => {
    setAnalysis(null);
    setJob(null);
    setError('');
  };

  const loadTree = async (nextPath: string) => {
    if (!rootId) return;
    setTreeLoading(true);
    try {
      setEntries(await getFileTree(rootId, nextPath));
    } catch {
      setEntries([]);
      setError('目录读取失败');
    } finally {
      setTreeLoading(false);
    }
  };

  const chooseRoot = (nextRoot: string) => {
    setRootId(nextRoot);
    setRelativePath('');
    setEntries([]);
    invalidateAnalysis();
    if (nextRoot) {
      setTreeLoading(true);
      getFileTree(nextRoot, '')
        .then(setEntries)
        .catch(() => setError('目录读取失败'))
        .finally(() => setTreeLoading(false));
    }
  };

  const openDirectory = (path: string) => {
    setRelativePath(path);
    invalidateAnalysis();
    void loadTree(path);
  };

  const goParent = () => {
    const parts = relativePath.split('/').filter(Boolean);
    parts.pop();
    openDirectory(parts.join('/'));
  };

  const waitForJob = async <T,>(jobId: string): Promise<BackgroundJob<T>> => {
    const controller = new AbortController();
    pollingControllers.current.add(controller);
    try {
      while (!controller.signal.aborted) {
        const current = await getJob<T>(jobId, controller.signal);
        setJob(current as BackgroundJob);
        if (!['pending', 'running'].includes(current.status)) return current;
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
      throw new DOMException('Polling aborted', 'AbortError');
    } finally {
      pollingControllers.current.delete(controller);
    }
  };

  const runAnalysis = async () => {
    if (!rootId) {
      setError('请选择允许目录');
      return;
    }
    setPhase('analyzing');
    setAnalysis(null);
    setError('');
    try {
      const accepted = await analyzeDataset({ ...selection(), idempotency_key: uniqueId() });
      const completed = await waitForJob<AnalysisResult>(accepted.job_id);
      if (completed.status === 'failed') {
        setError(completed.error_summary.message ?? '分析任务失败');
      } else {
        setAnalysis(completed.result);
      }
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === 'AbortError')) setError('目录分析失败');
    } finally {
      setPhase('idle');
    }
  };

  const submit = async () => {
    if (!analysis?.valid || !analysis.fingerprint) return;
    if (!name.trim()) {
      setError('请填写数据集名称');
      return;
    }
    setPhase('registering');
    setError('');
    const taskId = `registration-${uniqueId()}`;
    addTask({ id: taskId, label: `登记 ${name.trim()}`, status: 'running', progress: 0 });
    try {
      const accepted = await registerDataset({
        ...selection(),
        name: name.trim(),
        description: description.trim(),
        analysis_fingerprint: analysis.fingerprint,
        idempotency_key: uniqueId(),
      });
      const completed = await waitForJob(accepted.job_id);
      if (completed.status !== 'succeeded') {
        throw new Error(completed.error_summary.message ?? '登记任务失败');
      }
      updateTask(taskId, { status: 'done', progress: 100, message: '登记完成' });
      setPhase('done');
    } catch (caught) {
      updateTask(taskId, { status: 'error', message: '登记失败' });
      setError(caught instanceof Error ? caught.message : '登记失败');
      setPhase('idle');
    }
  };

  const progress = job && job.total_count > 0
    ? Math.round((job.processed_count / job.total_count) * 100)
    : phase === 'registering' || phase === 'analyzing' ? 10 : 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[88vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>登记服务器数据集</DialogTitle>
          <DialogDescription>从管理员批准的目录分析并登记不可变数据集版本。</DialogDescription>
        </DialogHeader>

        {phase === 'done' ? (
          <div className="py-10 text-center">
            <CheckCircle2 className="size-10 text-green-600 mx-auto mb-3" />
            <p className="text-sm font-medium text-gray-900">数据集登记完成</p>
            <button onClick={onSuccess} className="mt-5 px-3 py-2 text-sm bg-blue-600 text-white rounded">
              查看数据集
            </button>
          </div>
        ) : (
          <>
            <div className="grid md:grid-cols-2 gap-5">
              <div className="space-y-4">
                <div>
                  <label htmlFor="source-root" className="block text-xs font-medium text-gray-700 mb-1">允许目录</label>
                  <select
                    id="source-root"
                    value={rootId}
                    onChange={event => chooseRoot(event.target.value)}
                    className="w-full h-9 px-2 text-sm bg-white border border-gray-300 rounded"
                  >
                    <option value="">选择根目录</option>
                    {roots.map(root => <option key={root.id} value={root.id}>{root.label}</option>)}
                  </select>
                </div>
                <div>
                  <label htmlFor="relative-path" className="block text-xs font-medium text-gray-700 mb-1">相对路径</label>
                  <div className="flex gap-2">
                    <input
                      id="relative-path"
                      value={relativePath}
                      onChange={event => { setRelativePath(event.target.value); invalidateAnalysis(); }}
                      placeholder="incoming/warehouse"
                      className="flex-1 h-9 px-3 text-sm border border-gray-300 rounded font-mono"
                    />
                    <button
                      type="button"
                      onClick={() => void loadTree(relativePath)}
                      disabled={!rootId}
                      className="px-3 h-9 text-xs border border-gray-300 rounded disabled:opacity-50"
                    >
                      浏览
                    </button>
                  </div>
                </div>
                <div className="border border-gray-200 rounded h-44 overflow-y-auto bg-white">
                  <div className="h-8 px-2 flex items-center border-b border-gray-100 bg-gray-50">
                    <button
                      type="button"
                      title="上一级"
                      onClick={goParent}
                      disabled={!relativePath}
                      className="size-6 grid place-items-center text-gray-500 disabled:opacity-30"
                    >
                      <ChevronLeft className="size-4" />
                    </button>
                    <code className="ml-1 text-[11px] text-gray-500 truncate">/{relativePath}</code>
                  </div>
                  {treeLoading && <div className="h-32 grid place-items-center"><Loader2 className="size-5 animate-spin text-gray-400" /></div>}
                  {!treeLoading && entries.length === 0 && (
                    <p className="text-xs text-gray-400 text-center py-10">目录为空</p>
                  )}
                  {!treeLoading && entries.map(entry => (
                    <button
                      key={entry.path}
                      type="button"
                      disabled={entry.type === 'file'}
                      onClick={() => entry.type === 'dir' && openDirectory(entry.path)}
                      className="w-full h-8 flex items-center gap-2 px-3 text-left hover:bg-gray-50 disabled:hover:bg-white"
                    >
                      {entry.type === 'dir'
                        ? <Folder className="size-4 text-amber-500" />
                        : <FileJson className="size-4 text-gray-400" />}
                      <span className="text-xs text-gray-700 truncate">{entry.name}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-4">
                <div>
                  <label htmlFor="task-type" className="block text-xs font-medium text-gray-700 mb-1">任务类型</label>
                  <select
                    id="task-type"
                    value={taskType}
                    onChange={event => { setTaskType(event.target.value as TaskType); invalidateAnalysis(); }}
                    className="w-full h-9 px-2 text-sm bg-white border border-gray-300 rounded"
                  >
                    <option value="detection">目标检测</option>
                    <option value="instance_segmentation">实例分割</option>
                  </select>
                </div>
                <div>
                  <label htmlFor="categories" className="block text-xs font-medium text-gray-700 mb-1">初始类别</label>
                  <input
                    id="categories"
                    value={categoriesText}
                    onChange={event => { setCategoriesText(event.target.value); invalidateAnalysis(); }}
                    placeholder="person, rack, cargo"
                    className="w-full h-9 px-3 text-sm border border-gray-300 rounded"
                  />
                </div>
                <div>
                  <label htmlFor="dataset-name" className="block text-xs font-medium text-gray-700 mb-1">数据集名称</label>
                  <input
                    id="dataset-name"
                    value={name}
                    onChange={event => setName(event.target.value)}
                    placeholder="warehouse-cargo"
                    className="w-full h-9 px-3 text-sm border border-gray-300 rounded"
                  />
                </div>
                <div>
                  <label htmlFor="description" className="block text-xs font-medium text-gray-700 mb-1">描述</label>
                  <textarea
                    id="description"
                    value={description}
                    onChange={event => setDescription(event.target.value)}
                    rows={2}
                    className="w-full px-3 py-2 text-sm border border-gray-300 rounded resize-none"
                  />
                </div>
              </div>
            </div>

            <div className="border-t border-gray-200 pt-4">
              {phase === 'analyzing' || phase === 'registering' ? (
                <div className="flex items-center gap-3">
                  <Loader2 className="size-5 text-blue-600 animate-spin" />
                  <div className="flex-1">
                    <div className="flex justify-between text-xs mb-1">
                      <span>{phase === 'analyzing' ? '正在分析目录' : '正在登记数据集'} · {job?.stage ?? 'pending'}</span>
                      <span>{progress}%</span>
                    </div>
                    <div className="h-1.5 bg-gray-100 rounded overflow-hidden">
                      <div className="h-full bg-blue-600" style={{ width: `${progress}%` }} />
                    </div>
                  </div>
                </div>
              ) : analysis ? (
                <AnalysisPanel analysis={analysis} />
              ) : (
                <p className="text-xs text-gray-500">分析完成后才能登记数据集。</p>
              )}
              {error && (
                <div role="alert" className="mt-3 flex gap-2 text-xs text-red-700">
                  <AlertTriangle className="size-4 shrink-0" />{error}
                </div>
              )}
            </div>

            <DialogFooter>
              <button onClick={() => onOpenChange(false)} className="px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded">取消</button>
              <button
                onClick={() => void runAnalysis()}
                disabled={!rootId || phase !== 'idle'}
                className="px-3 py-2 text-sm border border-gray-300 rounded disabled:opacity-40"
              >
                分析目录
              </button>
              <button
                onClick={() => void submit()}
                disabled={!analysis?.valid || !analysis.fingerprint || phase !== 'idle'}
                className="px-3 py-2 text-sm bg-blue-600 text-white rounded disabled:opacity-40"
              >
                登记数据集
              </button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function AnalysisPanel({ analysis }: { analysis: AnalysisResult }) {
  if (!analysis.valid) {
    return (
      <div className="bg-red-50 border border-red-200 rounded p-3">
        <p className="text-xs font-medium text-red-800 mb-1">分析未通过</p>
        {analysis.errors.map(error => <p key={`${error.code}-${error.path}`} className="text-xs text-red-700">{error.message}</p>)}
      </div>
    );
  }
  return (
    <div className="grid grid-cols-4 gap-3 bg-green-50 border border-green-200 rounded p-3">
      <div>
        <p className="text-[11px] text-green-700">源格式</p>
        <p className="text-xs font-medium text-green-950">{formatLabels[analysis.source_format ?? '']}</p>
      </div>
      <div>
        <p className="text-[11px] text-green-700">媒体</p>
        <p className="text-xs font-medium text-green-950">{analysis.image_count.toLocaleString()} 张图片</p>
      </div>
      <div>
        <p className="text-[11px] text-green-700">标注</p>
        <p className="text-xs font-medium text-green-950">{analysis.annotation_count.toLocaleString()} 个</p>
      </div>
      <div>
        <p className="text-[11px] text-green-700">切分</p>
        <p className="text-xs font-medium text-green-950">{analysis.split_counts.train} / {analysis.split_counts.val} / {analysis.split_counts.test}</p>
      </div>
    </div>
  );
}
