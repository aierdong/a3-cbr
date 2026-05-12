<template>
  <div class="case-table-wrap">
    <div class="table-scroll">
      <table class="case-table" data-testid="case-table">
        <thead>
          <tr>
            <th>案例标识</th>
            <th>问题描述预览</th>
            <th>品牌</th>
            <th>门店</th>
            <th>问题类型</th>
            <th>状态</th>
            <th>标签</th>
            <th>创建时间</th>
            <th>更新时间</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.case_id">
            <td class="mono">{{ row.case_id }}</td>
            <td class="preview">{{ row.problem_description_preview }}</td>
            <td>{{ row.store_profile.brand_name }} ({{ row.store_profile.brand_id }})</td>
            <td>{{ row.store_profile.store_name }} ({{ row.store_profile.store_id }})</td>
            <td>{{ formatProblemType(row.problem_type) }}</td>
            <td>{{ formatStatus(row.status) }}</td>
            <td>{{ formatTags(row) }}</td>
            <td class="nowrap">{{ formatDt(row.created_at) }}</td>
            <td class="nowrap">{{ formatDt(row.updated_at) }}</td>
            <td>
              <router-link class="link" :to="{ name: 'case-detail', params: { id: row.case_id } }">
                详情
              </router-link>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="loadMoreErrorMessage" class="load-more-error" role="alert">
      <ErrorNotice :message="loadMoreErrorMessage" :show-retry="true" @retry="$emit('retry-load-more')" />
    </div>

    <div v-if="showLoadMore" class="load-more-row">
      <button
        type="button"
        class="load-more-btn"
        data-testid="load-more"
        :disabled="loadMoreButtonDisabled"
        @click="$emit('load-more')"
      >
        {{ loadMoreButtonLabel }}
      </button>
    </div>

    <p v-if="pageMetaLine" class="page-meta" data-testid="page-meta">{{ pageMetaLine }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { CaseListItem, PaginatedCaseListResponse } from '@/api/cases'
import ErrorNotice from '@/components/common/ErrorNotice.vue'

type CaseListRow = CaseListItem & { tags?: string[] }

const props = defineProps<{
  rows: CaseListRow[]
  hasNextPage: boolean
  isLoadingMore: boolean
  loadMoreErrorMessage?: string
  lastPageMeta: PaginatedCaseListResponse | null
}>()

defineEmits<{
  'load-more': []
  'retry-load-more': []
}>()

const loadMoreButtonLabel = computed(() => {
  if (props.isLoadingMore) return '加载中...'
  if (props.loadMoreErrorMessage) return '重试'
  return '加载更多'
})

const loadMoreButtonDisabled = computed(() => props.isLoadingMore)

const showLoadMore = computed(() => {
  if (props.rows.length === 0) return false
  return props.hasNextPage || Boolean(props.loadMoreErrorMessage)
})

const pageMetaLine = computed(() => {
  const m = props.lastPageMeta
  if (!m) return ''
  const next =
    m.next_cursor_created_at && m.next_cursor_case_id
      ? `下一页游标：${m.next_cursor_created_at} / ${m.next_cursor_case_id}`
      : '无下一页游标'
  return `每页 ${m.limit} 条 · ${next} · 排序：${m.sort}`
})

const problemLabels: Record<string, string> = {
  service: '服务',
  quality: '质量',
  operation: '运营',
  hygiene: '卫生',
  staffing: '人力',
  other: '其他',
}

const statusLabels: Record<string, string> = {
  draft: '草稿',
  active: '生效',
  archived: '归档',
}

function formatProblemType(v: string): string {
  return problemLabels[v] ?? v
}

function formatStatus(v: string): string {
  return statusLabels[v] ?? v
}

function formatTags(row: CaseListRow): string {
  if (row.tags?.length) return row.tags.join('、')
  return '—'
}

function formatDt(iso: string): string {
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}
</script>

<style scoped>
.case-table-wrap {
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  overflow: hidden;
}

.table-scroll {
  overflow-x: auto;
}

.case-table {
  min-width: 960px;
}

.mono {
  font-family: ui-monospace, monospace;
  font-size: 12px;
}

.preview {
  max-width: 280px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nowrap {
  white-space: nowrap;
  font-size: 12px;
}

.link {
  color: #1976d2;
}

.load-more-row {
  padding: 12px 16px;
  border-top: 1px solid #eee;
}

.load-more-btn {
  padding: 8px 16px;
  border-radius: 4px;
  border: 1px solid #1976d2;
  background: #fff;
  color: #1976d2;
  cursor: pointer;
}

.load-more-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.load-more-error {
  padding: 8px 16px 0;
}

.page-meta {
  padding: 8px 16px 12px;
  font-size: 12px;
  color: #666;
  border-top: 1px solid #f0f0f0;
  margin: 0;
}
</style>
