#!/usr/bin/env python
# ============================================
# 企业微信群发系统 — WebSocket 中继服务器
# ============================================
# 部署到 Render / Fly.io 免费层
# 启动: python relay.py
# 环境变量: PORT=8080
#
# 职责: 透明转发消息 — 接收到任何消息后广播给所有连接的客户端。
# 无状态、无业务逻辑，纯管道。
# ============================================

import asyncio
import os
import json
import logging
from websockets.asyncio.server import serve

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] relay: %(message)s"
)
logger = logging.getLogger("relay")

# 所有已连接的 WebSocket 客户端
CONNECTIONS = set()
CONNECTION_IDS = {}  # websocket -> client_id


async def handler(websocket):
    """处理 WebSocket 连接。"""
    client_id = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"

    CONNECTIONS.add(websocket)
    CONNECTION_IDS[websocket] = client_id

    join_msg = json.dumps({
        "type": "system",
        "event": "client_joined",
        "client_id": client_id,
        "total_connections": len(CONNECTIONS)
    })
    await broadcast(join_msg, exclude=websocket)

    logger.info(f"客户端已连接: {client_id} (共 {len(CONNECTIONS)} 个)")

    try:
        async for message in websocket:
            # 解析消息，获取目标信息
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                data = {"type": "raw", "content": message}

            # 如果消息带有 target，仅转发给目标
            target = data.get("target", None)
            if target:
                await send_to_target(target, message)
            else:
                # 否则广播给所有其他客户端
                await broadcast(message, exclude=websocket)

    except Exception as e:
        logger.error(f"客户端连接异常: {client_id}: {e}")
    finally:
        CONNECTIONS.discard(websocket)
        CONNECTION_IDS.pop(websocket, None)

        leave_msg = json.dumps({
            "type": "system",
            "event": "client_left",
            "client_id": client_id,
            "total_connections": len(CONNECTIONS)
        })
        await broadcast(leave_msg)
        logger.info(f"客户端已断开: {client_id} (共 {len(CONNECTIONS)} 个)")


async def broadcast(message, exclude=None):
    """广播消息给所有已连接的客户端。"""
    if not CONNECTIONS:
        return

    disconnected = set()
    for ws in CONNECTIONS:
        if ws is exclude:
            continue
        try:
            await ws.send(message)
        except Exception:
            disconnected.add(ws)

    # 清理已断开的连接
    for ws in disconnected:
        CONNECTIONS.discard(ws)
        CONNECTION_IDS.pop(ws, None)


async def send_to_target(target_id, message):
    """发送消息给指定客户端。"""
    for ws, cid in CONNECTION_IDS.items():
        if cid == target_id:
            try:
                await ws.send(message)
                return
            except Exception:
                CONNECTIONS.discard(ws)
                CONNECTION_IDS.pop(ws, None)


async def main():
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"中继服务器启动于端口 {port}")
    async with serve(handler, "0.0.0.0", port) as server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
