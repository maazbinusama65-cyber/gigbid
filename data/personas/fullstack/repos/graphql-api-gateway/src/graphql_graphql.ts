export const typeDefs = `
  type Item { id: ID! title: String! price: Float! }
  type Query { items(limit: Int = 20): [Item!]! }
`;
export const resolvers = { Query: { items: (_: unknown, a: { limit: number }, ctx: any) => ctx.db.items(a.limit) } };
