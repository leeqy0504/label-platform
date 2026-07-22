import { Suspense } from 'react';
import { RouterProvider } from 'react-router';
import { router } from './routes';

export default function App() {
  return (
    <Suspense fallback={<div className="min-h-screen grid place-items-center text-sm text-gray-500">正在加载...</div>}>
      <RouterProvider router={router} />
    </Suspense>
  );
}
