import { useState, useEffect } from 'react';
import { Wifi, WifiOff, Loader2, Plus, Power, RefreshCw } from 'lucide-react';
import {
  checkLabelStudioConnection,
  checkUnitTrainConnection,
  createAllowedRoot,
  getSystemConfig,
  listAuditLogs,
  updateAllowedRoot,
} from '../../services/api';
import type { SystemConfig, AuditLog } from '../../types';
import { PageLoading } from '../components/shared/EmptyState';
import { Pagination } from '../components/shared/Pagination';
import { cn } from '../components/ui/utils';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '../components/ui/dialog';

const RESOURCE_TYPE_LABEL: Record<string, string> = {
  dataset: '数据集',
  version: '版本',
  review: '审核任务',
  training: '训练任务',
  model: '模型',
  system: '系统',
};

function ConnectionStatus({ status }: { status: string }) {
  if (status === 'checking') return <Loader2 className="size-4 animate-spin text-gray-400" />;
  if (status === 'online') return (
    <span className="flex items-center gap-1 text-green-600 text-xs">
      <Wifi className="size-3.5" />在线
    </span>
  );
  return (
    <span className="flex items-center gap-1 text-red-600 text-xs">
      <WifiOff className="size-3.5" />离线
    </span>
  );
}

const TABS = ['访问目录', '服务连接', '审计日志'];

