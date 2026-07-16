import { lazy } from 'react';
import { createBrowserRouter, Navigate, redirect } from 'react-router';
import { Layout } from './components/layout/Layout';
import { useAuth } from './auth/AuthProvider';

const DatasetsPage = lazy(() => import('./pages/DatasetsPage'));
const DatasetDetailPage = lazy(() => import('./pages/DatasetDetailPage'));
const ReviewPage = lazy(() => import('./pages/ReviewPage'));
const TrainingPage = lazy(() => import('./pages/TrainingPage'));
const TrainingDetailPage = lazy(() => import('./pages/TrainingDetailPage'));
const ModelsPage = lazy(() => import('./pages/ModelsPage'));
const ModelDetailPage = lazy(() => import('./pages/ModelDetailPage'));
const SystemPage = lazy(() => import('./pages/SystemPage'));

function AdminRoute() {
  const { user } = useAuth();
  return user?.role === 'admin' ? <SystemPage /> : <Navigate to="/datasets" replace />;
}

export const router = createBrowserRouter([
  {
    path: '/',
    Component: Layout,
    children: [
      {
        index: true,
        loader: () => redirect('/datasets'),
      },
      { path: 'datasets', element: <DatasetsPage /> },
      { path: 'datasets/:id', element: <DatasetDetailPage /> },
      { path: 'review', element: <ReviewPage /> },
      { path: 'training', element: <TrainingPage /> },
      { path: 'training/:id', element: <TrainingDetailPage /> },
      { path: 'models', element: <ModelsPage /> },
      { path: 'models/:id', element: <ModelDetailPage /> },
      { path: 'admin', Component: AdminRoute },
    ],
  },
]);
