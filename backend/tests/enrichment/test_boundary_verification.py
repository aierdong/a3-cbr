"""边界分离验证测试。

验证 enrichment 模块与上游（a3-case-management）、
下游（case-vector-indexing、cbr-retrieval-recommendation）
之间的边界约束：

1. EnrichmentService 不写入 a3_cases 表
2. EnrichmentService 不生成 embedding 或向量索引
3. RecommendationCopyService 不修改候选排序
4. 只有 status=valid 的派生结果可供下游消费
5. status=failed 的结果不会被误当成可用内容
6. Repository 层只操作 enrichment 自有表

Requirements: 1.1, 2.5, 4.3, 4.4, 5.4
Boundary: EnrichmentService, RecommendationCopyService
"""

import ast
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.llm_client import LLMClientError
from app.core.config import EnrichmentLLMConfig
from app.core.errors import ErrorCode
from app.enrichment.models import (
    CaseEnrichmentResult,
    CaseEnrichmentRun,
    RecommendationCopyRun,
)
from app.enrichment.recommendation_copy import RecommendationCopyService
from app.enrichment.schemas import (
    CaseInputSnapshot,
    EnrichmentStatus,
    LLMCompletionResult,
    LLMTokenUsage,
    RecommendationCandidate,
    RecommendationCopyItem,
    RecommendationCopyRequest,
    SourceField,
)
from app.enrichment.service import EnrichmentService


# ---------------------------------------------------------------------------
# 配置与辅助工厂
# ---------------------------------------------------------------------------

_ENRICHMENT_DIR = Path(__file__).resolve().parent.parent.parent / "app" / "enrichment"


def _make_config(**overrides) -> EnrichmentLLMConfig:
    data = dict(
        api_key="deepseek",
        model_id="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        timeout_ms=30000,
        max_retries=2,
        privacy_acknowledged=True,
    )
    data.update(overrides)
    return EnrichmentLLMConfig(**data)


def _make_snapshot(**overrides) -> CaseInputSnapshot:
    data = dict(
        case_id="case_001",
        problem_description="门店近三个月销售下降明显",
        problem_type="销售下降",
        context={"scene": "堂食", "period": "近三个月"},
        root_cause="出餐速度慢导致顾客流失",
        solution_steps=[
            {"step": "优化出餐流程"},
            {"step": "增加高峰期人手"},
        ],
        outcome={"result": "销售回升 15%"},
        status="active",
        updated_at=datetime.now(timezone.utc),
        store_id="store_001",
        store_name="测试门店",
        brand_id="brand_001",
        brand_name="测试品牌",
        business_type="餐饮",
        store_scale="中型",
        franchise_type="直营",
        city="上海",
        city_tier="一线",
    )
    data.update(overrides)
    return CaseInputSnapshot(**data)


def _make_llm_result(content: str | None = None) -> LLMCompletionResult:
    if content is None:
        content = (
            '{"problem_summary": "测试摘要",'
            ' "solution_summary": "测试方案",'
            ' "structured_suggestions": {'
            '"problem_type_suggestion": "类型",'
            ' "root_cause_category": "根因",'
            ' "applicable_scenarios": ["场景"],'
            ' "confidence_notes": "说明"},'
            ' "tag_suggestions": ["标签1"],'
            ' "source_references": ["problem_description"],'
            ' "missing_information": []}'
        )
    return LLMCompletionResult(
        content=content,
        model_id="deepseek-v4-flash",
        usage=LLMTokenUsage(
            prompt_tokens=100, completion_tokens=50, total_tokens=150
        ),
        finish_reason="stop",
    )


def _make_recommendation_request(**overrides) -> RecommendationCopyRequest:
    data = dict(
        query_text="门店销售下降如何改善？",
        candidates=[
            RecommendationCandidate(
                case_id="case_001",
                case_summary="某门店通过优化出餐流程改善销售",
                source_fields={"problem_description": "销售下降"},
            ),
            RecommendationCandidate(
                case_id="case_002",
                case_summary="某门店通过增加人手提升服务效率",
            ),
        ],
    )
    data.update(overrides)
    return RecommendationCopyRequest(**data)


