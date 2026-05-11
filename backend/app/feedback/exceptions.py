"""反馈领域异常（服务层抛出，路由层映射 HTTP）。"""


class FeedbackTargetNotFoundError(Exception):
    """推荐运行不存在，或指定推荐项快照不存在。"""

    error_code = "FEEDBACK_TARGET_NOT_FOUND"


class FeedbackTargetMismatchError(Exception):
    """推荐项不属于给定推荐运行。"""

    error_code = "FEEDBACK_TARGET_MISMATCH"


class FeedbackDisabledError(Exception):
    """反馈功能已通过配置关闭。"""

    error_code = "FEEDBACK_DISABLED"  # 与 ErrorCode.FEEDBACK_DISABLED 对齐
