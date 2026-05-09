"""OutputValidator 单元测试。

覆盖：
- JSON 解析失败、字段缺失、枚举越界、标签规范化
- 来源引用校验、候选引用不匹配
- missing_information 契约：信息不足时必须返回结构化原因
- 摘要长度校验
- 输出侧注入嫌疑检测（角色声明、拒绝回答模板）
- 推荐文案校验：items 数量、case_id 匹配、顺序保持

Requirements: 2.3, 3.2, 3.3, 4.1, 4.2, 5.2, 5.3
"""
import json

import pytest

from app.enrichment.validators import (
    MAX_TAG_COUNT,
    OutputValidator,
    OutputValidationException,
    ValidationErrorCode,
    normalize_tags,
)


# ---------------------------------------------------------------------------
# 辅助工厂
# ---------------------------------------------------------------------------


def _valid_enrichment_output(**overrides) -> dict:
    """构建合法的案例增强输出。"""
    data = {
        "problem_summary": "门店近三个月销售下降明显，主要原因是出餐速度慢",
        "solution_summary": "优化出餐流程并增加高峰期人手，销售回升15%",
        "structured_suggestions": {
            "problem_type_suggestion": "销售下降",
            "root_cause_category": "运营效率",
            "applicable_scenarios": ["堂食高峰期"],
            "confidence_notes": "基于案例内容分析",
        },
        "tag_suggestions": ["销售下降", "出餐效率", "运营优化"],
        "source_references": ["problem_description", "root_cause"],
        "missing_information": [],
    }
    data.update(overrides)
    return data


def _valid_recommendation_items(**overrides) -> dict:
    """构建合法的推荐文案输出。"""
    data = {
        "items": [
            {
                "case_id": "case_001",
                "reason": "该案例与当前问题场景相似，都涉及出餐效率",
                "reference_points": ["优化出餐流程", "增加高峰期人手"],
                "cautions": ["需根据门店规模调整方案"],
                "source_references": ["root_cause", "solution_steps"],
            },
            {
                "case_id": "case_002",
                "reason": "该案例展示了类似客诉处理经验",
                "reference_points": ["建立客诉响应机制"],
                "cautions": ["注意品牌差异"],
                "source_references": ["problem_description"],
            },
        ],
    }
    data.update(overrides)
    return data


def _missing_info_enrichment_output() -> dict:
    """构建信息不足场景的合法输出。"""
    return {
        "problem_summary": None,
        "solution_summary": None,
        "structured_suggestions": {
            "problem_type_suggestion": "无法确定",
            "root_cause_category": "信息不足",
            "applicable_scenarios": ["需补充信息"],
            "confidence_notes": "案例内容不足，无法可靠分析",
        },
        "tag_suggestions": [],
        "source_references": [],
        "missing_information": [
            {
                "field": "problem_description",
                "reason": "问题描述缺失",
                "blocking_level": "required",
            },
            {
                "field": "root_cause",
                "reason": "根因分析缺失",
                "blocking_level": "required",
            },
        ],
    }


# ===========================================================================
# normalize_tags 测试
# ===========================================================================


class TestNormalizeTags:
    """标签规范化函数测试。"""

    def test_removes_empty_strings(self):
        """应移除空字符串标签。"""
        result = normalize_tags(["tag1", "", "  ", "tag2"])
        assert result == ["tag1", "tag2"]

    def test_removes_duplicates_preserving_order(self):
        """应去重并保留首次出现顺序。"""
        result = normalize_tags(["b", "a", "b", "c", "a"])
        assert result == ["b", "a", "c"]

    def test_strips_whitespace(self):
        """应去除标签前后空白。"""
        result = normalize_tags(["  tag1  ", " tag2 "])
        assert result == ["tag1", "tag2"]

    def test_limits_count(self):
        """应限制标签数量至 MAX_TAG_COUNT。"""
        tags = [f"tag{i}" for i in range(15)]
        result = normalize_tags(tags)
        assert len(result) == MAX_TAG_COUNT
        assert result == [f"tag{i}" for i in range(MAX_TAG_COUNT)]

    def test_empty_input(self):
        """空列表应返回空列表。"""
        assert normalize_tags([]) == []

    def test_all_empty(self):
        """全空标签应返回空列表。"""
        assert normalize_tags(["", "  ", ""]) == []

    def test_custom_max_count(self):
        """应支持自定义最大数量。"""
        tags = ["a", "b", "c", "d"]
        result = normalize_tags(tags, max_count=2)
        assert result == ["a", "b"]