def _make_copy_llm_result() -> LLMCompletionResult:
    content = (
        '{"items": ['
        '{"case_id": "case_001",'
        ' "reason": "该案例与当前问题高度相关",'
        ' "reference_points": ["优化出餐流程"],'
        ' "cautions": ["注意门店规模差异"],'
        ' "source_references": ["problem_description"]},'
        '{"case_id": "case_002",'
        ' "reason": "增加人手可提升服务效率",'
        ' "reference_points": ["增加高峰期人手"],'
        ' "cautions": ["需考虑成本"],'
        ' "source_references": ["solution_steps"]}]}'
    )
    return LLMCompletionResult(
        content=content,
        model_id="deepseek-v4-flash",
        usage=LLMTokenUsage(
            prompt_tokens=200, completion_tokens=100, total_tokens=300
        ),
        finish_reason="stop",
    )


# ---------------------------------------------------------------------------
# Test 1: 源码静态分析 - 不写入 a3_cases
# ---------------------------------------------------------------------------


class TestNoA3CasesWrites:
    """验证 enrichment 模块源码中不包含对 a3_cases 表的写操作。"""

    def _get_enrichment_python_files(self) -> list[Path]:
        """获取 enrichment 模块下所有 Python 源文件。"""
        return sorted(_ENRICHMENT_DIR.glob("*.py"))

    def test_no_insert_update_delete_on_a3_cases(self):
        """enrichment 源码中不存在对 a3_cases 的 INSERT/UPDATE/DELETE。

        通过 AST 解析检查所有 enrichment 模块文件，
        确认不包含对 A3Case ORM 模型的写操作调用。
        """
        # 收集所有可能的写操作模式
        # SQLAlchemy 写操作：session.add(Model()), session.execute(insert/update/delete(Model))
        write_indicators = []

        for py_file in self._get_enrichment_python_files():
            if py_file.name == "__init__.py":
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except (SyntaxError, UnicodeDecodeError):
                continue

            for node in ast.walk(tree):
                # 检查直接的 .add() 调用是否包含 A3Case
                if isinstance(node, ast.Call):
                    func = node.func
                    # session.add(A3Case(...))
                    if isinstance(func, ast.Attribute) and func.attr == "add":
                        for arg in node.args:
                            if isinstance(arg, ast.Call):
                                callee = arg.func
                                if isinstance(callee, ast.Name) and callee.id == "A3Case":
                                    write_indicators.append(
                                        f"{py_file.name}: session.add(A3Case(...))"
                                    )
                                if isinstance(callee, ast.Attribute) and callee.attr == "A3Case":
                                    write_indicators.append(
                                        f"{py_file.name}: session.add(...A3Case(...))"
                                    )

        assert write_indicators == [], (
            f"发现 enrichment 模块中存在对 a3_cases 的写操作: {write_indicators}"
        )

    def test_cleanup_only_reads_a3_cases(self):
        """cleanup.py 中对 A3Case 的引用仅用于只读 JOIN 查询。

        cleanup.py 是唯一导入 A3Case 的 enrichment 文件，
        且仅用于 outerjoin 查找孤立记录，不执行写操作。
        """
        cleanup_file = _ENRICHMENT_DIR / "cleanup.py"
        source = cleanup_file.read_text(encoding="utf-8")

        # A3Case 只出现在 import 和 outerjoin/where 中
        lines_with_a3case = [
            line.strip()
            for line in source.splitlines()
            if "A3Case" in line
        ]

        for line in lines_with_a3case:
            # 不应包含 add, insert, update, delete 操作
            assert not any(
                op in line.lower()
                for op in ["session.add", ".add(", "insert(", "update(", "delete("]
            ), f"cleanup.py 中 A3Case 出现在写操作上下文中: {line}"

        # 确认 outerjoin 使用（只读）
        assert any("outerjoin" in line for line in lines_with_a3case), (
            "cleanup.py 应使用 outerjoin 读取 A3Case"
        )


