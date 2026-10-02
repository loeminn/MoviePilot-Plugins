import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/components/Page.vue', import.meta.url), 'utf8');
const start = source.indexOf('const executeShareSync = async () => {');
const end = source.indexOf('\nconst buildAvailablePaths', start);
assert.ok(start >= 0 && end > start);
const action = source.slice(start, end);

async function runShareSync(saveResponse, saveError) {
  const calls = [];
  const context = {
    props: { initialConfig: {}, api: { post: async (path) => {
      calls.push(path);
      if (path.endsWith('/save_config')) {
        if (saveError) throw saveError;
        return saveResponse;
      }
      return { code: 0 };
    } } },
    pluginId: 'P115StrmHelper',
    shareSyncLoading: { value: false },
    shareDialog: { configs: [{}], globalMediaservers: [] },
    actionMessage: {}, actionMessageType: {},
    flushShareAuditQueueToInitialConfig() {},
    flushShareInteractiveGenStrmToInitialConfig() {},
    flushShareStrmCleanupToInitialConfig() {},
    getStatus: async () => calls.push('status'),
    closeShareDialog: () => calls.push('close'),
    console: { error() {} },
  };
  await vm.runInNewContext(`${action}\nexecuteShareSync()`, context);
  assert.equal(context.shareSyncLoading.value, false);
  return { context, calls };
}

test('failed or malformed saves never start sharing or show success', async () => {
  for (const response of [{ code: 1, msg: '路由刷新失败' }, null, {}, { success: true }]) {
    const { context, calls } = await runShareSync(response);
    assert.deepEqual(calls, ['plugin/P115StrmHelper/save_config']);
    assert.match(context.shareDialog.error, /路由刷新失败|保存配置失败/);
    assert.notEqual(context.actionMessageType.value, 'success');
  }
});

test('network save failure stops sharing and resets loading', async () => {
  const { context, calls } = await runShareSync(null, new Error('网络错误'));
  assert.deepEqual(calls, ['plugin/P115StrmHelper/save_config']);
  assert.match(context.shareDialog.error, /网络错误/);
});

test('successful save starts sharing then refreshes status and closes dialog', async () => {
  const { context, calls } = await runShareSync({ code: 0 });
  assert.deepEqual(calls, [
    'plugin/P115StrmHelper/save_config', 'plugin/P115StrmHelper/share_sync', 'status', 'close',
  ]);
  assert.equal(context.shareDialog.error, null);
  assert.equal(context.actionMessageType.value, 'success');
});
