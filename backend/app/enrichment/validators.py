"""LLM 输出解析、schema 校验和标签规范化。

将 LLM 原始输出解析为可信结构化结果。
校验必填字段、枚举、长度、来源引用与候选 case_id。
标签建议去重、去空、限制数量，校验通过后持久化为规范化标签字符串列表。
检测非预期系统级文本模式（角色声明、拒绝回答模板），命中则拒绝输出。

Requirements: 2.3, 3.2, 3.3, 4.1, 4.2, 5.2, 5.3
Boundary: OutputValidator
"""
import json
import logging
import re
from dataclasses import dataclass, field

from app.enrichment.schemas import (
    CaseEnrichmentOutput,
    RecommendationCopyItem,
    SourceField,
)

logger = logging.getLogger(__name__)

# =============================================================================
# 常量
# =============================================================================

MAX_TAG_COUNT = 10
MAX_SUMMARY_LENGTH = 200
OUTPUT_VERSION = "1.0"

_VALID_SOURCE_FIELD_VALUES: frozenset[str] = frozenset(
    e.value for e in SourceField
)

# 推荐文案 LLM 常返回与案例增强输出同名的字段别名，映射到 SourceField 契约值
_RECOMMENDATION_SOURCE_REF_ALIASES: dict[str, str] = {
    "problem_summary": SourceField.PROBLEM_DESCRIPTION.value,
    "solution_summary": SourceField.OUTCOME.value,
    "core_solution_steps": SourceField.SOLUTION_STEPS.value,
    "structured_suggestions": SourceField.CONTEXT.value,
    "tag_suggestions": SourceField.CONTEXT.value,
    "tag_suggestion": SourceField.CONTEXT.value,
    "applicable_scenarios": SourceField.CONTEXT.value,
    "root_cause_category": SourceField.ROOT_CAUSE.value,
    "problem_type_suggestion": SourceField.PROBLEM_DESCRIPTION.value,
}


def _canonical_source_field_token(token: str) -> str | None:
    """将 LLM 输出的来源字段标记规范化为 SourceField 枚举值。"""
    cleaned = token.strip()
    if not cleaned:
        return None
    key = cleaned.lower().replace(" ", "_").replace("-", "_")
    if key in _VALID_SOURCE_FIELD_VALUES:
        return key
    mapped = _RECOMMENDATION_SOURCE_REF_ALIASES.get(key)
    return mapped


def _normalize_recommendation_source_references(raw: object) -> list[str]:
    """解析并规范化推荐文案中的 source_references 列表。"""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for ref in raw:
        if isinstance(ref, dict):
            ref = ref.get("field_name") or ref.get("field")
        if not isinstance(ref, str):
            continue
        canon = _canonical_source_field_token(ref)
        if canon:
            out.append(canon)
    return out


def _coerce_recommendation_copy_item_raw(item_raw: object) -> object:
    """在校验前修正 LLM 常见漂移字段（不改排序、不删 case_id）。"""
    if not isinstance(item_raw, dict):
        return item_raw
    coerced = dict(item_raw)
    if "source_references" in coerced:
        coerced["source_references"] = _normalize_recommendation_source_references(
            coerced["source_references"],
        )
    return coerced


# =============================================================================
# 输出侧注入嫌疑模式
# =============================================================================

_INJECTION_SUSPECTED_PATTERNS: list[re.Pattern] = [
    re.compile(r"我是\s*(AI|人工智能|语言模型|助手|机器人)", re.IGNORECASE),
    re.compile(r"AI助手", re.IGNORECASE),
    re.compile(r"语言模型", re.IGNORECASE),
    re.compile(r"作为\s*(AI|人工智能|语言模型)", re.IGNORECASE),
    re.compile(r"as\s+(an?\s+)?(AI|language\s+model)", re.IGNORECASE),
    re.compile(r"I\s+am\s+(an?\s+)?(AI|language\s+model)", re.IGNORECASE),
    re.compile(r"抱歉[，,]?\s*(我)?(无法|不能|没有办法)", re.IGNORECASE),
    re.compile(r"无法回答", re.IGNORECASE),
    re.compile(r"不能提供", re.IGNORECASE),
    re.compile(r"(I'?m?\s+)?sorry[,.]?\s*(I\s+)?(can't|cannot|am\s+unable)", re.IGNORECASE),
    re.compile(r"忽略(以上|之前|前述)(指令|规则)", re.IGNORECASE),
]


