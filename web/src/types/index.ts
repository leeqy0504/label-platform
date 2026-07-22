export type DatasetStatus =
  | 'scanning'
  | 'pending_annotation'
  | 'reviewing'
  | 'trainable'
  | 'validation_failed'
  | 'archived';

export type TrainingStatus = 'queued' | 'running' | 'completed' | 'failed' | 'stopped';
export type ReviewStatus =
  | 'creating'
  | 'importing'
  | 'ready'
  | 'in_review'
  | 'exporting'
  | 'completed'
  | 'failed';
export type TaskType = 'detection' | 'instance_segmentation';
export type SourceFormat = 'image_directory' | 'coco_detection' | 'coco_instance' | 'label_studio';
export type SplitType = 'train' | 'val' | 'test';
export type AnnotationStatus = 'annotated' | 'unannotated' | 'partial';
export type ConnectionStatus = 'online' | 'offline' | 'checking';

export interface Category {
  id: number;
  name: string;
  supercategory: string;
  count: number;
  color?: string;
}

export interface DatasetVersion {
  id: string;
  version: string;
  parentVersion: string | null;
  source: 'initial_import' | 'review_export' | 'manual';
  imageCount: number;
  annotationCount: number;
  categorySchema: Category[];
  createdAt: string;
  reviewSessionId: string | null;
  trainingCount: number;
  isImmutable: boolean;
  notes: string;
  cocoFilePath: string;
}

export interface MediaFile {
  id: string;
  filename: string;
  path: string;
  split: SplitType;
  width: number;
  height: number;
  size: number;
  checksum: string;
  annotationCount: number;
  hasMask: boolean;
  hasBbox: boolean;
  hasAnomaly: boolean;
  thumbnailUrl: string;
  annotationStatus: AnnotationStatus;
  category: string;
}

export interface Dataset {
  id: string;
  name: string;
  description: string;
  currentVersion: string;
  mediaCount: number;
  categoryCount: number;
  annotationCount: number;
  status: DatasetStatus;
  updatedAt: string;
  createdAt: string;
  rootPath: string;
  categories: Category[];
  versions: DatasetVersion[];
  totalSize: number;
  trainCount: number;
  valCount: number;
  testCount: number;
  currentVersionId: string | null;
  taskType: TaskType;
  sourceFormat: SourceFormat | null;
  validationResult: {
    valid?: boolean;
    errors?: Array<{ code: string; path?: string; message: string }>;
  };
}

export interface ReviewSession {
  id: string;
  datasetId: string;
  datasetName: string;
  inputVersionId: string;
  inputVersion: string;
  labelStudioProjectId: number | null;
  labelStudioProjectUrl: string;
  totalTasks: number;
  completedTasks: number;
  skippedTasks: number;
  status: ReviewStatus;
  startedAt: string | null;
  completedAt: string | null;
  outputVersion: string | null;
  exportProgress?: ExportProgress;
  jobId: string | null;
  errorSummary: { code?: string; message?: string };
  jobStage?: string;
  jobProcessed?: number;
  jobTotal?: number;
}

export interface ExportProgress {
  stage: 'exporting' | 'extracting' | 'converting' | 'validating' | 'publishing' | 'done';
  percent: number;
  message: string;
}

export interface MetricPoint {
  epoch: number;
  trainLoss: number;
  valLoss: number;
  mAP50: number;
  mAP5095: number;
  lr: number;
}

export interface TrainingConfig {
  framework: string;
  model: string;
  batchSize: number;
  learningRate: number;
  imageSize: number;
  device: number | string;
  gradAccumSteps: number;
  earlyStopping: boolean;
}

export interface TrainingRun {
  id: string;
  name: string;
  datasetId: string;
  datasetName: string;
  datasetVersion: string;
  taskType: TaskType;
  status: TrainingStatus;
  currentEpoch: number;
  totalEpochs: number;
  primaryMetric: number;
  secondaryMetric: number;
  metricName: string;
  startedAt: string;
  completedAt: string | null;
  durationSeconds: number;
  config: TrainingConfig;
  logs: string[];
  metrics: MetricPoint[];
  outputModelId: string | null;
  errorMessage: string | null;
  unitTrainRunUrl: string;
  unitTrainRunId: string | null;
  jobId: string | null;
}

export interface CategoryAP {
  category: string;
  ap50: number;
  ap5095: number;
  count: number;
}

export interface Model {
  id: string;
  name: string;
  trainingRunId: string;
  datasetId: string;
  datasetName: string;
  datasetVersion: string;
  taskType: TaskType;
  framework: string;
  mAP50: number;
  mAP5095: number;
  precision: number;
  recall: number;
  fileSize: number;
  filePath: string;
  createdAt: string;
  categories: string[];
  categoryAP: CategoryAP[];
  evaluationFiles: Array<{ name: string; url: string }>;
}

export interface AllowedRoot {
  id: string;
  path: string;
  label: string;
  description: string;
  isActive: boolean;
}

export interface AuditLog {
  id: string;
  action: string;
  resourceType: string;
  resourceId: string;
  resourceName: string;
  timestamp: string;
  details: string;
}

export interface SystemConfig {
  allowedRoots: AllowedRoot[];
  labelStudio: {
    url: string;
    version: string;
    status: ConnectionStatus;
    apiKeyConfigured: boolean;
  };
  unitTrain: {
    url: string;
    version: string;
    status: ConnectionStatus;
    apiKeyConfigured: boolean;
  };
}

export interface FileTreeNode {
  name: string;
  path: string;
  type: 'dir' | 'file';
  children?: FileTreeNode[];
  fileCount?: number;
}

export interface ScanPreview {
  imageCount: number;
  videoCount: number;
  cocoFiles: string[];
  totalSizeMB: number;
  anomalies: string[];
  progress: number;
  isComplete: boolean;
}

export interface PageMeta {
  page: number;
  pageSize: number;
  total: number;
}

export interface ListResponse<T> {
  data: T[];
  meta: PageMeta;
}

export type JobStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled';

export interface AnalysisResult {
  valid: boolean;
  source_format: 'image_directory' | 'coco_detection' | 'coco_instance' | 'label_studio' | null;
  task_type: TaskType | null;
  image_count: number;
  annotation_count: number;
  categories: string[];
  split_counts: Record<SplitType, number>;
  unsupported_files: string[];
  errors: Array<{ code: string; path: string; message: string }>;
  fingerprint: string | null;
}

export interface BackgroundJob<T = Record<string, unknown>> {
  id: string;
  business_object_id: string | null;
  job_type: string;
  status: JobStatus;
  stage: string;
  processed_count: number;
  total_count: number;
  result: T;
  error_summary: { code?: string; message?: string };
  retry_count: number;
  log_path: string | null;
}

export interface SourceSelectionInput {
  source_root_id: string;
  relative_path: string;
  categories: string[];
  task_type: TaskType;
  split: { train: number; val: number; test: number; seed: number };
  idempotency_key: string;
}

export interface DatasetRegistrationInput extends SourceSelectionInput {
  name: string;
  description: string;
  analysis_fingerprint: string;
}
