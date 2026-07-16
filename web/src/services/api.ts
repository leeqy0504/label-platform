import { request } from './http';
import type {
  AllowedRoot,
  AnalysisResult,
  AuditLog,
  BackgroundJob,
  Category,
  Dataset,
  DatasetRegistrationInput,
  DatasetStatus,
  DatasetVersion,
  FileTreeNode,
  ListResponse,
  MediaFile,
  Model,
  ReviewSession,
  SourceSelectionInput,
  SystemConfig,
  TrainingRun,
  TrainingStatus,
  User,
} from '../types';

interface ApiMeta { page: number; page_size: number; total: number }
interface ApiList<T> { data: T[]; meta: ApiMeta }

interface ApiDataset {
  id: string;
  name: string;
  description: string;
  status: DatasetStatus;
  created_at: string;
  updated_at: string;
  created_by: string;
  current_version: number | null;
  current_version_id: string | null;
  item_count: number;
  annotation_count: number;
  category_count: number;
  class_schema: Array<{ id: number; name: string; supercategory?: string }>;
  category_counts: Record<string, number>;
  split_counts: { train: number; val: number; test: number };
  total_size: number;
  sources?: Array<{
    id: string;
    source_root_id: string;
    relative_path: string;
    source_format: Dataset['sourceFormat'];
    task_type: 'detection' | 'instance_segmentation';
    scan_status: string;
  }>;
}

interface ApiVersion {
  id: string;
  version_number: number;
  parent_id: string | null;
  review_session_id: string | null;
  status: 'building' | 'validating' | 'ready' | 'invalid';
  class_schema: Array<{ id: number; name: string }>;
  category_counts: Record<string, number>;
  item_count: number;
  annotation_count: number;
  training_count?: number;
  validation_result: Dataset['validationResult'];
  created_by: string | null;
  created_at: string;
}

interface ApiItem {
  id: string;
  sample_key: string;
  relative_path: string;
  media_type: string;
  width: number;
  height: number;
  file_size: number;
  sha256: string;
  split: 'train' | 'val' | 'test';
  status: 'annotated' | 'unannotated' | 'partial';
  annotation_count: number;
  group_key: string | null;
}

interface JobAccepted { job_id: string; status: BackgroundJob['status'] }

interface ApiReview {
  id: string;
  dataset_id: string;
  dataset_name: string;
  input_version_id: string;
  input_version_number: number;
  output_version_id: string | null;
  output_version_number: number | null;
  label_studio_project_id: number | null;
  label_studio_project_url: string | null;
  total_tasks: number;
  completed_tasks: number;
  skipped_tasks: number;
  status: ReviewSession['status'];
  error_summary: ReviewSession['errorSummary'];
  created_by: string;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  job_id: string | null;
}

interface ApiTrainingRun {
  id: string;
  name: string;
  dataset_id: string;
  dataset_name: string;
  dataset_version_id: string;
  dataset_version_number: number;
  task_type: TrainingRun['taskType'];
  status: TrainingStatus;
  unitrain_run_id: string | null;
  current_epoch: number;
  total_epochs: number;
  metric_summary: Record<string, number>;
  config: {
    framework: string;
    model: string;
    epochs: number;
    batch_size: number;
    learning_rate: number;
    image_size: number;
    device: number | string;
    grad_accum_steps: number;
    early_stopping: boolean;
    early_stopping_patience: number;
    early_stopping_min_delta: number;
    skip_evaluation: boolean;
  };
  external_detail_url: string | null;
  error_summary: { code?: string; message?: string };
  created_by: string;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  job_id: string | null;
}

interface ApiTrainingMetrics {
  run_id: string;
  summary: Record<string, number>;
  history: Array<Record<string, unknown>>;
  evaluation: Record<string, unknown>;
}

interface ApiTrainingLogs {
  run_id: string;
  offset: number;
  next_offset: number;
  lines: string[];
  truncated: boolean;
}

