import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../../plugins.v3/p115strmhelper/helper/hdhive/browser.py', import.meta.url), 'utf8');
const method = source.slice(source.indexOf('def _stealth_init_script()'));
const match = method.match(/return """([\s\S]*?)"""/);
assert.ok(match, 'actual browser initialization script must be present');

test('notification permission queries use the browser Notification API', async () => {
  for (const permission of ['default', 'granted', 'denied']) {
    const navigator = { permissions: { query() { throw new Error('unexpected delegation'); } } };
    const context = { navigator, window: { navigator }, Notification: { permission } };
    vm.runInNewContext(match[1], context);
    const result = await navigator.permissions.query({ name: 'notifications' });
    assert.equal(result.state, permission);
  }
});

test('other permission queries retain the original receiver and parameters', async () => {
  const parameters = { name: 'geolocation' };
  const result = { state: 'prompt' };
  const permissions = { query(received) {
    assert.equal(this, permissions);
    assert.equal(received, parameters);
    return Promise.resolve(result);
  } };
  const navigator = { permissions };
  vm.runInNewContext(match[1], { navigator, window: { navigator }, Notification: { permission: 'default' } });
  assert.equal(await permissions.query(parameters), result);
});

test('initialization tolerates browsers without the Permissions API', () => {
  const navigator = {};
  vm.runInNewContext(match[1], { navigator, window: { navigator } });
});