# =============================================================================
# 错误码
# =============================================================================


class ValidationErrorCode:
    """校验错误码常量。"""

    LLM_INVALID_RESPONSE = "LLM_INVALID_RESPONSE"
    INJECTION_SUSPECTED = "INJECTION_SUSPECTED"
    MISSING_FIELD = "MISSING_FIELD"
    INVALID_ENUM = "INVALID_ENUM"
    CONSTRAINT_VIOLATION = "CONSTRAINT_VIOLATION"
    CANDIDATE_MISMATCH = "CANDIDATE_MISMATCH"


# =============================================================================
# 校验错误
# =============================================================================


@dataclass
class ValidationError:
    """单条校验错误详情。"""

    field: str
    message: str
    code: str


@dataclass
class OutputValidationException(Exception):
    """输出校验异常，包含错误码和结构化错误详情。"""

    error_code: str
    message: str
    errors: list[ValidationError] = field(default_factory=list)

    def __str__(self) -> str:
        """格式化校验异常为可读字符串。"""
        if self.errors:
            details = "; ".join(
                f"{e.field}: {e.message}" for e in self.errors
            )
            return f"{self.error_code}: {self.message} ({details})"
        return f"{self.error_code}: {self.message}"


# =============================================================================
# 标签规范化
# =============================================================================


def normalize_tags(raw_tags: list[str], max_count: int = MAX_TAG_COUNT) -> list[str]:
    """标签去空、去重并限制数量。

    保留首次出现顺序，移除空白标签，去重后截断至 max_count。

    Args:
        raw_tags: 原始标签列表
        max_count: 最大标签数量，默认 10

    Returns:
        规范化后的标签列表
    """
    seen: set[str] = set()
    normalized: list[str] = []
    for tag in raw_tags:
        stripped = tag.strip()
        if not stripped:
            continue
        if stripped not in seen:
            seen.add(stripped)
            normalized.append(stripped)
    return normalized[:max_count]


# =============================================================================
# OutputValidator
# =============================================================================