interface ApiModel {
  id: string;
  name: string;
  training_run_id: string;
  unitrain_run_id: string;
  dataset_id: string;
  dataset_name: string;
  dataset_version_id: string;
  dataset_version_number: number;
  task_type: Model['taskType'];
  framework: string;
  metrics: Record<string, number>;
  category_metrics: Array<Record<string, unknown>>;
  categories: string[];
  file_size: number;
  file_path: string;
  evaluation_files: string[];
  evaluation_links: Array<{ name: string; url: string }>;
  created_at: string;
  created_by: string;
}

const categoryColors = ['#2563EB', '#059669', '#D97706', '#DC2626', '#7C3AED', '#0891B2'];

function pageMeta(meta: ApiMeta) {
  return { page: meta.page, pageSize: meta.page_size, total: meta.total };
}

function mapCategories(
  schema: ApiDataset['class_schema'],
  counts: Record<string, number>,
): Category[] {
  return schema.map((category, index) => ({
    ...category,
    supercategory: category.supercategory ?? '',
    count: counts[String(category.id)] ?? 0,
    color: categoryColors[index % categoryColors.length],
  }));
}

function mapVersion(version: ApiVersion, versions: ApiVersion[]): DatasetVersion {
  const parent = versions.find(candidate => candidate.id === version.parent_id);
  return {
    id: version.id,
    version: `v${version.version_number}`,
    parentVersion: parent ? `v${parent.version_number}` : null,
    source: version.version_number === 1
      ? 'initial_import'
      : version.review_session_id
        ? 'review_export'
        : 'manual',
    imageCount: version.item_count,
    annotationCount: version.annotation_count,
    categorySchema: mapCategories(version.class_schema, version.category_counts),
    createdAt: version.created_at,
    createdBy: version.created_by ?? '—',
    reviewSessionId: version.review_session_id,
    trainingCount: version.training_count ?? 0,
    isImmutable: version.status === 'ready',
    notes: version.status === 'invalid' ? '版本校验失败' : '',
    cocoFilePath: version.status === 'ready' ? 'annotations/instances.coco.json' : '',
  };
}

function mapDataset(dataset: ApiDataset, versions: ApiVersion[] = []): Dataset {
  const current = versions.find(version => version.id === dataset.current_version_id) ?? versions[0];
  return {
    id: dataset.id,
    name: dataset.name,
    description: dataset.description,
    currentVersion: dataset.current_version ? `v${dataset.current_version}` : '',
    currentVersionId: dataset.current_version_id,
    mediaCount: dataset.item_count,
    categoryCount: dataset.category_count,
    annotationCount: dataset.annotation_count,
    status: dataset.status,
    updatedAt: dataset.updated_at,
    createdAt: dataset.created_at,
    createdBy: dataset.created_by,
    rootPath: dataset.sources?.[0]?.relative_path ?? '',
    categories: mapCategories(dataset.class_schema, dataset.category_counts),
    versions: versions.map(version => mapVersion(version, versions)),
    totalSize: dataset.total_size / 1024 / 1024,
    trainCount: dataset.split_counts.train,
    valCount: dataset.split_counts.val,
    testCount: dataset.split_counts.test,
    taskType: dataset.sources?.[0]?.task_type ?? 'detection',
    sourceFormat: dataset.sources?.[0]?.source_format ?? null,
    validationResult: current?.validation_result ?? {},
  };
}

function mapReview(review: ApiReview): ReviewSession {
  return {
    id: review.id,
    datasetId: review.dataset_id,
    datasetName: review.dataset_name,
    inputVersionId: review.input_version_id,
    inputVersion: `v${review.input_version_number}`,
    labelStudioProjectId: review.label_studio_project_id,
    labelStudioProjectUrl: review.label_studio_project_url ?? '',
    totalTasks: review.total_tasks,
    completedTasks: review.completed_tasks,
    skippedTasks: review.skipped_tasks,
    status: review.status,
    createdBy: review.created_by,
    startedAt: review.started_at,
    completedAt: review.completed_at,
    outputVersion: review.output_version_number ? `v${review.output_version_number}` : null,
    jobId: review.job_id,
    errorSummary: review.error_summary,
  };
}

function numericMetric(values: Record<string, number>, ...keys: string[]): number {
  for (const key of keys) {
    const value = values[key];
    if (Number.isFinite(value)) return value;
  }
  return 0;
}

