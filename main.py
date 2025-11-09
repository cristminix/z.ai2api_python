#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import psutil
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core import openai
from app.utils.reload_config import RELOAD_CONFIG
from app.utils.logger import setup_logger
from app.providers import initialize_providers

from app.admin import routes as admin_routes
from app.admin import api as admin_api

from granian import Granian


# Setup logger
logger = setup_logger(log_dir="logs", debug_mode=settings.DEBUG_LOGGING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化 Token 数据库
    from app.services.token_dao import init_token_database
    await init_token_database()

    # 初始化提供商系统
    initialize_providers()

    # 从数据库初始化 token 池（Z.AI 提供商）
    from app.utils.token_pool import initialize_token_pool_from_db
    token_pool = await initialize_token_pool_from_db(
        provider="zai",
        failure_threshold=settings.TOKEN_FAILURE_THRESHOLD,
        recovery_timeout=settings.TOKEN_RECOVERY_TIMEOUT
    )

    if not token_pool and not settings.ANONYMOUS_MODE:
        logger.warning("⚠️ Token yang tersedia tidak ditemukan dan mode anonim tidak diaktifkan, layanan mungkin tidak berfungsi dengan normal")

    yield

    logger.info("🔄 Aplikasi sedang ditutup...")


# Create FastAPI app with lifespan
# root_path is used for reverse proxy path prefix (e.g., /api or /path-prefix)
app = FastAPI(lifespan=lifespan, root_path=settings.ROOT_PATH)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# 挂载web端静态文件目录
try:
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
except RuntimeError:
    # 如果 static 目录不存在，创建它
    os.makedirs("app/static/css", exist_ok=True)
    os.makedirs("app/static/js", exist_ok=True)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include API routers
app.include_router(openai.router)

# Include admin routers
app.include_router(admin_routes.router)
app.include_router(admin_api.router)


@app.options("/")
async def handle_options():
    """Handle OPTIONS requests"""
    return Response(status_code=200)


@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "OpenAI Compatible API Server"}


def run_server():
    service_name = settings.SERVICE_NAME

    logger.info(f"🚀 Memulai layanan {service_name}...")
    logger.info(f"📡 Alamat pendengaran: 0.0.0.0:{settings.LISTEN_PORT}")
    logger.info(f"🔧 Mode debug: {'Diaktifkan' if settings.DEBUG_LOGGING else 'Dimatikan'}")
    logger.info(f"🔐 Mode anonim: {'Diaktifkan' if settings.ANONYMOUS_MODE else 'Dimatikan'}")

    try:
        Granian(
            "main:app",
            interface="asgi",
            address="0.0.0.0",
            port=settings.LISTEN_PORT,
            reload=False,  # 生产环境请关闭热重载
            process_name=service_name,  # 设置进程名称
            **RELOAD_CONFIG,    # 热重载配置
        ).serve()
    except KeyboardInterrupt:
        logger.info("🛑 Menerima sinyal interupsi, sedang menutup layanan...")
    except Exception as e:
        logger.error(f"❌ Gagal memulai layanan: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_server()
