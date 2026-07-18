// Fixed-width timestamp formatting. toLocaleString("zh-TW") produces
// 上午/下午 prefixes and unpadded digits, so stacked timestamps never line
// up; a zero-padded 24h form keeps every row the same width (paired with
// tabular-nums in the CSS).
export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (value: number) => String(value).padStart(2, "0");
  return (
    `${date.getFullYear()}/${pad(date.getMonth() + 1)}/${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  );
}
