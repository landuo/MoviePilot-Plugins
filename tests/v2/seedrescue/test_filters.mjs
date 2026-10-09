import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizeFilters, statusQuery } from '../../../plugins.v2/seedrescue/src/utils/filters.js'

test('empty and cleared filters are omitted, including blank numeric fields', () => {
  assert.deepEqual(normalizeFilters({
    state: null, promotion: '', source_promotion: null, source_site_id: undefined, min_seeders: '', max_seeders: null,
  }), {})
  assert.equal(statusQuery('current', 1, 20, {}), 'view=current&page=1&page_size=20')
})

test('both views and every page send both promotion filters with zero preserved and keyword removed', () => {
  const filters = normalizeFilters({
    keyword: 'obsolete keyword', state: 'AWAITING_SELECTION', promotion: 'free', source_promotion: 'non_free', source_site_id: 7,
    min_seeders: '0', max_seeders: '2',
  })
  assert.equal(filters.min_seeders, 0)
  for (const view of ['current', 'history']) {
    for (const page of [1, 5]) {
      const query = new URLSearchParams(statusQuery(view, page, 20, filters))
      assert.equal(query.get('view'), view)
      assert.equal(query.get('page'), String(page))
      assert.equal(query.has('keyword'), false)
      assert.equal(query.get('source_promotion'), 'non_free')
      for (const [key, value] of Object.entries(filters)) assert.equal(query.get(key), String(value))
    }
  }
})

test('invalid ranges do not silently broaden the selection', () => {
  for (const value of [-1, 1.5, 'invalid', Infinity, false, []]) {
    assert.throws(() => normalizeFilters({ min_seeders: value }), /非负整数/)
  }
  assert.throws(() => normalizeFilters({ min_seeders: 5, max_seeders: 0 }), /不能大于/)
})
