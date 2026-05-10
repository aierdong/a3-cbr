"""向量索引持久化仓储（case_vectors / vector_index_jobs / pgvector 检索）。"""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import cast, delete, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.vector_indexing.models import (
    CaseVector,
    EmbeddingJobStatus,
    VectorIndexJob,
    VectorIndexJobType,
)
from app.vector_indexing.repository_types import (
    CaseVectorCreate,
    CaseVectorPersisted,
    VectorCandidateFilterPayload,
    VectorCandidateRecord,
    VectorIndexJobCreate,
    VectorIndexJobPatch,
    VectorIndexJobRecord,
    VectorSearchQuery,
)


def _float_vector(raw: Any) -> list[float]:
    """内部工具：将 ORM/pgvector 返回值规范为 Python float 列表。"""
    if raw is None:
        return []
    if hasattr(raw, "tolist"):
        return [float(x) for x in raw.tolist()]
    return [float(x) for x in raw]


def _normalize_tags(raw: Any) -> list[str]:
    """内部工具：将 JSON 标签规范为字符串列表。"""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return [str(raw)]


class VectorRepository:
    """封装向量写入、任务持久化与带结构化条件的语义检索。

    事务边界：写路径依赖调用方在同一 AsyncSession 上 commit；
    `refresh_case_vector` 在同一会话 flush 周期内先删后插。
    """

    def __init__(self, db: AsyncSession) -> None:
        """初始化仓储。

        Args:
            db: 异步数据库会话。

        Returns:
            VectorRepository 实例。
        """
        self._db = db

    def _row_to_case_vector(self, row: CaseVector) -> CaseVectorPersisted:
        """内部工具：CaseVector ORM → CaseVectorPersisted。"""
        return CaseVectorPersisted(
            vector_id=row.vector_id,
            case_id=row.case_id,
            case_updated_at=row.case_updated_at,
            enrichment_id=row.enrichment_id,
            enrichment_status=row.enrichment_status,
            embedding_model_id=row.embedding_model_id,
            embedding_dimension=row.embedding_dimension,
            embedding_vector=_float_vector(row.embedding_vector),
            brand_id=row.brand_id,
            store_id=row.store_id,
            problem_type=row.problem_type,
            tags=_normalize_tags(row.tags),
            case_status=row.case_status,
            degraded_reason=row.degraded_reason,
        )

    async def create_job(self, job: VectorIndexJobCreate) -> VectorIndexJobRecord:
        """创建一条向量索引任务记录。

        Args:
            job: 任务写入载荷。

        Returns:
            新建任务的快照。
        """
        row = VectorIndexJob(
            job_id=job.job_id,
            case_id=job.case_id,
            job_type=job.job_type,
            status=job.status,
            source_version=job.source_version,
            retry_count=job.retry_count,
            old_vector_id=job.old_vector_id,
            old_content_hash=job.old_content_hash,
            new_vector_id=job.new_vector_id,
            error_code=job.error_code,
            error_stage=job.error_stage,
            next_retry_at=job.next_retry_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )
        self._db.add(row)
        await self._db.flush()
        return VectorIndexJobRecord.model_validate(row)

    async def update_job(self, job_id: str, patch: VectorIndexJobPatch) -> VectorIndexJobRecord:
        """按任务标识更新可变字段。

        Args:
            job_id: 任务主键。
            patch: 非空字段参与 UPDATE。

        Returns:
            更新后的任务快照。

        Raises:
            ValueError: 任务不存在。
        """
        data = patch.model_dump(exclude_none=True)
        if not data:
            existing = await self._db.get(VectorIndexJob, job_id)
            if existing is None:
                raise ValueError("向量索引任务不存在")
            return VectorIndexJobRecord.model_validate(existing)

        await self._db.execute(
            update(VectorIndexJob).where(VectorIndexJob.job_id == job_id).values(**data),
        )
        await self._db.flush()
        refreshed = await self._db.get(VectorIndexJob, job_id)
        if refreshed is None:
            raise ValueError("向量索引任务不存在")
        return VectorIndexJobRecord.model_validate(refreshed)

    async def get_job_by_id(self, job_id: str) -> VectorIndexJobRecord | None:
        """按主键读取任务。

        Args:
            job_id: 任务主键。

        Returns:
            任务快照；不存在则为 ``None``。
        """
        row = await self._db.get(VectorIndexJob, job_id)
        if row is None:
            return None
        return VectorIndexJobRecord.model_validate(row)

    async def get_latest_job_for_case(self, case_id: str) -> VectorIndexJobRecord | None:
        """读取指定案例最近启动的任务。

        Args:
            case_id: 案例标识。

        Returns:
            ``started_at`` 最新的一条任务；若无则为 ``None``。
        """
        stmt = (
            select(VectorIndexJob)
            .where(VectorIndexJob.case_id == case_id)
            .order_by(VectorIndexJob.started_at.desc())
            .limit(1)
        )
        res = await self._db.execute(stmt)
        row = res.scalar_one_or_none()
        if row is None:
            return None
        return VectorIndexJobRecord.model_validate(row)

    async def get_inflight_refresh_job(self, case_id: str) -> VectorIndexJobRecord | None:
        """返回案例中仍处于排队或执行中的刷新类任务（避免重复排队）。"""
        stmt = (
            select(VectorIndexJob)
            .where(VectorIndexJob.case_id == case_id)
            .where(
                VectorIndexJob.job_type.in_(
                    (
                        VectorIndexJobType.REFRESH.value,
                        VectorIndexJobType.INDEX.value,
                        VectorIndexJobType.RETRY.value,
                    ),
                ),
            )
            .where(
                VectorIndexJob.status.in_(
                    (
                        EmbeddingJobStatus.QUEUED.value,
                        EmbeddingJobStatus.RUNNING.value,
                    ),
                ),
            )
            .order_by(VectorIndexJob.started_at.desc())
            .limit(1)
        )
        res = await self._db.execute(stmt)
        row = res.scalar_one_or_none()
        if row is None:
            return None
        return VectorIndexJobRecord.model_validate(row)

    async def case_has_succeeded_remove_job(self, case_id: str) -> bool:
        """判断是否已有成功的 remove 任务。

        Args:
            case_id: 案例标识。

        Returns:
            存在 ``job_type=remove`` 且 ``status=succeeded`` 时为 ``True``。
        """
        stmt = (
            select(VectorIndexJob.job_id)
            .where(
                VectorIndexJob.case_id == case_id,
                VectorIndexJob.job_type == VectorIndexJobType.REMOVE.value,
                VectorIndexJob.status == EmbeddingJobStatus.SUCCEEDED.value,
            )
            .limit(1)
        )
        hit = await self._db.execute(stmt)
        return hit.scalar_one_or_none() is not None

    async def refresh_case_vector(
        self,
        case_id: str,
        vector: CaseVectorCreate,
    ) -> tuple[CaseVectorPersisted, str | None]:
        """事务内删除旧向量（如有）并插入新向量，保证每案例至多一行。

        Args:
            case_id: 案例标识（必须与 payload.case_id 一致）。
            vector: 新向量写入载荷。

        Returns:
            (新向量快照, 被替换的旧 vector_id 或 None)。

        Raises:
            ValueError: case_id 与载荷不一致。
        """
        if vector.case_id != case_id:
            raise ValueError("case_id 与向量载荷中的 case_id 不一致")

        res = await self._db.execute(select(CaseVector).where(CaseVector.case_id == case_id))
        previous = res.scalar_one_or_none()
        old_vector_id = previous.vector_id if previous is not None else None
        if previous is not None:
            await self._db.delete(previous)
            await self._db.flush()

        row = CaseVector(
            vector_id=vector.vector_id,
            case_id=vector.case_id,
            case_updated_at=vector.case_updated_at,
            enrichment_id=vector.enrichment_id,
            enrichment_status=vector.enrichment_status,
            embedding_model_id=vector.embedding_model_id,
            embedding_dimension=vector.embedding_dimension,
            embedding_vector=vector.embedding_vector,
            brand_id=vector.brand_id,
            store_id=vector.store_id,
            problem_type=vector.problem_type,
            tags=vector.tags,
            case_status=vector.case_status,
            degraded_reason=vector.degraded_reason,
        )
        self._db.add(row)
        await self._db.flush()
        return self._row_to_case_vector(row), old_vector_id

    async def get_current_vector(self, case_id: str) -> CaseVectorPersisted | None:
        """读取指定案例当前向量行。

        Args:
            case_id: 案例标识。

        Returns:
            向量快照；不存在则为 None。
        """
        res = await self._db.execute(select(CaseVector).where(CaseVector.case_id == case_id))
        row = res.scalar_one_or_none()
        if row is None:
            return None
        return self._row_to_case_vector(row)

    async def delete_case_vector(
        self,
        case_id: str | None,
        vector_id: str | None,
    ) -> tuple[list[str], list[str]]:
        """删除向量行及其同一案例下的任务记录（幂等）。

        Args:
            case_id: 按案例删除时可填。
            vector_id: 按向量主键删除时可填。

        Returns:
            (已删除 vector_id 列表, 已删除 job_id 列表)。

        Raises:
            ValueError: 两个标识均未提供。
        """
        if case_id is None and vector_id is None:
            raise ValueError("case_id 与 vector_id 至少填写其一")

        resolved_case: str | None = None
        target_vector_pk: str | None = None

        if vector_id is not None:
            hit = await self._db.get(CaseVector, vector_id)
            if hit is None:
                return ([], [])
            resolved_case = hit.case_id
            target_vector_pk = vector_id
        else:
            assert case_id is not None
            resolved_case = case_id
            q = await self._db.execute(select(CaseVector).where(CaseVector.case_id == case_id))
            cv = q.scalar_one_or_none()
            if cv is not None:
                target_vector_pk = cv.vector_id

        job_sel = await self._db.execute(
            select(VectorIndexJob.job_id).where(VectorIndexJob.case_id == resolved_case),
        )
        deleted_job_ids = [r[0] for r in job_sel.all()]
        await self._db.execute(
            delete(VectorIndexJob).where(VectorIndexJob.case_id == resolved_case),
        )

        deleted_vector_ids: list[str] = []
        if target_vector_pk is not None:
            await self._db.execute(
                delete(CaseVector).where(CaseVector.vector_id == target_vector_pk),
            )
            deleted_vector_ids.append(target_vector_pk)

        await self._db.flush()
        return (deleted_vector_ids, deleted_job_ids)

    async def search(self, query: VectorSearchQuery) -> list[VectorCandidateRecord]:
        """在 case_vectors 上做 cosine 最近邻检索并应用结构化过滤。

        Args:
            query: 查询向量与过滤条件。

        Returns:
            按距离升序排列的候选列表。
        """
        await self._db.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))

        distance_expr = CaseVector.embedding_vector.cosine_distance(query.query_embedding)
        stmt = (
            select(CaseVector, distance_expr.label("distance"))
            .order_by(distance_expr)
            .limit(query.top_k)
        )

        if query.brand_id is not None:
            stmt = stmt.where(CaseVector.brand_id == query.brand_id)
        if query.store_id is not None:
            stmt = stmt.where(CaseVector.store_id == query.store_id)
        if query.problem_type is not None:
            stmt = stmt.where(CaseVector.problem_type == query.problem_type)
        if query.case_status is not None:
            stmt = stmt.where(CaseVector.case_status == query.case_status)
        if query.case_updated_at_from is not None:
            stmt = stmt.where(CaseVector.case_updated_at >= query.case_updated_at_from)
        if query.case_updated_at_to is not None:
            stmt = stmt.where(CaseVector.case_updated_at <= query.case_updated_at_to)
        if query.tags:
            contained = cast(query.tags, JSONB)
            stmt = stmt.where(cast(CaseVector.tags, JSONB).contains(contained))

        exec_result = await self._db.execute(stmt)
        rows: Sequence[Any] = exec_result.all()

        out: list[VectorCandidateRecord] = []
        for case_row, dist in rows:
            distance_f = float(dist)
            similarity = 1.0 - distance_f
            meta = VectorCandidateFilterPayload(
                brand_id=case_row.brand_id,
                store_id=case_row.store_id,
                problem_type=case_row.problem_type,
                tags=_normalize_tags(case_row.tags),
                case_status=case_row.case_status,
            )
            out.append(
                VectorCandidateRecord(
                    case_id=case_row.case_id,
                    vector_id=case_row.vector_id,
                    similarity_score=similarity,
                    distance=distance_f,
                    case_updated_at=case_row.case_updated_at,
                    filter_metadata=meta,
                ),
            )
        return out
