"""VectorRepository 持久化与搜索集成测试。

验证事务内刷新（删旧插新）、任务写入与更新、删除幂等及 pgvector 过滤检索。
Requirements: 1.5, 3.1, 3.2, 4.2, 4.5, 5.2, 6.2（持久化/搜索原语层）
Boundary: VectorRepository
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.vector_indexing.models import (
    CaseVector,
    EmbeddingJobStatus,
    VectorIndexJob,
    VectorIndexJobType,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _basis(dim: int, leading_one_at: int) -> list[float]:
    v = [0.0] * dim
    v[leading_one_at] = 1.0
    return v


@pytest.fixture
def dim() -> int:
    """向量维度（与设计默认 bge-large-zh 一致）。"""
    return 1024


@pytest.mark.asyncio
async def test_refresh_inserts_when_absent(db_session, dim):
    """不存在向量时应插入单行并成功提交。"""
    from app.vector_indexing.repository import VectorRepository
    from app.vector_indexing.repository_types import CaseVectorCreate

    repo = VectorRepository(db_session)
    payload = CaseVectorCreate(
        vector_id="vec_new",
        case_id="case_a",
        case_updated_at=_utc_now(),
        enrichment_id=None,
        enrichment_status=None,
        embedding_model_id="bge-large-zh",
        embedding_dimension=dim,
        embedding_vector=_basis(dim, 0),
        brand_id="b1",
        store_id="s1",
        problem_type="pt1",
        tags=["x"],
        case_status="open",
    )
    record, old_vid = await repo.refresh_case_vector("case_a", payload)
    await db_session.commit()

    assert old_vid is None
    assert record.vector_id == "vec_new"
    assert record.case_id == "case_a"

    count = await db_session.scalar(select(func.count()).select_from(CaseVector))
    assert count == 1


@pytest.mark.asyncio
async def test_refresh_deletes_then_inserts_single_row_per_case(db_session, dim):
    """刷新时应返回旧 vector_id 且表中仅存一行。"""
    from app.vector_indexing.repository import VectorRepository
    from app.vector_indexing.repository_types import CaseVectorCreate

    repo = VectorRepository(db_session)
    first = CaseVectorCreate(
        vector_id="vec_1",
        case_id="case_b",
        case_updated_at=_utc_now(),
        enrichment_id="enr1",
        enrichment_status="active",
        embedding_model_id="bge-large-zh",
        embedding_dimension=dim,
        embedding_vector=_basis(dim, 1),
        brand_id="b1",
        store_id="s1",
        problem_type="pt1",
        tags=["t"],
        case_status="open",
    )
    await repo.refresh_case_vector("case_b", first)
    second = first.model_copy(
        update={
            "vector_id": "vec_2",
            "embedding_vector": _basis(dim, 2),
            "case_updated_at": _utc_now(),
        },
    )
    record, old_vid = await repo.refresh_case_vector("case_b", second)
    await db_session.commit()

    assert old_vid == "vec_1"
    assert record.vector_id == "vec_2"

    rows = (await db_session.execute(select(CaseVector.case_id))).all()
    assert len(rows) == 1

    fetched = await repo.get_current_vector("case_b")
    assert fetched is not None
    assert fetched.vector_id == "vec_2"


@pytest.mark.asyncio
async def test_create_and_update_job_persists_failure_fields(db_session):
    """create_job 与 update_job 应持久化错误码与阶段。"""
    from app.vector_indexing.repository import VectorRepository
    from app.vector_indexing.repository_types import VectorIndexJobCreate, VectorIndexJobPatch

    repo = VectorRepository(db_session)
    sv = {
        "case_updated_at": _utc_now().isoformat(),
        "enrichment_id": "enr_x",
        "enrichment_status": "active",
    }
    job_in = VectorIndexJobCreate(
        job_id="job_1",
        case_id="case_j",
        job_type=VectorIndexJobType.REFRESH.value,
        status=EmbeddingJobStatus.RUNNING.value,
        source_version=sv,
        retry_count=0,
    )
    created = await repo.create_job(job_in)
    await db_session.flush()

    assert created.job_id == "job_1"
    assert created.status == EmbeddingJobStatus.RUNNING.value

    patched = await repo.update_job(
        "job_1",
        VectorIndexJobPatch(
            status=EmbeddingJobStatus.FAILED.value,
            error_code="EMBEDDING_TIMEOUT",
            error_stage="embedding_call",
            finished_at=_utc_now(),
            retry_count=1,
        ),
    )
    await db_session.commit()

    assert patched.status == EmbeddingJobStatus.FAILED.value
    assert patched.error_code == "EMBEDDING_TIMEOUT"
    assert patched.error_stage == "embedding_call"


def _remove_job_create(
    *,
    job_id: str,
    case_id: str,
    old_vid: str | None,
    old_hash: str | None,
):
    from app.vector_indexing.repository_types import VectorIndexJobCreate

    now = _utc_now()
    return VectorIndexJobCreate(
        job_id=job_id,
        case_id=case_id,
        job_type=VectorIndexJobType.REMOVE.value,
        status=EmbeddingJobStatus.SUCCEEDED.value,
        source_version={"delete_reason": "case_deleted", "requested_by": "system"},
        retry_count=0,
        old_vector_id=old_vid,
        old_content_hash=old_hash,
        started_at=now,
        finished_at=now,
    )


@pytest.mark.asyncio
async def test_delete_case_vector_removes_vector_and_jobs(db_session, dim):
    """删除应按案例清理向量、历史任务并追加 remove 审计行。"""
    from app.vector_indexing.repository import VectorRepository
    from app.vector_indexing.repository_types import CaseVectorCreate, VectorIndexJobCreate

    repo = VectorRepository(db_session)
    cv = CaseVectorCreate(
        vector_id="vec_del",
        case_id="case_del",
        case_updated_at=_utc_now(),
        enrichment_id=None,
        enrichment_status=None,
        embedding_model_id="bge-large-zh",
        embedding_dimension=dim,
        embedding_vector=_basis(dim, 0),
        brand_id="b1",
        store_id="s1",
        problem_type="pt1",
        tags=[],
        case_status="closed",
    )
    await repo.refresh_case_vector("case_del", cv)
    await repo.create_job(
        VectorIndexJobCreate(
            job_id="job_del",
            case_id="case_del",
            job_type=VectorIndexJobType.REFRESH.value,
            status=EmbeddingJobStatus.SUCCEEDED.value,
            source_version={"case_updated_at": _utc_now().isoformat()},
            retry_count=0,
        ),
    )
    await db_session.commit()

    first_remove_id = "job_rm_1"
    dv, dj = await repo.delete_case_vector(
        case_id="case_del",
        vector_id=None,
        remove_job=_remove_job_create(
            job_id=first_remove_id,
            case_id="case_del",
            old_vid="vec_del",
            old_hash="audit_hash_placeholder",
        ),
    )
    await db_session.commit()

    assert dv == ["vec_del"]
    assert "job_del" in dj

    res_one = await db_session.execute(
        select(VectorIndexJob).where(VectorIndexJob.case_id == "case_del"),
    )
    rows_after_first = res_one.scalars().all()
    assert len(rows_after_first) == 1
    assert rows_after_first[0].job_type == VectorIndexJobType.REMOVE.value
    assert rows_after_first[0].old_vector_id == "vec_del"

    dv2, dj2 = await repo.delete_case_vector(
        case_id="case_del",
        vector_id=None,
        remove_job=_remove_job_create(
            job_id="job_rm_2",
            case_id="case_del",
            old_vid=None,
            old_hash=None,
        ),
    )
    await db_session.commit()
    assert dv2 == []
    assert dj2 == [first_remove_id]


@pytest.mark.asyncio
async def test_search_returns_filtered_neighbors_ordered_by_similarity(db_session, dim):
    """search 应按 cosine 距离排序并支持 brand / tags 过滤。"""
    from app.vector_indexing.repository import VectorRepository
    from app.vector_indexing.repository_types import CaseVectorCreate, VectorSearchQuery

    repo = VectorRepository(db_session)
    base_time = _utc_now()

    async def publish(case_id: str, vid: str, axis: int, brand: str, tags: list[str]) -> None:
        payload = CaseVectorCreate(
            vector_id=vid,
            case_id=case_id,
            case_updated_at=base_time,
            enrichment_id=None,
            enrichment_status=None,
            embedding_model_id="bge-large-zh",
            embedding_dimension=dim,
            embedding_vector=_basis(dim, axis),
            brand_id=brand,
            store_id="s_shared",
            problem_type="pt_shared",
            tags=tags,
            case_status="open",
        )
        await repo.refresh_case_vector(case_id, payload)

    await publish("case_near", "v_near", 10, "brand_keep", ["alpha", "beta"])
    await publish("case_far", "v_far", 500, "brand_keep", ["alpha"])
    await publish("case_other_brand", "v_other", 11, "brand_other", ["alpha", "beta"])
    await db_session.commit()

    query_emb = _basis(dim, 10)
    hits_brand_only = await repo.search(
        VectorSearchQuery(
            query_embedding=query_emb,
            top_k=5,
            brand_id="brand_keep",
        ),
    )
    assert [h.case_id for h in hits_brand_only] == ["case_near", "case_far"]
    assert hits_brand_only[0].similarity_score >= hits_brand_only[1].similarity_score

    hits_tag = await repo.search(
        VectorSearchQuery(
            query_embedding=query_emb,
            top_k=5,
            brand_id="brand_keep",
            tags=["beta"],
        ),
    )
    assert [h.case_id for h in hits_tag] == ["case_near"]


@pytest.mark.asyncio
async def test_search_applies_case_updated_at_range(db_session, dim):
    """search 应按 case_updated_at 时间窗过滤。"""
    from app.vector_indexing.repository import VectorRepository
    from app.vector_indexing.repository_types import CaseVectorCreate, VectorSearchQuery

    repo = VectorRepository(db_session)
    t0 = _utc_now() - timedelta(days=10)
    t1 = _utc_now() - timedelta(days=5)

    async def one(case_id: str, vid: str, ts: datetime) -> None:
        payload = CaseVectorCreate(
            vector_id=vid,
            case_id=case_id,
            case_updated_at=ts,
            enrichment_id=None,
            enrichment_status=None,
            embedding_model_id="bge-large-zh",
            embedding_dimension=dim,
            embedding_vector=_basis(dim, 20),
            brand_id="b_range",
            store_id="s1",
            problem_type="p1",
            tags=[],
            case_status="open",
        )
        await repo.refresh_case_vector(case_id, payload)

    await one("old_case", "v_old", t0)
    await one("new_case", "v_new", t1)
    await db_session.commit()

    hits = await repo.search(
        VectorSearchQuery(
            query_embedding=_basis(dim, 20),
            top_k=10,
            case_updated_at_from=t1 - timedelta(days=1),
            case_updated_at_to=_utc_now(),
        ),
    )
    assert [h.case_id for h in hits] == ["new_case"]