# ===========================================================================
# validate_enrichment_output 测试
# ===========================================================================


class TestValidateEnrichmentOutput:
    """案例增强输出校验测试。"""

    def setup_method(self):
        """初始化测试夹具。"""
        self.validator = OutputValidator()

    # --- JSON 解析 ---

    def test_invalid_json_raises(self):
        """非法 JSON 应抛出 LLM_INVALID_RESPONSE。"""
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_enrichment_output(
                "not valid json",
                "case_001",
            )
        assert exc_info.value.error_code == ValidationErrorCode.LLM_INVALID_RESPONSE
        assert "JSON" in exc_info.value.message

    def test_json_array_raises(self):
        """JSON 数组（非对象）应抛出异常。"""
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_enrichment_output(
                json.dumps([1, 2, 3]),
                "case_001",
            )
        assert exc_info.value.error_code == ValidationErrorCode.LLM_INVALID_RESPONSE

    def test_empty_json_object_raises(self):
        """空 JSON 对象（缺字段）应抛出异常。"""
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_enrichment_output(
                json.dumps({}),
                "case_001",
            )
        assert exc_info.value.error_code == ValidationErrorCode.LLM_INVALID_RESPONSE

    # --- 合法输出 ---

    def test_valid_output_returns_model(self):
        """合法输出应返回 CaseEnrichmentOutput。"""
        raw = json.dumps(_valid_enrichment_output())
        result = self.validator.validate_enrichment_output(raw, "case_001")
        assert result.problem_summary is not None
        assert result.solution_summary is not None
        assert len(result.tag_suggestions) == 3

    def test_valid_output_with_missing_info(self):
        """信息不足场景的合法输出应通过校验。"""
        raw = json.dumps(_missing_info_enrichment_output())
        result = self.validator.validate_enrichment_output(raw, "case_001")
        assert result.problem_summary is None
        assert result.solution_summary is None
        assert len(result.missing_information) == 2

    # --- 字段缺失 ---

    def test_missing_structured_suggestions_raises(self):
        """缺少 structured_suggestions 应抛出异常。"""
        data = _valid_enrichment_output()
        del data["structured_suggestions"]
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_enrichment_output(
                json.dumps(data),
                "case_001",
            )
        assert exc_info.value.error_code == ValidationErrorCode.LLM_INVALID_RESPONSE

    def test_missing_tag_suggestions_raises(self):
        """缺少 tag_suggestions 应抛出异常。"""
        data = _valid_enrichment_output()
        del data["tag_suggestions"]
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_enrichment_output(
                json.dumps(data),
                "case_001",
            )
        assert exc_info.value.error_code == ValidationErrorCode.LLM_INVALID_RESPONSE

    def test_missing_source_references_raises(self):
        """缺少 source_references 应抛出异常。"""
        data = _valid_enrichment_output()
        del data["source_references"]
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_enrichment_output(
                json.dumps(data),
                "case_001",
            )
        assert exc_info.value.error_code == ValidationErrorCode.LLM_INVALID_RESPONSE

    def test_missing_missing_information_raises(self):
        """缺少 missing_information 应抛出异常。"""
        data = _valid_enrichment_output()
        del data["missing_information"]
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_enrichment_output(
                json.dumps(data),
                "case_001",
            )
        assert exc_info.value.error_code == ValidationErrorCode.LLM_INVALID_RESPONSE

    # --- 枚举越界 ---

    def test_invalid_source_reference_raises(self):
        """非法来源引用字段应抛出异常。"""
        data = _valid_enrichment_output(
            source_references=["problem_description", "invalid_field"],
        )
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_enrichment_output(
                json.dumps(data),
                "case_001",
            )
        assert exc_info.value.error_code == ValidationErrorCode.LLM_INVALID_RESPONSE

    def test_invalid_blocking_level_raises(self):
        """非法 blocking_level 应抛出异常。"""
        data = _missing_info_enrichment_output()
        data["missing_information"][0]["blocking_level"] = "invalid"
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_enrichment_output(
                json.dumps(data),
                "case_001",
            )
        assert exc_info.value.error_code == ValidationErrorCode.LLM_INVALID_RESPONSE

    # --- 标签规范化 ---

    def test_tags_deduplicated(self):
        """重复标签应被去重。"""
        data = _valid_enrichment_output(
            tag_suggestions=["tag1", "tag2", "tag1", "tag3"],
        )
        raw = json.dumps(data)
        result = self.validator.validate_enrichment_output(raw, "case_001")
        assert result.tag_suggestions == ["tag1", "tag2", "tag3"]

    def test_empty_tags_removed(self):
        """空标签应被移除。"""
        data = _valid_enrichment_output(
            tag_suggestions=["tag1", "", "  ", "tag2"],
        )
        raw = json.dumps(data)
        result = self.validator.validate_enrichment_output(raw, "case_001")
        assert result.tag_suggestions == ["tag1", "tag2"]

    def test_tags_limited_to_max(self):
        """标签数量应限制在 MAX_TAG_COUNT。"""
        data = _valid_enrichment_output(
            tag_suggestions=[f"tag{i}" for i in range(15)],
        )
        raw = json.dumps(data)
        result = self.validator.validate_enrichment_output(raw, "case_001")
        assert len(result.tag_suggestions) == MAX_TAG_COUNT

    def test_empty_tag_list_accepted(self):
        """空标签列表应被接受。"""
        data = _valid_enrichment_output(tag_suggestions=[])
        raw = json.dumps(data)
        result = self.validator.validate_enrichment_output(raw, "case_001")
        assert result.tag_suggestions == []

    # --- missing_information 一致性 ---

    def test_problem_summary_none_without_missing_info_raises(self):
        """problem_summary 为 None 但 missing_information 为空应拒绝。"""
        data = _valid_enrichment_output(
            problem_summary=None,
            missing_information=[],
        )
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_enrichment_output(
                json.dumps(data),
                "case_001",
            )
        assert exc_info.value.error_code == ValidationErrorCode.CONSTRAINT_VIOLATION
        assert "missing_information" in exc_info.value.message

    def test_solution_summary_none_without_missing_info_raises(self):
        """solution_summary 为 None 但 missing_information 为空应拒绝。"""
        data = _valid_enrichment_output(
            solution_summary=None,
            missing_information=[],
        )
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_enrichment_output(
                json.dumps(data),
                "case_001",
            )
        assert exc_info.value.error_code == ValidationErrorCode.CONSTRAINT_VIOLATION

    def test_both_summaries_none_with_missing_info_accepted(self):
        """两个摘要都为 None 且有 missing_information 应通过。"""
        data = _missing_info_enrichment_output()
        raw = json.dumps(data)
        result = self.validator.validate_enrichment_output(raw, "case_001")
        assert result.problem_summary is None
        assert len(result.missing_information) == 2

    def test_problem_summary_none_solution_present_without_missing_info(self):
        """只有 problem_summary 为 None 但有 solution_summary 应拒绝。"""
        data = _valid_enrichment_output(
            problem_summary=None,
            missing_information=[],
        )
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_enrichment_output(
                json.dumps(data),
                "case_001",
            )
        assert exc_info.value.error_code == ValidationErrorCode.CONSTRAINT_VIOLATION

    # --- 摘要长度 ---

    def test_problem_summary_too_long_raises(self):
        """问题摘要超长应拒绝。"""
        data = _valid_enrichment_output(
            problem_summary="x" * 201,
        )
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_enrichment_output(
                json.dumps(data),
                "case_001",
            )
        assert exc_info.value.error_code == ValidationErrorCode.CONSTRAINT_VIOLATION
        assert "problem_summary" in str(exc_info.value.errors)

    def test_solution_summary_too_long_raises(self):
        """方案摘要超长应拒绝。"""
        data = _valid_enrichment_output(
            solution_summary="x" * 201,
        )
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_enrichment_output(
                json.dumps(data),
                "case_001",
            )
        assert exc_info.value.error_code == ValidationErrorCode.CONSTRAINT_VIOLATION

    def test_summary_at_max_length_accepted(self):
        """摘要恰好等于最大长度应通过。"""
        data = _valid_enrichment_output(
            problem_summary="x" * 200,
            solution_summary="y" * 200,
        )
        raw = json.dumps(data)
        result = self.validator.validate_enrichment_output(raw, "case_001")
        assert len(result.problem_summary) == 200
        assert len(result.solution_summary) == 200

    def test_summary_none_accepted(self):
        """摘要为 None 应被接受（配合 missing_information）。"""
        data = _missing_info_enrichment_output()
        raw = json.dumps(data)
        result = self.validator.validate_enrichment_output(raw, "case_001")
        assert result.problem_summary is None

    # --- 结构化建议必填字段 ---

    def test_empty_problem_type_suggestion_raises(self):
        """空问题类型建议应拒绝。"""
        data = _valid_enrichment_output()
        data["structured_suggestions"]["problem_type_suggestion"] = ""
        with pytest.raises(OutputValidationException):
            self.validator.validate_enrichment_output(
                json.dumps(data),
                "case_001",
            )

    def test_empty_applicable_scenarios_raises(self):
        """空适用场景列表应拒绝。"""
        data = _valid_enrichment_output()
        data["structured_suggestions"]["applicable_scenarios"] = []
        with pytest.raises(OutputValidationException):
            self.validator.validate_enrichment_output(
                json.dumps(data),
                "case_001",
            )

    # --- 额外字段 ---

    def test_extra_field_raises(self):
        """额外字段应被拒绝（extra=forbid）。"""
        data = _valid_enrichment_output(extra_field="should not exist")
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_enrichment_output(
                json.dumps(data),
                "case_001",
            )
        assert exc_info.value.error_code == ValidationErrorCode.LLM_INVALID_RESPONSE


