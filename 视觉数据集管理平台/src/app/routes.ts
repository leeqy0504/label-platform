import { createBrowserRouter, redirect } from 'react-router';
import { Layout } from './components/layout/Layout';
import DatasetsPage from './pages/DatasetsPage';
import DatasetDetailPage from './pages/DatasetDetailPage';
import ReviewPage from './pages/ReviewPage';
import TrainingPage from './pages/TrainingPage';
import TrainingDetailPage from './pages/TrainingDetailPage';
import ModelsPage from './pages/ModelsPage';
import ModelDetailPage from './pages/ModelDetailPage';
import SystemPage from './pages/SystemPage';

export const router = createBrowserRouter([
  {
    path: '/',
    Component: Layout,
    children: [
      {
        index: true,
        loader: () => redirect('/datasets'),
      },
      { path: 'datasets', Component: DatasetsPage },
      { path: 'datasets/:id', Component: DatasetDetailPage },
      { path: 'review', Component: ReviewPage },
      { path: 'training', Component: TrainingPage },
      { path: 'training/:id', Component: TrainingDetailPage },
      { path: 'models', Component: ModelsPage },
      { path: 'models/:id', Component: ModelDetailPage },
      { path: 'admin', Component: SystemPage },
    ],
  },
]);
