export interface OperationsAdminDashboardItem {
  id: string;
  status: 'active' | 'paused' | 'cancelled';
  updatedAt: string;
}

export function scoreOperations(x: OperationsAdminDashboardItem): boolean {
  return x.status === 'active';
}
