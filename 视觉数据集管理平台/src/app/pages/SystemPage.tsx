import { useState, useEffect } from 'react';
import { Wifi, WifiOff, Loader2, Plus, Trash2, RefreshCw, CheckCircle2, XCircle } from 'lucide-react';
import { listUsers, getSystemConfig, checkLabelStudioConnection, checkUnitTrainConnection, listAuditLogs } from '../../services/api';
import type { User, SystemConfig, AuditLog } from '../../types';
import { PageLoading } from '../components/shared/EmptyState';
import { Pagination } from '../components/shared/Pagination';
import { cn } from '../components/ui/utils';

const ROLE_LABEL: Record<string, string> = {
  admin: '管理员',
  data_engineer: '数据工程师',
  annotator: '审核员',
};

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

const TABS = ['用户管理', '访问目录', '服务连接', '审计日志'];

export default function SystemPage() {
  const [activeTab, setActiveTab] = useState(0);
  const [users, setUsers] = useState<User[]>([]);
  const [config, setConfig] = useState<SystemConfig | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditPage, setAuditPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [lsStatus, setLsStatus] = useState<string>('online');
  const [utStatus, setUtStatus] = useState<string>('online');
  const [lsChecking, setLsChecking] = useState(false);
  const [utChecking, setUtChecking] = useState(false);

  useEffect(() => {
    setLoading(true);
    Promise.all([listUsers(), getSystemConfig()]).then(([u, c]) => {
      setUsers(u);
      setConfig(c);
      setLsStatus(c.labelStudio.status);
      setUtStatus(c.unitTrain.status);
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    listAuditLogs({ page: auditPage, pageSize: 20 }).then(result => {
      setAuditLogs(result.data);
      setAuditTotal(result.meta.total);
    });
  }, [auditPage]);

  const checkLs = async () => {
    setLsChecking(true);
    setLsStatus('checking');
    try {
      const res = await checkLabelStudioConnection();
      setLsStatus(res.status);
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
    } catch {
      setUtStatus('offline');
    } finally {
      setUtChecking(false);
    }
  };

  const formatDate = (iso: string) => new Date(iso).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });

  if (loading) return <div className="p-6"><PageLoading /></div>;

  return (
    <div className="flex flex-col h-full">
      {/* Tab bar */}
      <div className="bg-white border-b border-gray-200 px-6 shrink-0">
        <div className="flex gap-0">
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

      <div className="flex-1 overflow-y-auto p-6">
        {/* Users */}
        {activeTab === 0 && (
          <div className="max-w-3xl space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-gray-700">用户列表</h3>
              <button className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-700">
                <Plus className="size-3.5" />添加用户
              </button>
            </div>
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50">
                    <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">用户</th>
                    <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500">角色</th>
                    <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500">状态</th>
                    <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500">最后登录</th>
                    <th className="w-8" />
                  </tr>
                </thead>
                <tbody>
                  {users.map(user => (
                    <tr key={user.id} className="border-b border-gray-100">
                      <td className="px-4 py-2.5">
                        <div className="text-sm text-gray-800">{user.name}</div>
                        <div className="text-xs text-gray-500">{user.email}</div>
                      </td>
                      <td className="px-3 py-2.5">
                        <span className={cn(
                          'text-xs px-1.5 py-0.5 rounded border',
                          user.role === 'admin' ? 'bg-purple-50 text-purple-700 border-purple-200' :
                          user.role === 'data_engineer' ? 'bg-blue-50 text-blue-700 border-blue-200' :
                          'bg-gray-100 text-gray-600 border-gray-200'
                        )}>
                          {ROLE_LABEL[user.role]}
                        </span>
                      </td>
                      <td className="px-3 py-2.5">
                        {user.isActive
                          ? <span className="flex items-center gap-1 text-xs text-green-600"><CheckCircle2 className="size-3.5" />活跃</span>
                          : <span className="flex items-center gap-1 text-xs text-gray-400"><XCircle className="size-3.5" />停用</span>
                        }
                      </td>
                      <td className="px-3 py-2.5 text-xs text-gray-500">{formatDate(user.lastLogin)}</td>
                      <td className="px-3 py-2.5">
                        <button className="size-6 flex items-center justify-center text-gray-400 hover:text-red-500 hover:bg-red-50 rounded transition-colors" title="停用用户">
                          <Trash2 className="size-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Allowed Roots */}
        {activeTab === 1 && (
          <div className="max-w-2xl space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-gray-700">允许访问的服务器根目录</h3>
              <button className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-700">
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
                    </div>
                    <code className="text-xs text-gray-600 font-mono mt-0.5 block">{root.path}</code>
                    <p className="text-xs text-gray-400 mt-0.5">{root.description}</p>
                  </div>
                  <button className="size-6 flex items-center justify-center text-gray-400 hover:text-red-500 rounded transition-colors" title="删除">
                    <Trash2 className="size-3.5" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Service Connections */}
        {activeTab === 2 && (
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
              <div className="grid grid-cols-2 gap-3 text-xs">
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
                  <code className="text-gray-400 font-mono">••••••••••••••••</code>
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
              <div className="grid grid-cols-2 gap-3 text-xs">
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
                  <code className="text-gray-400 font-mono">••••••••••••••••</code>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Audit Log */}
        {activeTab === 3 && (
          <div className="max-w-4xl space-y-4">
            <h3 className="text-sm font-medium text-gray-700">审计日志</h3>
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50">
                    <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">操作</th>
                    <th className="text-left px-3 py-2.5 text-xs font-medium text-gray-500 w-24">操作人</th>
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
                      <td className="px-3 py-2.5 text-xs text-gray-600">{log.userName}</td>
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
    </div>
  );
}
