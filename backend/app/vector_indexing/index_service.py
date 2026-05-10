"""向量索引编排：单案例刷新与状态查询。"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.llm_client import LLMClientError
from app.core.errors import ErrorCode
from app.vector_indexing.embedding_client import EmbeddingClient
from app.vector_indexing.embedding_input_composer import EmbeddingInputComposer
from app.vector_indexing.embedding_input_models import (
    EmbeddingComposeInsufficient,
    EmbeddingComposeNotIndexable,
    EmbeddingInput,
)
from app.vector_indexing.models import EmbeddingJobStatus, VectorIndexJobType
from app.vector_indexing.repository import VectorRepository
from app.vector_indexing.repository_types import (
    CaseVectorCreate,
    CaseVectorPersisted,
    VectorIndexJobCreate,
    VectorIndexJobPatch,
    VectorIndexJobRecord,
)
from app.vector_indexing.schemas import (
    CaseVectorRecord,
    EmbeddingRequest,
    EmbeddingResult,
    RefreshVectorIndexRequest,
    SourceVersion,
    VectorErrorStage,
    VectorIndexJobResponse,
    VectorIndexStatus,
    VectorIndexStatusResponse,
    VectorJobStatus,
    VectorJobType,
)
from app.vector_indexing.source_models import IndexSourceSnapshot
from app.vector_indexing.source_provider import CaseIndexSourceProvider


INPUT_TEMPLATE_VERSION = "case_embedding_v1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _versions_match(vec: CaseVectorPersisted, sv: SourceVersion) -> bool:
    if _normalize_utc(vec.case_updated_at) != _normalize_utc(sv.case_updated_at):
        return False
    return vec.enrichment_id == sv.enrichment_id


def _source_version_blob(sv: SourceVersion) -> dict[str, object]:
    return {
        "case_updated_at": sv.case_updated_at.isoformat(),
        "enrichment_id": sv.enrichment_id,
        "enrichment_status": sv.enrichment_status,
    }


def _parse_job_source_version(raw: dict[str, object] | None) -> SourceVersion | None:
    if not raw:
        return None
    cua = raw.get("case_updated_at")
    if isinstance(cua, str):
        dt = datetime.fromisoformat(cua.replace("Z", "+00:00"))
    elif isinstance(cua, datetime):
        dt = cua
    else:
        return None
    enr_id_raw = raw.get("enrichment_id")
    enr_st_raw = raw.get("enrichment_status")
    enr_id = enr_id_raw if isinstance(enr_id_raw, str) else None
    enr_st = enr_st_raw if isinstance(enr_st_raw, str) else None
    return SourceVersion(
        case_updated_at=dt,
        enrichment_id=enr_id,
        enrichment_status=enr_st,
    )


def _job_record_matches_source_version(
    record: VectorIndexJobRecord,
    sv: SourceVersion,
) -> bool:
    parsed = _parse_job_source_version(record.source_version)
    if parsed is None:
        return False
    return (
        _normalize_utc(parsed.case_updated_at) == _normalize_utc(sv.case_updated_at)
        and parsed.enrichment_id == sv.enrichment_id
        and (parsed.enrichment_status or None) == (sv.enrichment_status or None)
    )


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _job_to_response(record: VectorIndexJobRecord) -> VectorIndexJobResponse:
    err_stage = None
    if record.error_stage:
        err_stage = VectorErrorStage(record.error_stage)
    return VectorIndexJobResponse(
        job_id=record.job_id,
        case_id=record.case_id,
        job_type=VectorJobType(record.job_type),
        status=VectorJobStatus(record.status),
        source_version=_parse_job_source_version(record.source_version),
        error_code=record.error_code,
        error_stage=err_stage,
        retry_count=record.retry_count,
        next_retry_at=record.next_retry_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


def _vector_to_api_record(vec: CaseVectorPersisted) -> CaseVectorRecord:
    ts = vec.case_updated_at
    return CaseVectorRecord(
        vector_id=vec.vector_id,
        case_id=vec.case_id,
        case_updated_at=vec.case_updated_at,
        enrichment_id=vec.enrichment_id,
        enrichment_status=vec.enrichment_status,
        input_template_version=INPUT_TEMPLATE_VERSION,
        input_content_hash="",
        embedding_model_id=vec.embedding_model_id,
        embedding_dimension=vec.embedding_dimension,
        is_current=True,
        searchable=True,
        degraded_reason=vec.degraded_reason,
        created_at=ts,
        updated_at=ts,
    )


class VectorIndexService:
    """编排 CaseIndexSourceProvider → Composer → Embedding → Repository。"""

    def __init__(
        self,
        db: AsyncSession,
        *,
        source_provider: CaseIndexSourceProvider,
        composer: EmbeddingInputComposer,
        embedding_client: EmbeddingClient,
    ) -> None:
        """组装向量索引编排依赖。

        Args:
            db: 异步数据库会话（事务边界由调用方提交）。
            source_provider: 案例与派生结果快照提供者。
            composer: 问题侧 embedding 输入组合器。
            embedding_client: 远程向量嵌入客户端。

        Returns:
            ``None``。
        """
        self._db = db
        self._sources = source_provider
        self._composer = composer
        self._embedding = embedding_client
        self._repo = VectorRepository(db)

    async def _abort_job(self, job_id: str, code: str, stage: str) -> VectorIndexJobResponse:
        await self._repo.update_job(
            job_id,
            VectorIndexJobPatch(
                status=EmbeddingJobStatus.FAILED.value,
                error_code=code,
                error_stage=stage,
                finished_at=_utc_now(),
            ),
        )
        await self._db.flush()
        fin = await self._repo.get_job_by_id(job_id)
        assert fin is not None
        return _job_to_response(fin)

    async def _audit_failed_refresh(
        self,
        case_id: str,
        blob: dict[str, object] | None,
        code: str,
        stage: str,
    ) -> VectorIndexJobResponse:
        job_id = uuid4().hex
        started = _utc_now()
        await self._repo.create_job(
            VectorIndexJobCreate(
                job_id=job_id,
                case_id=case_id,
                job_type=VectorIndexJobType.REFRESH.value,
                status=EmbeddingJobStatus.RUNNING.value,
                source_version=blob,
                retry_count=0,
                started_at=started,
            ),
        )
        await self._db.flush()
        return await self._abort_job(job_id, code, stage)

    async def _return_idempotent_refresh(
        self,
        case_id: str,
        sv: SourceVersion,
        current: CaseVectorPersisted,
    ) -> VectorIndexJobResponse:
        inflight = await self._repo.get_inflight_refresh_job(case_id)
        if inflight is not None:
            return _job_to_response(inflight)
        latest = await self._repo.get_latest_job_for_case(case_id)
        if latest is not None and _job_record_matches_source_version(latest, sv):
            return _job_to_response(latest)
        noop_id = uuid4().hex
        now = _utc_now()
        await self._repo.create_job(
            VectorIndexJobCreate(
                job_id=noop_id,
                case_id=case_id,
                job_type=VectorIndexJobType.REFRESH.value,
                status=EmbeddingJobStatus.SUCCEEDED.value,
                source_version=_source_version_blob(sv),
                retry_count=0,
                new_vector_id=current.vector_id,
                started_at=now,
                finished_at=now,
            ),
        )
        await self._db.flush()
        created = await self._repo.get_job_by_id(noop_id)
        assert created is not None
        return _job_to_response(created)

    async def _persist_refreshed_vector(
        self,
        job_id: str,
        case_id: str,
        snap: IndexSourceSnapshot,
        sv: SourceVersion,
        composed: EmbeddingInput,
        emb_res: EmbeddingResult,
    ) -> VectorIndexJobResponse:
        degraded_val = composed.degraded_reason.value if composed.degraded_reason else None
        case_ts = snap.case_updated_at if snap.case_updated_at is not None else sv.case_updated_at
        assert snap.filter_fields is not None

        create = CaseVectorCreate(
            vector_id=uuid4().hex,
            case_id=case_id,
            case_updated_at=case_ts,
            enrichment_id=sv.enrichment_id,
            enrichment_status=sv.enrichment_status,
            embedding_model_id=emb_res.embedding_model_id,
            embedding_dimension=emb_res.embedding_dimension,
            embedding_vector=emb_res.vector,
            brand_id=snap.filter_fields.brand_id,
            store_id=snap.filter_fields.store_id,
            problem_type=snap.filter_fields.problem_type,
            tags=snap.filter_fields.tags,
            case_status=snap.filter_fields.case_status,
            degraded_reason=degraded_val,
        )

        content_hash = _fingerprint(composed.text)
        try:
            persisted, old_vid = await self._repo.refresh_case_vector(case_id, create)
        except Exception:
            return await self._abort_job(
                job_id,
                ErrorCode.INTERNAL_ERROR,
                VectorErrorStage.PERSIST.value,
            )

        await self._repo.update_job(
            job_id,
            VectorIndexJobPatch(
                status=EmbeddingJobStatus.SUCCEEDED.value,
                old_vector_id=old_vid,
                old_content_hash=content_hash if old_vid else None,
                new_vector_id=persisted.vector_id,
                finished_at=_utc_now(),
            ),
        )
        await self._db.flush()
        fin = await self._repo.get_job_by_id(job_id)
        assert fin is not None
        return _job_to_response(fin)

    async def refresh_case_index(
        self,
        case_id: str,
        request: RefreshVectorIndexRequest,
    ) -> VectorIndexJobResponse:
        """执行同步刷新：短路版本未变、组合输入、嵌入并事务写入向量。

        Args:
            case_id: 案例标识。
            request: 刷新选项（如 ``force_rebuild``）。

        Returns:
            反映任务最终状态的 ``VectorIndexJobResponse``。
        """
        snap = await self._sources.load_source(case_id)
        sv = snap.source_version
        blob = _source_version_blob(sv) if sv is not None else None

        if snap.not_indexable_reason is not None:
            return await self._audit_failed_refresh(
                case_id,
                blob,
                ErrorCode.VECTOR_CASE_NOT_INDEXABLE,
                VectorErrorStage.LOAD_SOURCE.value,
            )

        if await self._repo.case_has_succeeded_remove_job(case_id):
            return await self._audit_failed_refresh(
                case_id,
                blob,
                ErrorCode.VECTOR_CASE_NOT_INDEXABLE,
                VectorErrorStage.LOAD_SOURCE.value,
            )

        if sv is None or snap.filter_fields is None:
            return await self._audit_failed_refresh(
                case_id,
                blob,
                ErrorCode.VECTOR_CASE_NOT_INDEXABLE,
                VectorErrorStage.LOAD_SOURCE.value,
            )

        current = await self._repo.get_current_vector(case_id)
        if current is not None and not request.force_rebuild and _versions_match(current, sv):
            return await self._return_idempotent_refresh(case_id, sv, current)

        job_id = uuid4().hex
        started = _utc_now()
        await self._repo.create_job(
            VectorIndexJobCreate(
                job_id=job_id,
                case_id=case_id,
                job_type=VectorIndexJobType.REFRESH.value,
                status=EmbeddingJobStatus.RUNNING.value,
                source_version=blob,
                retry_count=0,
                started_at=started,
            ),
        )
        await self._db.flush()

        composed = self._composer.compose_case_input(snap)
        if isinstance(composed, EmbeddingComposeNotIndexable):
            return await self._abort_job(
                job_id,
                ErrorCode.VECTOR_CASE_NOT_INDEXABLE,
                VectorErrorStage.COMPOSE_INPUT.value,
            )
        if isinstance(composed, EmbeddingComposeInsufficient):
            return await self._abort_job(
                job_id,
                ErrorCode.VECTOR_INPUT_INSUFFICIENT,
                VectorErrorStage.COMPOSE_INPUT.value,
            )

        emb_req = EmbeddingRequest(
            text=composed.text,
            case_id=case_id,
            correlation_id=job_id,
            content_fingerprint=_fingerprint(composed.text),
        )
        try:
            emb_res = await self._embedding.embed_for_index(emb_req)
        except LLMClientError as exc:
            stage = VectorErrorStage.EMBEDDING_CALL.value
            if exc.error_code in (
                ErrorCode.EMBEDDING_INVALID_RESPONSE,
                ErrorCode.EMBEDDING_DIMENSION_MISMATCH,
            ):
                stage = VectorErrorStage.VALIDATE_EMBEDDING.value
            return await self._abort_job(job_id, exc.error_code, stage)

        return await self._persist_refreshed_vector(job_id, case_id, snap, sv, composed, emb_res)

    async def get_case_status(self, case_id: str) -> VectorIndexStatusResponse:
        """聚合最近任务与当前向量行的可读状态。

        Args:
            case_id: 案例标识。

        Returns:
            ``VectorIndexStatusResponse``。
        """
        latest = await self._repo.get_latest_job_for_case(case_id)
        cur = await self._repo.get_current_vector(case_id)
        latest_resp = _job_to_response(latest) if latest else None

        if latest is None and cur is None:
            return VectorIndexStatusResponse(
                case_id=case_id,
                status=VectorIndexStatus.QUEUED,
                latest_job=None,
                message="尚无向量索引任务",
            )

        if latest is None:
            if cur and cur.degraded_reason:
                st = VectorIndexStatus.DEGRADED
            else:
                st = VectorIndexStatus.PUBLISHED
            return VectorIndexStatusResponse(
                case_id=case_id,
                status=st,
                latest_job=None,
                current_vector=_vector_to_api_record(cur) if cur else None,
            )

        last_err = (
            latest.error_code if latest.status == EmbeddingJobStatus.FAILED.value else None
        )

        if latest.status == EmbeddingJobStatus.RUNNING.value:
            agg = VectorIndexStatus.RUNNING
        elif latest.status == EmbeddingJobStatus.FAILED.value:
            agg = VectorIndexStatus.FAILED
        elif latest.status == EmbeddingJobStatus.SUCCEEDED.value:
            if cur is not None:
                agg = (
                    VectorIndexStatus.DEGRADED
                    if cur.degraded_reason
                    else VectorIndexStatus.PUBLISHED
                )
            else:
                agg = VectorIndexStatus.SUCCEEDED
        else:
            agg = VectorIndexStatus.QUEUED

        return VectorIndexStatusResponse(
            case_id=case_id,
            status=agg,
            latest_job=latest_resp,
            current_vector=_vector_to_api_record(cur) if cur else None,
            last_error_code=last_err,
        )
