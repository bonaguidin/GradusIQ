// Locale-aware replacement for value.toFixed(decimals) -- Intl.NumberFormat
// renders the decimal separator (and digit grouping, for anything past 999)
// the way the viewer's own locale expects, instead of always assuming
// en-US's "." the way toFixed() does. format.test.mjs pins it.

const formatterCache = new Map();

function fixedFormatter(decimals) {
  let formatter = formatterCache.get(decimals);
  if (!formatter) {
    formatter = new Intl.NumberFormat(undefined, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
    formatterCache.set(decimals, formatter);
  }
  return formatter;
}

/** Same shape as `value.toFixed(decimals)`, but through Intl so the locale is real. */
export function formatFixed(value, decimals) {
  return fixedFormatter(decimals).format(value);
}
