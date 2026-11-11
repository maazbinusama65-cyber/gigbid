export function paginate<T>(rows: T[], cursor = 0, limit = 50) {
  const page = rows.slice(cursor, cursor + limit);
  return { data: page, next: cursor + limit < rows.length ? cursor + limit : null };
}
