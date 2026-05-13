import { describe, it, expect } from 'vitest'
import type { CaseEnrichmentStatusResponse } from '../../src/api/enrichment'
import type { VectorIndexStatusResponse } from '../../src/api/vectorIndexing'
import { isEnrichmentDetailOk, isVectorDetailOk } from '../../src/domain/caseDerivationStatus'

describe('caseDerivationStatus', () => {
  it('增强成功判定', () => {
    const okSample: CaseEnrichmentStatusResponse = {
      case_id: 'x',
      latest_run: {
        run_id: 'r1',
        case_id: 'x',
        task_type: 'case_enrichment',
        status: 'succeeded',
        model_id: 'm',
        request_purpose: 'case_enrichment',
        case_updated_at: '2026-01-01T00:00:00Z',
        retry_count: 0,
        started_at: '2026-01-01T00:00:00Z',
      },
      current_result: {
        enrichment_id: 'e1',
        case_id: 'x',
        case_updated_at: '2026-01-01T00:00:00Z',
        status: 'valid',
        structured_suggestions: {
          problem_type_suggestion: 'p',
          root_cause_category: 'r',
          applicable_scenarios: [],
          confidence_notes: 'c',
        },
        tag_suggestions: [],
        source_references: [],
        output_version: '1',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    }
    expect(isEnrichmentDetailOk(okSample)).toBe(true)

    expect(
      isEnrichmentDetailOk({
        case_id: 'x',
        latest_run: { ...okSample.latest_run!, status: 'failed' },
        current_result: okSample.current_result,
      })
    ).toBe(false)
  })

  it('向量聚合状态成功判定', () => {
    const pub: VectorIndexStatusResponse = {
      case_id: 'x',
      status: 'published',
      latest_job: null,
      current_vector: null,
      last_error_code: null,
      message: null,
    }
    expect(isVectorDetailOk(pub)).toBe(true)
    expect(isVectorDetailOk({ ...pub, status: 'failed' })).toBe(false)
  })
})
