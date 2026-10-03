import { computed, ref } from 'vue';
import { P115_STRM_HELPER_PLUGIN_ID } from '../../utils/pluginId.js';

export function useR302Cache(api) {
  const items = ref([]);
  const total = ref(0);
  const page = ref(1);
  const keyword = ref('');
  const selected = ref([]);
  const pending = ref([]);
  const loading = ref(false);
  const deleting = ref(false);
  const error = ref('');
  const notice = ref('');
  const noticeType = ref('success');
  const busy = computed(() => loading.value || deleting.value);
  const pages = computed(() => Math.max(1, Math.ceil(total.value / 20)));
  const base = `plugin/${P115_STRM_HELPER_PLUGIN_ID}`;

  async function load() {
    loading.value = true;
    error.value = '';
    selected.value = [];
    try {
      const query = new URLSearchParams({ keyword: keyword.value, page: String(page.value), page_size: '20' });
      const result = await api.get(`${base}/list_302_cache?${query}`);
      if (!result || result.code !== 0 || !result.data) throw new Error(result?.msg || '获取缓存失败');
      items.value = result.data.items;
      total.value = result.data.total;
      page.value = result.data.page;
    } catch (err) {
      items.value = [];
      total.value = 0;
      page.value = 1;
      error.value = `获取缓存失败：${err.message || '未知错误'}`;
    } finally {
      loading.value = false;
    }
  }

  async function refresh() {
    if (busy.value) return;
    notice.value = '';
    await load();
  }

  async function search(value) {
    if (busy.value) return;
    keyword.value = value.trim();
    page.value = 1;
    await refresh();
  }

  async function changePage(value) {
    if (busy.value) return;
    page.value = value;
    await refresh();
  }

  function requestDelete(keys) {
    if (busy.value) return;
    const visible = new Set(items.value.map(item => item.key));
    pending.value = [...new Set(keys)].filter(key => visible.has(key));
  }

  async function confirmDelete() {
    if (busy.value || !pending.value.length) return;
    deleting.value = true;
    notice.value = '';
    try {
      const result = await api.post(`${base}/delete_302_cache`, { keys: [...pending.value] });
      if (!result || result.code !== 0 || !result.data) throw new Error(result?.msg || '删除缓存失败');
      noticeType.value = result.data.failed_keys.length ? 'warning' : 'success';
      notice.value = result.msg;
    } catch (err) {
      noticeType.value = 'error';
      notice.value = `删除缓存失败：${err.message || '未知错误'}`;
    } finally {
      pending.value = [];
      await load();
      deleting.value = false;
    }
  }

  return { items, total, page, selected, pending, loading, deleting, error, notice,
    noticeType, busy, pages, refresh, search, changePage, requestDelete, confirmDelete };
}
