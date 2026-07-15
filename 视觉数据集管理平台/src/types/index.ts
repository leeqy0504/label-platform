export type DatasetStatus =
  | 'scanning'
  | 'pending_annotation'
  | 'reviewing'
  | 'trainable'
  | 'validation_failed'
  | 'archived';

export type TrainingStatus = 'queued' | 'running' | 'completed' | 'failed' | 'stopped';
export type ReviewStatus = 'active' | 'completed' | 'exporting' | 'failed';
export type UserRole = 'admin' | 'data_engineer' | 'annotator';
export type TaskType = 'detection' | 'instance_segmentation';
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
  createdBy: string;
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
  createdBy: string;
  rootPath: string;
  categories: Category[];
  versions: DatasetVersion[];
  totalSize: number;
  trainCount: number;
  valCount: number;
  testCount: number;
}

export interface ReviewSession {
  id: string;
  datasetId: string;
  datasetName: string;
  inputVersion: string;
  labelStudioProjectId: number;
  labelStudioProjectUrl: string;
  totalTasks: number;
  completedTasks: number;
  skippedTasks: number;
  status: ReviewStatus;
  createdBy: string;
  startedAt: string;
  completedAt: string | null;
  outputVersion: string | null;
  exportProgress?: ExportProgress;
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
  model: string;
  batchSize: number;
  learningRate: number;
  optimizer: string;
  imageSize: number;
  augmentation: boolean;
  trainSplit: number;
  valSplit: number;
  warmupEpochs: number;
  weightDecay: number;
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
  metricName: string;
  startedBy: string;
  startedAt: string;
  completedAt: string | null;
  durationSeconds: number;
  config: TrainingConfig;
  logs: string[];
  metrics: MetricPoint[];
  outputModelId: string | null;
  errorMessage: string | null;
  gpuUtil: number;
  gpuMem: number;
  unitTrainRunUrl: string;
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
  mAP50: number;
  mAP5095: number;
  precision: number;
  recall: number;
  fileSize: number;
  filePath: string;
  createdAt: string;
  createdBy: string;
  categories: string[];
  categoryAP: CategoryAP[];
}

export interface User {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  createdAt: string;
  lastLogin: string;
  isActive: boolean;
}

export interface AllowedRoot {
  id: string;
  path: string;
  label: string;
  description: string;
}

export interface AuditLog {
  id: string;
  action: string;
  userId: string;
  userName: string;
  resourceType: 'dataset' | 'version' | 'review' | 'training' | 'model' | 'system';
  resourceId: string;
  resourceName: string;
  timestamp: string;
  details: string;
  ipAddress: string;
}

export interface SystemConfig {
  allowedRoots: AllowedRoot[];
  labelStudio: {
    url: string;
    version: string;
    status: ConnectionStatus;
    apiKey: string;
  };
  unitTrain: {
    url: string;
    version: string;
    status: ConnectionStatus;
    apiKey: string;
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
