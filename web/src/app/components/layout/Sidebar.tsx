import { NavLink, useLocation } from 'react-router';
import {
  Database,
  ClipboardCheck,
  Play,
  Box,
  Settings,
  BookOpen,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { cn } from '../ui/utils';

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

const navItems = [
  { to: '/datasets', icon: Database, label: '数据集' },
  { to: '/review', icon: ClipboardCheck, label: '审核任务' },
  { to: '/training', icon: Play, label: '训练任务' },
  { to: '/models', icon: Box, label: '模型' },
  { to: '/admin', icon: Settings, label: '系统管理' },
  { to: '/guide', icon: BookOpen, label: '使用手册' },
];

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const location = useLocation();

  return (
    <aside
      className={cn(
        'flex flex-col bg-white border-r border-gray-200 transition-all duration-200 shrink-0 h-full',
        collapsed ? 'w-14' : 'w-56'
      )}
    >
      {/* Logo */}
      <div className={cn('flex items-center h-12 px-3 border-b border-gray-200 shrink-0', collapsed ? 'justify-center' : 'gap-2')}>
        <div className="size-6 bg-blue-600 rounded flex items-center justify-center shrink-0">
          <Database className="size-3.5 text-white" />
        </div>
        {!collapsed && (
          <span className="text-sm font-semibold text-gray-900 truncate">数据集平台</span>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 py-2 overflow-y-auto">
        {navItems.map(({ to, icon: Icon, label }) => {
          const isActive = location.pathname.startsWith(to);
          return (
            <NavLink
              key={to}
              to={to}
              title={collapsed ? label : undefined}
              className={cn(
                'flex items-center gap-2.5 mx-1.5 my-0.5 px-2.5 py-2 rounded text-sm transition-colors',
                isActive
                  ? 'bg-blue-50 text-blue-700 font-medium'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900',
                collapsed && 'justify-center px-0'
              )}
            >
              <Icon className="size-4 shrink-0" />
              {!collapsed && <span className="truncate">{label}</span>}
            </NavLink>
          );
        })}
      </nav>

      {/* Collapse toggle */}
      <div className="shrink-0 border-t border-gray-200 p-2">
        <button
          onClick={onToggle}
          title={collapsed ? '展开侧边栏' : '收起侧边栏'}
          className={cn(
            'w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors',
            collapsed && 'justify-center'
          )}
        >
          {collapsed ? <ChevronRight className="size-4" /> : (
            <>
              <ChevronLeft className="size-4" />
              <span>收起</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}