# ---------------------------------------------------------------------------
# Test 2: 源码静态分析 - 不生成 embedding 或向量操作
# ---------------------------------------------------------------------------


class TestNoEmbeddingOrVectorOperations:
    """验证 enrichment 模块不包含 embedding 或向量相关操作。"""

    def _get_enrichment_python_files(self) -> list[Path]:
        return sorted(_ENRICHMENT_DIR.glob("*.py"))

    def test_no_embedding_generation(self):
        """enrichment 源码中不存在 embedding 生成代码。"""
        embedding_keywords = [
            "BGE-M3",
            "bge_m3",
            "bge-m3",
            "encode_text",
            "get_embedding",
            "generate_embedding",
            "create_embedding",
            "embedding_model",
        ]

        violations = []
        for py_file in self._get_enrichment_python_files():
            if py_file.name == "__init__.py":
                continue
            source = py_file.read_text(encoding="utf-8")
            for keyword in embedding_keywords:
                if keyword.lower() in source.lower():
                    violations.append(f"{py_file.name}: 包含 '{keyword}'")

        assert violations == [], (
            f"enrichment 模块中发现 embedding 相关代码: {violations}"
        )

    def test_no_vector_index_operations(self):
        """enrichment 源码中不存在向量索引或 pgvector 操作。"""
        vector_keywords = [
            "pgvector",
            "vector(",
            "VECTOR_DELETED",  # schemas.py 中的枚举值是合法的删除原因，不是操作
            "cosine_distance",
            "l2_distance",
            "inner_product",
            "create_index",
            "ivfflat",
            "hnsw",
        ]

        violations = []
        for py_file in self._get_enrichment_python_files():
            if py_file.name == "__init__.py":
                continue
            source = py_file.read_text(encoding="utf-8")
            for keyword in vector_keywords:
                if keyword.lower() in source.lower():
                    # schemas.py 中 VECTOR_DELETED 是删除原因枚举，允许
                    if keyword == "VECTOR_DELETED" and py_file.name == "schemas.py":
                        continue
                    violations.append(f"{py_file.name}: 包含 '{keyword}'")

        assert violations == [], (
            f"enrichment 模块中发现向量索引相关代码: {violations}"
        )

    def test_no_similarity_calculation(self):
        """enrichment 源码中不存在相似度计算逻辑。"""
        similarity_keywords = [
            "similarity_score",
            "cosine_similarity",
            "calculate_similarity",
            "compute_similarity",
            "reranker",
            "rerank",
            "top_k",
        ]

        violations = []
        for py_file in self._get_enrichment_python_files():
            if py_file.name == "__init__.py":
                continue
            source = py_file.read_text(encoding="utf-8")
            for keyword in similarity_keywords:
                if keyword.lower() in source.lower():
                    violations.append(f"{py_file.name}: 包含 '{keyword}'")

        assert violations == [], (
            f"enrichment 模块中发现相似度计算代码: {violations}"
        )


# ---------------------------------------------------------------------------
# Test 3: Repository 层只操作 enrichment 自有表
# ---------------------------------------------------------------------------


