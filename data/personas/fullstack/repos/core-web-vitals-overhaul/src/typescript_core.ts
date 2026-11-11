export interface CoreWebVitalsOverhaulItem {
  id: string;
  status: 'active' | 'paused' | 'cancelled';
  updatedAt: string;
}

export function runCore(x: CoreWebVitalsOverhaulItem): boolean {
  return x.status === 'active';
}
