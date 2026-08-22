import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const NODE = new URL('../src/components/RequirementGroupNode.tsx', import.meta.url);
const OPTIONS = new URL('../src/components/TechnicalElectiveCandidates.tsx', import.meta.url);

test('course options are nested only under the Technical Electives source rule', async () => {
  const source = await readFile(NODE, 'utf8');
  assert.match(source, /group\.coursedog_rule_id === 'AjzAZTn4'/);
  assert.match(source, /<TechnicalElectiveCandidates requirementGroupId=\{group\.id\}/);
});

test('candidate list is explicit, collapsed, bounded, and non-persisting', async () => {
  const source = await readFile(OPTIONS, 'utf8');
  assert.match(source, /useState\(false\)/);
  assert.match(source, /View course options/);
  assert.match(source, /slice\(0, 6\)/);
  assert.match(source, /View all \$\{result\.candidates\.length\} options/);
  assert.match(source, /Adviser approval is required/);
  assert.doesNotMatch(source, /supabase|addPlanned|persist|method:\s*'POST'/i);
});
