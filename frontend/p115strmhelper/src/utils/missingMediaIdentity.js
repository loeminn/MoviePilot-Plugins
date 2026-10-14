const sources = {
  themoviedb: ['TMDB', 'tmdbid'],
  douban: ['豆瓣', 'doubanid'],
  tvdb: ['TVDB', 'tvdbid'],
  imdb: ['IMDB', 'imdbid'],
  bangumi: ['Bangumi'],
  anilist: ['AniList'],
  anidb: ['AniDB'],
  musicbrainz: ['MusicBrainz'],
};

export const hasNativeMediaId = (item) =>
  Boolean(item.media_source && String(item.media_id ?? '').trim() && String(item.media_id).trim() !== '0');

export const nativeMediaIdLabel = (item) => {
  if (!hasNativeMediaId(item)) return '';
  const [label, legacyKey] = Object.hasOwn(sources, item.media_source)
    ? sources[item.media_source]
    : [item.media_source];
  if (legacyKey && String(item[legacyKey] ?? '') === String(item.media_id)) return '';
  return `${label}: ${item.media_id}`;
};
