import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import RecommendationCard from '../../../src/components/recommendations/RecommendationCard.vue'
import type { RecommendationItem } from '../../../src/api/recommendations'

const baseItem = (): RecommendationItem => ({
  recommendation_item_id: 'it-1',
  case_id: 'case-1',
  rank: 1,
  case_reference: {
    title_preview: '标题',
    description_preview: '描述预览',
    case_updated_at: '2026-01-01T00:00:00Z',
  },
  core_solution_steps: ['步骤一'],
  outcome_summary: '效果好',
  vector_similarity_score: 0.81,
  semantic_similarity_score: 0.72,
  structured_similarity_score: 0.65,
  business_score: 0.1,
  final_score: 0.77,
  score_breakdown: { final_score_source: 'aggregated' },
  recommendation_reason: '理由',
  reference_points: ['点 A'],
  cautions: ['注意 B'],
  source_references: ['来源 C'],
  explanation_status: 'generated',
  missing_fields: [],
})

describe('RecommendationCard', () => {
  it('应渲染契约内推荐项字段', () => {
    const w = mount(RecommendationCard, { props: { item: baseItem() } })
    const html = w.html()
    expect(html).toContain('case-1')
    expect(html).toContain('向量相似度')
    expect(html).toContain('语义相似度')
    expect(html).toContain('推荐理由')
    expect(html).toContain('理由')
  })

  it('语义/结构化分为 null 时应展示降级说明', () => {
    const item = baseItem()
    item.semantic_similarity_score = null
    item.structured_similarity_score = null
    const w = mount(RecommendationCard, { props: { item } })
    expect(w.find('[data-testid="semantic-null"]').text()).toContain('不可用')
    expect(w.find('[data-testid="structured-null"]').text()).toContain('不可用')
  })

  it('missing_fields 非空时应展示列表', () => {
    const item = baseItem()
    item.missing_fields = ['outcome.notes']
    const w = mount(RecommendationCard, { props: { item } })
    expect(w.find('[data-testid="card-missing"]').text()).toContain('outcome.notes')
  })

  it('解释降级时可结合运行级 degraded_reason 展示提示', () => {
    const item = baseItem()
    item.explanation_status = 'fallback'
    const w = mount(RecommendationCard, {
      props: { item, runDegradedReason: 'explanation_fallback' },
    })
    expect(w.html()).toContain('explanation_fallback')
  })
})
