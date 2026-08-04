import { FileJson2, FolderOpen, Layers3 } from 'lucide-react';
import type { Dataset, SourceFormat, TaskType } from '../../../types';
import { CopyButton } from '../shared/CopyButton';

const SOURCE_FORMAT_LABEL: Record<SourceFormat, string> = {
  image_directory: '图片目录',
  coco_detection: 'COCO Detection',
  coco_instance: 'COCO Instance Segmentation',
  label_studio: 'Label Studio 导出',
  yolo_detection: 'YOLO Detection',
};

const TASK_TYPE_LABEL: Record<TaskType, string> = {
  detection: '目标检测',
  instance_segmentation: '实例分割',
};

export function FormatSplitsTab({ dataset }: { dataset: Dataset }) {
  const total = dataset.trainCount + dataset.valCount + dataset.testCount;
  const splits = [
    { name: 'train', label: '训练集', count: dataset.trainCount, color: 'bg-blue-600' },
    { name: 'val', label: '验证集', count: dataset.valCount, color: 'bg-emerald-600' },
    { name: 'test', label: '测试集', count: dataset.testCount, color: 'bg-amber-500' },
  ];

  return (
    <div className="p-4 md:p-5 space-y-5 overflow-y-auto">
      <section className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100">
          <h3 className="text-sm font-medium text-gray-800">格式</h3>
        </div>
        <dl className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4">
          <FormatValue icon={FolderOpen} label="来源格式" value={dataset.sourceFormat ? SOURCE_FORMAT_LABEL[dataset.sourceFormat] : '—'} />
          <FormatValue icon={Layers3} label="任务类型" value={TASK_TYPE_LABEL[dataset.taskType]} />
          <FormatValue icon={FileJson2} label="规范格式" value="platform-dataset-v2" mono />
          <FormatValue icon={FileJson2} label="标注文件" value="annotations/instances.coco.json" mono />
        </dl>
        {dataset.rootPath && (
          <div className="flex items-center gap-2 px-4 py-3 border-t border-gray-100 text-xs">
            <span className="text-gray-500 shrink-0">来源路径</span>
            <code className="text-gray-700 truncate">{dataset.rootPath}</code>
            <CopyButton text={dataset.rootPath} />
          </div>
        )}
      </section>

      <section className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
          <h3 className="text-sm font-medium text-gray-800">数据划分</h3>
          <span className="text-xs text-gray-500 tabular-nums">共 {total.toLocaleString()} 个样本</span>
        </div>
        <div className="divide-y divide-gray-100">
          {splits.map(split => {
            const percent = total > 0 ? (split.count / total) * 100 : 0;
            return (
              <div key={split.name} className="grid grid-cols-[5rem_1fr_5rem] sm:grid-cols-[7rem_1fr_7rem] items-center gap-3 px-4 py-3">
                <div>
                  <p className="text-sm text-gray-800">{split.label}</p>
                  <code className="text-[11px] text-gray-400">{split.name}</code>
                </div>
                <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div className={`h-full ${split.color}`} style={{ width: `${percent}%` }} />
                </div>
                <div className="text-right">
                  <p className="text-sm font-medium text-gray-800 tabular-nums">{split.count.toLocaleString()}</p>
                  <p className="text-[11px] text-gray-400 tabular-nums">{percent.toFixed(1)}%</p>
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function FormatValue({
  icon: Icon,
  label,
  value,
  mono = false,
}: {
  icon: typeof FileJson2;
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-start gap-3 px-4 py-4 border-b sm:border-b-0 sm:border-r border-gray-100 last:border-r-0">
      <Icon className="size-4 text-gray-400 mt-0.5 shrink-0" />
      <div className="min-w-0">
        <dt className="text-xs text-gray-500">{label}</dt>
        <dd className={`mt-1 text-sm text-gray-800 truncate ${mono ? 'font-mono text-xs' : ''}`}>{value}</dd>
      </div>
    </div>
  );
}
