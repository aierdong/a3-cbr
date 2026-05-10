"""A3 案例管理后端应用入口。"""
import logging

from fastapi import FastAPI

from app.cases.router import router as case_router
from app.core.config import get_app_config, settings
from app.db.session import async_session_maker
from app.enrichment.cleanup import EnrichmentCleanupService, load_cleanup_config
from app.enrichment.router import router as enrichment_router
from app.vector_indexing.cleanup import VectorCleanupService

logger = logging.getLogger(__name__)

# 清理服务实例（模块级别，供 startup/shutdown 钩子使用）
cleanup_service: EnrichmentCleanupService | None = None
vector_cleanup_service: VectorCleanupService | None = None


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""
    app = FastAPI(
        title="A3 案例管理系统",
        description="提供 A3 案例的创建、编辑、详情、列表查询和删除能力",
        version="0.1.0",
    )

    # 注册案例路由
    app.include_router(case_router)

    # 注册增强路由
    app.include_router(enrichment_router)

    return app


app = create_app()


@app.on_event("startup")
async def start_cleanup_service():
    """启动增强清理服务后台任务。

    加载清理配置，创建 EnrichmentCleanupService 实例，
    使用 asyncio.create_task 启动周期性清理后台任务。
    启动失败时记录错误日志，不阻塞应用启动。
    """
    global cleanup_service, vector_cleanup_service
    try:
        config = load_cleanup_config()
        cleanup_service = EnrichmentCleanupService(
            db_session_factory=async_session_maker,
            config=config,
        )
        cleanup_service.start()
        logger.info("增强清理服务已启动")
    except Exception:
        logger.exception("增强清理服务启动失败，不影响应用正常运行")

    try:
        emb = get_app_config().embedding
        vector_cleanup_service = VectorCleanupService(
            db_session_factory=async_session_maker,
            interval_seconds=emb.vector_cleanup_interval_seconds,
        )
        vector_cleanup_service.start()
        logger.info("向量孤立清理服务已启动")
    except Exception:
        logger.exception("向量孤立清理服务启动失败，不影响应用正常运行")


@app.on_event("shutdown")
async def stop_cleanup_service():
    """停止增强清理服务。

    优雅停止清理服务后台任务。
    """
    global vector_cleanup_service
    if cleanup_service is not None:
        await cleanup_service.stop()
        logger.info("增强清理服务已停止")

    if vector_cleanup_service is not None:
        await vector_cleanup_service.stop()
        logger.info("向量孤立清理服务已停止")


@app.get("/health")
def health_check():
    """健康检查端点。"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True,
    )