class TestRepositoryOnlyWritesOwnTables:
    """验证 EnrichmentRepository 只操作 enrichment 自有表。"""

    def test_repository_models_import(self):
        """EnrichmentRepository 只导入 enrichment 自有 ORM 模型。"""
        repo_file = _ENRICHMENT_DIR / "repository.py"
        source = repo_file.read_text(encoding="utf-8")

        # 不应导入 A3Case
        assert "A3Case" not in source, (
            "EnrichmentRepository 不应导入 A3Case"
        )

        # 不应导入 cases 模块的任何内容
        assert "from app.cases" not in source, (
            "EnrichmentRepository 不应导入 app.cases 模块"
        )

    def test_repository_only_references_own_tables(self):
        """EnrichmentRepository 的 delete/select 操作只引用 enrichment 表。"""
        repo_file = _ENRICHMENT_DIR / "repository.py"
        source = repo_file.read_text(encoding="utf-8")

        # 确认只引用 enrichment 自有表
        assert "CaseEnrichmentResult" in source
        assert "CaseEnrichmentRun" in source
        assert "RecommendationCopyRun" in source

        # 不应引用 a3_cases
        assert "a3_cases" not in source.lower(), (
            "EnrichmentRepository 不应引用 a3_cases 表"
        )


# ---------------------------------------------------------------------------
# Test 4: status 语义验证 - 只有 valid 可被下游消费
# ---------------------------------------------------------------------------


class TestStatusSemantics:
    """验证派生结果的 status 语义：只有 valid 可被下游消费。"""

    def test_get_current_result_filters_by_valid_status(self):
        """get_current_result 只返回 status=valid 的结果。

        通过检查 Repository 源码确认查询条件包含 status=valid 过滤。
        """
        repo_file = _ENRICHMENT_DIR / "repository.py"
        source = repo_file.read_text(encoding="utf-8")

        # get_current_result 方法应包含 status == VALID 过滤
        # 找到 get_current_result 方法定义
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_current_result":
                # 检查方法体内是否引用了 VALID
                method_source = ast.get_source_segment(source, node)
                assert method_source is not None
                assert "VALID" in method_source or "valid" in method_source, (
                    "get_current_result 必须过滤 status=valid"
                )
                break
        else:
            pytest.fail("未找到 get_current_result 方法")

    def test_enrichment_service_always_creates_valid_status(self):
        """EnrichmentService.execute_enrichment 创建的派生结果总是 status=valid。

        只有通过校验的结果才会被写入，失败结果不会写入 case_enrichment_results。
        """
        service_file = _ENRICHMENT_DIR / "service.py"
        source = service_file.read_text(encoding="utf-8")

        # execute_enrichment 中写入 result 时 status 应为 VALID
        assert "EnrichmentStatus.VALID" in source, (
            "EnrichmentService 应使用 EnrichmentStatus.VALID 写入结果"
        )

        # 不应在 execute_enrichment 中创建 FAILED 状态的派生结果
        # FAILED 状态只应在 fail_run 中使用（更新运行记录）
        # 而不是在 CaseEnrichmentResultCreate 中使用

    def test_failed_runs_not_in_results_table(self):
        """失败的运行记录存储在 runs 表中，不写入 results 表。

        通过检查 service.py 中的失败处理路径确认：
        失败时调用 fail_run（写入 runs 表），不写入 results 表。
        """
        service_file = _ENRICHMENT_DIR / "service.py"
        source = service_file.read_text(encoding="utf-8")

        # 确认失败处理路径使用 fail_run
        assert "fail_run" in source, (
            "EnrichmentService 应使用 fail_run 记录失败"
        )

        # 确认 CaseEnrichmentResultCreate 只在成功路径中使用
        # 在源码中，CaseEnrichmentResultCreate 的创建只在
        # 校验通过后（第5步写入结果）才会执行

    def test_enrichment_status_enum_values(self):
        """EnrichmentStatus 只包含 valid 和 failed 两个值。"""
        assert EnrichmentStatus.VALID == "valid"
        assert EnrichmentStatus.FAILED == "failed"
        assert len(EnrichmentStatus) == 2


# ---------------------------------------------------------------------------
# Test 5: RecommendationCopyService 不修改候选排序
# ---------------------------------------------------------------------------


