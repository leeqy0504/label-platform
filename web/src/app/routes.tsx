import { lazy } from 'react';
import { createBrowserRouter, redirect } from 'react-router';
import { Layout } from './components/layout/Layout';

const DatasetsPage = lazy(() => import('./pages/DatasetsPage'));
const DatasetDetailPage = lazy(() => import('./pages/DatasetDetailPage'));
const ReviewPage = lazy(() => import('./pages/ReviewPage'));
const TrainingPage = lazy(() => import('./pages/TrainingPage'));
const TrainingDetailPage = lazy(() => import('./pages/TrainingDetailPage'));
const ModelsPage = lazy(() => import('./pages/ModelsPage'));
const ModelDetailPage = lazy(() => import('./pages/ModelDetailPage'));
const SystemPage = lazy(() => import('./pages/SystemPage'));
const GuidePage = lazy(() => import('./pages/GuidePage'));

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
      { path: 'admin', element: <SystemPage /> },
      { path: 'guide', element: <GuidePage /> },
    ],
  },
]);
