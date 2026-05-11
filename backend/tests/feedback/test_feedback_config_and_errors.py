"""任务 1.1：反馈共享配置与错误码契约测试。"""

import pytest

from app.core.config import FeedbackConfig, get_app_config
from app.core.errors import ErrorCode, _FEEDBACK_PUBLIC_MESSAGES


def test_error_code_feedback_constants_exist() -> None:
    """稳定错误码：目标不存在、目标不匹配、字段校验。"""
    assert ErrorCode.FEEDBACK_TARGET_NOT_FOUND == "FEEDBACK_TARGET_NOT_FOUND"
    assert ErrorCode.FEEDBACK_TARGET_MISMATCH == "FEEDBACK_TARGET_MISMATCH"
    assert ErrorCode.FEEDBACK_VALIDATION_ERROR == "FEEDBACK_VALIDATION_ERROR"


def test_feedback_public_messages_cover_feedback_codes() -> None:
    """错误码具备可对外展示的稳定文案（不含敏感正文）。"""
    assert ErrorCode.FEEDBACK_TARGET_NOT_FOUND in _FEEDBACK_PUBLIC_MESSAGES
    assert ErrorCode.FEEDBACK_TARGET_MISMATCH in _FEEDBACK_PUBLIC_MESSAGES
    assert ErrorCode.FEEDBACK_VALIDATION_ERROR in _FEEDBACK_PUBLIC_MESSAGES
    for text in _FEEDBACK_PUBLIC_MESSAGES.values():
        assert isinstance(text, str)
        assert len(text) > 0


def test_feedback_config_defaults() -> None:
    """反馈配置默认值：开关、备注最大长度、统计默认时间范围。"""
    cfg = FeedbackConfig()
    assert cfg.enabled is True
    assert cfg.comment_max_length == 2000
    assert cfg.stats_default_range_days == 30


def test_load_app_config_includes_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    """AppConfig 聚合反馈配置，且可从环境变量覆盖。"""
    monkeypatch.delenv("FEEDBACK_ENABLED", raising=False)
    monkeypatch.delenv("FEEDBACK_COMMENT_MAX_LENGTH", raising=False)
    monkeypatch.delenv("FEEDBACK_STATS_DEFAULT_RANGE_DAYS", raising=False)
    get_app_config.cache_clear()
    try:
        app_cfg = get_app_config()
        assert app_cfg.feedback.enabled is True
        assert app_cfg.feedback.comment_max_length == 2000
        assert app_cfg.feedback.stats_default_range_days == 30
    finally:
        get_app_config.cache_clear()


def test_load_app_config_feedback_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEEDBACK_ENABLED", "false")
    monkeypatch.setenv("FEEDBACK_COMMENT_MAX_LENGTH", "512")
    monkeypatch.setenv("FEEDBACK_STATS_DEFAULT_RANGE_DAYS", "7")
    get_app_config.cache_clear()
    try:
        app_cfg = get_app_config()
        assert app_cfg.feedback.enabled is False
        assert app_cfg.feedback.comment_max_length == 512
        assert app_cfg.feedback.stats_default_range_days == 7
    finally:
        monkeypatch.delenv("FEEDBACK_ENABLED", raising=False)
        monkeypatch.delenv("FEEDBACK_COMMENT_MAX_LENGTH", raising=False)
        monkeypatch.delenv("FEEDBACK_STATS_DEFAULT_RANGE_DAYS", raising=False)
        get_app_config.cache_clear()
