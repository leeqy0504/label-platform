import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../test/server';
import ModelDetailPage from './ModelDetailPage';

it('shows the absolute model path and formats the file size to two decimals', async () => {
  server.use(
    http.get('/api/models/model-1', () => HttpResponse.json({
      id: 'model-1',
      name: 'best.pt',
      training_run_id: 'training-1',
      unitrain_run_id: 'unitrain-1',
      dataset_id: 'dataset-1',
      dataset_name: 'mouse_seg',
      dataset_version_id: 'version-1',
      dataset_version_number: 1,
      task_type: 'instance_segmentation',
      framework: 'ultralytics',
      metrics: { mAP50: 0.9, mAP50_95: 0.8, precision: 0.7, recall: 0.6 },
      category_metrics: [],
      categories: ['object'],
      file_size: 1_294_674,
      file_path: '/home/try/code/label-platform/var/unitrain/runs/unitrain-1/artifacts/best.pt',
      evaluation_files: [],
      evaluation_links: [],
      created_at: '2026-08-03T00:00:00Z',
    })),
  );

  render(
    <MemoryRouter initialEntries={['/models/model-1']}>
      <Routes>
        <Route path="/models/:id" element={<ModelDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );

  expect(await screen.findByText(
    '/home/try/code/label-platform/var/unitrain/runs/unitrain-1/artifacts/best.pt',
  )).toBeInTheDocument();
  expect(screen.getByText('1.23 MB')).toBeInTheDocument();
});
