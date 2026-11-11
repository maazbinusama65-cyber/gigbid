export interface MagazinePublishingPlatformItem {
  id: string;
  status: 'active' | 'paused' | 'cancelled';
  updatedAt: string;
}

export function checkMagazine(x: MagazinePublishingPlatformItem): boolean {
  return x.status === 'active';
}
