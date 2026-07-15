import { ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '../ui/utils';

interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onChange: (page: number) => void;
}

export function Pagination({ page, pageSize, total, onChange }: PaginationProps) {
  const totalPages = Math.ceil(total / pageSize);
  if (totalPages <= 1) return null;

  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);

  return (
    <div className="flex items-center justify-between px-3 py-2 border-t border-gray-100 bg-white">
      <span className="text-xs text-gray-500">
        显示 {start}–{end}，共 {total} 条
      </span>
      <div className="flex items-center gap-1">
        <button
          onClick={() => onChange(page - 1)}
          disabled={page <= 1}
          className={cn(
            'size-7 flex items-center justify-center rounded text-xs transition-colors',
            page <= 1 ? 'text-gray-300 cursor-not-allowed' : 'text-gray-600 hover:bg-gray-100'
          )}
        >
          <ChevronLeft className="size-4" />
        </button>
        {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
          let pageNum: number;
          if (totalPages <= 7) {
            pageNum = i + 1;
          } else if (page <= 4) {
            pageNum = i + 1;
          } else if (page >= totalPages - 3) {
            pageNum = totalPages - 6 + i;
          } else {
            pageNum = page - 3 + i;
          }
          return (
            <button
              key={pageNum}
              onClick={() => onChange(pageNum)}
              className={cn(
                'size-7 flex items-center justify-center rounded text-xs transition-colors',
                pageNum === page
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-600 hover:bg-gray-100'
              )}
            >
              {pageNum}
            </button>
          );
        })}
        <button
          onClick={() => onChange(page + 1)}
          disabled={page >= totalPages}
          className={cn(
            'size-7 flex items-center justify-center rounded text-xs transition-colors',
            page >= totalPages ? 'text-gray-300 cursor-not-allowed' : 'text-gray-600 hover:bg-gray-100'
          )}
        >
          <ChevronRight className="size-4" />
        </button>
      </div>
    </div>
  );
}
