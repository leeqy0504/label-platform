import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../test/server';
import DatasetsPage from './DatasetsPage';

it('renders datasets returned by the platform API', async () => {
  server.use(
    http.get('/api/datasets', () => HttpResponse.json({
    data: [{
      id: 'dataset-1', name: 'warehouse', description: 'cargo images', status: 'trainable',
      created_at: '2026-07-16T00:00:00Z', updated_at: '2026-07-16T00:00:00Z',
      current_version: 1, current_version_id: 'version-1',
      item_count: 1000, annotation_count: 5280, category_count: 2,
      class_schema: [{ id: 1, name: 'person' }, { id: 2, name: 'rack' }],
      category_counts: { 1: 3200, 2: 2080 },
      split_counts: { train: 800, val: 200, test: 0 }, total_size: 1024,
    }],
    meta: { page: 1, page_size: 20, total: 1 },
    })),
  );

  render(<MemoryRouter><DatasetsPage /></MemoryRouter>);

  expect(await screen.findByText('warehouse')).toBeInTheDocument();
  expect(screen.getByText('1,000')).toBeInTheDocument();
  expect(screen.queryByText('forklift-safety')).not.toBeInTheDocument();
});
