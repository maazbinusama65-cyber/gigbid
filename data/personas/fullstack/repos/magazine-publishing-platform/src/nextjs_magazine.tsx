export const revalidate = 60;

export default async function Page() {
  const res = await fetch(process.env.API_URL + '/magazine_publishing_platform', { next: { revalidate } });
  const data = await res.json();
  return <pre>{JSON.stringify(data, null, 2)}</pre>;
}
