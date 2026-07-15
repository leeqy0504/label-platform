import { useState } from 'react';
import { Copy, Check } from 'lucide-react';
import { cn } from '../ui/utils';

interface CopyButtonProps {
  text: string;
  className?: string;
}

export function CopyButton({ text, className }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // fallback
    }
  };

  return (
    <button
      onClick={handleCopy}
      title="复制"
      className={cn(
        'inline-flex items-center justify-center size-5 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors',
        className
      )}
    >
      {copied ? <Check className="size-3 text-green-600" /> : <Copy className="size-3" />}
    </button>
  );
}
