"""A3 案例管理后端应用入口。"""
from fastapi import FastAPI

from app.cases.router import router as case_router
from app.core.config import settings
from app.enrichment.router import router as enrichment_router


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