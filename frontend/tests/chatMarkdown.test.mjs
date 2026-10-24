import test from 'node:test'
import assert from 'node:assert/strict'
import { parseChatMarkdown, parseInline } from '../src/lib/chatMarkdown.mjs'

test('paragraphs, bullet and numbered lists', () => {
  const blocks = parseChatMarkdown('Here is the plan:\n\n- Take CS 3341\n- Drop MATH 2339\n\n1. First\n2. Second\nThanks')
  assert.deepEqual(blocks.map((b) => b.type), ['p', 'ul', 'ol', 'p'])
  assert.equal(blocks[1].items.length, 2)
  assert.deepEqual(blocks[1].items[0], [{ type: 'text', text: 'Take CS 3341' }])
})

test('consecutive lines stay in one paragraph as separate lines', () => {
  const [p] = parseChatMarkdown('one\ntwo')
  assert.equal(p.type, 'p')
  assert.equal(p.lines.length, 2)
})

test('bold, italic, code and a heading', () => {
  assert.deepEqual(parseInline('GPA is **3.42** now'), [
    { type: 'text', text: 'GPA is ' },
    { type: 'strong', children: [{ type: 'text', text: '3.42' }] },
    { type: 'text', text: ' now' },
  ])
  assert.deepEqual(parseInline('*soon* `CS 1341`'), [
    { type: 'em', children: [{ type: 'text', text: 'soon' }] },
    { type: 'text', text: ' ' },
    { type: 'code', text: 'CS 1341' },
  ])
  const [heading] = parseChatMarkdown('## Next steps')
  assert.equal(heading.lines[0][0].type, 'strong')
})

test('links are kept only for in-app paths and https', () => {
  assert.deepEqual(parseInline('[GPA](/dashboard?section=academic)'), [
    { type: 'link', href: '/dashboard?section=academic', children: [{ type: 'text', text: 'GPA' }] },
  ])
  assert.equal(parseInline('[SMU](https://smu.edu)')[0].type, 'link')
  for (const href of ['javascript:alert(1)', 'data:text/html,x', 'http://smu.edu', '//evil.example', 'mailto:a@b.c']) {
    const nodes = parseInline(`[click](${href})`)
    assert.ok(nodes.every((n) => n.type === 'text'), href)
    assert.equal(nodes[0].text, 'click', href)
  }
})

test('markup in the text stays literal text', () => {
  const [p] = parseChatMarkdown('<img src=x onerror=alert(1)>')
  assert.deepEqual(p.lines[0], [{ type: 'text', text: '<img src=x onerror=alert(1)>' }])
})
