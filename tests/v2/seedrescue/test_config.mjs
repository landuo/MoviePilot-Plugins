import assert from 'node:assert/strict'
import test from 'node:test'
import { optionalLimit } from '../../../plugins.v2/seedrescue/src/utils/config.js'

test('blank and zero limits persist as null, not a default number', () => {
  for (const value of [undefined, null, '', '  ', 0, '0', ' 0 ']) {
    const payload = Object.fromEntries(['minimum_seeders', 'max_download_count', 'initial_limit']
      .map(key => [key, optionalLimit(value, key)]))
    assert.deepEqual(JSON.parse(JSON.stringify(payload)), {
      minimum_seeders: null, max_download_count: null, initial_limit: null,
    })
  }
})

test('explicit positive integer limits remain unchanged', () => {
  for (const value of [1, 5, 20, 100, '1', '5', '20', '100']) {
    assert.equal(optionalLimit(value, '限制'), Number(value))
  }
})

test('invalid input cannot silently disable a limit', () => {
  for (const value of [-1, '-1', 1.5, '1.5', 'invalid', NaN, Infinity, false, {}, []]) {
    assert.throws(() => optionalLimit(value, '同时下载数'), /同时下载数请填写非负整数/)
  }
})
