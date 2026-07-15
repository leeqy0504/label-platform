import { cn } from '../ui/utils';
import type { DatasetStatus, TrainingStatus, ReviewStatus } from '../../../types';

type Status = DatasetStatus | TrainingStatus | ReviewStatus | string;

const statusConfig: Record<string, { label: string; className: string }> = {
  // Dataset
  scanning: { label: '扫描中', className: 'bg-blue-50 text-blue-700 border-blue-200' },
  pending_annotation: { label: '待标注', className: 'bg-gray-100 text-gray-600 border-gray-200' },
  reviewing: { label: '审核中', className: 'bg-amber-50 text-amber-700 border-amber-200' },
  trainable: { label: '可训练', className: 'bg-green-50 text-green-700 border-green-200' },
  validation_failed: { label: '校验失败', className: 'bg-red-50 text-red-700 border-red-200' },
  archived: { label: '已归档', className: 'bg-gray-100 text-gray-500 border-gray-200' },
  // Training
  queued: { label: '排队中', className: 'bg-gray-100 text-gray-600 border-gray-200' },
  running: { label: '运行中', className: 'bg-blue-50 text-blue-700 border-blue-200' },
  completed: { label: '已完成', className: 'bg-green-50 text-green-700 border-green-200' },
  failed: { label: '失败', className: 'bg-red-50 text-red-700 border-red-200' },
  stopped: { label: '已停止', className: 'bg-gray-100 text-gray-500 border-gray-200' },
  // Review
  active: { label: '进行中', className: 'bg-blue-50 text-blue-700 border-blue-200' },
  exporting: { label: '导出中', className: 'bg-amber-50 text-amber-700 border-amber-200' },
};

interface StatusBadgeProps {
  status: Status;
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const config = statusConfig[status] ?? { label: status, className: 'bg-gray-100 text-gray-600 border-gray-200' };
  return (
    <span
      className={cn(
        'inline-flex items-center px-1.5 py-0.5 rounded text-xs border',
        config.className,
        className
      )}
    >
      {config.label}
    </span>
  );
}

export function statusLabel(status: Status): string {
  return statusConfig[status]?.label ?? status;
}
