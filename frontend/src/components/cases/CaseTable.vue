<template>
  <div class="case-table-wrap">
    <div class="table-scroll">
      <table class="case-table" data-testid="case-table">
        <thead>
          <tr>
            <th>CASE_ID</th>
            <th>问题描述</th>
            <th>品牌</th>
            <th>问题类型</th>
            <th>场景</th>
            <th>创建时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.case_id">
            <td>{{ row.case_id }}</td>
            <td class="preview-cell">
              <router-link
                class="preview-link"
                :to="{ name: 'case-detail', params: { id: row.case_id } }"
                :title="listItemProblemPreview(row) || '查看案例详情'"
              >
                {{ problemDescCellText(row) }}
              </router-link>
            </td>
            <td class="brand">{{ formatBrandName(row) }}</td>
            <td class="problem-type">{{ formatCaseProblemType(row.problem_type) }}</td>
            <td class="scene">{{ formatScene(row) }}</td>
            <td class="nowrap time">{{ formatDt(row.created_at) }}</td>
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
import type { PaginatedCaseListResponse } from '@/api/cases'
import ErrorNotice from '@/components/common/ErrorNotice.vue'
import {
  listItemContextScene,
  listItemProblemPreview,
  listItemStore,
  type CaseListRowApi,
} from '@/domain/caseListDisplay'
import { formatCaseProblemType } from '@/domain/caseProblemType'

type CaseListRow = CaseListRowApi & { tags?: string[] }

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

function problemDescCellText(row: CaseListRow): string {
  const t = listItemProblemPreview(row).trim()
  return t || '（无摘要）'
}

function formatBrandName(row: CaseListRow): string {
  const s = listItemStore(row)
  return s?.brand_name?.trim() ? s.brand_name : '—'
}

function formatScene(row: CaseListRow): string {
  const s = listItemContextScene(row).trim()
  return s || '—'
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
  min-width: 640px;
}

.preview-cell {
  max-width: 280px;
  vertical-align: top;
}

.preview-link {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  overflow: hidden;
  word-break: break-word;
  line-height: 1.35;
  color: #1976d2;
  text-decoration: none;
  white-space: normal;
}

.preview-link:hover {
  text-decoration: underline;
}

.brand {
  width: 100px;
  min-width: 100px;
  max-width: 100px;
}

.problem-type {
  width: 100px;
  min-width: 100px;
  max-width: 100px;
}

.scene {
  width: 300px;
  min-width: 300px;
  max-width: 300px;
  font-size: 13px;
  line-height: 1.35;
}

.time {
  width: 140px;
  min-width: 140px;
  max-width: 140px;
}

.nowrap {
  white-space: nowrap;
  font-size: 12px;
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
