/**
 * 任务 5.3：页面级「检索 → 展示 → 运行级反馈」闭环（需求 4.2、5.1、5.3）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import RecommendationPage from '../../src/pages/RecommendationPage.vue'

const apiClient = vi.hoisted(() => ({
  post: vi.fn(),
  get: vi.fn(),
  put: vi.fn(),
}))

vi.mock('../../src/api/client', () => ({
  createApiClient: vi.fn(() => apiClient),
}))

describe('RecommendationPage', () => {
  beforeEach(() => {
    apiClient.post.mockReset()
    apiClient.post.mockImplementation(async (path: string) => {
      if (path === '/api/recommendations/similar-cases') {
        return {
          ok: true,
          data: {
            recommendation_run_id: 'run-page-1',
            contract_version: 'v1',
            status: 'succeeded',
            applied_filters: {},
            score_weights: {},
            query_metadata: {
              query_hash: 'h',
              requested_top_k: 5,
              vector_candidate_count: 3,
              returned_count: 1,
              latency_ms: 12,
            },
            items: [
              {
                recommendation_item_id: 'item-1',
                case_id: 'case-a',
                rank: 1,
                case_reference: {
                  title_preview: '标题',
                  description_preview: '描述',
                  case_updated_at: '2026-01-02T00:00:00.000Z',
                },
                vector_similarity_score: 0.88,
                final_score: 0.91,
                score_breakdown: { final_score_source: 'aggregated' },
                explanation_status: 'generated',
                missing_fields: [],
              },
            ],
          },
        }
      }
      if (path === '/api/recommendation-feedback') {
        return {
          ok: true,
          data: {
            feedback_id: 'fb-1',
            recommendation_run_id: 'run-page-1',
            recommendation_item_id: null,
            case_id: null,
            usefulness: 'useful',
            comment: null,
            target_scope: 'run',
            created_at: '2026-01-03T00:00:00.000Z',
            updated_at: '2026-01-03T01:00:00.000Z',
          },
        }
      }
      return {
        ok: false,
        error: { kind: 'unknown', code: 'UNEXPECTED', message: 'unexpected path', status: 0 },
      }
    })
  })

  it('提交检索后应调用推荐接口并渲染推荐项与运行级反馈区', async () => {
    const w = mount(RecommendationPage)
    await w.find('textarea').setValue('门店服务投诉')
    await w.find('form').trigger('submit')
    await flushPromises()

    expect(apiClient.post).toHaveBeenCalledWith(
      '/api/recommendations/similar-cases',
      expect.objectContaining({ query_text: '门店服务投诉' })
    )
    expect(w.text()).toContain('run-page-1')
    expect(w.text()).toContain('case-a')
    expect(w.find('[data-testid="feedback-run"]').exists()).toBe(true)
  })

  it('运行级反馈提交应调用反馈接口并展示已保存状态', async () => {
    const w = mount(RecommendationPage)
    await w.find('textarea').setValue('问题 A')
    await w.find('form').trigger('submit')
    await flushPromises()

    await w.find('[data-testid="feedback-run"] [data-testid="feedback-submit"]').trigger('click')
    await flushPromises()

    expect(apiClient.post).toHaveBeenCalledWith(
      '/api/recommendation-feedback',
      expect.objectContaining({
        recommendation_run_id: 'run-page-1',
        recommendation_item_id: null,
        actor_id: 'anonymous_user',
        source_channel: 'admin_web',
      })
    )
    expect(w.find('[data-testid="feedback-run"] [data-testid="feedback-success"]').exists()).toBe(
      true
    )
  })
})
