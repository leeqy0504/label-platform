import type { LucideIcon } from 'lucide-react';
import { Inbox, AlertCircle, Wifi, SearchX } from 'lucide-react';
import { cn } from '../ui/utils';

interface EmptyStateProps {
  type?: 'empty' | 'error' | 'offline' | 'no-results';
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

const defaultIcons: Record<string, LucideIcon> = {
  empty: Inbox,
  error: AlertCircle,
  offline: Wifi,
  'no-results': SearchX,
};

export function EmptyState({ type = 'empty', icon: IconProp, title, description, action, className }: EmptyStateProps) {
  const Icon = IconProp ?? defaultIcons[type];
  const iconColorClass = type === 'error' ? 'text-red-400' : type === 'offline' ? 'text-amber-400' : 'text-gray-300';

  return (
    <div className={cn('flex flex-col items-center justify-center py-16 px-4 text-center', className)}>
      <Icon className={cn('size-10 mb-3', iconColorClass)} />
      <p className="text-sm font-medium text-gray-700 mb-1">{title}</p>
      {description && <p className="text-xs text-gray-500 max-w-sm">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function LoadingRows({ rows = 5, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, i) => (
        <tr key={i} className="border-b border-gray-100">
          {Array.from({ length: cols }, (_, j) => (
            <td key={j} className="px-3 py-2.5">
              <div className={cn('h-4 bg-gray-100 rounded animate-pulse', j === 0 ? 'w-32' : j === cols - 1 ? 'w-16' : 'w-24')} />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

export function PageLoading() {
  return (
    <div className="flex items-center justify-center h-48">
      <div className="flex gap-1">
        {[0, 1, 2].map(i => (
          <div
            key={i}
            className="size-2 bg-blue-400 rounded-full animate-bounce"
            style={{ animationDelay: `${i * 0.1}s` }}
          />
        ))}
      </div>
    </div>
  );
}
