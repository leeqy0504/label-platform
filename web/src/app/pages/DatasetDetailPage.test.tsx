import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../test/server';
import DatasetDetailPage from './DatasetDetailPage';

function datasetHandlers() {
  server.use(
    http.get('/api/datasets/dataset-1', () => HttpResponse.json({
      id: 'dataset-1',
      name: 'warehouse',
      description: 'cargo images',
      status: 'trainable',
      created_at: '2026-07-16T00:00:00Z',
      updated_at: '2026-07-16T01:00:00Z',
      current_version: 2,
      current_version_id: 'version-2',
      item_count: 10,
      annotation_count: 17,
      category_count: 2,
      class_schema: [{ id: 1, name: 'cargo' }, { id: 2, name: 'person' }],
      category_counts: { 1: 12, 2: 5 },
      split_counts: { train: 8, val: 2, test: 0 },
      total_size: 10 * 1024 * 1024,
      sources: [{
        id: 'source-1', source_root_id: 'root-1', relative_path: 'incoming/warehouse',
        source_format: 'coco_instance', task_type: 'instance_segmentation', scan_status: 'registered',
      }],
    })),
    http.get('/api/datasets/dataset-1/versions', () => HttpResponse.json({
      data: [
        {
          id: 'version-2', version_number: 2, parent_id: 'version-1', status: 'ready',
          class_schema: [{ id: 1, name: 'cargo' }, { id: 2, name: 'person' }],
          category_counts: { 1: 12, 2: 5 }, item_count: 10, annotation_count: 17,
          validation_result: { valid: true, errors: [] },
          created_at: '2026-07-16T01:00:00Z',
        },
        {
          id: 'version-1', version_number: 1, parent_id: null, status: 'ready',
          class_schema: [{ id: 1, name: 'cargo' }, { id: 2, name: 'person' }],
          category_counts: { 1: 8, 2: 3 }, item_count: 10, annotation_count: 11,
          validation_result: { valid: true, errors: [] },
          created_at: '2026-07-16T00:00:00Z',
        },
      ],
      meta: { page: 1, page_size: 2, total: 2 },
    })),
    http.get('/api/reviews', () => HttpResponse.json({ detail: 'Not Found' }, { status: 404 })),
    http.get('/api/integrations/label-studio/health', () => (
      HttpResponse.json({ detail: 'Not Found' }, { status: 404 })
    )),
  );
}

it('renders real dataset metadata and an explicit unavailable review state', async () => {
  datasetHandlers();
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/datasets/dataset-1']}>
      <Routes>
        <Route path="/datasets/:id" element={<DatasetDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );

  expect(await screen.findByText('17')).toBeInTheDocument();
  expect(screen.getByText('规范格式校验')).toBeInTheDocument();

  await user.click(screen.getByRole('button', { name: '格式与划分' }));
  expect(screen.getByText('COCO Instance Segmentation')).toBeInTheDocument();
  expect(screen.getByText('8')).toBeInTheDocument();
  expect(screen.getByText('80.0%')).toBeInTheDocument();

  await user.click(screen.getByRole('button', { name: '版本' }));
  expect(screen.getAllByText('v1').length).toBeGreaterThan(0);

  await user.click(screen.getByRole('button', { name: 'Label Studio 审核' }));
  expect(await screen.findByText('审核服务不可用')).toBeInTheDocument();
});