class OutputValidator:
    """LLM 输出解析与 schema 校验。

    将 LLM 原始输出解析为可信结构化结果：
    1. 解析 JSON
    2. 校验 schema（必填字段、枚举、长度）
    3. 检测输出侧注入嫌疑模式
    4. 规范化标签
    5. 校验 missing_information 一致性
    6. 校验摘要长度

    推荐文案校验：
    1. 解析 JSON
    2. 校验 items 数量与候选一致
    3. 校验 case_id 引用匹配
    4. 检测输出侧注入嫌疑模式
    """

    # 输出侧注入嫌疑模式
    _INJECTION_SUSPECTED_PATTERNS = _INJECTION_SUSPECTED_PATTERNS

    # -----------------------------------------------------------------
    # 输出侧注入检测
    # -----------------------------------------------------------------

    def check_output_injection(self, text: str) -> tuple[bool, str]:
        """检测输出文本中的注入嫌疑模式。

        Args:
            text: 待检测文本

        Returns:
            (is_suspected, reason)
            - 嫌疑命中返回 (True, "输出侧注入嫌疑: ...")
            - 无命中返回 (False, "")
        """
        for pattern in self._INJECTION_SUSPECTED_PATTERNS:
            match = pattern.search(text)
            if match:
                reason = f"输出侧注入嫌疑: {pattern.pattern}"
                logger.warning(
                    "输出侧注入检测: pattern=%s, match=%s, text_preview=%s",
                    pattern.pattern,
                    match.group(),
                    text[:200],
                )
                return True, reason
        return False, ""

    # -----------------------------------------------------------------
    # 案例增强输出校验
    # -----------------------------------------------------------------

    def validate_enrichment_output(
        self,
        raw_content: str,
        case_id: str,
    ) -> CaseEnrichmentOutput:
        """校验案例增强 LLM 输出。

        执行步骤：
        1. 解析 JSON
        2. 规范化标签（去空、去重、数量限制）
        3. 校验 against CaseEnrichmentOutput schema
        4. 检测输出侧注入嫌疑模式
        5. 校验 missing_information 一致性
        6. 校验摘要长度

        Args:
            raw_content: LLM 原始输出字符串
            case_id: 案例标识，用于错误日志

        Returns:
            校验通过的 CaseEnrichmentOutput

        Raises:
            OutputValidationException: 校验失败时抛出
        """
        # 1. 解析 JSON
        try:
            data = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            logger.warning(
                "JSON 解析失败: case_id=%s, error=%s, content_preview=%s",
                case_id,
                str(exc),
                raw_content, #raw_content[:200],
            )
            raise OutputValidationException(
                error_code=ValidationErrorCode.LLM_INVALID_RESPONSE,
                message=f"无法解析 LLM 输出为 JSON: {exc}",
            ) from exc

        if not isinstance(data, dict):
            raise OutputValidationException(
                error_code=ValidationErrorCode.LLM_INVALID_RESPONSE,
                message="LLM 输出不是 JSON 对象",
            )

        # 2. 规范化标签（在 schema 校验前清理）
        if "tag_suggestions" in data and isinstance(data["tag_suggestions"], list):
            data["tag_suggestions"] = normalize_tags(data["tag_suggestions"])

        # 3. Schema 校验
        try:
            output = CaseEnrichmentOutput.model_validate(data)
        except Exception as exc:
            errors = self._extract_pydantic_errors(exc)
            logger.warning(
                "Schema 校验失败: case_id=%s, errors=%s",
                case_id,
                errors,
            )
            raise OutputValidationException(
                error_code=ValidationErrorCode.LLM_INVALID_RESPONSE,
                message="LLM 输出 schema 校验失败",
                errors=errors,
            ) from exc

        # 4. 检测输出侧注入嫌疑
        self._check_enrichment_injection(output, case_id)

        # 5. 校验 missing_information 一致性
        self._check_missing_information_consistency(output, case_id)

        # 6. 校验摘要长度
        self._check_summary_length(output, case_id)

        return output

    # -----------------------------------------------------------------
    # 推荐文案校验
    # -----------------------------------------------------------------

    def validate_recommendation_copy(
        self,
        raw_content: str,
        candidate_case_ids: list[str],
    ) -> list[RecommendationCopyItem]:
        """校验推荐文案 LLM 输出。

        执行步骤：
        1. 解析 JSON
        2. 提取 items 数组
        3. 校验 items 数量与候选一致
        4. 校验每个 item 的 schema
        5. 校验 case_id 引用匹配
        6. 检测输出侧注入嫌疑模式

        Args:
            raw_content: LLM 原始输出字符串
            candidate_case_ids: 输入候选的 case_id 列表（保持顺序）

        Returns:
            校验通过的 RecommendationCopyItem 列表

        Raises:
            OutputValidationException: 校验失败时抛出
        """
        # 1. 解析 JSON
        try:
            data = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            logger.warning(
                "推荐文案 JSON 解析失败: error=%s, content_preview=%s",
                str(exc),
                raw_content[:200],
            )
            raise OutputValidationException(
                error_code=ValidationErrorCode.LLM_INVALID_RESPONSE,
                message=f"无法解析推荐文案 LLM 输出为 JSON: {exc}",
            ) from exc

        if not isinstance(data, dict):
            raise OutputValidationException(
                error_code=ValidationErrorCode.LLM_INVALID_RESPONSE,
                message="推荐文案 LLM 输出不是 JSON 对象",
            )

        # 2. 提取 items 数组
        items_raw = data.get("items")
        if not isinstance(items_raw, list):
            raise OutputValidationException(
                error_code=ValidationErrorCode.MISSING_FIELD,
                message="推荐文案输出缺少 items 数组",
                errors=[
                    ValidationError(
                        field="items",
                        message="字段缺失或类型不是数组",
                        code=ValidationErrorCode.MISSING_FIELD,
                    ),
                ],
            )

        # 3. 校验 items 数量与候选一致
        if len(items_raw) != len(candidate_case_ids):
            raise OutputValidationException(
                error_code=ValidationErrorCode.CANDIDATE_MISMATCH,
                message=(
                    f"推荐文案项数量({len(items_raw)})与"
                    f"候选数量({len(candidate_case_ids)})不匹配"
                ),
                errors=[
                    ValidationError(
                        field="items",
                        message=(
                            f"期望 {len(candidate_case_ids)} 项，"
                            f"实际 {len(items_raw)} 项"
                        ),
                        code=ValidationErrorCode.CANDIDATE_MISMATCH,
                    ),
                ],
            )

        # 4. 逐项 schema 校验
        validated_items: list[RecommendationCopyItem] = []
        errors: list[ValidationError] = []
        for i, item_raw in enumerate(items_raw):
            try:
                coerced = _coerce_recommendation_copy_item_raw(item_raw)
                item = RecommendationCopyItem.model_validate(coerced)
                validated_items.append(item)
            except Exception as exc:
                item_errors = self._extract_pydantic_errors(exc)
                for err in item_errors:
                    err.field = f"items[{i}].{err.field}"
                errors.extend(item_errors)

        if errors:
            logger.warning("推荐文案 schema 校验失败: errors=%s", errors)
            raise OutputValidationException(
                error_code=ValidationErrorCode.LLM_INVALID_RESPONSE,
                message="推荐文案 schema 校验失败",
                errors=errors,
            )

        # 5. 校验 case_id 引用匹配（顺序和值）
        for i, (item, expected_id) in enumerate(
            zip(validated_items, candidate_case_ids)
        ):
            if item.case_id != expected_id:
                raise OutputValidationException(
                    error_code=ValidationErrorCode.CANDIDATE_MISMATCH,
                    message=(
                        f"推荐文案项[{i}]的 case_id('{item.case_id}')"
                        f"与候选('{expected_id}')不匹配"
                    ),
                    errors=[
                        ValidationError(
                            field=f"items[{i}].case_id",
                            message=(
                                f"期望 '{expected_id}'，"
                                f"实际 '{item.case_id}'"
                            ),
                            code=ValidationErrorCode.CANDIDATE_MISMATCH,
                        ),
                    ],
                )

        # 6. 检测输出侧注入嫌疑
        for i, item in enumerate(validated_items):
            self._check_recommendation_item_injection(item, i)

        return validated_items

    # -----------------------------------------------------------------
    # 内部辅助方法
    # -----------------------------------------------------------------

    def _check_enrichment_injection(
        self,
        output: CaseEnrichmentOutput,
        case_id: str,
    ) -> None:
        """检测案例增强输出中的注入嫌疑。

        拼接所有文本字段后统一检测。
        """
        text_parts: list[str] = []
        if output.problem_summary:
            text_parts.append(output.problem_summary)
        if output.solution_summary:
            text_parts.append(output.solution_summary)
        text_parts.append(output.structured_suggestions.problem_type_suggestion)
        text_parts.append(output.structured_suggestions.root_cause_category)
        text_parts.extend(output.structured_suggestions.applicable_scenarios)
        text_parts.append(output.structured_suggestions.confidence_notes)
        for item in output.missing_information:
            text_parts.append(item.reason)

        combined = "\n".join(text_parts)
        is_suspected, reason = self.check_output_injection(combined)
        if is_suspected:
            logger.warning(
                "案例增强输出注入嫌疑: case_id=%s, reason=%s",
                case_id,
                reason,
            )
            raise OutputValidationException(
                error_code=ValidationErrorCode.INJECTION_SUSPECTED,
                message=reason,
            )

    def _check_recommendation_item_injection(
        self,
        item: RecommendationCopyItem,
        index: int,
    ) -> None:
        """检测推荐文案项中的注入嫌疑。"""
        text_parts = [item.reason]
        text_parts.extend(item.reference_points)
        text_parts.extend(item.cautions)

        combined = "\n".join(text_parts)
        is_suspected, reason = self.check_output_injection(combined)
        if is_suspected:
            logger.warning(
                "推荐文案注入嫌疑: item[%d], case_id=%s, reason=%s",
                index,
                item.case_id,
                reason,
            )
            raise OutputValidationException(
                error_code=ValidationErrorCode.INJECTION_SUSPECTED,
                message=f"推荐文案项[{index}]注入嫌疑: {reason}",
            )

    @staticmethod
    def is_result_publishable(output: CaseEnrichmentOutput) -> bool:
        """判断增强结果是否可发布为 valid 状态。

        当 missing_information 中存在 blocking_level=required 的条目时，
        结果不得发布为 valid（不得发布伪成功结果）。

        Args:
            output: 已校验通过的增强输出

        Returns:
            True 表示可发布，False 表示存在阻断性缺失信息
        """
        from app.enrichment.schemas import BlockingLevel

        return not any(
            item.blocking_level == BlockingLevel.REQUIRED
            for item in output.missing_information
        )

    def _check_missing_information_consistency(
        self,
        output: CaseEnrichmentOutput,
        case_id: str,
    ) -> None:
        """校验 missing_information 一致性。

        校验规则：
        1. 若 problem_summary 或 solution_summary 为空，
           但 missing_information 为空列表，则视为"空理由但宣称成功"，
           阻止发布。
        2. 若摘要存在但 missing_information 包含 blocking_level=required 的条目，
           则视为"伪成功"——声称能生成但实际有阻断性缺失，
           阻止发布。
        """
        from app.enrichment.schemas import BlockingLevel

        summaries_missing = (
            output.problem_summary is None
            or output.solution_summary is None
        )
        has_missing_info = len(output.missing_information) > 0

        if summaries_missing and not has_missing_info:
            logger.warning(
                "摘要缺失但 missing_information 为空: case_id=%s",
                case_id,
            )
            raise OutputValidationException(
                error_code=ValidationErrorCode.CONSTRAINT_VIOLATION,
                message=(
                    "摘要或推荐文案不可可靠生成时，"
                    "必须在 missing_information 中返回缺失信息说明"
                ),
                errors=[
                    ValidationError(
                        field="missing_information",
                        message=(
                            "problem_summary 或 solution_summary 为空时，"
                            "missing_information 不得为空"
                        ),
                        code=ValidationErrorCode.CONSTRAINT_VIOLATION,
                    ),
                ],
            )

        has_required_blocker = any(
            item.blocking_level == BlockingLevel.REQUIRED
            for item in output.missing_information
        )
        if has_required_blocker and not summaries_missing:
            logger.warning(
                "missing_information 含 required 级别条目但摘要已生成"
                "（伪成功）: case_id=%s",
                case_id,
            )
            raise OutputValidationException(
                error_code=ValidationErrorCode.CONSTRAINT_VIOLATION,
                message=(
                    "missing_information 中存在 required 级别的缺失条目时，"
                    "不得发布摘要（伪成功结果）"
                ),
                errors=[
                    ValidationError(
                        field="missing_information",
                        message=(
                            "blocking_level=required 的缺失条目存在时，"
                            "problem_summary 和 solution_summary 必须为 null"
                        ),
                        code=ValidationErrorCode.CONSTRAINT_VIOLATION,
                    ),
                ],
            )

    def _check_summary_length(
        self,
        output: CaseEnrichmentOutput,
        case_id: str,
    ) -> None:
        """校验摘要长度。"""
        errors: list[ValidationError] = []

        if output.problem_summary and len(output.problem_summary) > MAX_SUMMARY_LENGTH:
            errors.append(
                ValidationError(
                    field="problem_summary",
                    message=(
                        f"问题摘要长度({len(output.problem_summary)})超出"
                        f"限制({MAX_SUMMARY_LENGTH})"
                    ),
                    code=ValidationErrorCode.CONSTRAINT_VIOLATION,
                ),
            )

        if output.solution_summary and len(output.solution_summary) > MAX_SUMMARY_LENGTH:
            errors.append(
                ValidationError(
                    field="solution_summary",
                    message=(
                        f"方案摘要长度({len(output.solution_summary)})超出"
                        f"限制({MAX_SUMMARY_LENGTH})"
                    ),
                    code=ValidationErrorCode.CONSTRAINT_VIOLATION,
                ),
            )

        if errors:
            logger.warning("摘要长度超限: case_id=%s, errors=%s", case_id, errors)
            raise OutputValidationException(
                error_code=ValidationErrorCode.CONSTRAINT_VIOLATION,
                message="摘要长度超出限制",
                errors=errors,
            )

    def _extract_pydantic_errors(self, exc: Exception) -> list[ValidationError]:
        """从 Pydantic 校验异常中提取结构化错误。"""
        errors: list[ValidationError] = []
        if hasattr(exc, "errors"):
            for err in exc.errors():
                loc = err.get("loc", ())
                field_path = ".".join(str(part) for part in loc)
                errors.append(
                    ValidationError(
                        field=field_path or "<root>",
                        message=err.get("msg", str(err)),
                        code=ValidationErrorCode.MISSING_FIELD
                        if err.get("type") == "missing"
                        else ValidationErrorCode.INVALID_ENUM
                        if "enum" in err.get("type", "")
                        else ValidationErrorCode.CONSTRAINT_VIOLATION,
                    ),
                )
        else:
            errors.append(
                ValidationError(
                    field="<root>",
                    message=str(exc),
                    code=ValidationErrorCode.CONSTRAINT_VIOLATION,
                ),
            )
        return errors
