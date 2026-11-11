export interface GraphqlApiGatewayItem {
  id: string;
  status: 'active' | 'paused' | 'cancelled';
  updatedAt: string;
}

export function buildGraphql(x: GraphqlApiGatewayItem): boolean {
  return x.status === 'active';
}
