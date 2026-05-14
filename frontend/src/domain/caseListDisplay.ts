/**
 * 列表 / 详情中门店块字段兼容：后端序列化为 `store`，OpenAPI 生成类型为 `store_profile`。
 * 列表另有 `problem_description` vs `problem_description_preview`。
 */

import type { CaseDetailResponse, CaseListItem } from '@/api/cases'
import type { components } from '@/api/generated/cases'

export type CaseListStoreShape = components['schemas']['StoreProfile']

/** 实际 GET /a3-cases 可能返回的列表项（契约超集） */
export type CaseListRowApi = CaseListItem & {
  store?: CaseListStoreShape & { updated_at?: string }
  problem_description?: string
}

/** 实际 GET /a3-cases/{id} 可能返回的详情（契约超集） */
export type CaseDetailResponseApi = CaseDetailResponse & {
  store?: CaseListStoreShape & { updated_at?: string }
}

export function embeddedStoreProfile(
  row: { store_profile?: CaseListStoreShape; store?: CaseListStoreShape & { updated_at?: string } },
): CaseListStoreShape | null {
  return (row.store_profile ?? row.store) ?? null
}

export function listItemStore(row: CaseListRowApi): CaseListStoreShape | null {
  return embeddedStoreProfile(row)
}

export function detailStore(detail: CaseDetailResponseApi): CaseListStoreShape | null {
  return embeddedStoreProfile(detail)
}

export function listItemProblemPreview(row: CaseListRowApi): string {
  const v = row.problem_description_preview ?? row.problem_description ?? ''
  return typeof v === 'string' ? v : ''
}

/** 从列表行的 `context`（对象或 JSON 字符串）中取 `scene` 展示文案。 */
export function listItemContextScene(row: CaseListRowApi): string {
  const ctx = row.context
  if (ctx == null) return ''
  if (typeof ctx === 'string') {
    try {
      const o = JSON.parse(ctx) as { scene?: unknown }
      return typeof o.scene === 'string' ? o.scene : ''
    } catch {
      return ''
    }
  }
  if (typeof ctx === 'object' && 'scene' in ctx) {
    const s = (ctx as { scene?: unknown }).scene
    return typeof s === 'string' ? s : ''
  }
  return ''
}
