# 企业微信群发系统 — 连接管理器

import asyncio
import json
import logging
from typing import Optional, Callable

import websockets

from .lan_discovery import LANDiscovery

logger = logging.getLogger(__name__)


class ConnectionManager:
    """连接管理器。

    负责主控与执行端之间的 WebSocket 连接管理。
    启动时优先尝试局域网直连，失败则连接云中继。
    """

    def __init__(self, mode="worker", config=None):
        self.mode = mode  # "master" 或 "worker"
        self._config = config or {}
        self._ws = None
        self._connected = False
        self._on_message: Optional[Callable] = None
        self._on_connect: Optional[Callable] = None
        self._on_disconnect: Optional[Callable] = None

    # ---- 事件回调 ----

    def on_message(self, callback: Callable):
        """设置消息回调。"""
        self._on_message = callback

    def on_connect(self, callback: Callable):
        """设置连接回调。"""
        self._on_connect = callback

    def on_disconnect(self, callback: Callable):
        """设置断连回调。"""
        self._on_disconnect = callback

    # ---- 连接生命周期 ----

    async def connect(self) -> str:
        """建立连接，返回实际使用的连接地址。"""
        relay_url = self._config.get("relay", {}).get("url", "ws://localhost:8080")

        # 1. 尝试局域网直连
        direct_url = None
        if self.mode == "worker":
            discovery = LANDiscovery()
            direct_url = discovery.discover(timeout=3)
            if not direct_url:
                direct_url = LANDiscovery.discover_mdns(timeout=3)

        if direct_url:
            logger.info(f"尝试直连: {direct_url}")
            try:
                self._ws = await websockets.connect(
                    direct_url,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5
                )
                logger.info(f"直连成功: {direct_url}")
                self._connected = True
                if self._on_connect:
                    self._on_connect(direct_url)
                return direct_url
            except Exception as e:
                logger.warning(f"直连失败: {e}, 降级到中继")

        # 2. 降级到云中继
        logger.info(f"连接中继: {relay_url}")
        try:
            self._ws = await websockets.connect(
                relay_url,
                ping_interval=30,
                ping_timeout=10,
                close_timeout=5
            )
            logger.info(f"中继连接成功: {relay_url}")
            self._connected = True
            if self._on_connect:
                self._on_connect(relay_url)
            return relay_url
        except Exception as e:
            logger.error(f"连接中继失败: {e}")
            raise

    async def disconnect(self):
        """断开连接。"""
        self._connected = False
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def send(self, data: dict):
        """发送 JSON 消息。"""
        if not self._ws or not self._connected:
            logger.warning("未连接，消息丢弃")
            return

        try:
            message = json.dumps(data, ensure_ascii=False, default=str)
            await self._ws.send(message)
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            self._connected = False

    async def listen(self):
        """持续监听消息（阻塞循环）。"""
        if not self._ws:
            logger.error("未建立连接，无法监听")
            return

        try:
            async for message in self._ws:
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    data = {"type": "raw", "content": message}

                if self._on_message:
                    # 根据消息类型可异步或同步处理
                    result = self._on_message(data)
                    if asyncio.iscoroutine(result):
                        await result

        except websockets.ConnectionClosed:
            logger.warning("WebSocket 连接已关闭")
            self._connected = False
            if self._on_disconnect:
                self._on_disconnect()
        except Exception as e:
            logger.error(f"监听异常: {e}")
            self._connected = False
            if self._on_disconnect:
                self._on_disconnect()

    @property
    def is_connected(self):
        return self._connected

    async def reconnect(self, max_retries=5, delay=5):
        """自动重连。"""
        for attempt in range(max_retries):
            logger.info(f"重连尝试 {attempt + 1}/{max_retries}")
            try:
                await self.connect()
                return True
            except Exception as e:
                logger.warning(f"重连失败: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
        return False
