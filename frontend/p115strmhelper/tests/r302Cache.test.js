import assert from 'node:assert/strict';
import test from 'node:test';
import { useR302Cache } from '../src/components/composables/useR302Cache.js';
import { formatCacheExpiry } from '../src/utils/r302CacheDisplay.js';

test('cache expiry uses seconds and local time, unknown deadlines remain unknown', () => {
  for (const value of [null, undefined, '', '4102444500', NaN, Infinity, -1, 0, 1e20]) {
    assert.equal(formatCacheExpiry(value), '未知');
  }
  const date = new Date(2030, 5, 15, 13, 24, 56);
  assert.equal(formatCacheExpiry(date.getTime() / 1000), '2030/06/15 13:24:56');
});

const row = key => ({ key, file_name: key, url: `https://example.test/${key}` });
const response = (items, total = items.length, page = 1) => ({ code: 0, data: { items, total, page } });

test('search, refresh and page changes clear selection and use server page', async () => {
  const urls = [];
  const state = useR302Cache({ get: async url => { urls.push(url); return response([row('a')]); } });
  await state.refresh();
  state.selected.value = ['a'];
  await state.search('  电影  ');
  assert.deepEqual(state.selected.value, []);
  assert.equal(new URLSearchParams(urls.at(-1).split('?')[1]).get('keyword'), '电影');
  state.selected.value = ['a'];
  await state.changePage(2);
  assert.equal(state.page.value, 1);
  assert.deepEqual(state.selected.value, []);
});

test('delete confirmation supports cancellation, exact keys, partial failures and reload', async () => {
  const bodies = [];
  const state = useR302Cache({
    get: async () => response([row('file○UA'), row('file○UA2')]),
    post: async (url, body) => {
      assert.ok(url.endsWith('/delete_302_cache'));
      bodies.push(body);
      return { code: 0, msg: '部分失败', data: { processed_keys: ['file○UA'], failed_keys: ['file○UA2'] } };
    },
  });
  await state.refresh();
  state.requestDelete(['file○UA']);
  assert.equal(bodies.length, 0);
  state.pending.value = [];
  await state.confirmDelete();
  assert.equal(bodies.length, 0);
  state.requestDelete(['file○UA', 'file○UA', 'file○UA2', 'hidden']);
  await state.confirmDelete();
  assert.deepEqual(bodies, [{ keys: ['file○UA', 'file○UA2'] }]);
  assert.equal(state.noticeType.value, 'warning');
  assert.deepEqual(state.pending.value, []);
  assert.equal(state.items.value.length, 2);
});

test('duplicate submits blocked until deletion and reload complete', async () => {
  let release;
  let calls = 0;
  const state = useR302Cache({
    get: async () => response([row('a')]),
    post: async () => { calls++; return await new Promise(resolve => { release = resolve; }); },
  });
  await state.refresh();
  state.requestDelete(['a']);
  const deletion = state.confirmDelete();
  await state.confirmDelete();
  assert.equal(calls, 1);
  release({ code: 0, msg: '已处理', data: { processed_keys: ['a'], failed_keys: [] } });
  await deletion;
  assert.equal(state.busy.value, false);
});

test('failed requests show errors and do not retain stale selectable rows', async () => {
  const state = useR302Cache({ get: async () => { throw new Error('offline'); } });
  state.items.value = [row('stale')];
  state.selected.value = ['stale'];
  await state.refresh();
  assert.match(state.error.value, /offline/);
  assert.deepEqual(state.items.value, []);
  assert.deepEqual(state.selected.value, []);
  assert.equal(state.busy.value, false);
});

test('delete network failure reloads actual state and retains error notice', async () => {
  let reads = 0;
  const state = useR302Cache({
    get: async () => { reads++; return response([row('a')]); },
    post: async () => { throw new Error('timeout'); },
  });
  await state.refresh();
  state.requestDelete(['a']);
  await state.confirmDelete();
  assert.equal(reads, 2);
  assert.match(state.notice.value, /timeout/);
  assert.equal(state.noticeType.value, 'error');
});
