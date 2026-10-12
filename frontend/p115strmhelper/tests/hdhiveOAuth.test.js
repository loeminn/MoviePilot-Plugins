import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/components/composables/useHdhiveOAuth.js', import.meta.url), 'utf8')
  .replace(/^import .* from 'vue';\r?\n/m, '')
  .replace('export function useHdhiveOAuth', 'function useHdhiveOAuth');

function createOAuth() {
  const calls = [];
  const listeners = new Map();
  const message = {};
  const popup = { closed: false, close() { this.closed = true; } };
  const context = {
    URL, console,
    reactive: value => value,
    onMounted: callback => callback(),
    onUnmounted: () => {},
    setTimeout: () => 1,
    clearTimeout: () => {},
    window: {
      addEventListener: (name, callback) => listeners.set(name, callback),
      open: () => popup,
    },
    message,
    api: {
      get: async path => path.endsWith('/start')
        ? { code: 0, data: {
          authorize_url: 'https://re0.me/oauth/authorize',
          redirect_uri: 'https://broker.example/callback', state: 'expected-state',
        } }
        : { code: 0, data: { auth_mode: 'oauth' } },
      post: async (path, data) => {
        calls.push({ path, data });
        return { code: 0 };
      },
    },
  };
  const oauth = vm.runInNewContext(`${source}\nuseHdhiveOAuth(api, message, 'P115StrmHelper')`, context);
  const receive = async (origin, state = 'expected-state') => {
    listeners.get('message')({ origin, data: { code: 'test-code', state } });
    await new Promise(resolve => setImmediate(resolve));
  };
  return { oauth, calls, message, popup, receive };
}

test('RE0 and the configured callback origin can complete pending OAuth', async () => {
  for (const origin of ['https://re0.me', 'https://broker.example']) {
    const { oauth, calls, popup, receive } = createOAuth();
    await oauth.startOAuth();
    await receive(origin);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].path, 'plugin/P115StrmHelper/hdhive/oauth/complete');
    assert.equal(calls[0].data.redirect_uri, 'https://broker.example/callback');
    assert.equal(calls[0].data.state, 'expected-state');
    assert.equal(oauth.oauth.pending, false);
    assert.equal(popup.closed, true);
  }
});

test('old HDHive and unrelated origins cannot complete OAuth', async () => {
  const { oauth, calls, receive } = createOAuth();
  await oauth.startOAuth();
  for (const origin of ['https://hdhive.com', 'https://re0.me.attacker.example', 'https://unrelated.example']) {
    await receive(origin);
  }
  assert.equal(calls.length, 0);
  assert.equal(oauth.oauth.pending, true);
});

test('OAuth rejects mismatched state from an allowed origin', async () => {
  const { oauth, calls, message, receive } = createOAuth();
  await oauth.startOAuth();
  await receive('https://re0.me', 'wrong-state');
  assert.equal(calls.length, 0);
  assert.equal(message.type, 'error');
  assert.match(message.text, /state/);
});

test('OAuth messages outside a pending request are ignored', async () => {
  const { calls, receive } = createOAuth();
  await receive('https://re0.me');
  assert.equal(calls.length, 0);
});
