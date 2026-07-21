import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../../../test/server';
import type { Dataset } from '../../../types';
import { AuthProvider } from '../../auth/AuthProvider';
import { ReviewTab } from './ReviewTab';

const dataset: Dataset = {
  id: 'dataset-1',
  name: 'warehouse',
  description: '',
  currentVersion: 'v2',
  currentVersionId: 'version-2',
  mediaCount: 80,
  categoryCount: 1,
  annotationCount: 80,
  status: 'reviewing',
  updatedAt: '2026-07-21T06:00:00Z',
  createdAt: '2026-07-21T05:00:00Z',
  createdBy: 'Dataset Engineer',
  rootPath: '',
  categories: [],
  versions: [{
    id: 'version-2',
    version: 'v2',
    parentVersion: 'v1',
    source: 'initial_import',
    imageCount: 80,
    annotationCount: 80,
    categorySchema: [],
    createdAt: '2026-07-21T05:00:00Z',
    createdBy: 'Dataset Engineer',
    reviewSessionId: null,
    trainingCount: 0,
    isImmutable: true,
    notes: '',
    cocoFilePath: 'annotations/instances.coco.json',
  }],
  totalSize: 1,
  trainCount: 64,
  valCount: 16,
  testCount: 0,
  taskType: 'detection',
  sourceFormat: 'coco_detection',
  validationResult: { valid: true, errors: [] },
};

const review = {
  id: 'review-1',
  dataset_id: 'dataset-1',
  dataset_name: 'warehouse',
  input_version_id: 'version-2',
  input_version_number: 2,
  output_version_id: null,
  output_version_number: null,
  label_studio_project_id: 10,
  label_studio_project_url: 'http://labels.test/projects/10/data',
  total_tasks: 80,
  completed_tasks: 80,
  skipped_tasks: 0,
  status: 'in_review',
  config_hash: 'a'.repeat(64),
  error_summary: {},
  created_by: 'Dataset Engineer',
  started_at: '2026-07-21T06:00:00Z',
  completed_at: null,
  created_at: '2026-07-21T06:00:00Z',
  updated_at: '2026-07-21T06:00:00Z',
  job_id: null,
};

it('deletes an active review after destructive confirmation', async () => {
  let deleted = false;
  server.use(
    http.get('/api/auth/me', () => HttpResponse.json({
      id: 'user-1', email: 'engineer@example.test', name: 'Dataset Engineer',
      role: 'data_engineer', is_active: true,
    })),
    http.get('/api/integrations/label-studio/health', () => (
      HttpResponse.json({ status: 'online', version: '1.21.0' })
    )),
    http.get('/api/reviews', () => HttpResponse.json({
      data: deleted ? [] : [review],
      meta: { page: 1, page_size: 20, total: deleted ? 0 : 1 },
    })),
    http.post('/api/reviews/review-1/sync', () => HttpResponse.json(review)),
    http.delete('/api/reviews/review-1', () => {
      deleted = true;
      return new HttpResponse(null, { status: 204 });
    }),
  );
  const user = userEvent.setup();
  render(
    <AuthProvider>
      <ReviewTab dataset={dataset} />
    </AuthProvider>,
  );

  const deleteButton = await screen.findByRole('button', { name: '删除审核任务' });
  const labelStudioLink = screen.getByRole('link', { name: '在 Label Studio 中打开' });
  expect(deleteButton.nextElementSibling).toBe(labelStudioLink);

  await user.click(deleteButton);
  expect(screen.getByRole('heading', { name: '删除审核任务' })).toBeInTheDocument();
  expect(screen.getByText('删除 Label Studio 项目 10')).toBeInTheDocument();
  expect(screen.getByText('不会删除原始数据集及其版本')).toBeInTheDocument();

  await user.click(screen.getByRole('button', { name: '确认删除' }));

  await waitFor(() => expect(deleted).toBe(true));
  expect(await screen.findByText('暂无审核任务')).toBeInTheDocument();
});