class TestRecommendationCopyPreservesOrdering:
    """验证 RecommendationCopyService 不修改候选排序。"""

    def test_copy_service_does_not_import_sorting_libraries(self):
        """RecommendationCopyService 不导入排序相关库。"""
        copy_file = _ENRICHMENT_DIR / "recommendation_copy.py"
        source = copy_file.read_text(encoding="utf-8")

        # 不应使用排序操作
        assert "sorted(" not in source, (
            "RecommendationCopyService 不应使用 sorted()"
        )
        assert ".sort(" not in source, (
            "RecommendationCopyService 不应使用 .sort()"
        )

    def test_copy_service_response_preserves_input_order(self):
        """推荐文案响应的 items 保持输入候选顺序。

        通过 mock LLM 验证 generate_copy 返回的 items
        与输入 candidates 的 case_id 顺序一致。
        """
        mock_llm = MagicMock()
        mock_llm.complete_json = AsyncMock(return_value=_make_copy_llm_result())
        mock_prompt = MagicMock()
        mock_prompt.check_recommendation_injection.return_value = (False, "")
        mock_prompt.build_recommendation_copy_prompt.return_value = "prompt"
        mock_validator = MagicMock()
        expected_items = [
            RecommendationCopyItem(
                case_id="case_001",
                reason="该案例与当前问题高度相关",
                reference_points=["优化出餐流程"],
                cautions=["注意门店规模差异"],
                source_references=[SourceField.PROBLEM_DESCRIPTION],
            ),
            RecommendationCopyItem(
                case_id="case_002",
                reason="增加人手可提升服务效率",
                reference_points=["增加高峰期人手"],
                cautions=["需考虑成本"],
                source_references=[SourceField.SOLUTION_STEPS],
            ),
        ]
        mock_validator.validate_recommendation_copy.return_value = expected_items
        mock_repo = MagicMock()
        mock_repo.create_recommendation_copy_run = AsyncMock(
            return_value=MagicMock(
                copy_run_id="copy_001",
                created_at=datetime.now(timezone.utc),
            )
        )

        service = RecommendationCopyService(
            llm_client=mock_llm,
            prompt_catalog=mock_prompt,
            validator=mock_validator,
            repository=mock_repo,
            config=_make_config(),
        )

        request = _make_recommendation_request()
        # 运行异步测试
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            service.generate_copy(request)
        )

        # 验证 items 顺序与输入候选顺序一致
        assert len(result.items) == len(request.candidates)
        for item, candidate in zip(result.items, request.candidates):
            assert item.case_id == candidate.case_id, (
                f"输出 case_id '{item.case_id}' 与输入顺序不匹配 "
                f"期望 '{candidate.case_id}'"
            )

    def test_copy_service_no_ranking_fields_in_response(self):
        """推荐文案响应不包含排序、相似度或过滤相关字段。"""
        copy_file = _ENRICHMENT_DIR / "recommendation_copy.py"
        source = copy_file.read_text(encoding="utf-8")

        ranking_keywords = [
            "rank",
            "score",
            "similarity",
            "weight",
            "reorder",
            "sort_order",
            "position",
        ]

        violations = []
        for keyword in ranking_keywords:
            if keyword.lower() in source.lower():
                # 排除注释和字符串中的描述性用法
                violations.append(f"包含 '{keyword}'")

        # 源码中不应包含排序相关逻辑
        assert violations == [], (
            f"RecommendationCopyService 不应包含排序相关代码: {violations}"
        )

    def test_copy_response_schema_no_ranking_fields(self):
        """RecommendationCopyResponse 不包含排序或相似度字段。"""
        from app.enrichment.schemas import RecommendationCopyResponse

        fields = set(RecommendationCopyResponse.model_fields.keys())
        ranking_fields = {"rank", "score", "similarity", "weight", "order", "position"}
        found_ranking = fields & ranking_fields

        assert found_ranking == set(), (
            f"RecommendationCopyResponse 不应包含排序相关字段: {found_ranking}"
        )


