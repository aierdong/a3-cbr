import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import RecommendationCard from '../../../src/components/recommendations/RecommendationCard.vue'
import type { RecommendationItem } from '../../../src/api/recommendations'

function baseScoreMetadata(
  overrides: Partial<RecommendationItem['score_metadata']> = {}
): RecommendationItem['score_metadata'] {
  return {
    vector_similarity_score: 0.81,
    semantic_similarity_score: 0.72,
    structured_similarity_score: 0.65,
    business_score: 0.1,
    final_score: 0.77,
    final_score_source: 'aggregated',
    normalized_scores: {},
    effective_weights: {},
    ...overrides,
  }
}

const baseItem = (): RecommendationItem => ({
  recommendation_item_id: 'it-1',
  case_id: 'case-1',
  rank: 1,
  case_reference: {
    title_preview: '标题',
    description_preview: '描述预览',
    case_updated_at: '2026-01-01T00:00:00Z',
  },
  core_solution_steps: '步骤一',
  outcome_summary: '效果好',
  vector_similarity_score: 0.81,
  semantic_similarity_score: 0.72,
  structured_similarity_score: 0.65,
  business_score: 0.1,
  final_score: 0.77,
  score_metadata: baseScoreMetadata(),
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
    expect(html).toContain('步骤一')
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

  it('有推荐项标识且传入 feedback 依赖时应渲染反馈控件', () => {
    const feedbackApi = { submit: vi.fn() } as unknown as import('../../../src/api/feedback').FeedbackApiService
    const w = mount(RecommendationCard, {
      props: { item: baseItem(), recommendationRunId: 'run-1', feedbackApi },
    })
    expect(w.find('[data-testid="feedback-item-it-1"]').exists()).toBe(true)
  })

  it('score_metadata.final_score_source 应展示在分值来源', () => {
    const item = baseItem()
    item.score_metadata = baseScoreMetadata({ final_score_source: 'default_zero_not_aggregated' })
    const w = mount(RecommendationCard, { props: { item } })
    expect(w.html()).toContain('default_zero_not_aggregated')
  })

  it('无 description_preview 时应回退 case_enrichment_results.problem_summary', () => {
    const item: RecommendationItem = {
      ...baseItem(),
      case_reference: {
        case_id: 'c1',
        case_enrichment_results: { problem_summary: '增强问题摘要' },
      },
    }
    delete (item.case_reference as { description_preview?: string }).description_preview
    const w = mount(RecommendationCard, { props: { item } })
    expect(w.html()).toContain('增强问题摘要')
  })

  it('无 core_solution_steps 时应回退 case_enrichment_results.solution_summary', () => {
    const item: RecommendationItem = {
      ...baseItem(),
      core_solution_steps: null,
      case_reference: {
        case_id: 'c1',
        case_enrichment_results: { solution_summary: '增强方案摘要' },
      },
    }
    const w = mount(RecommendationCard, { props: { item } })
    expect(w.html()).toContain('增强方案摘要')
  })

  it('无 title_preview 时应以 description_preview 作为标题预览', () => {
    const longDesc = '晚市高峰期出餐慢、等位严重、翻台低。烤炉超负荷,主菜等待超30分钟,前后场信息断层,催菜滞后。'
    const item: RecommendationItem = {
      ...baseItem(),
      case_reference: {
        case_id: 'case_x',
        description_preview: longDesc,
        case_updated_at: '2026-05-13T01:41:10.836693+00:00',
        case_enrichment_results: { problem_summary: longDesc },
      },
    }
    delete (item.case_reference as { title_preview?: string }).title_preview
    const w = mount(RecommendationCard, { props: { item } })
    expect(w.html()).toContain('晚市高峰期出餐慢')
    expect(w.html()).not.toContain('案例 case_x')
  })

  it('注意事项应展示在效果摘要之后', () => {
    const w = mount(RecommendationCard, { props: { item: baseItem() } })
    const html = w.html()
    const iEffect = html.indexOf('效果摘要')
    const iCautionHeading = html.indexOf('注意事项')
    const iCautionText = html.indexOf('注意 B')
    expect(iEffect).toBeGreaterThan(-1)
    expect(iCautionHeading).toBeGreaterThan(iEffect)
    expect(iCautionText).toBeGreaterThan(iCautionHeading)
  })

  it('case_reference 仅含 case_id 时应展示回退标题', () => {
    const item = {
      ...baseItem(),
      case_reference: { case_id: 'case_only_id' } as RecommendationItem['case_reference'],
    }
    const w = mount(RecommendationCard, { props: { item } })
    expect(w.html()).toContain('案例 case_only_id')
  })
})