export default function SystemPage() {
  const [activeTab, setActiveTab] = useState(0);
  const [config, setConfig] = useState<SystemConfig | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditPage, setAuditPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [lsStatus, setLsStatus] = useState<string>('online');
  const [utStatus, setUtStatus] = useState<string>('online');
  const [lsChecking, setLsChecking] = useState(false);
  const [utChecking, setUtChecking] = useState(false);
  const [rootDialogOpen, setRootDialogOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [rootForm, setRootForm] = useState({ path: '', label: '', description: '' });

  useEffect(() => {
    setLoading(true);
    getSystemConfig()
      .then(c => {
        setConfig(c);
        setLsStatus(c.labelStudio.status);
        setUtStatus(c.unitTrain.status);
        void checkLabelStudioConnection().then(result => {
          setLsStatus(result.status);
          setConfig(current => current ? {
            ...current,
            labelStudio: { ...current.labelStudio, status: result.status, version: result.version },
          } : current);
        }).catch(() => setLsStatus('offline'));
        void checkUnitTrainConnection().then(result => {
          setUtStatus(result.status);
          setConfig(current => current ? {
            ...current,
            unitTrain: { ...current.unitTrain, status: result.status, version: result.version },
          } : current);
        }).catch(() => setUtStatus('offline'));
      })
      .catch(() => setActionError('系统配置加载失败'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    listAuditLogs({ page: auditPage, pageSize: 20 })
      .then(result => {
        setAuditLogs(result.data);
        setAuditTotal(result.meta.total);
      })
      .catch(() => setActionError('审计日志加载失败'));
  }, [auditPage]);

  const checkLs = async () => {
    setLsChecking(true);
    setLsStatus('checking');
    try {
      const res = await checkLabelStudioConnection();
      setLsStatus(res.status);
      setConfig(current => current ? {
        ...current,
        labelStudio: { ...current.labelStudio, status: res.status, version: res.version },
      } : current);
    } catch {
      setLsStatus('offline');
    } finally {
      setLsChecking(false);
    }
  };

  const checkUt = async () => {
    setUtChecking(true);
    setUtStatus('checking');
    try {
      const res = await checkUnitTrainConnection();
      setUtStatus(res.status);
      setConfig(current => current ? {
        ...current,
        unitTrain: { ...current.unitTrain, status: res.status, version: res.version },
      } : current);
    } catch {
      setUtStatus('offline');
    } finally {
      setUtChecking(false);
    }
  };

  const submitRoot = async () => {
    setActionLoading(true);
    setActionError(null);
    try {
      await createAllowedRoot(rootForm);
      setConfig(await getSystemConfig());
      setRootDialogOpen(false);
      setRootForm({ path: '', label: '', description: '' });
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '添加目录失败');
    } finally {
      setActionLoading(false);
    }
  };

  const toggleRoot = async (rootId: string, isActive: boolean) => {
    setActionError(null);
    try {
      await updateAllowedRoot(rootId, { is_active: !isActive });
      setConfig(await getSystemConfig());
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '更新目录失败');
    }
  };

  const formatDate = (iso: string) => iso
    ? new Date(iso).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
    : '—';

  if (loading) return <div className="p-6"><PageLoading /></div>;

  return (
    <div className="flex flex-col h-full">
      {/* Tab bar */}
      <div className="bg-white border-b border-gray-200 px-2 md:px-6 shrink-0 overflow-x-auto">
        <div className="flex gap-0 min-w-max">
          {TABS.map((tab, i) => (
            <button
              key={tab}
              onClick={() => setActiveTab(i)}
              className={cn(
                'px-4 py-3 text-sm border-b-2 transition-colors',
                activeTab === i
                  ? 'border-blue-600 text-blue-700 font-medium'
                  : 'border-transparent text-gray-600 hover:text-gray-900'
              )}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 md:p-6">
        {actionError && (
          <div role="alert" className="mb-4 max-w-3xl px-3 py-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded">
            {actionError}
          </div>
        )}
        {/* Allowed Roots */}
        {activeTab === 0 && (
          <div className="max-w-2xl space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-gray-700">允许访问的服务器根目录</h3>
              <button onClick={() => setRootDialogOpen(true)} className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-700">
                <Plus className="size-3.5" />添加目录
              </button>
            </div>
            <p className="text-xs text-gray-500">登记数据集时，用户只能从以下目录中选择数据，不能输入任意路径。</p>
            <div className="space-y-2">
              {config?.allowedRoots.map(root => (
                <div key={root.id} className="flex items-start justify-between p-3.5 bg-white border border-gray-200 rounded-lg">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-gray-800">{root.label}</span>
                      <span className={cn('text-[10px] px-1.5 py-0.5 rounded', root.isActive ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-500')}>
                        {root.isActive ? '启用' : '停用'}
                      </span>
                    </div>
                    <code className="text-xs text-gray-600 font-mono mt-0.5 block">{root.path}</code>
                    <p className="text-xs text-gray-400 mt-0.5">{root.description}</p>
                  </div>
                  <button onClick={() => toggleRoot(root.id, root.isActive)} className="size-6 flex items-center justify-center text-gray-400 hover:text-red-500 rounded transition-colors" title={root.isActive ? '停用目录' : '启用目录'}>
                    <Power className="size-3.5" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Service Connections */}
        {activeTab === 1 && (
          <div className="max-w-2xl space-y-4">
            {/* Label Studio */}
            <div className="bg-white border border-gray-200 rounded-lg p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-medium text-gray-800">Label Studio</h3>
                  <ConnectionStatus status={lsStatus} />
                </div>
                <button
                  onClick={checkLs}
                  disabled={lsChecking}
                  className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-gray-200 text-gray-700 hover:bg-gray-50 rounded disabled:opacity-50"
                >
                  <RefreshCw className={cn('size-3.5', lsChecking && 'animate-spin')} />
                  测试连接
                </button>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                <div>
                  <p className="text-gray-500 mb-1">服务地址</p>
                  <code className="text-gray-700 font-mono">{config?.labelStudio.url}</code>
                </div>
                <div>
                  <p className="text-gray-500 mb-1">版本</p>
                  <span className="text-gray-700">{config?.labelStudio.version}</span>
                </div>
                <div>
                  <p className="text-gray-500 mb-1">API Key</p>
                  <span className="text-gray-700">{config?.labelStudio.apiKeyConfigured ? '已配置' : '未配置'}</span>
                </div>
              </div>
            </div>

            {/* UnitTrain */}
            <div className="bg-white border border-gray-200 rounded-lg p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-medium text-gray-800">UnitTrain</h3>
                  <ConnectionStatus status={utStatus} />
                </div>
                <button
                  onClick={checkUt}
                  disabled={utChecking}
                  className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-gray-200 text-gray-700 hover:bg-gray-50 rounded disabled:opacity-50"
                >
                  <RefreshCw className={cn('size-3.5', utChecking && 'animate-spin')} />
                  测试连接
                </button>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                <div>
                  <p className="text-gray-500 mb-1">服务地址</p>
                  <code className="text-gray-700 font-mono">{config?.unitTrain.url}</code>
                </div>
                <div>
                  <p className="text-gray-500 mb-1">版本</p>
                  <span className="text-gray-700">{config?.unitTrain.version}</span>
                </div>
                <div>
                  <p className="text-gray-500 mb-1">API Key</p>
                  <span className="text-gray-700">{config?.unitTrain.apiKeyConfigured ? '已配置' : '未配置'}</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Audit Log */}
        {activeTab === 2 && (
          <div className="max-w-4xl space-y-4">
            <h3 className="text-sm font-medium text-gray-700">审计日志</h3>
            <div className="bg-white border border-gray-200 rounded-lg overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50">
                    <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">操作</th>
                    <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-16">资源类型</th>
                    <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500">资源名称</th>
                    <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-32">时间</th>
                  </tr>
                </thead>
                <tbody>
                  {auditLogs.map(log => (
                    <tr key={log.id} className="border-b border-gray-100">
                      <td className="px-4 py-2.5">
                        <div className="text-xs font-medium text-gray-800">{log.action}</div>
                        <div className="text-xs text-gray-500 mt-0.5">{log.details}</div>
                      </td>
                      <td className="px-3 py-2.5">
                        <span className="text-xs px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded">
                          {RESOURCE_TYPE_LABEL[log.resourceType] ?? log.resourceType}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-xs font-mono text-gray-700 truncate max-w-48">
                        {log.resourceName}
                      </td>
                      <td className="px-3 py-2.5 text-xs text-gray-500">{formatDate(log.timestamp)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Pagination page={auditPage} pageSize={20} total={auditTotal} onChange={setAuditPage} />
            </div>
          </div>
        )}
      </div>

      <Dialog open={rootDialogOpen} onOpenChange={setRootDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>添加来源目录</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <input value={rootForm.label} onChange={event => setRootForm(form => ({ ...form, label: event.target.value }))} placeholder="显示名称" className="w-full h-9 px-3 text-sm border border-gray-200 rounded" />
            <input value={rootForm.path} onChange={event => setRootForm(form => ({ ...form, path: event.target.value }))} placeholder="服务器绝对路径" className="w-full h-9 px-3 text-sm font-mono border border-gray-200 rounded" />
            <textarea value={rootForm.description} onChange={event => setRootForm(form => ({ ...form, description: event.target.value }))} placeholder="说明（可选）" rows={3} className="w-full px-3 py-2 text-sm border border-gray-200 rounded resize-none" />
          </div>
          <DialogFooter>
            <button onClick={() => setRootDialogOpen(false)} className="px-3 py-1.5 text-sm text-gray-600">取消</button>
            <button onClick={submitRoot} disabled={actionLoading || !rootForm.label || !rootForm.path} className="px-3 py-1.5 text-sm text-white bg-blue-600 rounded disabled:opacity-40">添加</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
