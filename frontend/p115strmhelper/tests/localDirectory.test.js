import assert from 'node:assert/strict';
import test from 'node:test';
import { browseLocalDirectory } from '../src/utils/localDirectory.js';
import { useDirSelector } from '../src/components/composables/useDirSelector.js';

const files = [
  { name: 'folder10', path: '/folder10', type: 'dir' },
  { name: 'movie.mkv', path: '/movie.mkv', type: 'file' },
  { name: 'folder2', path: '/folder2', type: 'dir' },
];
const expected = [
  { name: 'folder2', path: '/folder2', is_dir: true },
  { name: 'folder10', path: '/folder10', is_dir: true },
];

test('V3 response filters files, sorts directories and sends the selected path', async () => {
  const api = { post: async (url, body) => {
    assert.equal(url, 'storage/list');
    assert.equal(body.path, '/media');
    return { success: true, message: '', data: files };
  } };
  assert.deepEqual(await browseLocalDirectory(api, '/media'), expected);
});

test('empty V3 directory is a successful result and blank path uses root', async () => {
  const api = { post: async (_, body) => {
    assert.equal(body.path, '/');
    return { success: true, message: '', data: [] };
  } };
  assert.deepEqual(await browseLocalDirectory(api, ''), []);
});

test('legacy bare arrays remain supported', async () => {
  assert.deepEqual(await browseLocalDirectory({ post: async () => files }, '/'), expected);
});

test('host business failure retains the original message', async () => {
  await assert.rejects(browseLocalDirectory({ post: async () => ({
    success: false, message: '没有目录访问权限', data: [],
  }) }, '/'), /没有目录访问权限/);
});

test('malformed responses and network failures are not treated as empty directories', async () => {
  for (const response of [null, {}, { success: true, data: null }, { success: true, data: {} }]) {
    await assert.rejects(browseLocalDirectory({ post: async () => response }, '/'), /无效响应/);
  }
  await assert.rejects(browseLocalDirectory({ post: async () => { throw new Error('网络错误'); } }, '/'), /网络错误/);
});

test('config selector consumes the V3 directory result and resets loading', async () => {
  const selector = useDirSelector({ post: async () => ({ success: true, message: '', data: files }) }, {}, {}, 'P115StrmHelper', {});
  await selector.loadDirContent();
  assert.deepEqual([...selector.dirDialog.items], expected);
  assert.equal(selector.dirDialog.error, null);
  assert.equal(selector.dirDialog.loading, false);
});
