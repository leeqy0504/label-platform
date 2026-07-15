import {
  mockDatasets,
  mockMediaFiles,
  mockReviewSessions,
  mockTrainingRuns,
  mockModels,
  mockUsers,
  mockAuditLogs,
  mockSystemConfig,
  mockFileTree,
} from '../data/mockData';
import type {
  Dataset,
  MediaFile,
  ReviewSession,
  TrainingRun,
  Model,
  User,
  AuditLog,
  SystemConfig,
  FileTreeNode,
  ScanPreview,
  DatasetStatus,
  TrainingStatus,
  ListResponse,
  AllowedRoot,
} from '../types';

const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

// ─── Datasets ─────────────────────────────────────────────────────────────────

export async function listDatasets(params?: {
  search?: string;
  status?: DatasetStatus | '';
  page?: number;
  pageSize?: number;
}): Promise<ListResponse<Dataset>> {
  await delay(300);
  let data = [...mockDatasets];
  if (params?.search) {
    const q = params.search.toLowerCase();
    data = data.filter(d => d.name.toLowerCase().includes(q) || d.description.toLowerCase().includes(q));
  }
  if (params?.status && params.status !== '__all__') {
    data = data.filter(d => d.status === params.status);
  }
  const page = params?.page ?? 1;
  const pageSize = params?.pageSize ?? 20;
  const total = data.length;
  data = data.slice((page - 1) * pageSize, page * pageSize);
  return { data, meta: { page, pageSize, total } };
}

export async function getDataset(id: string): Promise<Dataset> {
  await delay(200);
  const ds = mockDatasets.find(d => d.id === id);
  if (!ds) throw new Error(`Dataset ${id} not found`);
  return ds;
}

export async function archiveDataset(id: string): Promise<void> {
  await delay(400);
  const ds = mockDatasets.find(d => d.id === id);
  if (ds) ds.status = 'archived';
}

// ─── Media Files ───────────────────────────────────────────────────────────────

export async function listMediaFiles(
  datasetId: string,
  params?: {
    search?: string;
    split?: string;
    annotationStatus?: string;
    hasAnomaly?: boolean;
    page?: number;
    pageSize?: number;
  }
): Promise<ListResponse<MediaFile>> {
  await delay(250);
  let data = [...mockMediaFiles];
  if (params?.search) {
    const q = params.search.toLowerCase();
    data = data.filter(f => f.filename.toLowerCase().includes(q));
  }
  if (params?.split && params.split !== '__all__') data = data.filter(f => f.split === params.split);
  if (params?.annotationStatus && params.annotationStatus !== '__all__') data = data.filter(f => f.annotationStatus === params.annotationStatus);
  if (params?.hasAnomaly) data = data.filter(f => f.hasAnomaly);
  const page = params?.page ?? 1;
  const pageSize = params?.pageSize ?? 20;
  const total = data.length;
  data = data.slice((page - 1) * pageSize, page * pageSize);
  return { data, meta: { page, pageSize, total } };
}

// ─── File Tree ─────────────────────────────────────────────────────────────────

export async function listAllowedRoots(): Promise<AllowedRoot[]> {
  await delay(150);
  return mockSystemConfig.allowedRoots;
}

export async function getFileTree(rootPath: string): Promise<FileTreeNode[]> {
  await delay(400);
  const root = mockFileTree.find(n => n.path === rootPath);
  return root ? [root] : [];
}

export async function scanDirectory(path: string): Promise<ScanPreview> {
  // Simulates a progressive scan by resolving after a delay
  await delay(800);
  const isIncoming = path.includes('incoming');
  return {
    imageCount: isIncoming ? 680 : 1200,
    videoCount: 0,
    cocoFiles: isIncoming ? [] : ['annotations.json'],
    totalSizeMB: isIncoming ? 2720 : 4820,
    anomalies: isIncoming ? ['发现 3 个损坏文件: img_00231.jpg, img_00455.jpg, img_00612.jpg'] : [],
    progress: 100,
    isComplete: true,
  };
}