function historyNumber(item: Record<string, unknown>, ...keys: string[]): number {
  for (const key of keys) {
    const value = item[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string' && Number.isFinite(Number(value))) return Number(value);
  }
  return 0;
}

function mapMetricHistory(history: ApiTrainingMetrics['history']): TrainingRun['metrics'] {
  return history.map((item, index) => ({
    epoch: historyNumber(item, 'epoch', 'Epoch') || index + 1,
    trainLoss: historyNumber(item, 'train_loss', 'train/box_loss', 'train/loss', 'loss'),
    valLoss: historyNumber(item, 'val_loss', 'val/box_loss', 'validation_loss'),
    mAP50: historyNumber(item, 'mAP50', 'map50', 'metrics/mAP50(B)', 'val/mAP_50'),
    mAP5095: historyNumber(item, 'mAP50_95', 'map', 'metrics/mAP50-95(B)', 'val/mAP_50_95'),
    lr: historyNumber(item, 'lr', 'learning_rate', 'lr/pg0'),
  }));
}

function mapTrainingRun(
  run: ApiTrainingRun,
  metrics?: ApiTrainingMetrics,
  logs: string[] = [],
): TrainingRun {
  const summary = metrics?.summary ?? run.metric_summary;
  const startedAt = run.started_at ?? run.created_at;
  const end = run.completed_at ? new Date(run.completed_at).getTime() : Date.now();
  const start = new Date(startedAt).getTime();
  return {
    id: run.id,
    name: run.name,
    datasetId: run.dataset_id,
    datasetName: run.dataset_name,
    datasetVersion: `v${run.dataset_version_number}`,
    taskType: run.task_type,
    status: run.status,
    currentEpoch: run.current_epoch,
    totalEpochs: run.total_epochs,
    primaryMetric: numericMetric(summary, 'mAP50', 'map50', 'mask_mAP50'),
    secondaryMetric: numericMetric(summary, 'mAP50_95', 'map', 'mask_mAP50_95'),
    metricName: 'mAP50',
    startedBy: run.created_by,
    startedAt,
    completedAt: run.completed_at,
    durationSeconds: Number.isFinite(start) ? Math.max(0, Math.floor((end - start) / 1000)) : 0,
    config: {
      framework: run.config.framework,
      model: run.config.model,
      batchSize: run.config.batch_size,
      learningRate: run.config.learning_rate,
      imageSize: run.config.image_size,
      device: run.config.device,
      gradAccumSteps: run.config.grad_accum_steps,
      earlyStopping: run.config.early_stopping,
    },
    logs,
    metrics: mapMetricHistory(metrics?.history ?? []),
    outputModelId: null,
    errorMessage: run.error_summary.message ?? null,
    unitTrainRunUrl: run.external_detail_url ?? '',
    unitTrainRunId: run.unitrain_run_id,
    jobId: run.job_id,
  };
}

function mapModel(model: ApiModel): Model {
  const metric = (item: Record<string, unknown>, ...keys: string[]) => {
    for (const key of keys) {
      const value = item[key];
      if (typeof value === 'number' && Number.isFinite(value)) return value;
    }
    return 0;
  };
  return {
    id: model.id,
    name: model.name,
    trainingRunId: model.training_run_id,
    datasetId: model.dataset_id,
    datasetName: model.dataset_name,
    datasetVersion: `v${model.dataset_version_number}`,
    taskType: model.task_type,
    framework: model.framework,
    mAP50: numericMetric(model.metrics, 'mAP50', 'map50', 'mask_mAP50'),
    mAP5095: numericMetric(model.metrics, 'mAP50_95', 'map', 'mask_mAP50_95'),
    precision: numericMetric(model.metrics, 'precision', 'mask_precision'),
    recall: numericMetric(model.metrics, 'recall', 'mask_recall'),
    fileSize: model.file_size / 1024 / 1024,
    filePath: model.file_path,
    createdAt: model.created_at,
    createdBy: model.created_by,
    categories: model.categories,
    categoryAP: model.category_metrics.map(item => ({
      category: String(item.category ?? item.class_name ?? item.name ?? 'unknown'),
      ap50: metric(item, 'mAP50', 'ap50', 'map@50'),
      ap5095: metric(item, 'mAP50_95', 'ap5095', 'map@50:95'),
      count: metric(item, 'count', 'samples'),
    })),
    evaluationFiles: model.evaluation_links,
  };
}

export async function listDatasets(params?: {
  search?: string;
  status?: DatasetStatus | '';
  page?: number;
  pageSize?: number;
}): Promise<ListResponse<Dataset>> {
  const query = new URLSearchParams({
    page: String(params?.page ?? 1),
    page_size: String(params?.pageSize ?? 20),
  });
  if (params?.search) query.set('search', params.search);
  if (params?.status) query.set('status', params.status);
  const result = await request<ApiList<ApiDataset>>(`/api/datasets?${query}`);
  return { data: result.data.map(dataset => mapDataset(dataset)), meta: pageMeta(result.meta) };
}

export async function getDataset(id: string): Promise<Dataset> {
  const [dataset, versionResult] = await Promise.all([
    request<ApiDataset>(`/api/datasets/${id}`),
    request<ApiList<ApiVersion>>(`/api/datasets/${id}/versions`),
  ]);
  return mapDataset(dataset, versionResult.data);
}

export async function archiveDataset(id: string): Promise<void> {
  await request(`/api/datasets/${id}/archive`, { method: 'POST' });
}

export async function listMediaFiles(
  datasetId: string,
  params?: {
    search?: string;
    split?: string;
    annotationStatus?: string;
    page?: number;
    pageSize?: number;
  },
): Promise<ListResponse<MediaFile>> {
  const dataset = await request<ApiDataset>(`/api/datasets/${datasetId}`);
  if (!dataset.current_version_id) {
    return { data: [], meta: { page: 1, pageSize: params?.pageSize ?? 20, total: 0 } };
  }
  const query = new URLSearchParams({
    page: String(params?.page ?? 1),
    page_size: String(params?.pageSize ?? 20),
  });
  if (params?.search) query.set('search', params.search);
  if (params?.split) query.set('split', params.split);
  if (params?.annotationStatus) query.set('annotation_status', params.annotationStatus);
  const versionId = dataset.current_version_id;
  const response = await request<ApiList<ApiItem>>(
    `/api/datasets/${datasetId}/versions/${versionId}/items?${query}`,
  );
  const data = response.data.map<MediaFile>(item => ({
    id: item.id,
    filename: item.relative_path.split('/').at(-1) ?? item.relative_path,
    path: item.relative_path,
    split: item.split,
    width: item.width,
    height: item.height,
    size: item.file_size,
    checksum: item.sha256,
    annotationCount: item.annotation_count,
    hasMask: dataset.sources?.[0]?.task_type === 'instance_segmentation' && item.status === 'annotated',
    hasBbox: dataset.sources?.[0]?.task_type === 'detection' && item.status === 'annotated',
    hasAnomaly: false,
    thumbnailUrl: `/api/datasets/${datasetId}/versions/${versionId}/items/${item.id}/media`,
    annotationStatus: item.status,
    category: '',
  }));
  return { data, meta: pageMeta(response.meta) };
}

export async function listAllowedRoots(): Promise<AllowedRoot[]> {
  const roots = await request<Array<{
    id: string; path: string; label: string; description: string; is_active: boolean;
  }>>('/api/source-roots');
  return roots.map(root => ({
    id: root.id,
    path: root.path,
    label: root.label,
    description: root.description,
    isActive: root.is_active,
  }));
}

export async function getFileTree(rootId: string, path = ''): Promise<FileTreeNode[]> {
  const query = new URLSearchParams({ path });
  const response = await request<{ path: string; entries: FileTreeNode[] }>(
    `/api/source-roots/${rootId}/tree?${query}`,
  );
  return response.entries;
}

export function analyzeDataset(payload: SourceSelectionInput): Promise<JobAccepted> {
  return request('/api/datasets/analyze', { method: 'POST', body: JSON.stringify(payload) });
}

export function registerDataset(payload: DatasetRegistrationInput): Promise<JobAccepted> {
  return request('/api/datasets/register', { method: 'POST', body: JSON.stringify(payload) });
}

export function getJob<T = Record<string, unknown>>(id: string, signal?: AbortSignal) {
  return request<BackgroundJob<T>>(`/api/jobs/${id}`, { signal });
}

export async function listReviewSessions(params?: {
  datasetId?: string; search?: string; page?: number; pageSize?: number;
}) {
  const query = new URLSearchParams({
    page: String(params?.page ?? 1),
    page_size: String(params?.pageSize ?? 20),
  });
  if (params?.datasetId) query.set('dataset_id', params.datasetId);
  if (params?.search) query.set('search', params.search);
  const response = await request<ApiList<ApiReview>>(`/api/reviews?${query}`);
  return { data: response.data.map(mapReview), meta: pageMeta(response.meta) };
}

export async function getReviewSession(id: string) {
  return mapReview(await request<ApiReview>(`/api/reviews/${id}`));
}

export async function createReviewSession(payload: { datasetId: string; inputVersionId: string }) {
  const review = await request<ApiReview>('/api/reviews', {
    method: 'POST',
    body: JSON.stringify({
      dataset_id: payload.datasetId,
      input_version_id: payload.inputVersionId,
      idempotency_key: crypto.randomUUID(),
    }),
  });
  return mapReview(review);
}

export async function syncReviewSession(id: string): Promise<ReviewSession> {
  return mapReview(await request<ApiReview>(`/api/reviews/${id}/sync`, { method: 'POST' }));
}

export async function finalizeReviewSession(id: string): Promise<ReviewSession> {
  return mapReview(await request<ApiReview>(`/api/reviews/${id}/complete`, { method: 'POST' }));
}

export async function retryReviewSession(id: string): Promise<ReviewSession> {
  return mapReview(await request<ApiReview>(`/api/reviews/${id}/retry`, { method: 'POST' }));
}

export function checkLabelStudioConnection() {
  return request<{ status: 'online' | 'offline'; version: string }>('/api/integrations/label-studio/health');
}

export async function listTrainingRuns(params?: {
  datasetId?: string; status?: TrainingStatus | ''; search?: string; page?: number; pageSize?: number;
}) {
  const query = new URLSearchParams({ page: String(params?.page ?? 1), page_size: String(params?.pageSize ?? 20) });
  if (params?.datasetId) query.set('dataset_id', params.datasetId);
  if (params?.status) query.set('status', params.status);
  if (params?.search) query.set('search', params.search);
  const response = await request<ApiList<ApiTrainingRun>>(`/api/training-runs?${query}`);
  return { data: response.data.map(run => mapTrainingRun(run)), meta: pageMeta(response.meta) };
}

export async function getTrainingRun(id: string): Promise<TrainingRun> {
  let run = await request<ApiTrainingRun>(`/api/training-runs/${id}`);
  if (run.unitrain_run_id && ['queued', 'running'].includes(run.status)) {
    try {
      run = await request<ApiTrainingRun>(`/api/training-runs/${id}/sync`, { method: 'POST' });
    } catch {
      // Keep the last mirrored state while UnitTrain is temporarily unavailable.
    }
  }
  if (!run.unitrain_run_id) return mapTrainingRun(run);
  const [logsResult, metricsResult] = await Promise.allSettled([
    request<ApiTrainingLogs>(`/api/training-runs/${id}/logs?offset=0&limit=500`),
    request<ApiTrainingMetrics>(`/api/training-runs/${id}/metrics`),
  ]);
  const logs = logsResult.status === 'fulfilled' ? logsResult.value.lines : [];
  const metrics = metricsResult.status === 'fulfilled' ? metricsResult.value : undefined;
  return mapTrainingRun(run, metrics, logs);
}

export function createTrainingRun(payload: {
  name: string; datasetId: string; datasetVersionId: string; config: Record<string, unknown>;
}) {
  return request<ApiTrainingRun>('/api/training-runs', {
    method: 'POST',
    body: JSON.stringify({
      name: payload.name,
      dataset_id: payload.datasetId,
      dataset_version_id: payload.datasetVersionId,
      idempotency_key: crypto.randomUUID(),
      config: payload.config,
    }),
  }).then(run => mapTrainingRun(run));
}

export function stopTrainingRun(id: string) {
  return request<ApiTrainingRun>(`/api/training-runs/${id}/stop`, { method: 'POST' })
    .then(run => mapTrainingRun(run));
}

export function retryJob(id: string): Promise<void> {
  return request(`/api/jobs/${id}/retry`, { method: 'POST' }).then(() => undefined);
}

export function checkUnitTrainConnection() {
  return request<{ status: 'online' | 'offline'; version: string }>('/api/integrations/unitrain/health');
}

export async function listModels(params?: { search?: string; taskType?: string; page?: number; pageSize?: number }) {
  const query = new URLSearchParams({ page: String(params?.page ?? 1), page_size: String(params?.pageSize ?? 20) });
  if (params?.search) query.set('search', params.search);
  if (params?.taskType) query.set('task_type', params.taskType);
  const response = await request<ApiList<ApiModel>>(`/api/models?${query}`);
  return { data: response.data.map(mapModel), meta: pageMeta(response.meta) };
}

export function getModel(id: string) {
  return request<ApiModel>(`/api/models/${id}`).then(mapModel);
}

export async function listUsers(): Promise<User[]> {
  const users = await request<Array<{
    id: string; name: string; email: string; role: User['role']; is_active: boolean;
    created_at: string; last_login_at: string | null;
  }>>('/api/admin/users');
  return users.map(user => ({
    id: user.id,
    name: user.name,
    email: user.email,
    role: user.role,
    isActive: user.is_active,
    createdAt: user.created_at,
    lastLogin: user.last_login_at ?? '',
  }));
}

export function createUser(payload: {
  name: string; email: string; password: string; role: User['role'];
}): Promise<void> {
  return request('/api/admin/users', {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(() => undefined);
}

export function updateUser(
  userId: string,
  payload: { name?: string; role?: User['role']; is_active?: boolean },
): Promise<void> {
  return request(`/api/admin/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }).then(() => undefined);
}

export function createAllowedRoot(payload: {
  path: string; label: string; description: string;
}): Promise<void> {
  return request('/api/admin/source-roots', {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(() => undefined);
}

export function updateAllowedRoot(
  rootId: string,
  payload: { label?: string; description?: string; is_active?: boolean },
): Promise<void> {
  return request(`/api/admin/source-roots/${rootId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }).then(() => undefined);
}

export async function listAuditLogs(params?: { page?: number; pageSize?: number }) {
  const query = new URLSearchParams({ page: String(params?.page ?? 1), page_size: String(params?.pageSize ?? 20) });
  const response = await request<ApiList<{
    id: string; action: string; user_id: string | null; user_name: string;
    resource_type: string; resource_id: string; resource_name: string;
    timestamp: string; details: Record<string, unknown>; ip_address: string | null;
  }>>(`/api/admin/audit-events?${query}`);
  return {
    data: response.data.map<AuditLog>(event => ({
      id: event.id,
      action: event.action,
      userId: event.user_id ?? '',
      userName: event.user_name,
      resourceType: event.resource_type,
      resourceId: event.resource_id,
      resourceName: event.resource_name,
      timestamp: event.timestamp,
      details: JSON.stringify(event.details),
      ipAddress: event.ip_address ?? '',
    })),
    meta: pageMeta(response.meta),
  };
}

export async function getSystemConfig(): Promise<SystemConfig> {
  const [allowedRoots, config] = await Promise.all([
    listAllowedRoots(),
    request<{
      label_studio: { url: string; version: string; status: 'online' | 'offline' | 'checking'; api_key_configured: boolean };
      unitrain: { url: string; version: string; status: 'online' | 'offline' | 'checking'; api_key_configured: boolean };
    }>('/api/admin/system-config'),
  ]);
  return {
    allowedRoots,
    labelStudio: {
      url: config.label_studio.url,
      version: config.label_studio.version,
      status: config.label_studio.status,
      apiKeyConfigured: config.label_studio.api_key_configured,
    },
    unitTrain: {
      url: config.unitrain.url,
      version: config.unitrain.version,
      status: config.unitrain.status,
      apiKeyConfigured: config.unitrain.api_key_configured,
    },
  };
}
