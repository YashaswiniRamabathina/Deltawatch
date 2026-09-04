export function parseInstant(dateStr) {
  if (!dateStr) return null;
  const hasOffset = /Z$|[+-]\d{2}:\d{2}$/.test(dateStr);
  return new Date(hasOffset ? dateStr : `${dateStr}Z`);
}

export function formatPrice(symbol, price) {
  if (price == null) return '—';
  const n = Number(price).toFixed(2);
  if (typeof symbol === 'string' && (symbol.endsWith('.NS') || symbol.endsWith('.BO'))) {
    return `₹${n}`;
  }
  return `$${n}`;
}
