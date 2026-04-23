import { createBrowserRouter } from 'react-router-dom';
import MainLayout from './components/Layout/MainLayout';

// Lazy load pages
import Dashboard from './pages/Dashboard';
import Generate from './pages/Generate';
import Documents from './pages/Documents';
import DocumentDetail from './pages/Documents/Detail';
import KnowledgeBase from './pages/KnowledgeBase';
import ChemicalDetail from './pages/KnowledgeBase/Detail';
import Calculator from './pages/Calculator';

const router = createBrowserRouter([
  {
    path: '/',
    element: <MainLayout><Dashboard /></MainLayout>,
  },
  {
    path: '/generate',
    element: <MainLayout><Generate /></MainLayout>,
  },
  {
    path: '/documents',
    element: <MainLayout><Documents /></MainLayout>,
  },
  {
    path: '/documents/:id',
    element: <MainLayout><DocumentDetail /></MainLayout>,
  },
  {
    path: '/knowledge',
    element: <MainLayout><KnowledgeBase /></MainLayout>,
  },
  {
    path: '/knowledge/:cas',
    element: <MainLayout><ChemicalDetail /></MainLayout>,
  },
  {
    path: '/calculator',
    element: <MainLayout><Calculator /></MainLayout>,
  },
]);

export default router;
