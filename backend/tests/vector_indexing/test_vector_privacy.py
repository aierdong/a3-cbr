"""向量索引隐私、安全与生命周期枚举契约测试。

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
Boundary: VectorIndexService, VectorSearchService, EmbeddingClient, ErrorMapper, runtime_guards
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.common.llm_client import LLMClientError
from app.core.config import EmbeddingConfig, EmbeddingConfigStatus, get_embedding_config_status
from app.core.errors import ErrorCode, ErrorMapper
from app.vector_indexing.embedding_client import EmbeddingClient
from app.vector_indexing.embedding_input_composer import EmbeddingInputComposer
from app.vector_indexing.embedding_input_models import EmbeddingInput
from app.vector_indexing.index_service import VectorIndexService
from app.vector_indexing.models import EmbeddingJobStatus, VectorIndexJobType
from app.vector_indexing.repository import VectorRepository
from app.vector_indexing.repository_types import VectorIndexJobCreate
from app.vector_indexing.runtime_guards import (
    EmbeddingConfigMissingError,
    assert_embedding_production_config_or_fail,
)
from app.vector_indexing.schemas import (
    EmbeddingRequest,
    RefreshVectorIndexRequest,
    SourceVersion,
    VectorSearchRequest,
)
from app.vector_indexing.search import VectorSearchService
from app.vector_indexing.source_models import IndexSourceSnapshot

from tests.vector_indexing.test_embedding_input_composer import (
    _case_base,
    _enrichment,
    _filter,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _fake_emb_cfg(**kwargs: object) -> EmbeddingConfig:
    base = dict(
        api_key="fake",
        model_id="bge-large-zh",
        base_url="http://localhost",
        privacy_acknowledged=True,
    )
    base.update(kwargs)
    return EmbeddingConfig(**base)  # type: ignore[arg-type]


class _SnapOnlyProvider:
    def __init__(self, snap: IndexSourceSnapshot) -> None:
        self._snap = snap

    async def load_source(self, case_id: str) -> IndexSourceSnapshot:  # noqa: ARG002
        return self._snap


@pytest.mark.asyncio
async def test_refresh_embed_request_text_excludes_solution_effect_solution_summary(
    db_session,
) -> None:
    """Req 6.1：``embed_for_index`` 收到的 ``EmbeddingRequest.text`` 不包含排除字段实际正文。"""
    case = _case_base()
    enr = _enrichment()
    t = case.updated_at
    snap = IndexSourceSnapshot(
        case_id=case.case_id,
        case_detail=case,
        filter_fields=_filter(tags=["apple", "zebra"]),
        case_updated_at=t,
        enrichment_consumable=enr,
        source_version=SourceVersion(
            case_updated_at=t,
            enrichment_id=enr.enrichment_id,
            enrichment_status=enr.status.value,
        ),
    )
    composer = EmbeddingInputComposer()
    composed_check = composer.compose_case_input(snap)
    assert isinstance(composed_check, EmbeddingInput)

    embed = AsyncMock()
    embed.embed_for_index.side_effect = LLMClientError(
        ErrorCode.EMBEDDING_TIMEOUT,
        "stop-after-args",
        retryable=False,
    )

    svc = VectorIndexService(
        db_session,
        source_provider=_SnapOnlyProvider(snap),
        composer=composer,
        embedding_client=embed,
    )
    await svc.refresh_case_index(case.case_id, RefreshVectorIndexRequest(force_rebuild=True))
    await db_session.commit()

    embed.embed_for_index.assert_awaited_once()
    req_arg = embed.embed_for_index.call_args[0][0]
    text_sent = req_arg.text
    assert text_sent == composed_check.text
    forbidden = (
        "绝不允许进入向量",
        "效果也不可进入",
        enr.solution_summary or "",
        "置信说明也不得进入",
    )
    for frag in forbidden:
        assert frag not in text_sent


def test_embedding_job_status_enum_matches_expected_strings() -> None:
    """Req 6.2：任务状态字面量覆盖排队、执行中、成功、失败、重试与删除（cancelled）。"""
    expected = {"queued", "running", "succeeded", "failed", "retryable", "cancelled"}
    assert {s.value for s in EmbeddingJobStatus} == expected


def test_vector_index_job_type_enum_matches_design() -> None:
    """Req 6.2：``job_type`` 枚举与设计一致。"""
    assert {t.value for t in VectorIndexJobType} == {"index", "refresh", "retry", "remove"}


@pytest.mark.asyncio
async def test_get_case_status_failed_maps_last_error_code(db_session) -> None:
    """Req 6.3：最近任务 ``failed`` 时聚合 ``FAILED`` 并回填 ``last_error_code``。"""
    repo = VectorRepository(db_session)
    jid = "job_fail_privacy"
    now = _utc_now()
    await repo.create_job(
        VectorIndexJobCreate(
            job_id=jid,
            case_id="case_fe",
            job_type=VectorIndexJobType.REFRESH.value,
            status=EmbeddingJobStatus.FAILED.value,
            source_version={"case_updated_at": now.isoformat()},
            retry_count=0,
            error_code=ErrorCode.EMBEDDING_TIMEOUT,
            error_stage="embedding_call",
            started_at=now,
            finished_at=now,
        ),
    )
    await db_session.commit()

    svc = VectorIndexService(
        db_session,
        source_provider=_SnapOnlyProvider(IndexSourceSnapshot(case_id="case_fe")),
        composer=EmbeddingInputComposer(),
        embedding_client=AsyncMock(),
    )
    st = await svc.get_case_status("case_fe")
    assert st.status.value == "failed"
    assert st.last_error_code == ErrorCode.EMBEDDING_TIMEOUT


@pytest.mark.asyncio
async def test_get_case_status_retryable_maps_last_error_code(db_session) -> None:
    """Req 6.3：``retryable`` 任务同样暴露 ``last_error_code``。"""
    repo = VectorRepository(db_session)
    jid = "job_retry_privacy"
    now = _utc_now()
    await repo.create_job(
        VectorIndexJobCreate(
            job_id=jid,
            case_id="case_rt",
            job_type=VectorIndexJobType.REFRESH.value,
            status=EmbeddingJobStatus.RETRYABLE.value,
            source_version={"case_updated_at": now.isoformat()},
            retry_count=1,
            error_code=ErrorCode.EMBEDDING_RATE_LIMITED,
            error_stage="embedding_call",
            started_at=now,
            finished_at=now,
            next_retry_at=now,
        ),
    )
    await db_session.commit()

    svc = VectorIndexService(
        db_session,
        source_provider=_SnapOnlyProvider(IndexSourceSnapshot(case_id="case_rt")),
        composer=EmbeddingInputComposer(),
        embedding_client=AsyncMock(),
    )
    st = await svc.get_case_status("case_rt")
    assert st.status.value == "retryable"
    assert st.last_error_code == ErrorCode.EMBEDDING_RATE_LIMITED


def test_get_embedding_config_status_privacy_false_with_real_key_is_config_missing() -> None:
    """Req 6.4：生产密钥齐备但未确认隐私时归入 ``config_missing``。"""
    cfg = EmbeddingConfig(
        api_key="real-key",
        model_id="bge-large-zh",
        base_url="https://x",
        privacy_acknowledged=False,
    )
    assert get_embedding_config_status(cfg) == EmbeddingConfigStatus.CONFIG_MISSING


def test_assert_embedding_production_config_raises_when_privacy_missing() -> None:
    """Req 6.4：启动守卫拒绝「真密钥 + 未确认隐私」。"""
    cfg = EmbeddingConfig(
        api_key="real-key",
        model_id="bge-large-zh",
        base_url="https://x",
        privacy_acknowledged=False,
    )
    with pytest.raises(EmbeddingConfigMissingError) as ei:
        assert_embedding_production_config_or_fail(cfg)
    assert ei.value.error_code == ErrorCode.EMBEDDING_CONFIG_MISSING


def test_assert_embedding_production_config_skips_fake_api_key() -> None:
    """开发 fake 密钥不走生产守卫抛错分支。"""
    assert_embedding_production_config_or_fail(_fake_emb_cfg())


@pytest.mark.asyncio
async def test_vector_search_failure_logs_exclude_full_query_text(caplog) -> None:
    """Req 6.5：搜索嵌入失败路径日志不出现完整 ``query_text``。"""
    secret = "FULL_QUERY_TEXT_SECRET_MARKER_ABC987"
    composer = EmbeddingInputComposer()
    emb = AsyncMock()
    emb.embed_for_query.side_effect = LLMClientError(
        ErrorCode.EMBEDDING_TIMEOUT,
        "nested-" + secret,
        retryable=False,
    )
    svc = VectorSearchService(composer, emb, repository=AsyncMock())
    caplog.set_level(logging.DEBUG)
    with pytest.raises(LLMClientError):
        await svc.search(VectorSearchRequest(query_text=secret, top_k=3))
    joined = caplog.text
    assert secret not in joined


@pytest.mark.asyncio
async def test_refresh_embedding_error_logs_exclude_case_only_forbidden_fragments(
    db_session,
    caplog,
) -> None:
    """Req 6.5：刷新异常路径日志不出现仅存在于解法/摘要等排除字段的片段。"""
    case = _case_base()
    enr = _enrichment()
    t = case.updated_at
    snap = IndexSourceSnapshot(
        case_id=case.case_id,
        case_detail=case,
        filter_fields=_filter(),
        case_updated_at=t,
        enrichment_consumable=enr,
        source_version=SourceVersion(
            case_updated_at=t,
            enrichment_id=enr.enrichment_id,
            enrichment_status=enr.status.value,
        ),
    )
    composer = EmbeddingInputComposer()
    embed = AsyncMock()
    embed.embed_for_index.side_effect = LLMClientError(
        ErrorCode.EMBEDDING_TIMEOUT,
        "provider-" + (enr.solution_summary or ""),
        retryable=False,
    )
    svc = VectorIndexService(
        db_session,
        source_provider=_SnapOnlyProvider(snap),
        composer=composer,
        embedding_client=embed,
    )
    caplog.set_level(logging.DEBUG)
    await svc.refresh_case_index(case.case_id, RefreshVectorIndexRequest(force_rebuild=True))
    blob = caplog.text
    assert (enr.solution_summary or "") not in blob
    assert "绝不允许进入向量" not in blob


@pytest.mark.asyncio
async def test_embedding_client_logs_use_safe_extra_fields_only(caplog) -> None:
    """Req 6.5：EmbeddingClient 日志 extra 含指纹与标识，不含明文向量数组。"""
    distinct_vec = [0.111, -0.222, 0.333] + [0.0] * 1021
    stub_resp = SimpleNamespace(
        data=[SimpleNamespace(index=0, embedding=distinct_vec)],
    )
    mock = MagicMock()
    mock.embeddings.create = AsyncMock(return_value=stub_resp)

    client = EmbeddingClient(
        _fake_emb_cfg(vector_dimension=1024),
        _async_client_index=mock,
    )
    caplog.set_level(logging.INFO, logger="app.vector_indexing.embedding_client")
    await client.embed_for_index(
        EmbeddingRequest(
            text="body-not-in-log-check",
            case_id="cid_z",
            correlation_id="corr_z",
            content_fingerprint="fp_z",
        ),
    )
    records = [r for r in caplog.records if r.name == "app.vector_indexing.embedding_client"]
    assert records
    safe_record = records[-1]
    assert getattr(safe_record, "embedding_model_id", None) == "bge-large-zh"
    assert getattr(safe_record, "case_id", None) == "cid_z"
    assert getattr(safe_record, "correlation_id", None) == "corr_z"
    assert getattr(safe_record, "content_fingerprint", None) == "fp_z"
    assert "0.111" not in caplog.text and "-0.222" not in caplog.text


@pytest.mark.asyncio
async def test_vector_search_success_log_has_query_hash_and_dimension(caplog) -> None:
    """Req 6.5：搜索成功路径摘要日志含 ``query_hash``、``model_id``、``dimension``。"""
    composer = EmbeddingInputComposer()

    stub_resp = SimpleNamespace(
        data=[SimpleNamespace(index=0, embedding=[0.1] + [0.0] * 1023)],
    )
    mock = MagicMock()
    mock.embeddings.create = AsyncMock(return_value=stub_resp)

    emb = EmbeddingClient(
        _fake_emb_cfg(vector_dimension=1024),
        _async_client_search=mock,
    )
    svc = VectorSearchService(composer, emb, repository=AsyncMock())
    caplog.set_level(logging.INFO, logger="app.vector_indexing.search")
    await svc.search(VectorSearchRequest(query_text="门店漏水诉求", top_k=2))
    names = [r.name for r in caplog.records]
    assert "app.vector_indexing.search" in names
    hit = next(r for r in caplog.records if r.message == "vector_search_query_embedding_ok")
    assert getattr(hit, "query_hash", None)
    assert getattr(hit, "model_id", None) == "bge-large-zh"
    assert getattr(hit, "dimension", None) == 1024


def test_error_mapper_embedding_response_hides_upstream_echo_in_detail() -> None:
    """Req 6.5：``EMBEDDING_*`` 映射响应不使用上游自由文本，避免夹带案例正文片段。"""
    leak = "FULL_CASE_BODY_SECRET_TOKEN_FOR_ERRORMAPPER"
    exc = LLMClientError(ErrorCode.EMBEDDING_TIMEOUT, leak, retryable=True)
    http_exc = ErrorMapper().to_http_exception(exc)
    detail_str = str(http_exc.detail)
    assert leak not in detail_str


@pytest.mark.asyncio
async def test_vector_search_logs_exclude_raw_query_on_repository_failure(caplog) -> None:
    """Req 6.5：仓储阶段失败也不应在日志中写出完整查询明文。"""
    secret = "QUERY_REPO_FAIL_SECRET_XYZ"
    composer = EmbeddingInputComposer()

    stub_resp = SimpleNamespace(
        data=[SimpleNamespace(index=0, embedding=[0.05] + [0.0] * 1023)],
    )
    mock_emb = MagicMock()
    mock_emb.embeddings.create = AsyncMock(return_value=stub_resp)

    emb = EmbeddingClient(
        _fake_emb_cfg(vector_dimension=1024),
        _async_client_search=mock_emb,
    )
    repo = AsyncMock()
    repo.search.side_effect = RuntimeError("db-down")

    svc = VectorSearchService(composer, emb, repository=repo)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(RuntimeError):
        await svc.search(VectorSearchRequest(query_text=secret, top_k=3))
    assert secret not in caplog.text
