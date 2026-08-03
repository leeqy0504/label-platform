import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../test/server';
import ModelsPage from './ModelsPage';

it('shows a dedicated offline state when UnitTrain is unavailable', async () => {
  server.use(
    http.get('/api/models', () => (
      HttpResponse.json({ detail: 'UnitTrain is unavailable' }, { status: 503 })
    )),
  );

  render(<MemoryRouter><ModelsPage /></MemoryRouter>);

  expect(await screen.findByText('UnitTrain 服务不可用')).toBeInTheDocument();
  expect(screen.getByText('模型数据暂时无法同步，请稍后重试。')).toBeInTheDocument();
});

it('formats model file sizes to two decimals', async () => {
  server.use(
    http.get('/api/models', () => HttpResponse.json({
      data: [{
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
        metrics: { mAP50: 0.9, mAP50_95: 0.8 },
        category_metrics: [],
        categories: ['object'],
        file_size: 1_294_674,
        file_path: '/home/try/code/label-platform/var/unitrain/runs/unitrain-1/artifacts/best.pt',
        evaluation_files: [],
        evaluation_links: [],
        created_at: '2026-08-03T00:00:00Z',
      }],
      meta: { page: 1, page_size: 20, total: 1 },
    })),
  );

  render(<MemoryRouter><ModelsPage /></MemoryRouter>);

  expect(await screen.findByText('1.23 MB')).toBeInTheDocument();
});
