# 企业微信群发系统 — 日志系统

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

def setup_logging(config=None):
    """初始化日志系统。"""
    if config is None:
        from .config import Config
        config = Config()

    log_config = config.get("logging", {})
    level = getattr(logging, log_config.get("level", "INFO").upper(), logging.INFO)
    fmt = log_config.get("format", "%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 清除已有处理器
    root_logger.handlers.clear()

    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(fmt))
    root_logger.addHandler(console_handler)

    # 文件输出
    log_file = log_config.get("file", "logs/app.log")
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=log_config.get("max_size_mb", 10) * 1024 * 1024,
        backupCount=log_config.get("backup_count", 7),
        encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(fmt))
    root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name):
    """获取指定名称的 logger。"""
    return logging.getLogger(name)
