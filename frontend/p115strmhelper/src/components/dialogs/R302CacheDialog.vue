<template>
  <v-dialog :model-value="modelValue" :persistent="busy" max-width="1150"
    @update:model-value="$emit('update:modelValue', $event)">
    <v-card>
      <v-card-title>直链缓存</v-card-title>
      <v-card-text class="cache-dialog-body">
        <p class="text-caption mb-3">仅管理 302 直链缓存。删除后，再次播放时会重新获取直链。</p>
        <p class="text-caption mb-3">缓存到期时间按本地时区显示，比直链失效时间提前 5 分钟。</p>
        <form class="d-flex flex-wrap ga-2 mb-3" @submit.prevent="search(searchText)">
          <v-text-field v-model="searchText" label="搜索文件名、缓存标识、UA 或直链" density="compact"
            variant="outlined" hide-details :disabled="busy" maxlength="2048" class="cache-search" />
          <v-btn type="submit" :disabled="busy" variant="tonal">搜索</v-btn>
          <v-btn :disabled="busy" :loading="loading" @click="refresh">刷新</v-btn>
          <v-btn color="error" :disabled="busy || !selected.length" @click="requestDelete(selected)">
            删除所选（{{ selected.length }}）
          </v-btn>
        </form>
        <v-alert v-if="error" type="error" variant="tonal" class="mb-3">{{ error }}</v-alert>
        <v-alert v-if="notice" :type="noticeType" variant="tonal" class="mb-3">{{ notice }}</v-alert>
        <v-progress-linear v-if="loading" indeterminate color="primary" />
        <div class="cache-table-scroll">
          <v-table density="compact">
            <thead><tr>
              <th><v-checkbox-btn :model-value="allSelected" :indeterminate="selected.length > 0 && !allSelected"
                :disabled="busy || !items.length" aria-label="选择当前页全部缓存" @update:model-value="toggleAll" /></th>
              <th>文件名</th><th>文件缓存标识</th><th>User-Agent</th><th>缓存到期时间</th><th>直链</th><th>操作</th>
            </tr></thead>
            <tbody>
              <tr v-for="item in items" :key="item.key">
                <td><v-checkbox-btn v-model="selected" :value="item.key" :disabled="busy"
                  :aria-label="`选择 ${item.file_name}`" /></td>
                <td><span class="cache-cell" :title="item.file_name">{{ item.file_name }}</span></td>
                <td><span class="cache-cell" :title="item.pick_code">{{ item.pick_code }}</span></td>
                <td><span class="cache-cell" :title="item.user_agent">{{ item.user_agent }}</span></td>
                <td><span class="cache-expiry">{{ formatCacheExpiry(item.expires_at) }}</span></td>
                <td><span class="cache-cell" :title="item.url">{{ item.url }}</span>
                  <v-btn variant="text" size="small" @click="detail = item">查看直链</v-btn></td>
                <td><v-btn color="error" variant="text" size="small" :disabled="busy"
                  @click="requestDelete([item.key])">删除</v-btn></td>
              </tr>
              <tr v-if="!items.length && !loading"><td colspan="7" class="text-center py-6">
                {{ error ? '列表加载失败，请重试' : '暂无匹配的有效直链缓存' }}
              </td></tr>
            </tbody>
          </v-table>
        </div>
        <div class="text-caption mt-2">共 {{ total }} 条，每页 20 条</div>
        <v-pagination :model-value="page" :length="pages" :total-visible="5" :disabled="busy"
          @update:model-value="changePage" />
      </v-card-text>
      <v-card-actions><v-spacer /><v-btn :disabled="busy" @click="$emit('update:modelValue', false)">关闭</v-btn></v-card-actions>
    </v-card>
    <v-dialog :model-value="pending.length > 0" :persistent="deleting" max-width="420"
      @update:model-value="value => { if (!value && !deleting) pending = []; }">
      <v-card title="删除直链缓存">
        <v-card-text>确认删除所选 {{ pending.length }} 条缓存？不会删除网盘文件。</v-card-text>
        <v-card-actions><v-spacer /><v-btn :disabled="deleting" @click="pending = []">取消</v-btn>
          <v-btn color="error" :loading="deleting" :disabled="deleting" @click="confirmDelete">确认删除</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
    <v-dialog :model-value="!!detail" max-width="750" @update:model-value="value => { if (!value) detail = null; }">
      <v-card title="完整直链">
        <v-card-text v-if="detail">
          <div class="cache-detail mb-3">{{ detail.file_name }}</div>
          <div class="text-caption cache-detail mb-3">{{ detail.user_agent }}</div>
          <div class="text-caption mb-3">缓存到期时间：{{ formatCacheExpiry(detail.expires_at) }}</div>
          <v-textarea :model-value="detail.url" label="直链 URL" readonly auto-grow variant="outlined" />
          <v-alert v-if="copyMessage" type="info" variant="tonal">{{ copyMessage }}</v-alert>
        </v-card-text>
        <v-card-actions><v-spacer /><v-btn @click="copyUrl">复制直链</v-btn><v-btn @click="detail = null">关闭</v-btn></v-card-actions>
      </v-card>
    </v-dialog>
  </v-dialog>
</template>

<script setup>
import { computed, inject, ref, watch } from 'vue';
import { useR302Cache } from '../composables/useR302Cache.js';
import { formatCacheExpiry } from '../../utils/r302CacheDisplay.js';

const props = defineProps({ modelValue: Boolean });
defineEmits(['update:modelValue']);
const { items, total, page, selected, pending, loading, deleting, error, notice, noticeType,
  busy, pages, refresh, search, changePage, requestDelete, confirmDelete } = useR302Cache(inject('api'));
const searchText = ref('');
const detail = ref(null);
const copyMessage = ref('');
const allSelected = computed(() => items.value.length > 0 && selected.value.length === items.value.length);
function toggleAll(value) {
  selected.value = value ? items.value.map(item => item.key) : [];
}
async function copyUrl() {
  try {
    await navigator.clipboard.writeText(detail.value.url);
    copyMessage.value = '直链已复制';
  } catch {
    copyMessage.value = '无法自动复制，请选中上方完整直链手动复制';
  }
}
watch(detail, () => { copyMessage.value = ''; });
watch(() => props.modelValue, value => {
  if (value) {
    searchText.value = '';
    search('');
  } else {
    detail.value = null;
    pending.value = [];
  }
});
</script>

<style scoped>
.cache-dialog-body { max-height: 75vh; overflow-y: auto; }
.cache-search { flex: 1 1 280px; }
.cache-table-scroll { overflow-x: auto; }
.cache-table-scroll th { white-space: nowrap; }
.cache-cell { display: block; max-width: 210px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cache-detail { overflow-wrap: anywhere; }
.cache-expiry { white-space: nowrap; }
</style>
