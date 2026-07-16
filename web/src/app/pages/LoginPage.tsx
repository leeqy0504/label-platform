import { type FormEvent, useState } from 'react';
import { Database, Loader2, LogIn } from 'lucide-react';
import { useAuth } from '../auth/AuthProvider';

export default function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      await login(email, password);
    } catch {
      setError('邮箱或密码不正确');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="min-h-screen bg-[#f6f7f9] text-gray-900 grid lg:grid-cols-[280px_1fr]">
      <aside className="hidden lg:flex bg-[#18212b] text-white px-8 py-10 flex-col justify-between">
        <div className="flex items-center gap-3">
          <span className="size-9 grid place-items-center bg-blue-500 rounded">
            <Database className="size-5" />
          </span>
          <span className="text-sm font-semibold">Label Platform</span>
        </div>
        <p className="text-xs text-gray-400">内部数据与训练工作台</p>
      </aside>
      <section className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="flex items-center gap-3 mb-10 lg:hidden">
            <span className="size-9 grid place-items-center bg-blue-600 text-white rounded">
              <Database className="size-5" />
            </span>
            <span className="text-sm font-semibold">Label Platform</span>
          </div>
          <h1 className="text-2xl font-semibold mb-2">视觉数据集管理平台</h1>
          <p className="text-sm text-gray-500 mb-8">使用部门账号登录</p>
          <form onSubmit={submit} className="space-y-5">
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1.5">邮箱</label>
              <input
                id="email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={event => setEmail(event.target.value)}
                className="w-full h-10 px-3 bg-white border border-gray-300 rounded outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </div>
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1.5">密码</label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={event => setPassword(event.target.value)}
                className="w-full h-10 px-3 bg-white border border-gray-300 rounded outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </div>
            {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
            <button
              type="submit"
              disabled={submitting}
              className="w-full h-10 inline-flex items-center justify-center gap-2 bg-blue-600 text-white text-sm font-medium rounded hover:bg-blue-700 disabled:opacity-60"
            >
              {submitting ? <Loader2 className="size-4 animate-spin" /> : <LogIn className="size-4" />}
              登录
            </button>
          </form>
        </div>
      </section>
    </main>
  );
}
