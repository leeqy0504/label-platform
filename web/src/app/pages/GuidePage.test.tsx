import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { Sidebar } from '../components/layout/Sidebar';
import GuidePage from './GuidePage';

it('embeds the synchronized user guide', () => {
  render(<GuidePage />);

  expect(screen.getByTitle('视觉数据集管理平台使用手册')).toHaveAttribute(
    'src',
    '/manual/index.html?embedded=1',
  );
});

it('shows an active user guide entry in the platform sidebar', () => {
  render(
    <MemoryRouter initialEntries={['/guide']}>
      <Sidebar collapsed={false} onToggle={() => {}} />
    </MemoryRouter>,
  );

  const link = screen.getByRole('link', { name: '使用手册' });
  expect(link).toHaveAttribute('href', '/guide');
  expect(link).toHaveClass('bg-blue-50', 'text-blue-700');
});
