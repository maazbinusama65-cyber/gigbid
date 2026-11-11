export interface SaasBillingPortalItem {
  id: string;
  status: 'active' | 'paused' | 'cancelled';
  updatedAt: string;
}

export function syncSaas(x: SaasBillingPortalItem): boolean {
  return x.status === 'active';
}
