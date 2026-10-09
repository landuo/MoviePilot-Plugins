import assert from 'node:assert/strict'
import test from 'node:test'
import { canSelectCandidate, chooseCandidate, matchesCandidateFilters } from '../../../plugins.v2/seedrescue/src/utils/selection.js'

const job = {
  state: 'AWAITING_SELECTION',
  candidates: [
    { candidate_id: 'paid', site_id: 7, promotion: 'non_free' },
    { candidate_id: 'free', site_id: 8, promotion: 'free' },
  ],
  target_candidate: { candidate_id: 'target', site_id: 1, is_target: true, selectable: true, promotion: 'free' },
}

test('free filter defaults to the free source, not the first paid source', () => {
  assert.equal(chooseCandidate(job, undefined, { source_promotion: 'free' }), 'free')
  assert.equal(chooseCandidate(job, undefined, {}), 'paid')
})

test('site and promotion must match one cross-site candidate; never fall back to original', () => {
  assert.equal(chooseCandidate(job, undefined, { source_site_id: '7', source_promotion: 'free' }), undefined)
  assert.equal(matchesCandidateFilters(job.target_candidate, { source_promotion: 'free' }), false)
  assert.equal(chooseCandidate(job, undefined, { source_site_id: '8', source_promotion: 'free' }), 'free')
})

test('polling preserves deliberate user choices and already submitted sources', () => {
  assert.equal(chooseCandidate(job, 'paid', { source_promotion: 'free' }), 'paid')
  assert.equal(chooseCandidate({ ...job, selected_candidate_id: 'paid' }, undefined, { source_promotion: 'free' }), 'paid')
})

test('unavailable or removed selections are replaced only with an eligible matching source', () => {
  assert.equal(chooseCandidate(job, 'removed', { source_promotion: 'free' }), 'free')
  assert.equal(chooseCandidate({ ...job, state: 'SOURCE_DOWNLOADING', target_candidate: null }, 'free', {}), undefined)
})

test('excluded cross-site sources remain filterable but cannot be selected or recommended', () => {
  const excluded = { candidate_id: 'excluded', site_id: 9, promotion: 'free', eligible: false }
  const withExcluded = { ...job, candidates: [excluded, ...job.candidates] }
  assert.equal(canSelectCandidate(withExcluded, excluded), false)
  assert.equal(matchesCandidateFilters(excluded, { source_site_id: '9', source_promotion: 'free' }), true)
  assert.equal(chooseCandidate(withExcluded, 'excluded', { source_promotion: 'free' }), 'free')
  assert.equal(chooseCandidate(withExcluded, undefined, { source_site_id: '9' }), undefined)
})
