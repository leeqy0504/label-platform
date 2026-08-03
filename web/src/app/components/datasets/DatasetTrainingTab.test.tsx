import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import type { Dataset } from '../../../types';
import { CreateTrainingDialog } from './DatasetTrainingTab';

const apiMocks = vi.hoisted(() => ({
  createTrainingRun: vi.fn(),
}));

vi.mock('../../../services/api', () => ({
  checkUnitTrainConnection: vi.fn(),
  createTrainingRun: apiMocks.createTrainingRun,
  listTrainingRuns: vi.fn(),
}));

const dataset: Dataset = {
  id: 'mouse-seg',
  name: 'mouse-seg',
  description: '',
  currentVersion: 'v1',
  currentVersionId: 'mouse-seg-v1',
  mediaCount: 64,
  categoryCount: 1,
  annotationCount: 64,
  status: 'trainable',
  updatedAt: '2026-07-31T00:00:00Z',
  createdAt: '2026-07-31T00:00:00Z',
  rootPath: '',
  categories: [{ id: 1, name: 'object', supercategory: '', count: 64 }],
  versions: [{
    id: 'mouse-seg-v1',
    version: 'v1',
    parentVersion: null,
    source: 'initial_import',
    imageCount: 64,
    annotationCount: 64,
    categorySchema: [{ id: 1, name: 'object', supercategory: '', count: 64 }],
    createdAt: '2026-07-31T00:00:00Z',
    reviewSessionId: null,
    trainingCount: 0,
    isImmutable: true,
    notes: '',
    cocoFilePath: 'annotations/instances.coco.json',
  }],
  totalSize: 1024,
  trainCount: 52,
  valCount: 12,
  testCount: 0,
  taskType: 'instance_segmentation',
  sourceFormat: 'coco_instance',
  validationResult: { valid: true, errors: [] },
};

it('switches to RF-DETR seg-nano and submits the selected framework', async () => {
  apiMocks.createTrainingRun.mockResolvedValue({});
  const user = userEvent.setup();
  render(
    <CreateTrainingDialog
      open
      onOpenChange={() => {}}
      dataset={dataset}
      onCreated={() => {}}
    />,
  );

  expect(screen.getByRole('combobox', { name: '模型' })).toHaveTextContent('yolo11n-seg');
  await user.click(screen.getByRole('combobox', { name: '框架' }));
  await user.click(screen.getByRole('option', { name: 'RF-DETR' }));
  expect(screen.getByRole('combobox', { name: '模型' })).toHaveTextContent('seg-nano');

  await user.clear(screen.getByRole('spinbutton', { name: 'Batch Size' }));
  await user.type(screen.getByRole('spinbutton', { name: 'Batch Size' }), '1');
  await user.clear(screen.getByRole('spinbutton', { name: 'Epochs' }));
  await user.type(screen.getByRole('spinbutton', { name: 'Epochs' }), '1');
  await user.click(screen.getByRole('button', { name: '提交训练' }));

  await waitFor(() => expect(apiMocks.createTrainingRun).toHaveBeenCalledOnce());
  expect(apiMocks.createTrainingRun).toHaveBeenCalledWith(expect.objectContaining({
    datasetId: 'mouse-seg',
    datasetVersionId: 'mouse-seg-v1',
    config: {
      framework: 'rfdetr',
      model: 'seg-nano',
      batch_size: 1,
      epochs: 1,
    },
  }));
});

