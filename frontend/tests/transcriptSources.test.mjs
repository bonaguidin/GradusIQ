import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { GENERIC_TRANSCRIPT_STEPS, isAcceptedTranscriptFile, transcriptSourceFor } from '../src/lib/transcriptSources.mjs'

test('known schools resolve to their portal', () => {
  assert.equal(transcriptSourceFor('Texas A&M University').portalUrl, 'https://howdy.tamu.edu')
  assert.equal(transcriptSourceFor('Southern Methodist University').portalUrl, 'https://my.smu.edu')
  assert.equal(transcriptSourceFor('Southern Methodist University').steps.length, 3)
})

test('unknown or missing schools fall back to generic steps', () => {
  assert.equal(transcriptSourceFor('University of Texas at Austin'), null)
  assert.equal(transcriptSourceFor(null), null)
  assert.equal(transcriptSourceFor('  '), null)
  assert.equal(GENERIC_TRANSCRIPT_STEPS.length, 3)
})

test('drop accepts only what the upload route accepts', () => {
  assert.equal(isAcceptedTranscriptFile('transcript.PDF'), true)
  assert.equal(isAcceptedTranscriptFile('record.docx'), true)
  assert.equal(isAcceptedTranscriptFile('scan.png'), false)
  assert.equal(isAcceptedTranscriptFile('old.doc'), false)
  assert.equal(isAcceptedTranscriptFile(undefined), false)
})

test('upload copy no longer promises Canvas & Blackboard sync', async () => {
  for (const file of ['../src/components/TranscriptUpload.tsx', '../src/components/GuidedTour.tsx']) {
    const source = await readFile(new URL(file, import.meta.url), 'utf8')
    assert.doesNotMatch(source, /Blackboard sync is coming soon/)
  }
})