# ===========================================================================
# 输出侧注入嫌疑检测测试
# ===========================================================================


class TestOutputInjectionDetection:
    """输出侧注入嫌疑检测测试。"""

    def setup_method(self):
        """初始化测试夹具。"""
        self.validator = OutputValidator()

    @pytest.mark.parametrize(
        "text, description",
        [
            ("我是 AI 助手", "中文：我是 AI 助手"),
            ("AI助手为您服务", "中文：AI助手"),
            ("这是一个语言模型的输出", "中文：语言模型"),
            ("作为AI，我认为", "中文：作为AI"),
            ("As an AI, I think", "英文：as an AI"),
            ("I am a language model", "英文：I am a language model"),
            ("抱歉，我无法回答此问题", "中文：抱歉，无法回答"),
            ("抱歉，我不能提供该信息", "中文：抱歉，不能提供"),
            ("无法回答您的问题", "中文：无法回答"),
            ("不能提供该信息", "中文：不能提供"),
            ("Sorry, I can't help with that", "英文：sorry, can't"),
            ("I'm sorry, I cannot provide", "英文：sorry, cannot provide"),
        ],
    )
    def test_injection_patterns_detected(self, text, description):
        """注入嫌疑模式应被检测。"""
        is_suspected, reason = self.validator.check_output_injection(text)
        assert is_suspected is True, f"应检测到: {description}"
        assert "注入嫌疑" in reason

    @pytest.mark.parametrize(
        "text",
        [
            "门店近三个月销售下降明显",
            "根因：出餐速度慢导致顾客流失",
            "解决步骤：优化出餐流程",
            "",
            "问题类型：销售下降",
            "优化出餐流程并增加高峰期人手",
        ],
    )
    def test_safe_text_passes(self, text):
        """正常业务文本不应被标记为注入嫌疑。"""
        is_suspected, reason = self.validator.check_output_injection(text)
        assert is_suspected is False
        assert reason == ""

    def test_injection_in_problem_summary_blocks(self):
        """问题摘要中包含注入嫌疑应拒绝。"""
        data = _valid_enrichment_output(
            problem_summary="我是 AI 助手，为您分析此案例",
        )
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_enrichment_output(
                json.dumps(data),
                "case_001",
            )
        assert exc_info.value.error_code == ValidationErrorCode.INJECTION_SUSPECTED

    def test_injection_in_solution_summary_blocks(self):
        """方案摘要中包含注入嫌疑应拒绝。"""
        data = _valid_enrichment_output(
            solution_summary="抱歉，我无法回答此问题",
        )
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_enrichment_output(
                json.dumps(data),
                "case_001",
            )
        assert exc_info.value.error_code == ValidationErrorCode.INJECTION_SUSPECTED

    def test_injection_in_structured_suggestions_blocks(self):
        """结构化建议中包含注入嫌疑应拒绝。"""
        data = _valid_enrichment_output()
        data["structured_suggestions"]["confidence_notes"] = "作为AI，我无法确定"
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_enrichment_output(
                json.dumps(data),
                "case_001",
            )
        assert exc_info.value.error_code == ValidationErrorCode.INJECTION_SUSPECTED

    def test_injection_in_missing_information_reason_blocks(self):
        """缺失信息原因中包含注入嫌疑应拒绝。"""
        data = _missing_info_enrichment_output()
        data["missing_information"][0]["reason"] = "抱歉，我无法提供该信息"
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_enrichment_output(
                json.dumps(data),
                "case_001",
            )
        assert exc_info.value.error_code == ValidationErrorCode.INJECTION_SUSPECTED


