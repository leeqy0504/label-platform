import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../../../test/server';
import { RegisterDatasetDialog } from './RegisterDatasetDialog';

function handlers(valid = true, sourceFormat = 'coco_instance') {
  server.use(
    http.get('/api/source-roots', () => HttpResponse.json([
      {
        id: 'root-1', path: '/data/incoming', label: '待处理数据', description: '',
        is_active: true, created_at: '', updated_at: '',
      },
    ])),
    http.get('/api/source-roots/root-1/tree', () => HttpResponse.json({ path: '', entries: [] })),
    http.post('/api/datasets/analyze', () => HttpResponse.json({ job_id: 'analysis-1', status: 'pending' }, { status: 202 })),
    http.get('/api/jobs/analysis-1', () => HttpResponse.json({
      id: 'analysis-1', business_object_id: null, job_type: 'dataset_analysis',
      status: 'succeeded', stage: 'done', processed_count: valid ? 1000 : 0,
      total_count: valid ? 1000 : 0, retry_count: 0, log_path: null,
      error_summary: {},
      result: {
        valid,
        source_format: valid ? sourceFormat : null,
        task_type: valid ? 'instance_segmentation' : null,
        image_count: valid ? 1000 : 0,
        annotation_count: valid ? 5280 : 0,
        categories: ['person', 'rack'],
        split_counts: { train: valid ? 800 : 0, val: valid ? 200 : 0, test: 0 },
        unsupported_files: [],
        errors: valid ? [] : [{ code: 'source_invalid', path: 'source', message: '发现损坏图片' }],
        fingerprint: valid ? 'a'.repeat(64) : null,
      },
      created_at: '', updated_at: '', started_at: null, finished_at: null,
    })),
  );
}

async function fillAndAnalyze() {
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByLabelText('允许目录'), 'root-1');
  await user.type(screen.getByLabelText('相对路径'), 'incoming/warehouse');
  await user.type(screen.getByLabelText('初始类别'), 'person, rack');
  await user.click(screen.getByRole('button', { name: '分析目录' }));
  return user;
}

it('analyzes a server directory before enabling registration', async () => {
  handlers(true);
  render(<RegisterDatasetDialog open onOpenChange={() => {}} onSuccess={() => {}} />);

  await fillAndAnalyze();

  expect(await screen.findByText('COCO Instance Segmentation')).toBeInTheDocument();
  expect(screen.getByText('1,000 张图片')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '登记数据集' })).toBeEnabled();
  expect(screen.getByText(/YOLO 类别以 data.yaml 为准/)).toBeInTheDocument();
});

it('shows the YOLO Detection source format returned by analysis', async () => {
  handlers(true, 'yolo_detection');
  render(<RegisterDatasetDialog open onOpenChange={() => {}} onSuccess={() => {}} />);

  await fillAndAnalyze();

  expect(await screen.findByText('YOLO Detection')).toBeInTheDocument();
});

it('keeps registration disabled when analysis reports normalization errors', async () => {
  handlers(false);
  render(<RegisterDatasetDialog open onOpenChange={() => {}} onSuccess={() => {}} />);

  await fillAndAnalyze();

  expect(await screen.findByText('发现损坏图片')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '登记数据集' })).toBeDisabled();
});
