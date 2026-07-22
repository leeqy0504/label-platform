import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, Link, useNavigate } from 'react-router';
import { ChevronLeft, ExternalLink, Download, AlertTriangle, RefreshCw, Box, Square, RotateCcw } from 'lucide-react';
import { getTrainingRun, retryJob, stopTrainingRun } from '../../services/api';
import type { MetricPoint, TrainingRun } from '../../types';
import { StatusBadge } from '../components/shared/StatusBadge';
import { CopyButton } from '../components/shared/CopyButton';
import { PageLoading, EmptyState } from '../components/shared/EmptyState';
import { Progress } from '../components/ui/progress';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts';
import { cn } from '../components/ui/utils';

function MetricChart({
  data,
  title,
  lines,
}: {
  data: MetricPoint[];
  title: string;
  lines: Array<{ key: string; color: string; label: string }>;
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <h3 className="text-xs font-medium text-gray-600 mb-3">{title}</h3>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 12, bottom: 4, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
            <XAxis
              dataKey="epoch"
              tick={{ fontSize: 11, fill: '#9CA3AF' }}
              label={{ value: 'Epoch', position: 'insideBottom', offset: -2, fontSize: 11, fill: '#9CA3AF' }}
            />
            <YAxis tick={{ fontSize: 11, fill: '#9CA3AF' }} width={36} />
            <Tooltip
              contentStyle={{ fontSize: 12, padding: '4px 8px', borderRadius: 4 }}
              formatter={(v: number, name: string) => [v.toFixed(4), name]}
            />
            <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
            {lines.map(l => (
              <Line
                key={l.key}
                dataKey={l.key}
                name={l.label}
                stroke={l.color}
                dot={false}
                strokeWidth={1.5}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function LogViewer({ logs }: { logs: string[] }) {
  const [autoScroll, setAutoScroll] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  const handleDownload = () => {
    const blob = new Blob([logs.join('\n')], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'training.log';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-gray-50">
        <span className="text-xs font-medium text-gray-600">训练日志</span>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={e => setAutoScroll(e.target.checked)}
              className="size-3"
            />
            自动滚动
          </label>
          <button onClick={handleDownload} title="下载日志" className="size-6 flex items-center justify-center text-gray-500 hover:text-gray-800 hover:bg-gray-100 rounded">
            <Download className="size-3.5" />
          </button>
        </div>
      </div>
      <div
        ref={containerRef}
        className="h-52 overflow-y-auto p-3 font-mono text-xs text-gray-700 bg-gray-950 space-y-0.5"
      >
        {logs.length === 0 ? (
          <p className="text-gray-500">暂无日志</p>
        ) : (
          logs.map((line, i) => {
            const isError = line.includes('ERROR');
            const isWarn = line.includes('WARN');
            return (
              <div key={i} className={cn(isError ? 'text-red-400' : isWarn ? 'text-amber-400' : 'text-gray-300')}>
                {line}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function formatDuration(seconds: number): string {
  if (seconds === 0) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

export default function TrainingDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [run, setRun] = useState<TrainingRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (showLoading = true) => {
    if (!id) return;
    if (showLoading) setLoading(true);
    setError(null);
    try {
      const data = await getTrainingRun(id);
      setRun(data);
    } catch {
      setError('训练任务不存在或加载失败');
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [id]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!run || !['queued', 'running'].includes(run.status)) return;
    const interval = window.setInterval(() => { void load(false); }, 5000);
    return () => window.clearInterval(interval);
  }, [load, run?.status]);

  const stop = async () => {
    if (!id) return;
    try {
      await stopTrainingRun(id);
      await load(false);
    } catch {
      setError('停止训练任务失败');
    }
  };

  const retry = async () => {
    if (!run?.jobId) return;
    try {
      await retryJob(run.jobId);
      await load(false);
    } catch {
      setError('重试训练提交失败');
    }
  };

  if (loading) return <div className="p-6"><PageLoading /></div>;
  if (error || !run) return (
    <div className="p-6">
      <EmptyState type="error" title="加载失败" description={error ?? '未知错误'} action={
        <Link to="/training" className="text-sm text-blue-600 hover:underline">返回训练列表</Link>
      } />
    </div>
  );

  const configEntries: [string, string][] = [
    ['框架', run.config.framework],
    ['模型', run.config.model],
    ['Batch Size', String(run.config.batchSize)],
    ['Learning Rate', String(run.config.learningRate)],
    ['Image Size', String(run.config.imageSize)],
    ['Device', String(run.config.device)],
    ['Gradient Accumulation', String(run.config.gradAccumSteps)],
    ['Epochs', String(run.totalEpochs)],
    ['Early Stopping', run.config.earlyStopping ? 'On' : 'Off'],
  ];

  return (
    <div className="p-4 md:p-6 max-w-screen-xl mx-auto space-y-5">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <button onClick={() => navigate('/training')} className="text-gray-400 hover:text-gray-700">
            <ChevronLeft className="size-4" />
          </button>
          <span className="text-xs text-gray-500">训练任务</span>
          <span className="text-xs text-gray-400">/</span>
          <span className="text-xs text-gray-700 font-mono">{run.name}</span>
        </div>
        <div className="flex flex-col lg:flex-row items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <h2 className="text-base font-semibold text-gray-900 font-mono">{run.name}</h2>
              <StatusBadge status={run.status} />
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
              <span>{run.datasetName} <code className="font-mono text-gray-700">{run.datasetVersion}</code></span>
              <span>启动时间: {new Date(run.startedAt).toLocaleString('zh-CN')}</span>
              <span>耗时: {formatDuration(run.durationSeconds)}</span>
              <span className="flex items-center gap-1">
                Run ID: <code className="font-mono text-gray-700">{run.id}</code>
                <CopyButton text={run.id} />
              </span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={() => void load(false)} title="刷新" className="size-7 flex items-center justify-center text-gray-400 hover:bg-gray-100 rounded">
              <RefreshCw className="size-3.5" />
            </button>
            {['queued', 'running'].includes(run.status) && (
              <button onClick={stop}
                className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-red-200 text-red-700 hover:bg-red-50 rounded">
                <Square className="size-3" />停止
              </button>
            )}
            {run.status === 'failed' && !run.unitTrainRunId && run.jobId && (
              <button onClick={retry}
                className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-blue-200 text-blue-700 hover:bg-blue-50 rounded">
                <RotateCcw className="size-3.5" />重试提交
              </button>
            )}
            {run.unitTrainRunUrl && (
              <a href={run.unitTrainRunUrl} target="_blank" rel="noreferrer"
                className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-gray-200 text-gray-700 hover:bg-gray-50 rounded">
                <ExternalLink className="size-3.5" />UnitTrain
              </a>
            )}
            {run.outputModelId && (
              <Link
                to={`/models/${run.outputModelId}`}
                className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs bg-blue-600 hover:bg-blue-700 text-white rounded"
              >
                <Box className="size-3.5" />查看输出模型
              </Link>
            )}
          </div>
        </div>
      </div>

      {/* Error banner */}
      {run.status === 'failed' && run.errorMessage && (
        <div className="flex items-start gap-3 p-3.5 bg-red-50 border border-red-200 rounded-lg">
          <AlertTriangle className="size-4 text-red-500 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-red-800 mb-1">训练失败</p>
            <p className="text-xs text-red-700">{run.errorMessage}</p>
          </div>
        </div>
      )}

      {/* Progress bar for running */}
      {['queued', 'running'].includes(run.status) && (
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-gray-700">训练进度</span>
            <span className="text-xs tabular-nums text-gray-600">
              Epoch {run.currentEpoch} / {run.totalEpochs}
            </span>
          </div>
          <Progress value={(run.currentEpoch / Math.max(1, run.totalEpochs)) * 100} className="h-2" />
          <div className="flex items-center gap-4 mt-2">
            <span className="text-xs text-gray-500">{run.metricName}: <strong className="text-gray-800">{run.primaryMetric.toFixed(3)}</strong></span>
          </div>
        </div>
      )}

      {/* Metrics + Config */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <div className="xl:col-span-2 space-y-4 min-w-0">
          {run.metrics.length > 0 ? (
            <>
              <MetricChart
                data={run.metrics}
                title="Loss 曲线"
                lines={[
                  { key: 'trainLoss', color: '#3B82F6', label: 'Train Loss' },
                  { key: 'valLoss', color: '#EF4444', label: 'Val Loss' },
                ]}
              />
              <MetricChart
                data={run.metrics}
                title="mAP 曲线"
                lines={[
                  { key: 'mAP50', color: '#10B981', label: 'mAP50' },
                  { key: 'mAP5095', color: '#F59E0B', label: 'mAP50-95' },
                ]}
              />
            </>
          ) : (
            <div className="bg-white border border-gray-200 rounded-lg p-8 text-center text-sm text-gray-400">
              训练开始后将显示指标曲线
            </div>
          )}
        </div>

        <div className="space-y-4">
          {/* Summary metrics */}
          {run.primaryMetric > 0 && (
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <h3 className="text-xs font-medium text-gray-600 mb-3">最终指标</h3>
              <div className="space-y-2">
                {[
                  ['mAP50', run.primaryMetric.toFixed(3)],
                  ['mAP50-95', run.secondaryMetric.toFixed(3)],
                  ['Best Epoch', String(run.currentEpoch)],
                ].map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between text-xs">
                    <span className="text-gray-500">{k}</span>
                    <span className="font-semibold font-mono text-gray-900">{v}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Config */}
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <h3 className="text-xs font-medium text-gray-600 mb-3">训练参数</h3>
            <div className="space-y-1.5">
              {configEntries.map(([k, v]) => (
                <div key={k} className="flex items-center justify-between text-xs">
                  <span className="text-gray-500">{k}</span>
                  <span className="font-mono text-gray-800">{v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Logs */}
      <LogViewer logs={run.logs} />
    </div>
  );
}
