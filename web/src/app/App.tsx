import { Suspense } from 'react';
import { RouterProvider } from 'react-router';
import { router } from './routes';
import { AuthProvider, useAuth } from './auth/AuthProvider';
import LoginPage from './pages/LoginPage';

export default function App() {
  return (
    <AuthProvider>
      <AuthenticatedApp />
    </AuthProvider>
  );
}

function AuthenticatedApp() {
  const { user, loading } = useAuth();
  if (loading) {
    return <div className="min-h-screen grid place-items-center text-sm text-gray-500">正在加载...</div>;
  }
  if (!user) return <LoginPage />;
  return (
    <Suspense fallback={<div className="min-h-screen grid place-items-center text-sm text-gray-500">正在加载...</div>}>
      <RouterProvider router={router} />
    </Suspense>
  );
}
