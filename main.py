#!/usr/bin/env python
# 企业微信群发系统 — 入口

import sys
import argparse
from pathlib import Path

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.shared.config import Config
from app.shared.logger import setup_logging
from app.shared.state import get_state_store


def main():
    parser = argparse.ArgumentParser(description="企业微信群发系统")
    parser.add_argument("--mode", choices=["master", "worker"], default="master",
                        help="运行模式: master(主控) 或 worker(执行端)")
    parser.add_argument("--config", type=str, default=None,
                        help="配置文件路径")
    parser.add_argument("--port", type=int, default=None,
                        help="主控端口")
    parser.add_argument("--relay", type=str, default=None,
                        help="中继服务器地址")

    args = parser.parse_args()

    # 加载配置
    config = Config.load(args.config)
    setup_logging(Config())

    # 初始化状态存储
    store = get_state_store()
    store.reset_daily()

    # 命令行参数覆盖
    if args.port:
        config["relay"]["master_port"] = args.port
    if args.relay:
        config["relay"]["url"] = args.relay

    if args.mode == "master":
        from app.master.server import MasterServer
        server = MasterServer()
        server.start()
    elif args.mode == "worker":
        from app.worker.client import WorkerClient
        client = WorkerClient()
        client.start()


if __name__ == "__main__":
    main()