export async function registerDataset(payload: {
  name: string;
  description: string;
  rootPath: string;
  categories: string[];
}): Promise<Dataset> {
  await delay(1500);
  const newDs: Dataset = {
    id: `ds-${Date.now()}`,
    name: payload.name,
    description: payload.description,
    currentVersion: 'v1',
    mediaCount: 0,
    categoryCount: payload.categories.length,
    annotationCount: 0,
    status: 'scanning',
    updatedAt: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    createdBy: 'alice',
    rootPath: payload.rootPath,
    totalSize: 0,
    trainCount: 0,
    valCount: 0,
    testCount: 0,
    categories: [],
    versions: [],
  };
  mockDatasets.unshift(newDs);
  return newDs;
}

// ─── Review Sessions ───────────────────────────────────────────────────────────

export async function listReviewSessions(params?: {
  datasetId?: string;
  page?: number;
  pageSize?: number;
}): Promise<ListResponse<ReviewSession>> {
  await delay(250);
  let data = [...mockReviewSessions];
  if (params?.datasetId) data = data.filter(r => r.datasetId === params.datasetId);
  const page = params?.page ?? 1;
  const pageSize = params?.pageSize ?? 20;
  const total = data.length;
  data = data.slice((page - 1) * pageSize, page * pageSize);
  return { data, meta: { page, pageSize, total } };
}

export async function getReviewSession(id: string): Promise<ReviewSession> {
  await delay(150);
  const rs = mockReviewSessions.find(r => r.id === id);
  if (!rs) throw new Error(`ReviewSession ${id} not found`);
  return rs;
}

export async function createReviewSession(payload: {
  datasetId: string;
  inputVersion: string;
}): Promise<ReviewSession> {
  await delay(800);
  const ds = mockDatasets.find(d => d.id === payload.datasetId);
  const newSession: ReviewSession = {
    id: `rs-${Date.now()}`,
    datasetId: payload.datasetId,
    datasetName: ds?.name ?? '',
    inputVersion: payload.inputVersion,
    labelStudioProjectId: Math.floor(Math.random() * 90 + 10),
    labelStudioProjectUrl: `http://label-studio.internal/projects/${Math.floor(Math.random() * 90 + 10)}`,
    totalTasks: ds?.mediaCount ?? 0,
    completedTasks: 0,
    skippedTasks: 0,
    status: 'active',
    createdBy: 'alice',
    startedAt: new Date().toISOString(),
    completedAt: null,
    outputVersion: null,
  };
  mockReviewSessions.push(newSession);
  return newSession;
}

export async function finalizeReviewSession(id: string): Promise<void> {
  await delay(3000);
  const rs = mockReviewSessions.find(r => r.id === id);
  if (rs) {
    rs.status = 'completed';
    rs.completedAt = new Date().toISOString();
    rs.outputVersion = 'v-new';
  }
}

export async function checkLabelStudioConnection(): Promise<{ status: 'online' | 'offline'; version: string }> {
  await delay(600);
  return { status: 'online', version: '1.11.0' };
}

// ─── Training Runs ─────────────────────────────────────────────────────────────

export async function listTrainingRuns(params?: {
  datasetId?: string;
  status?: TrainingStatus | '';
  search?: string;
  page?: number;
  pageSize?: number;
}): Promise<ListResponse<TrainingRun>> {
  await delay(250);
  let data = [...mockTrainingRuns];
  if (params?.datasetId) data = data.filter(r => r.datasetId === params.datasetId);
  if (params?.status && params.status !== '__all__') data = data.filter(r => r.status === params.status);
  if (params?.search) {
    const q = params.search.toLowerCase();
    data = data.filter(r => r.name.toLowerCase().includes(q));
  }
  const page = params?.page ?? 1;
  const pageSize = params?.pageSize ?? 20;
  const total = data.length;
  data = data.slice((page - 1) * pageSize, page * pageSize);
  return { data, meta: { page, pageSize, total } };
}

