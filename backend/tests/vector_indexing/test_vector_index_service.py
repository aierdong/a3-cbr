"""VectorIndexService 编排测试（假 Provider / Composer / EmbeddingClient）。

覆盖 Req 4.1 版本短路、2.1 embedding 调用链、3.1 发布向量与降级原因持久化。
Boundary: VectorIndexService
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.core.errors import ErrorCode
from app.vector_indexing.embedding_input_composer import EmbeddingInputComposer
from app.vector_indexing.embedding_input_models import (
    EmbeddingInput,
    EmbeddingInputSection,
    EmbeddingSegmentKind,
    EmbeddingSourceRef,
)
from app.vector_indexing.index_service import VectorIndexService
from app.vector_indexing.models import CaseVector, VectorIndexJob
from app.vector_indexing.repository import VectorRepository
from app.vector_indexing.repository_types import CaseVectorCreate
from app.vector_indexing.schemas import (
    EmbeddingResult,
    RefreshVectorIndexRequest,
    SourceVersion,
    VectorIndexStatus,
    VectorJobStatus,
)
from app.vector_indexing.source_models import (
    CaseIndexFilterSnapshot,
    IndexSourceDegradedReason,
    IndexSourceNotIndexableReason,
    IndexSourceSnapshot,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _basis(dim: int, axis: int) -> list[float]:
    v = [0.0] * dim
    v[axis] = 1.0
    return v


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


def _service(
    db_session,
    *,
    snap: IndexSourceSnapshot,
    composer_payload: EmbeddingInput,
    embed_client: AsyncMock,
) -> VectorIndexService:
    return VectorIndexService(
        db_session,
        source_provider=_FakeProvider(snap),
        composer=_FakeComposer(composer_payload),
        embedding_client=embed_client,
    )


@pytest.mark.asyncio
async def test_refresh_skips_embedding_when_source_version_matches(db_session):
    """RED→GREEN：case_updated_at + enrichment_id 未变时应短路且不调用 embed。"""
    dim = 1024
    t0 = _utc_now()
    repo = VectorRepository(db_session)
    await repo.refresh_case_vector(
        "case_skip",
        CaseVectorCreate(
            vector_id="vec_keep",
            case_id="case_skip",
            case_updated_at=t0,
            enrichment_id="enr1",
            enrichment_status="active",
            embedding_model_id="bge-large-zh",
            embedding_dimension=dim,
            embedding_vector=_basis(dim, 0),
            brand_id="b1",
            store_id="s1",
            problem_type="pt",
            tags=["t"],
            case_status="open",
        ),
    )
    await db_session.flush()

    snap = IndexSourceSnapshot(
        case_id="case_skip",
        filter_fields=_filter_snapshot(),
        case_updated_at=t0,
        source_version=SourceVersion(
            case_updated_at=t0,
            enrichment_id="enr1",
            enrichment_status="active",
        ),
        enrichment_consumable=None,
    )

    embed = AsyncMock()
    svc = _service(
        db_session,
        snap=snap,
        composer_payload=EmbeddingInput(
            text="should-not-run",
            sections=[_emb_section("should-not-run")],
            degraded_reason=None,
        ),
        embed_client=embed,
    )

    req = RefreshVectorIndexRequest(force_rebuild=False)
    resp = await svc.refresh_case_index("case_skip", req)
    resp2 = await svc.refresh_case_index("case_skip", req)
    await db_session.commit()

    embed.embed_for_index.assert_not_called()
    assert resp.status == VectorJobStatus.SUCCEEDED
    assert resp.job_id == resp2.job_id
    stmt = select(func.count()).select_from(VectorIndexJob).where(
        VectorIndexJob.case_id == "case_skip",
    )
    cnt = (await db_session.execute(stmt)).scalar_one()
    assert cnt == 1
    cur = await repo.get_current_vector("case_skip")
    assert cur is not None
    assert cur.vector_id == "vec_keep"


@pytest.mark.asyncio
async def test_refresh_calls_embedding_when_enrichment_changes(db_session):
    """enrichment_id 变化时应调用云端嵌入并写入新向量行。"""
    dim = 1024
    t0 = _utc_now()
    repo = VectorRepository(db_session)
    await repo.refresh_case_vector(
        "case_chg",
        CaseVectorCreate(
            vector_id="vec_old",
            case_id="case_chg",
            case_updated_at=t0,
            enrichment_id="enr_old",
            enrichment_status="active",
            embedding_model_id="bge-large-zh",
            embedding_dimension=dim,
            embedding_vector=_basis(dim, 1),
            brand_id="b1",
            store_id="s1",
            problem_type="pt",
            tags=["t"],
            case_status="open",
        ),
    )
    await db_session.flush()

    snap = IndexSourceSnapshot(
        case_id="case_chg",
        filter_fields=_filter_snapshot(),
        case_updated_at=t0,
        source_version=SourceVersion(
            case_updated_at=t0,
            enrichment_id="enr_new",
            enrichment_status="active",
        ),
        enrichment_consumable=None,
    )

    embed = AsyncMock()
    embed.embed_for_index = AsyncMock(
        return_value=EmbeddingResult(
            embedding_model_id="bge-large-zh",
            embedding_dimension=dim,
            vector=_basis(dim, 2),
        ),
    )
    svc = _service(
        db_session,
        snap=snap,
        composer_payload=EmbeddingInput(
            text="compose ok",
            sections=[_emb_section("compose ok")],
            degraded_reason=None,
        ),
        embed_client=embed,
    )

    resp = await svc.refresh_case_index("case_chg", RefreshVectorIndexRequest(force_rebuild=False))
    await db_session.commit()

    embed.embed_for_index.assert_awaited_once()
    assert resp.status == VectorJobStatus.SUCCEEDED
    cur = await repo.get_current_vector("case_chg")
    assert cur is not None
    assert cur.vector_id != "vec_old"
    assert cur.enrichment_id == "enr_new"


@pytest.mark.asyncio
async def test_refresh_persists_degraded_reason_on_vector_row(db_session):
    """降级路径成功发布后应在 case_vectors.degraded_reason 落库。"""
    dim = 1024
    t0 = _utc_now()
    snap = IndexSourceSnapshot(
        case_id="case_deg",
        filter_fields=_filter_snapshot(),
        case_updated_at=t0,
        source_version=SourceVersion(
            case_updated_at=t0,
            enrichment_id=None,
            enrichment_status=None,
        ),
        enrichment_consumable=None,
        degraded_reason=IndexSourceDegradedReason.ENRICHMENT_MISSING,
    )

    embed = AsyncMock()
    embed.embed_for_index = AsyncMock(
        return_value=EmbeddingResult(
            embedding_model_id="bge-large-zh",
            embedding_dimension=dim,
            vector=_basis(dim, 3),
        ),
    )
    composed = EmbeddingInput(
        text="degraded path",
        sections=[_emb_section("degraded path")],
        degraded_reason=IndexSourceDegradedReason.ENRICHMENT_MISSING,
    )
    svc = _service(db_session, snap=snap, composer_payload=composed, embed_client=embed)

    await svc.refresh_case_index("case_deg", RefreshVectorIndexRequest(force_rebuild=False))
    await db_session.commit()

    row = (
        await db_session.execute(select(CaseVector).where(CaseVector.case_id == "case_deg"))
    ).scalar_one()
    assert row.degraded_reason == IndexSourceDegradedReason.ENRICHMENT_MISSING.value


@pytest.mark.asyncio
async def test_refresh_aborts_when_case_not_indexable(db_session):
    """归档等不可索引快照应失败且不调用嵌入。"""
    t0 = _utc_now()
    snap = IndexSourceSnapshot(
        case_id="case_arc",
        filter_fields=_filter_snapshot(),
        case_updated_at=t0,
        source_version=SourceVersion(
            case_updated_at=t0,
            enrichment_id="e1",
            enrichment_status="active",
        ),
        not_indexable_reason=IndexSourceNotIndexableReason.CASE_ARCHIVED,
    )

    embed = AsyncMock()
    svc = _service(
        db_session,
        snap=snap,
        composer_payload=EmbeddingInput(
            text="x",
            sections=[_emb_section("x")],
            degraded_reason=None,
        ),
        embed_client=embed,
    )

    resp = await svc.refresh_case_index("case_arc", RefreshVectorIndexRequest(force_rebuild=False))
    await db_session.commit()

    embed.embed_for_index.assert_not_called()
    assert resp.status == VectorJobStatus.FAILED
    assert resp.error_code == ErrorCode.VECTOR_CASE_NOT_INDEXABLE


@pytest.mark.asyncio
async def test_get_case_status_published_without_jobs(db_session):
    """仅有向量行而无任务记录时应返回 PUBLISHED。"""
    dim = 1024
    repo = VectorRepository(db_session)
    await repo.refresh_case_vector(
        "case_pub",
        CaseVectorCreate(
            vector_id="vec_pub",
            case_id="case_pub",
            case_updated_at=_utc_now(),
            enrichment_id=None,
            enrichment_status=None,
            embedding_model_id="bge-large-zh",
            embedding_dimension=dim,
            embedding_vector=_basis(dim, 4),
            brand_id="b1",
            store_id="s1",
            problem_type="pt",
            tags=[],
            case_status="open",
        ),
    )
    await db_session.commit()

    snap = IndexSourceSnapshot(case_id="case_pub")
    embed = AsyncMock()
    svc = _service(
        db_session,
        snap=snap,
        composer_payload=EmbeddingInput(
            text="z",
            sections=[_emb_section("z")],
            degraded_reason=None,
        ),
        embed_client=embed,
    )

    status = await svc.get_case_status("case_pub")
    assert status.status == VectorIndexStatus.PUBLISHED
    assert status.latest_job is None
    assert status.current_vector is not None

