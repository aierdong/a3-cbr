"""VectorCleanupService 孤立向量清理测试。

Boundary: VectorCleanupService
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.cases.models import A3Case, CaseStatus, StoreInfo
from app.vector_indexing.cleanup import VectorCleanupService
from app.vector_indexing.models import CaseVector, VectorIndexJob, VectorIndexJobType
from app.vector_indexing.repository import VectorRepository
from app.vector_indexing.repository_types import CaseVectorCreate


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _basis(dim: int, axis: int) -> list[float]:
    v = [0.0] * dim
    v[axis] = 1.0
    return v


@pytest.fixture
def dim() -> int:
    """与设计一致的向量维度。"""
    return 1024


@pytest.mark.asyncio
async def test_cleanup_removes_vector_when_case_missing(db_session, dim):
    """案例不存在时应删除向量并写入 remove 审计。"""
    repo = VectorRepository(db_session)
    await repo.refresh_case_vector(
        "case_no_row",
        CaseVectorCreate(
            vector_id="vec_nc",
            case_id="case_no_row",
            case_updated_at=_utc_now(),
            enrichment_id=None,
            enrichment_status=None,
            embedding_model_id="bge-large-zh",
            embedding_dimension=dim,
            embedding_vector=_basis(dim, 1),
            brand_id="b1",
            store_id="s1",
            problem_type="pt1",
            tags=[],
            case_status="open",
        ),
    )
    await db_session.commit()

    svc = VectorCleanupService(lambda: db_session, interval_seconds=3600, enabled=False)
    deleted = await svc.cleanup_orphan_vectors(session=db_session)
    await db_session.commit()

    assert deleted == 1

    cnt = await db_session.scalar(select(func.count()).select_from(CaseVector))
    assert cnt == 0

    job_rows = (await db_session.execute(select(VectorIndexJob))).scalars().all()
    assert len(job_rows) == 1
    assert job_rows[0].job_type == VectorIndexJobType.REMOVE.value
    assert job_rows[0].source_version is not None
    assert job_rows[0].source_version.get("requested_by") == "system"


@pytest.mark.asyncio
async def test_cleanup_removes_vector_when_enrichment_missing(db_session, dim):
    """指向不存在 enrichment 行的向量应在案例仍存在时被清理。"""
    db_session.add(
        StoreInfo(
            store_id="store_vc",
            store_name="门店_vc",
            brand_id="brand_vc",
            brand_name="品牌_vc",
            business_type="food",
            store_scale="small",
            franchise_type="direct",
            city="x",
            city_tier="t1",
            updated_at=_utc_now(),
        ),
    )
    db_session.add(
        A3Case(
            case_id="case_bad_enr",
            problem_description="p",
            store_id="store_vc",
            problem_type="customer_complaint",
            context="{}",
            root_cause="r",
            solution_steps="[]",
            outcome="{}",
            status=CaseStatus.ACTIVE.value,
            created_at=_utc_now(),
            updated_at=_utc_now(),
        ),
    )
    await db_session.flush()

    repo = VectorRepository(db_session)
    await repo.refresh_case_vector(
        "case_bad_enr",
        CaseVectorCreate(
            vector_id="vec_be",
            case_id="case_bad_enr",
            case_updated_at=_utc_now(),
            enrichment_id="enr_ghost",
            enrichment_status="active",
            embedding_model_id="bge-large-zh",
            embedding_dimension=dim,
            embedding_vector=_basis(dim, 2),
            brand_id="b1",
            store_id="s1",
            problem_type="pt1",
            tags=[],
            case_status="open",
        ),
    )
    await db_session.commit()

    svc = VectorCleanupService(lambda: db_session, interval_seconds=3600, enabled=False)
    deleted = await svc.cleanup_orphan_vectors(session=db_session)
    await db_session.commit()

    assert deleted == 1

    cv_row = await db_session.get(CaseVector, "vec_be")
    assert cv_row is None

    job_rows = (await db_session.execute(select(VectorIndexJob))).scalars().all()
    assert len(job_rows) == 1
    assert job_rows[0].job_type == VectorIndexJobType.REMOVE.value
    assert job_rows[0].source_version.get("delete_reason") == "enrichment_deleted"
