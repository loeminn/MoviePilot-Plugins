/** 浏览宿主本地目录，解析 V3 envelope 及旧版裸数组响应 */
export async function browseLocalDirectory(api, path) {
  const response = await api.post('storage/list', {
    path: path || '/', type: 'share', flag: 'ROOT',
  });
  if (response?.success === false) {
    throw new Error(response.message || '浏览目录失败');
  }
  const items = Array.isArray(response) ? response : response?.data;
  if (!Array.isArray(items)) {
    throw new Error('浏览目录失败：无效响应');
  }
  return items
    .filter(item => item.type === 'dir')
    .map(item => ({ name: item.name, path: item.path, is_dir: true }))
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }));
}