export async function getTrainingRun(id: string): Promise<TrainingRun> {
  await delay(200);
  const tr = mockTrainingRuns.find(t => t.id === id);
  if (!tr) throw new Error(`TrainingRun ${id} not found`);
  return tr;
}

export async function createTrainingRun(payload: {
  name: string;
  datasetId: string;
  datasetVersion: string;
  taskType: string;
  config: Record<string, unknown>;
}): Promise<TrainingRun> {
  await delay(600);
  const ds = mockDatasets.find(d => d.id === payload.datasetId);
  const newRun: TrainingRun = {
    id: `tr-${Date.now()}`,
    name: payload.name,
    datasetId: payload.datasetId,
    datasetName: ds?.name ?? '',
    datasetVersion: payload.datasetVersion,
    taskType: payload.taskType as 'detection' | 'instance_segmentation',
    status: 'queued',
    currentEpoch: 0,
    totalEpochs: 100,
    primaryMetric: 0,
    metricName: 'mAP50',
    startedBy: 'alice',
    startedAt: new Date().toISOString(),
    completedAt: null,
    durationSeconds: 0,
    config: {
      model: 'yolov8l',
      batchSize: 16,
      learningRate: 0.01,
      optimizer: 'AdamW',
      imageSize: 640,
      augmentation: true,
      trainSplit: 0.8,
      valSplit: 0.2,
      warmupEpochs: 3,
      weightDecay: 0.0005,
      ...payload.config,
    },
    logs: ['[queued] 任务已提交，等待 GPU 资源...'],
    metrics: [],
    outputModelId: null,
    errorMessage: null,
    gpuUtil: 0,
    gpuMem: 0,
    unitTrainRunUrl: `http://unittrain.internal/runs/tr-${Date.now()}`,
  };
  mockTrainingRuns.unshift(newRun);
  return newRun;
}

export async function checkUnitTrainConnection(): Promise<{ status: 'online' | 'offline'; version: string }> {
  await delay(600);
  return { status: 'online', version: '2.4.1' };
}

// ─── Models ───────────────────────────────────────────────────────────────────

export async function listModels(params?: {
  search?: string;
  taskType?: string;
  page?: number;
  pageSize?: number;
}): Promise<ListResponse<Model>> {
  await delay(250);
  let data = [...mockModels];
  if (params?.search) {
    const q = params.search.toLowerCase();
    data = data.filter(m => m.name.toLowerCase().includes(q));
  }
  if (params?.taskType && params.taskType !== '__all__') data = data.filter(m => m.taskType === params.taskType);
  const page = params?.page ?? 1;
  const pageSize = params?.pageSize ?? 20;
  const total = data.length;
  data = data.slice((page - 1) * pageSize, page * pageSize);
  return { data, meta: { page, pageSize, total } };
}

export async function getModel(id: string): Promise<Model> {
  await delay(200);
  const m = mockModels.find(m => m.id === id);
  if (!m) throw new Error(`Model ${id} not found`);
  return m;
}

// ─── Users ────────────────────────────────────────────────────────────────────

export async function listUsers(): Promise<User[]> {
  await delay(200);
  return mockUsers;
}

// ─── Audit Logs ───────────────────────────────────────────────────────────────

export async function listAuditLogs(params?: {
  page?: number;
  pageSize?: number;
}): Promise<ListResponse<AuditLog>> {
  await delay(200);
  const page = params?.page ?? 1;
  const pageSize = params?.pageSize ?? 20;
  const total = mockAuditLogs.length;
  const data = mockAuditLogs.slice((page - 1) * pageSize, page * pageSize);
  return { data, meta: { page, pageSize, total } };
}

// ─── System Config ─────────────────────────────────────────────────────────────

export async function getSystemConfig(): Promise<SystemConfig> {
  await delay(200);
  return mockSystemConfig;
}

export async function updateAllowedRoots(roots: AllowedRoot[]): Promise<void> {
  await delay(400);
  mockSystemConfig.allowedRoots.splice(0, mockSystemConfig.allowedRoots.length, ...roots);
}
