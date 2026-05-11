"""反馈路径与检索写路径边界（静态检查）。"""

import inspect

import app.feedback.service as feedback_service


def test_feedback_service_does_not_reference_retrieval_pipeline() -> None:
    """确认反馈服务源码未耦合推荐检索主流程。"""
    src = inspect.getsource(feedback_service)
    assert "RecommendationService" not in src
    assert "recommend_similar_cases" not in src
    assert "RerankerClient" not in src
