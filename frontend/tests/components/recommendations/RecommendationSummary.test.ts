import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import RecommendationSummary from '../../../src/components/recommendations/RecommendationSummary.vue'
import type { RecommendationResponse } from '../../../src/api/recommendations'

const sample: RecommendationResponse = {
  recommendation_run_id: 'run-x',
  contract_version: '2026-01',
  status: 'degraded',
  degraded_reason: 'reranker_failed',
  message: '降级成功',
  applied_filters: { brand_id: 'b1', store_id: 's1' },
  score_weights: { brand: 0.3 },
  query_metadata: {
    query_hash: 'abc123',
    requested_top_k: 10,
    vector_candidate_count: 40,
    returned_count: 3,
    latency_ms: 88,
  },
  items: [],
}

describe('RecommendationSummary', () => {
  it('应展示运行标识、状态、候选与返回数量及降级提示', () => {
    const w = mount(RecommendationSummary, { props: { response: sample } })
    expect(w.get('[data-testid="sum-run-id"]').text()).toBe('run-x')
    expect(w.get('[data-testid="sum-status"]').text()).toContain('degraded')
    expect(w.get('[data-testid="sum-degraded"]').text()).toContain('reranker_failed')
    expect(w.get('[data-testid="sum-candidates"]').text()).toBe('40')
    expect(w.get('[data-testid="sum-returned"]').text()).toBe('3')
    expect(w.get('[data-testid="sum-applied-filters"]').text()).toContain('brand_id')
  })
})
