export const query = (q: string, brand?: string) => ({
  query: { bool: { must: [{ multi_match: { query: q, fields: ['title^3', 'body'], fuzziness: 'AUTO' } }], filter: brand ? [{ term: { brand } }] : [] } },
  aggs: { brands: { terms: { field: 'brand' } } },
});
