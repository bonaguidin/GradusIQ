// "1 term", "3 terms", "1 confirmed course" -- a count with its noun agreeing.
// countLabel.test.mjs pins it.

export function countLabel(count, singular, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}
