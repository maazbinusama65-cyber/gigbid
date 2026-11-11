export function money(n: number | null | undefined, currency = "USD"): string {
  if (n == null) return "n/a";
  return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 0 }).format(n);
}

export function budgetLabel(b: { type: string; min: number | null; max: number | null; currency: string }): string {
  const unit = b.type === "hourly" ? "/hr" : "";
  if (b.min != null && b.max != null && b.min !== b.max) return `${money(b.min, b.currency)} – ${money(b.max, b.currency)}${unit}`;
  return `${money(b.max ?? b.min, b.currency)}${unit}`;
}

export function pct(n: number, digits = 0): string {
  return `${(n * 100).toFixed(digits)}%`;
}

export function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 48) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

export function shortDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" });
}

export function ms(n: number | null | undefined): string {
  if (n == null) return "";
  return n >= 1000 ? `${(n / 1000).toFixed(1)}s` : `${n}ms`;
}

export function usd(n: number, digits = 4): string {
  return `$${n.toFixed(digits)}`;
}

export function paragraphsOf(text: string): string[] {
  return text.split(/\n{2,}/);
}