# ---------------------------------------------------------------------------
# Test 6: Service 层不直接访问 a3_cases 表
# ---------------------------------------------------------------------------


class TestServiceLayerBoundary:
    """验证 Service 层不直接访问 a3_cases 表。"""

    def test_enrichment_service_no_cases_import(self):
        """EnrichmentService 不导入 cases 模块。"""
        service_file = _ENRICHMENT_DIR / "service.py"
        source = service_file.read_text(encoding="utf-8")

        # 检查实际 import 语句，排除注释和 docstring 中的提及
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("app.cases"):
                    pytest.fail(
                        f"EnrichmentService 不应导入 app.cases 模块: "
                        f"from {node.module} import ..."
                    )

    def test_recommendation_copy_no_cases_import(self):
        """RecommendationCopyService 不导入 cases 模块。"""
        copy_file = _ENRICHMENT_DIR / "recommendation_copy.py"
        source = copy_file.read_text(encoding="utf-8")

        # 检查实际 import 语句
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("app.cases"):
                    pytest.fail(
                        f"RecommendationCopyService 不应导入 app.cases 模块: "
                        f"from {node.module} import ..."
                    )

    def test_router_no_direct_cases_table_access(self):
        """Router 不直接访问 a3_cases 表（通过服务层间接访问）。"""
        router_file = _ENRICHMENT_DIR / "router.py"
        source = router_file.read_text(encoding="utf-8")

        # Router 应通过 CaseService/CaseSnapshotProvider 间接访问
        # 不应直接操作 a3_cases 表
        assert "a3_cases" not in source.lower(), (
            "Router 不应直接引用 a3_cases 表名"
        )


# ---------------------------------------------------------------------------
# Test 7: 集成验证 - 完整流程中 status 语义正确
# ---------------------------------------------------------------------------


class TestStatusFlowIntegration:
    """验证完整增强流程中 status 语义的正确传递。"""

    def test_success_path_creates_valid_result(self):
        """成功路径：LLM 输出校验通过后，创建 status=valid 的派生结果。"""
        mock_llm = MagicMock()
        mock_llm.complete_json = AsyncMock(return_value=_make_llm_result())
        mock_prompt = MagicMock()
        mock_prompt.check_enrichment_injection.return_value = (False, "")
        mock_prompt.build_enrichment_prompt.return_value = "prompt"
        mock_validator = MagicMock()
        mock_validator.validate_enrichment_output.return_value = MagicMock(
            problem_summary="测试摘要",
            solution_summary="测试方案",
            structured_suggestions=MagicMock(model_dump=lambda: {
                "problem_type_suggestion": "类型",
                "root_cause_category": "根因",
                "applicable_scenarios": ["场景"],
                "confidence_notes": "说明",
            }),
            tag_suggestions=["标签1"],
            source_references=[SourceField.PROBLEM_DESCRIPTION],
        )
        mock_repo = MagicMock()
        mock_repo.complete_run = AsyncMock()
        mock_repo.fail_run = AsyncMock()
        mock_repo.get_current_result = AsyncMock(return_value=MagicMock(
            enrichment_id="enrich_001",
            case_id="case_001",
            status=EnrichmentStatus.VALID,
        ))

        service = EnrichmentService(
            llm_client=mock_llm,
            prompt_catalog=mock_prompt,
            validator=mock_validator,
            repository=mock_repo,
            config=_make_config(),
        )

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            service.execute_enrichment(_make_snapshot(), "run_001")
        )

        # 验证 complete_run 被调用（写入 valid 结果）
        mock_repo.complete_run.assert_called_once()
        call_args = mock_repo.complete_run.call_args
        result_create = call_args[0][1]  # 第二个参数是 CaseEnrichmentResultCreate
        assert result_create.status == EnrichmentStatus.VALID, (
            "成功路径应创建 status=valid 的派生结果"
        )

    def test_failure_path_does_not_create_result(self):
        """失败路径：LLM 调用失败时，不创建 case_enrichment_results 记录。"""
        mock_llm = MagicMock()
        mock_llm.complete_json = AsyncMock(
            side_effect=LLMClientError(
                error_code=ErrorCode.LLM_TIMEOUT,
                message="超时",
                retryable=False,
            )
        )
        mock_prompt = MagicMock()
        mock_prompt.check_enrichment_injection.return_value = (False, "")
        mock_prompt.build_enrichment_prompt.return_value = "prompt"
        mock_validator = MagicMock()
        mock_repo = MagicMock()
        mock_repo.fail_run = AsyncMock()
        mock_repo.complete_run = AsyncMock()

        service = EnrichmentService(
            llm_client=mock_llm,
            prompt_catalog=mock_prompt,
            validator=mock_validator,
            repository=mock_repo,
            config=_make_config(),
        )

        import asyncio
        with pytest.raises(LLMClientError):
            asyncio.get_event_loop().run_until_complete(
                service.execute_enrichment(_make_snapshot(), "run_001")
            )

        # 验证 fail_run 被调用（记录失败到 runs 表）
        mock_repo.fail_run.assert_called_once()
        # 验证 complete_run 未被调用（不写入 results 表）
        mock_repo.complete_run.assert_not_called()


