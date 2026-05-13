/**
 * 案例问题类型：与 OpenAPI `ProblemType` / 后端 `ProblemType` 单一对齐，供表单、筛选、表格展示共用。
 */
import type { components } from '@/api/generated/cases'

export type CaseProblemType = components['schemas']['ProblemType']

export const CASE_PROBLEM_TYPE_OPTIONS = [
  { value: 'customer_complaint', label: '客户投诉' },
  { value: 'service_quality', label: '服务质量' },
  { value: 'operations', label: '运营' },
  { value: 'environment', label: '环境' },
  { value: 'product_quality', label: '产品质量' },
  { value: 'safety_hygiene', label: '安全卫生' },
  { value: 'staff_training', label: '人员培训' },
  { value: 'equipment_maintenance', label: '设备维护' },
  { value: 'other', label: '其他' },
] as const satisfies ReadonlyArray<{ value: CaseProblemType; label: string }>

/** 将 API 返回值格式化为中文短标签；未知值原样返回。 */
export function formatCaseProblemType(value: string): string {
  const row = CASE_PROBLEM_TYPE_OPTIONS.find((o) => o.value === value)
  return row?.label ?? value
}
