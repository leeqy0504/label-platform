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
