export interface ModelDemoWebAppItem {
  id: string;
  status: 'active' | 'paused' | 'cancelled';
  updatedAt: string;
}

export function loadModel(x: ModelDemoWebAppItem): boolean {
  return x.status === 'active';
}