# ===========================================================================
# validate_recommendation_copy 测试
# ===========================================================================


class TestValidateRecommendationCopy:
    """推荐文案校验测试。"""

    def setup_method(self):
        """初始化测试夹具。"""
        self.validator = OutputValidator()

    # --- JSON 解析 ---

    def test_invalid_json_raises(self):
        """非法 JSON 应抛出 LLM_INVALID_RESPONSE。"""
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_recommendation_copy(
                "not json",
                ["case_001"],
            )
        assert exc_info.value.error_code == ValidationErrorCode.LLM_INVALID_RESPONSE

    def test_json_array_raises(self):
        """JSON 数组（非对象）应抛出异常。"""
        with pytest.raises(OutputValidationException):
            self.validator.validate_recommendation_copy(
                json.dumps([1, 2]),
                ["case_001"],
            )

    # --- items 字段 ---

    def test_missing_items_raises(self):
        """缺少 items 应抛出 MISSING_FIELD。"""
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_recommendation_copy(
                json.dumps({}),
                ["case_001"],
            )
        assert exc_info.value.error_code == ValidationErrorCode.MISSING_FIELD

    def test_items_not_array_raises(self):
        """items 非数组应抛出 MISSING_FIELD。"""
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_recommendation_copy(
                json.dumps({"items": "not a list"}),
                ["case_001"],
            )
        assert exc_info.value.error_code == ValidationErrorCode.MISSING_FIELD

    # --- 候选数量匹配 ---

    def test_items_count_mismatch_raises(self):
        """items 数量与候选不匹配应抛出 CANDIDATE_MISMATCH。"""
        data = _valid_recommendation_items()
        # 2 items but 3 candidates
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_recommendation_copy(
                json.dumps(data),
                ["case_001", "case_002", "case_003"],
            )
        assert exc_info.value.error_code == ValidationErrorCode.CANDIDATE_MISMATCH
        assert "不匹配" in exc_info.value.message

    def test_items_count_too_few_raises(self):
        """items 数量少于候选应拒绝。"""
        data = {"items": [_valid_recommendation_items()["items"][0]]}
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_recommendation_copy(
                json.dumps(data),
                ["case_001", "case_002"],
            )
        assert exc_info.value.error_code == ValidationErrorCode.CANDIDATE_MISMATCH

    # --- case_id 匹配 ---

    def test_case_id_mismatch_raises(self):
        """case_id 不匹配应抛出 CANDIDATE_MISMATCH。"""
        data = _valid_recommendation_items()
        # items have case_001, case_002 but candidates have case_001, case_003
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_recommendation_copy(
                json.dumps(data),
                ["case_001", "case_003"],
            )
        assert exc_info.value.error_code == ValidationErrorCode.CANDIDATE_MISMATCH
        assert "case_003" in str(exc_info.value.errors[0].message)

    def test_case_id_order_mismatch_raises(self):
        """case_id 顺序不匹配应拒绝。"""
        data = _valid_recommendation_items()
        # items order: case_001, case_002; candidates order: case_002, case_001
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_recommendation_copy(
                json.dumps(data),
                ["case_002", "case_001"],
            )
        assert exc_info.value.error_code == ValidationErrorCode.CANDIDATE_MISMATCH

    # --- 合法输出 ---

    def test_valid_output_returns_items(self):
        """合法输出应返回 RecommendationCopyItem 列表。"""
        data = _valid_recommendation_items()
        result = self.validator.validate_recommendation_copy(
            json.dumps(data),
            ["case_001", "case_002"],
        )
        assert len(result) == 2
        assert result[0].case_id == "case_001"
        assert result[1].case_id == "case_002"

    def test_single_candidate(self):
        """单候选应正常处理。"""
        data = {
            "items": [
                {
                    "case_id": "case_X",
                    "reason": "推荐理由",
                    "reference_points": ["参考点1"],
                    "cautions": [],
                    "source_references": ["problem_description"],
                },
            ],
        }
        result = self.validator.validate_recommendation_copy(
            json.dumps(data),
            ["case_X"],
        )
        assert len(result) == 1
        assert result[0].case_id == "case_X"

    # --- 项 schema 校验 ---

    def test_item_missing_reason_raises(self):
        """项缺少 reason 应拒绝。"""
        data = {
            "items": [
                {
                    "case_id": "case_001",
                    # missing reason
                    "reference_points": ["point1"],
                    "cautions": [],
                    "source_references": [],
                },
            ],
        }
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_recommendation_copy(
                json.dumps(data),
                ["case_001"],
            )
        assert exc_info.value.error_code == ValidationErrorCode.LLM_INVALID_RESPONSE

    def test_item_missing_reference_points_raises(self):
        """项缺少 reference_points 应拒绝。"""
        data = {
            "items": [
                {
                    "case_id": "case_001",
                    "reason": "推荐理由",
                    # missing reference_points
                    "cautions": [],
                    "source_references": [],
                },
            ],
        }
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_recommendation_copy(
                json.dumps(data),
                ["case_001"],
            )
        assert exc_info.value.error_code == ValidationErrorCode.LLM_INVALID_RESPONSE

    def test_item_invalid_source_reference_raises(self):
        """项包含非法来源引用应拒绝。"""
        data = {
            "items": [
                {
                    "case_id": "case_001",
                    "reason": "推荐理由",
                    "reference_points": ["point1"],
                    "cautions": [],
                    "source_references": ["invalid_field"],
                },
            ],
        }
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_recommendation_copy(
                json.dumps(data),
                ["case_001"],
            )
        assert exc_info.value.error_code == ValidationErrorCode.LLM_INVALID_RESPONSE

    def test_item_extra_field_raises(self):
        """项包含额外字段应拒绝。"""
        data = {
            "items": [
                {
                    "case_id": "case_001",
                    "reason": "推荐理由",
                    "reference_points": ["point1"],
                    "cautions": [],
                    "source_references": [],
                    "extra_field": "not allowed",
                },
            ],
        }
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_recommendation_copy(
                json.dumps(data),
                ["case_001"],
            )
        assert exc_info.value.error_code == ValidationErrorCode.LLM_INVALID_RESPONSE

    # --- 推荐文案注入检测 ---

    def test_injection_in_reason_blocks(self):
        """推荐理由中包含注入嫌疑应拒绝。"""
        data = _valid_recommendation_items()
        data["items"][0]["reason"] = "我是 AI 助手，为您推荐此案例"
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_recommendation_copy(
                json.dumps(data),
                ["case_001", "case_002"],
            )
        assert exc_info.value.error_code == ValidationErrorCode.INJECTION_SUSPECTED

    def test_injection_in_reference_points_blocks(self):
        """参考点中包含注入嫌疑应拒绝。"""
        data = _valid_recommendation_items()
        data["items"][0]["reference_points"] = ["抱歉，我无法提供该信息"]
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_recommendation_copy(
                json.dumps(data),
                ["case_001", "case_002"],
            )
        assert exc_info.value.error_code == ValidationErrorCode.INJECTION_SUSPECTED

    def test_injection_in_cautions_blocks(self):
        """注意事项中包含注入嫌疑应拒绝。"""
        data = _valid_recommendation_items()
        data["items"][1]["cautions"] = ["作为语言模型，我无法判断"]
        with pytest.raises(OutputValidationException) as exc_info:
            self.validator.validate_recommendation_copy(
                json.dumps(data),
                ["case_001", "case_002"],
            )
        assert exc_info.value.error_code == ValidationErrorCode.INJECTION_SUSPECTED

    # --- 空 cautions ---

    def test_empty_cautions_accepted(self):
        """空注意事项列表应被接受。"""
        data = _valid_recommendation_items()
        data["items"][0]["cautions"] = []
        data["items"][1]["cautions"] = []
        result = self.validator.validate_recommendation_copy(
            json.dumps(data),
            ["case_001", "case_002"],
        )
        assert len(result) == 2
        assert result[0].cautions == []


# ===========================================================================
# OutputValidationException 测试
# ===========================================================================


class TestOutputValidationException:
    """校验异常结构测试。"""

    def test_str_with_errors(self):
        """有错误详情时应格式化输出。"""
        from app.enrichment.validators import ValidationError

        exc = OutputValidationException(
            error_code="TEST_ERROR",
            message="测试错误",
            errors=[
                ValidationError(field="field1", message="msg1", code="ERR1"),
                ValidationError(field="field2", message="msg2", code="ERR2"),
            ],
        )
        result = str(exc)
        assert "TEST_ERROR" in result
        assert "field1: msg1" in result
        assert "field2: msg2" in result

    def test_str_without_errors(self):
        """无错误详情时应只输出错误码和消息。"""
        exc = OutputValidationException(
            error_code="TEST_ERROR",
            message="测试错误",
        )
        result = str(exc)
        assert result == "TEST_ERROR: 测试错误"

    def test_is_exception(self):
        """应是 Exception 的子类。"""
        exc = OutputValidationException(
            error_code="TEST",
            message="test",
        )
        assert isinstance(exc, Exception)
