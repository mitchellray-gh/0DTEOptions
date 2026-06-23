// Shared display formatters used across the UI and the scanner's output strings.
export const fmt$ = (x) => '$' + Number(x).toFixed(2);
export const fmtPct = (x) => (x * 100).toFixed(1) + '%'; // one decimal
export const fmtPct0 = (x) => (x * 100).toFixed(0) + '%'; // whole percent
