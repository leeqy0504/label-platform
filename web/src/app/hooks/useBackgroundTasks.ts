import { useState, useEffect, useCallback, useRef } from 'react';

export interface BackgroundTask {
  id: string;
  label: string;
  status: 'running' | 'done' | 'error';
  progress?: number;
  message?: string;
}

// Module-level task store
let _tasks: BackgroundTask[] = [];
const _listeners = new Set<(tasks: BackgroundTask[]) => void>();

function notifyAll() {
  _listeners.forEach(fn => fn([..._tasks]));
}

export function addTask(task: BackgroundTask) {
  _tasks = [..._tasks, task];
  notifyAll();
}

export function updateTask(id: string, updates: Partial<BackgroundTask>) {
  _tasks = _tasks.map(t => (t.id === id ? { ...t, ...updates } : t));
  notifyAll();
}

export function removeTask(id: string) {
  _tasks = _tasks.filter(t => t.id !== id);
  notifyAll();
}

export function useBackgroundTasks() {
  const [tasks, setTasks] = useState<BackgroundTask[]>(_tasks);
  const setTasksRef = useRef(setTasks);
  setTasksRef.current = setTasks;

  useEffect(() => {
    const fn = (t: BackgroundTask[]) => setTasksRef.current(t);
    _listeners.add(fn);
    return () => { _listeners.delete(fn); };
  }, []);

  const add = useCallback(addTask, []);
  const update = useCallback(updateTask, []);
  const remove = useCallback(removeTask, []);

  return { tasks, addTask: add, updateTask: update, removeTask: remove };
}
