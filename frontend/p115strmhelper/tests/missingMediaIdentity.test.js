import assert from 'node:assert/strict';
import test from 'node:test';
import { hasNativeMediaId, nativeMediaIdLabel } from '../src/utils/missingMediaIdentity.js';

test('失效分享记录展示原生媒体来源和编号', () => {
  for (const [source, label] of [['bangumi', 'Bangumi'], ['anilist', 'AniList'], ['anidb', 'AniDB'], ['musicbrainz', 'MusicBrainz'], ['custom', 'custom']]) {
    assert.equal(nativeMediaIdLabel({ media_source: source, media_id: '123' }), `${label}: 123`);
  }
});

test('兼容旧记录并避免重复展示同一编号', () => {
  assert.equal(nativeMediaIdLabel({ tmdbid: '123' }), '');
  assert.equal(nativeMediaIdLabel({ media_source: 'themoviedb', media_id: 123, tmdbid: '123' }), '');
  assert.equal(nativeMediaIdLabel({ media_source: 'themoviedb', media_id: '123' }), 'TMDB: 123');
  assert.equal(nativeMediaIdLabel({ media_source: 'douban', media_id: '123', tmdbid: '123' }), '豆瓣: 123');
});

test('空来源、空编号及零编号不显示', () => {
  for (const media_id of [null, undefined, '', ' ', 0, '0']) {
    assert.equal(hasNativeMediaId({ media_source: 'bangumi', media_id }), false);
    assert.equal(nativeMediaIdLabel({ media_source: 'bangumi', media_id }), '');
  }
  assert.equal(hasNativeMediaId({ media_id: '123' }), false);
});

test('自定义来源与对象原型属性同名时仍能展示', () => {
  for (const source of ['constructor', '__proto__', 'toString']) {
    assert.equal(nativeMediaIdLabel({ media_source: source, media_id: '123' }), `${source}: 123`);
  }
});