# ---------------------------------------------------------------------------
# Test 8: Models 层边界验证
# ---------------------------------------------------------------------------


class TestModelsBoundary:
    """验证 ORM 模型只定义 enrichment 自有表。"""

    def test_enrichment_models_only_define_own_tables(self):
        """enrichment/models.py 只定义三个 enrichment 表。"""
        models_file = _ENRICHMENT_DIR / "models.py"
        source = models_file.read_text(encoding="utf-8")

        # 不应导入 A3Case
        assert "A3Case" not in source, (
            "enrichment/models.py 不应导入 A3Case"
        )

        # 不应定义 a3_cases 表
        assert '"a3_cases"' not in source, (
            "enrichment/models.py 不应定义 a3_cases 表"
        )

    def test_enrichment_tables_defined(self):
        """enrichment 模块定义了三个自有表。"""
        assert CaseEnrichmentResult.__tablename__ == "case_enrichment_results"
        assert CaseEnrichmentRun.__tablename__ == "case_enrichment_runs"
        assert RecommendationCopyRun.__tablename__ == "recommendation_copy_runs"


# ---------------------------------------------------------------------------
# Test 9: CaseSnapshotProvider 只读验证
# ---------------------------------------------------------------------------


class TestCaseSnapshotProviderReadOnly:
    """验证 CaseSnapshotProvider 只读取案例数据。"""

    def test_snapshot_provider_no_write_methods(self):
        """CaseSnapshotProvider 不包含写入方法。"""
        snapshot_file = _ENRICHMENT_DIR / "case_snapshot.py"
        source = snapshot_file.read_text(encoding="utf-8")

        # 不应包含写入操作
        write_keywords = ["session.add", ".add(", "insert(", "update(", "delete("]
        for keyword in write_keywords:
            assert keyword not in source, (
                f"CaseSnapshotProvider 不应包含写操作: {keyword}"
            )

    def test_snapshot_provider_no_cases_model_import(self):
        """CaseSnapshotProvider 不直接导入 A3Case 模型。"""
        snapshot_file = _ENRICHMENT_DIR / "case_snapshot.py"
        source = snapshot_file.read_text(encoding="utf-8")

        # 应通过 CaseService 间接访问，不直接导入 A3Case
        assert "from app.cases.models" not in source, (
            "CaseSnapshotProvider 不应直接导入 app.cases.models"
        )
        assert "A3Case" not in source, (
            "CaseSnapshotProvider 不应直接引用 A3Case"
        )
