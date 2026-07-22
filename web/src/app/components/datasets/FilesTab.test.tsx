import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../../../test/server';
import type { Dataset } from '../../../types';
import { FilesTab } from './FilesTab';

const dataset: Dataset = {
  id: 'dataset-1',
  name: 'warehouse',
  description: '',
  currentVersion: 'v1',
  currentVersionId: 'version-1',
  mediaCount: 1,
  categoryCount: 2,
  annotationCount: 2,
  status: 'trainable',
  updatedAt: '2026-07-22T06:00:00Z',
  createdAt: '2026-07-22T05:00:00Z',
  rootPath: '',
  categories: [
    { id: 1, name: 'cargo', supercategory: '', count: 1 },
    { id: 2, name: 'person', supercategory: '', count: 1 },
  ],
  versions: [],
  totalSize: 1024,
  trainCount: 1,
  valCount: 0,
  testCount: 0,
  taskType: 'detection',
  sourceFormat: 'coco_detection',
  validationResult: { valid: true, errors: [] },
};

function handlers() {
  server.use(
    http.get('/api/datasets/dataset-1', () => HttpResponse.json({
      id: 'dataset-1',
      name: 'warehouse',
      description: '',
      status: 'trainable',
      created_at: '2026-07-22T05:00:00Z',
      updated_at: '2026-07-22T06:00:00Z',
      current_version: 1,
      current_version_id: 'version-1',
      item_count: 1,
      annotation_count: 2,
      category_count: 2,
      class_schema: [{ id: 1, name: 'cargo' }, { id: 2, name: 'person' }],
      category_counts: { 1: 1, 2: 1 },
      split_counts: { train: 1, val: 0, test: 0 },
      total_size: 1024,
      sources: [{
        id: 'source-1',
        source_root_id: 'root-1',
        relative_path: 'incoming',
        source_format: 'coco_detection',
        task_type: 'detection',
        scan_status: 'registered',
      }],
    })),
    http.get('/api/datasets/dataset-1/versions/version-1/items', () => HttpResponse.json({
      data: [{
        id: 'file-1',
        sample_key: 'sample-1',
        relative_path: 'images/frame.jpg',
        media_type: 'image/jpeg',
        width: 200,
        height: 100,
        file_size: 1024,
        sha256: 'a'.repeat(64),
        split: 'train',
        status: 'annotated',
        annotation_count: 2,
        annotations: [
          { category_id: 1, bbox: [10, 20, 50, 30] },
          { category_id: 2, bbox: [80, 10, 40, 70] },
        ],
        group_key: null,
      }],
      meta: { page: 1, page_size: 24, total: 1 },
    })),
  );
}

it('renders color-coded boxes without category labels in grid and inspector images', async () => {
  handlers();
  const user = userEvent.setup();
  render(<FilesTab dataset={dataset} />);

  await user.click(screen.getByRole('button', { name: '网格视图' }));
  const image = await screen.findByRole('img', { name: 'frame.jpg' });
  const gridOverlay = await screen.findByTestId('bbox-overlay-file-1');
  const gridBoxes = gridOverlay.querySelectorAll('rect');

  expect(gridOverlay).toHaveAttribute('viewBox', '0 0 200 100');
  expect(gridBoxes).toHaveLength(2);
  expect(gridBoxes[0]).toHaveAttribute('stroke', '#ef4444');
  expect(gridBoxes[1]).toHaveAttribute('stroke', '#22c55e');
  expect(screen.queryByText('cargo')).not.toBeInTheDocument();
  expect(screen.queryByText('person')).not.toBeInTheDocument();

  await user.click(image);
  await waitFor(() => {
    expect(screen.getAllByTestId('bbox-overlay-file-1')).toHaveLength(2);
  });
  expect(screen.getAllByTestId('bbox-overlay-file-1')[1].querySelectorAll('rect')).toHaveLength(2);
});
