import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App';

it('logs in and opens the dataset workspace', async () => {
  render(<App />);
  const user = userEvent.setup();

  await user.type(await screen.findByLabelText('邮箱'), 'engineer@example.test');
  await user.type(screen.getByLabelText('密码'), 'correct-horse');
  await user.click(screen.getByRole('button', { name: '登录' }));

  expect(await screen.findByRole('heading', { name: '数据集' })).toBeInTheDocument();
});
