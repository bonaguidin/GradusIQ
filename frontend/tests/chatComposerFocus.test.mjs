import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('the chat input stays enabled while a reply is pending so Enter keeps focus', async () => {
  const panel = await readFile(new URL('../src/components/ChatPanel.tsx', import.meta.url), 'utf8')
  const input = panel.match(/<input\s+ref=\{inputRef\}[\s\S]*?\/>/)
  assert.ok(input, 'chat input carries the focus ref')
  assert.match(input[0], /disabled=\{!canSend\}/)
  assert.doesNotMatch(input[0], /disabled=\{sending/)
  assert.match(panel, /if \(!trimmed \|\| sending \|\| !canSend\) return;/)
  assert.match(panel, /inputRef\.current\?\.focus\(\);\s*void submit\(s\);/)
})
