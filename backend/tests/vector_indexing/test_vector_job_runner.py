"""VectorJobRunner 手动重试与 RETRYABLE 状态测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.common.llm_client import LLMClientError
from app.core.errors import ErrorCode
from app.vector_indexing.embedding_input_composer import EmbeddingInputComposer
from app.vector_indexing.embedding_input_models import (
    EmbeddingInput,
    EmbeddingInputSection,
    EmbeddingSegmentKind,
    EmbeddingSourceRef,
)
from app.vector_indexing.index_service import VectorIndexService
from app.vector_indexing.job_runner import (
    VectorIndexJobNotFoundError,
    VectorJobRetryNotAllowedError,
    VectorJobRunner,
)
from app.vector_indexing.models import EmbeddingJobStatus, VectorIndexJobType
from app.vector_indexing.repository import VectorRepository
from app.vector_indexing.repository_types import VectorIndexJobCreate
from app.vector_indexing.schemas import (
    EmbeddingResult,
    RefreshVectorIndexRequest,
    SourceVersion,
    VectorJobStatus,
)
from app.vector_indexing.source_models import CaseIndexFilterSnapshot, IndexSourceSnapshot

T0 = datetime.now(timezone.utc)


def _basis(dim: int, axis: int) -> list[float]:
    v = [0.0] * dim
    v[axis] = 1.0
    return v


def _emb_section(desc: str) -> EmbeddingInputSection:
    return EmbeddingInputSection(
        kind=EmbeddingSegmentKind.PROBLEM_DESCRIPTION,
        text=desc,
        sources=[
            EmbeddingSourceRef(
                field_path="A3Case.problem_description",
                version_token="case_ver",
            ),
        ],
    )


def _filter_snapshot() -> CaseIndexFilterSnapshot:
    return CaseIndexFilterSnapshot(
        brand_id="b1",
        store_id="s1",
        business_type="",
        store_scale="",
        franchise_type="",
        city="",
        city_tier="",
        problem_type="pt",
        tags=["t"],
        case_status="open",
    )


def _snap(case_id: str, enrichment_id: str = "enr1") -> IndexSourceSnapshot:
    return IndexSourceSnapshot(
        case_id=case_id,
        filter_fields=_filter_snapshot(),
        case_updated_at=T0,
        source_version=SourceVersion(
            case_updated_at=T0,
            enrichment_id=enrichment_id,
            enrichment_status="active",
        ),
        enrichment_consumable=None,
    )


class _FakeProvider:
    def __init__(self, snap: IndexSourceSnapshot) -> None:
        self._snap = snap

    async def load_source(self, case_id: str) -> IndexSourceSnapshot:  # noqa: ARG002
        return self._snap


class _FakeComposer(EmbeddingInputComposer):
    def __init__(self, payload: EmbeddingInput) -> None:
        self._payload = payload

    def compose_case_input(self, source: IndexSourceSnapshot) -> EmbeddingInput:  # noqa: ARG002
        return self._payload


def _stack(db_session, *, snap: IndexSourceSnapshot, embed: AsyncMock, dim: int = 1024):
    composed = EmbeddingInput(
        text="body",
        sections=[_emb_section("body")],
        degraded_reason=None,
    )
    svc = VectorIndexService(
        db_session,
        source_provider=_FakeProvider(snap),
        composer=_FakeComposer(composed),
        embedding_client=embed,
    )
    runner = VectorJobRunner(db_session, svc, max_manual_retries=2)
    svc.register_job_runner(runner)
    return svc, runner, dim


@pytest.mark.asyncio
async def test_embedding_timeout_marks_job_retryable(db_session):
    """超时类嵌入失败应将任务置为 RETRYABLE。"""
    snap = _snap("case_rt")
    embed = AsyncMock()
    embed.embed_for_index = AsyncMock(
        side_effect=LLMClientError(ErrorCode.EMBEDDING_TIMEOUT, "timeout"),
    )
    svc, _, _ = _stack(db_session, snap=snap, embed=embed)

    resp = await svc.refresh_case_index("case_rt", RefreshVectorIndexRequest(force_rebuild=False))
    await db_session.commit()

    assert resp.status == VectorJobStatus.RETRYABLE
    assert resp.error_code == ErrorCode.EMBEDDING_TIMEOUT
    assert resp.next_retry_at is not None


@pytest.mark.asyncio
async def test_dimension_mismatch_not_retryable(db_session):
    """维度不匹配应 FAILED 且不可自动标记为重试候选形态。"""
    snap = _snap("case_dm")
    embed = AsyncMock()
    embed.embed_for_index = AsyncMock(
        side_effect=LLMClientError(ErrorCode.EMBEDDING_DIMENSION_MISMATCH, "bad dim"),
    )
    svc, _, _ = _stack(db_session, snap=snap, embed=embed)

    resp = await svc.refresh_case_index("case_dm", RefreshVectorIndexRequest(force_rebuild=False))
    await db_session.commit()

    assert resp.status == VectorJobStatus.FAILED
    assert resp.error_code == ErrorCode.EMBEDDING_DIMENSION_MISMATCH
    assert resp.next_retry_at is None


@pytest.mark.asyncio
async def test_retry_job_reuses_runner_and_increments_retry_count(db_session):
    """手动重试应再走嵌入链路并将新任务 retry_count 递增。"""
    dim = 1024
    snap = _snap("case_ok")
    embed = AsyncMock()
    embed.embed_for_index = AsyncMock(
        side_effect=[
            LLMClientError(ErrorCode.EMBEDDING_TIMEOUT, "t1"),
            EmbeddingResult(
                embedding_model_id="bge-large-zh",
                embedding_dimension=dim,
                vector=_basis(dim, 0),
            ),
        ],
    )
    svc, runner, _ = _stack(db_session, snap=snap, embed=embed)

    first = await svc.refresh_case_index("case_ok", RefreshVectorIndexRequest(force_rebuild=False))
    assert first.status == VectorJobStatus.RETRYABLE

    second = await runner.retry_job(first.job_id)
    await db_session.commit()

    assert second.status == VectorJobStatus.SUCCEEDED
    assert second.retry_count == 1
    assert embed.embed_for_index.await_count == 2


@pytest.mark.asyncio
async def test_retry_job_not_found(db_session):
    """未知任务标识应抛出 VectorIndexJobNotFoundError。"""
    svc, runner, _ = _stack(db_session, snap=_snap("case_x"), embed=AsyncMock())
    with pytest.raises(VectorIndexJobNotFoundError):
        await runner.retry_job("missing")


@pytest.mark.asyncio
async def test_retry_job_rejects_running_job(db_session):
    """进行中任务不允许走手动重试。"""
    repo = VectorRepository(db_session)
    await repo.create_job(
        VectorIndexJobCreate(
            job_id="job_run",
            case_id="case_run",
            job_type=VectorIndexJobType.REFRESH.value,
            status=EmbeddingJobStatus.RUNNING.value,
            source_version={"case_updated_at": T0.isoformat(), "enrichment_id": "e"},
            retry_count=0,
            started_at=T0,
        ),
    )
    await db_session.flush()

    svc, runner, _ = _stack(db_session, snap=_snap("case_run"), embed=AsyncMock())
    with pytest.raises(VectorJobRetryNotAllowedError) as ei:
        await runner.retry_job("job_run")
    assert ei.value.error_code == ErrorCode.VECTOR_STATE_CONFLICT


@pytest.mark.asyncio
async def test_retry_job_rejects_non_retryable_failure(db_session):
    """输入不足等非瞬时失败不允许手动重试。"""
    repo = VectorRepository(db_session)
    await repo.create_job(
        VectorIndexJobCreate(
            job_id="job_nf",
            case_id="case_nf",
            job_type=VectorIndexJobType.REFRESH.value,
            status=EmbeddingJobStatus.FAILED.value,
            source_version={"case_updated_at": T0.isoformat(), "enrichment_id": "e"},
            retry_count=0,
            error_code=ErrorCode.VECTOR_INPUT_INSUFFICIENT,
            error_stage="compose_input",
            started_at=T0,
            finished_at=T0,
        ),
    )
    await db_session.flush()

    svc, runner, _ = _stack(db_session, snap=_snap("case_nf"), embed=AsyncMock())
    with pytest.raises(VectorJobRetryNotAllowedError) as ei:
        await runner.retry_job("job_nf")
    assert ei.value.error_code == ErrorCode.VECTOR_RETRY_NOT_ALLOWED


@pytest.mark.asyncio
async def test_retry_job_blocked_at_retry_cap(db_session):
    """达到 manual retry 上限后拒绝再次重试。"""
    repo = VectorRepository(db_session)
    await repo.create_job(
        VectorIndexJobCreate(
            job_id="job_cap",
            case_id="case_cap",
            job_type=VectorIndexJobType.REFRESH.value,
            status=EmbeddingJobStatus.RETRYABLE.value,
            source_version={"case_updated_at": T0.isoformat(), "enrichment_id": "e"},
            retry_count=2,
            error_code=ErrorCode.EMBEDDING_TIMEOUT,
            error_stage="embedding_call",
            started_at=T0,
            finished_at=T0,
        ),
    )
    await db_session.flush()

    svc, runner, _ = _stack(db_session, snap=_snap("case_cap"), embed=AsyncMock())
    with pytest.raises(VectorJobRetryNotAllowedError):
        await runner.retry_job("job_cap")
