import { useLocation } from 'react-router';
import { ChevronRight, Loader2 } from 'lucide-react';
import { useBackgroundTasks } from '../../hooks/useBackgroundTasks';

const breadcrumbMap: Record<string, string> = {
  datasets: '数据集',
  review: '审核任务',
  training: '训练任务',
  models: '模型',
  admin: '系统管理',
  guide: '使用手册',
  detail: '详情',
  new: '新建',
};

function getBreadcrumbs(pathname: string): { label: string; path: string }[] {
  const parts = pathname.split('/').filter(Boolean);
  const crumbs: { label: string; path: string }[] = [];
  let accumulated = '';
  for (const part of parts) {
    accumulated += `/${part}`;
    // skip UUIDs / IDs (long random-looking strings or ds-xxx, tr-xxx patterns)
    const isId = /^(ds|tr|rs|mdl|v)-/.test(part) || part.length > 20;
    const label = breadcrumbMap[part] ?? (isId ? '详情' : part);
    crumbs.push({ label, path: accumulated });
  }
  return crumbs;
}

export function TopBar() {
  const location = useLocation();
  const breadcrumbs = getBreadcrumbs(location.pathname);
  const { tasks } = useBackgroundTasks();
  const activeTasks = tasks.filter(t => t.status === 'running');

  return (
    <header className="h-12 bg-white border-b border-gray-200 flex items-center px-4 gap-3 shrink-0">
      {/* Breadcrumbs */}
      <nav className="flex items-center gap-1 flex-1 text-sm min-w-0">
        {breadcrumbs.map((crumb, i) => (
          <span key={crumb.path} className="flex items-center gap-1 min-w-0">
            {i > 0 && <ChevronRight className="size-3.5 text-gray-400 shrink-0" />}
            <span
              className={
                i === breadcrumbs.length - 1
                  ? 'text-gray-900 font-medium truncate'
                  : 'text-gray-500 truncate'
              }
            >
              {crumb.label}
            </span>
          </span>
        ))}
      </nav>

      {/* Background tasks indicator */}
      {activeTasks.length > 0 && (
        <div className="flex items-center gap-1.5 text-xs text-blue-600 bg-blue-50 px-2.5 py-1 rounded border border-blue-100">
          <Loader2 className="size-3.5 animate-spin" />
          <span>{activeTasks.length} 个后台任务</span>
        </div>
      )}
    </header>
  );
}
