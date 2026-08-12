# 企业微信群发系统 — 执行端客户端

import asyncio
import json
import logging
import os
import sys
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.shared.config import Config
from app.shared.connection import ConnectionManager
from app.shared.state import get_state_store
from app.shared.template_engine import get_template_engine
from app.worker.monitor import MonitorEngine
from app.worker.sender import SendEngine

logger = logging.getLogger(__name__)


class WorkerClient:
    """执行端客户端。

    负责:
    1. 连接主控 (局域网直连或云中继)
    2. 心跳上报
    3. 监控引擎 — 轮询 + 上报客户消息
    4. 发送引擎 — 接收并执行群发任务
    5. 预警本地弹窗
    """

    def __init__(self, worker_name: str = None):
        self.config = Config()
        self.store = get_state_store()

        # 执行端标识
        self.worker_name = worker_name or os.environ.get(
            "WECOM_WORKER_NAME",
            f"worker_{os.getpid()}"
        )
        self.worker_id = self.worker_name

        # 模块
        self.connection: Optional[ConnectionManager] = None
        self.monitor = MonitorEngine(self.worker_id)
        self.sender = SendEngine(self.worker_id)
        self.template_engine = get_template_engine()

        # 本地负责的群
        self._assigned_groups: set = set()

        # 控制
        self._running = False
        self._heartbeat_task: Optional[asyncio.Task] = None

    # ==== 启动 ====

    async def start_async(self):
        """异步启动执行端。"""
        self._running = True
        logger.info(f"执行端启动: {self.worker_id}")

        # 建立连接
        self.connection = ConnectionManager(mode="worker", config=self.config.get_all())
        self.connection.on_message(self._handle_message)
        self.connection.on_disconnect(self._handle_disconnect)

        url = await self.connection.connect()
        logger.info(f"已连接到: {url}")

        # 发送上线通知
        await self.connection.send({
            "type": "worker_info",
            "worker_id": self.worker_id,
            "info": {
                "name": self.worker_name,
                "hostname": os.environ.get("COMPUTERNAME", "unknown"),
                "version": "1.0.0",
                "started_at": datetime.now().isoformat(),
            }
        })

        # 启动心跳
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # 启动监控引擎
        self.monitor.on_customer_msg(self._on_customer_detected)
        self.monitor.on_staff_reply(self._on_staff_reply_detected)
        self.monitor.on_alert(self._on_local_alert)
        await self.monitor.start()

        # 设置发送引擎回调
        self.sender.on_result(self._on_send_result)

        # 启动消息监听
        listen_task = asyncio.create_task(self.connection.listen())

        # ====== 持续运行 ======
        try:
            await listen_task
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    def start(self):
        """启动执行端（同步入口）。"""
        asyncio.run(self.start_async())

    async def shutdown(self):
        """关闭执行端。"""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        await self.monitor.stop()
        if self.connection:
            await self.connection.disconnect()
        logger.info(f"执行端已关闭: {self.worker_id}")

    # ==== 心跳 ====

    async def _heartbeat_loop(self):
        """心跳循环。"""
        interval = self.config.get("monitor.heartbeat_interval", 10)
        while self._running:
            try:
                stats = self.monitor.get_stats()
                send_progress = self.sender.get_progress()

                await self.connection.send({
                    "type": "heartbeat",
                    "worker_id": self.worker_id,
                    "timestamp": datetime.now().isoformat(),
                    "monitor_stats": stats,
                    "send_progress": send_progress,
                })
            except Exception as e:
                logger.warning(f"心跳发送失败: {e}")
                await self._handle_disconnect()
                break
            await asyncio.sleep(interval)

    # ==== 消息处理 ====

    async def _handle_message(self, data: dict):
        """处理来自主控的消息。"""
        msg_type = data.get("type", "")

        if msg_type == "send_task":
            # 收到发送任务
            task_id = data.get("task_id")
            groups = data.get("groups", [])
            logger.info(f"收到发送任务: {task_id}, {len(groups)} 个群")

            # 异步执行发送
            asyncio.create_task(self.sender.execute_task(data))
        elif msg_type == "auto_reply":
            group_name = data.get("group_name")
            reply_text = data.get("reply_text")
            if group_name and reply_text:
                logger.info(f"收到自动回复任务: {group_name}")
                asyncio.create_task(self.sender.send_auto_reply(group_name, reply_text))

        elif msg_type == "takeover":
            # 接管其他执行端的群
            groups = data.get("groups", [])
            logger.info(f"接管群: {groups}")
            self._assigned_groups.update(groups)
            self.monitor.add_groups(groups)

        elif msg_type == "alert":
            # 收到主控广播的预警
            await self._handle_remote_alert(data)

        elif msg_type == "worker_status_update":
            # 执行端状态更新
            pass  # 仅记录，不需要特殊处理

        elif msg_type == "system":
            event = data.get("event", "")
            if event == "client_joined":
                logger.info(f"其他客户端上线: {data.get('client_id')}")
            elif event == "client_left":
                logger.info(f"其他客户端离线: {data.get('client_id')}")

    # ==== 监控回调 ====

    async def _on_customer_detected(self, data: dict):
        """监控到客户发言 → 上报主控。"""
        if self.connection and self.connection.is_connected:
            await self.connection.send({
                "type": "monitor_update",
                **data
            })

    async def _on_staff_reply_detected(self, data: dict):
        """监控到员工回复 → 上报主控。"""
        if self.connection and self.connection.is_connected:
            await self.connection.send({
                "type": "staff_reply",
                **data
            })

    async def _on_local_alert(self, data: dict):
        """本地超时预警 → 弹窗 + 上报主控。"""
        logger.warning(f"本地预警: {data.get('group_name')}")

        # 本地弹窗
        self._show_local_notification(data)

        # 上报主控（主控会广播给其他端）
        if self.connection and self.connection.is_connected:
            await self.connection.send({
                "type": "alert_trigger",
                **data
            })

    async def _on_send_result(self, data: dict):
        """发送结果 → 上报主控。"""
        if self.connection and self.connection.is_connected:
            await self.connection.send({
                "type": "send_result",
                **data
            })

    async def _handle_remote_alert(self, data: dict):
        """处理来自主控的远程预警 → 本地弹窗。"""
        group_name = data.get("group_name", "未知群")
        elapsed = data.get("elapsed_seconds", 0)
        logger.warning(f"收到预警: {group_name} ({elapsed}s)")
        self._show_local_notification(data)

    # ==== 本地通知 ====

    def _show_local_notification(self, data: dict):
        """显示本地桌面通知 + 播放声音。"""
        group_name = data.get("group_name", "未知群")
        elapsed = data.get("elapsed_seconds", 0)

        # 桌面弹窗
        try:
            from win10toast import ToastNotifier
            toaster = ToastNotifier()
            toaster.show_toast(
                title=f"⚠ 超时预警 - {group_name}",
                msg=f"客户发言 {elapsed} 秒未回复",
                duration=10,
                threaded=True,
            )
            logger.info(f"桌面通知已显示: {group_name}")
        except ImportError:
            logger.debug("win10toast 未安装，跳过桌面通知")
        except Exception as e:
            logger.warning(f"桌面通知失败: {e}")

        # 声音提醒
        try:
            from playsound import playsound
            sound_file = self.config.get("alert.sound_file", "")
            if sound_file and Path(sound_file).exists():
                threading.Thread(
                    target=playsound,
                    args=(sound_file,),
                    daemon=True
                ).start()
        except ImportError:
            logger.debug("playsound 未安装，跳过声音提醒")
        except Exception as e:
            logger.warning(f"声音播放失败: {e}")

    # ==== 断连处理 ====

    async def _handle_disconnect(self):
        """处理断连。"""
        logger.warning("连接已断开，尝试重连...")
        if self.connection:
            success = await self.connection.reconnect(max_retries=10, delay=5)
            if success:
                logger.info("重连成功")
                # 重新上报状态
                await self.connection.send({
                    "type": "worker_info",
                    "worker_id": self.worker_id,
                    "info": {"name": self.worker_name, "reconnected": True}
                })
            else:
                logger.error("重连失败，执行端将继续本地运行")
                # 本地模式: 仍可监控和弹窗，但无法上报


