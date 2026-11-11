import { useState } from 'react';

export function ModelDemoWebAppItem({ items }: { items: string[] }) {
  const [q, setQ] = useState('');
  const shown = items.filter((i) => i.toLowerCase().includes(q.toLowerCase()));
  return (<div><input value={q} onChange={(e) => setQ(e.target.value)} /><ul>{shown.map((i) => <li key={i}>{i}</li>)}</ul></div>);
}
