#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
from pathlib import Path
from loguru import logger

# Global logger instance
app_logger = None


def setup_logger(log_dir, log_retention_days=7, log_rotation="1 day", debug_mode=False):
    """
    Create a logger instance

    Parameters:
        log_dir (str): Direktori log
        log_retention_days (int): Jumlah hari retensi log
        log_rotation (str): Interval rotasi log
        debug_mode (bool): Apakah akan mengaktifkan mode debug
    """
    global app_logger

    # Hapus semua prosesor log yang ada (mendukung pemuatan ulang panas)
    logger.remove()

    log_level = "DEBUG" if debug_mode else "INFO"

    console_format = (
        "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
        if not debug_mode
        else "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>"
    )

    # 添加控制台输出（根据 debug_mode 设置级别）
    logger.add(sys.stderr, level=log_level, format=console_format, colorize=True)

    # 只有在 debug_mode 时才添加文件输出
    if debug_mode:
        try:
            log_path = Path(log_dir)
            log_path.mkdir(parents=True, exist_ok=True)

            log_file = log_path / "{time:YYYY-MM-DD}.log"
            file_format = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}"

            logger.add(
                str(log_file),
                level=log_level,
                format=file_format,
                rotation=log_rotation,
                retention=f"{log_retention_days} days",
                encoding="utf-8",
                compression="zip",
                enqueue=True,
                catch=True,
            )
        except (PermissionError, OSError) as e:
            # Jika tidak dapat membuat direktori atau file log, turunkan ke hanya output konsol
            logger.warning(f"⚠️ Tidak dapat membuat file log ({e}), hanya akan menggunakan output konsol")

    app_logger = logger

    return logger


def get_logger():
    """Get the logger instance"""
    global app_logger
    if app_logger is None:
        # Jika logger belum pernah diatur, gunakan konfigurasi default
        logger.remove()  # Hapus semua prosesor yang ada
        logger.add(sys.stderr, level="INFO", format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>")
        app_logger = logger
    return app_logger


if __name__ == "__main__":
    """Test the logger"""
    import tempfile

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            setup_logger(temp_dir, debug_mode=True)

            logger.debug("Ini adalah log debug")
            logger.info("Ini adalah log informasi")
            logger.warning("Ini adalah log peringatan")
            logger.error("Ini adalah log kesalahan")
            logger.critical("Ini adalah log kritis")

            try:
                1 / 0
            except ZeroDivisionError:
                logger.exception("Terjadi pengecualian pembagian nol")

            print("✅ Uji log selesai")

            logger.remove()

        except Exception as e:
            print(f"❌ Uji log gagal: {e}")
            logger.remove()
            raise
