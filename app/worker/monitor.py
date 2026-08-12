# 企业微信群发系统 — 执行端监控引擎

import asyncio
import logging
import time
from datetime import datetime
from typing import Optional, Set

from app.shared.config import Config
from app.shared.uia_scanner import get_scanner, ChatListItem
from app.shared.classifier import get_classifier

logger = logging.getLogger(__name__)


class MonitorEngine:
    """执行端消息监控引擎。

    周期性轮询企微聊天列表，检测客户新发言，
    识别员工回复，上报给主控。
    """

    def __init__(self, worker_id: str, assigned_groups: Set[str] = None):
        self.worker_id = worker_id
        self.config = Config()
        self.scanner = get_scanner()
        self.classifier = get_classifier()

        # 负责监控的群集合
        self._assigned_groups: Set[str] = assigned_groups or set()

        # 已知的聊天状态（用于比对变化）
        self._known_messages: dict = {}  # group_name -> last_message_text

        # 回调
        self._on_customer_msg = None
        self._on_staff_reply = None
        self._on_alert = None

        # 控制
        self._running = False
        self._task: Optional[asyncio.Task] = None

    # ==== 事件回调 ====

    def on_customer_msg(self, callback):
        """客户发言回调。"""
        self._on_customer_msg = callback

    def on_staff_reply(self, callback):
        """员工回复回调。"""
        self._on_staff_reply = callback

    def on_alert(self, callback):
        """超时预警回调。"""
        self._on_alert = callback

    # ==== 生命周期 ====

    async def start(self):
        """启动监控循环。"""
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(f"监控引擎已启动 (负责 {len(self._assigned_groups)} 个群)")

    async def stop(self):
        """停止监控。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("监控引擎已停止")

    def add_groups(self, groups: list):
        """动态添加监控群。"""
        for g in groups:
            self._assigned_groups.add(g)
        logger.info(f"新增监控群: {groups}")

    def remove_groups(self, groups: list):
        """移除监控群。"""
        for g in groups:
            self._assigned_groups.discard(g)

    # ==== 监控循环 ====

    async def _monitor_loop(self):
        """主监控循环。"""
        poll_interval = self.config.get("monitor.poll_interval", 30)
        alert_timeout = self.config.get("alert.timeout_seconds", 300)

        # 记录客户发言和员工回复的时间
        customer_msg_times: dict = {}  # group_name -> timestamp
        staff_reply_times: dict = {}
        alerted_groups: set = set()

        while self._running:
            try:
                items = await asyncio.to_thread(self.scanner.scan)

                for item in items:
                    group_name = item.group_name

                    # 过滤：只关注分配到的群
                    if self._assigned_groups and group_name not in self._assigned_groups:
                        continue

                    # 检测是否有新消息（与已知状态比对）
                    msg_key = f"{item.sender_name}:{item.last_message}"
                    known = self._known_messages.get(group_name, "")
                    if msg_key == known:
                        continue  # 无变化

                    self._known_messages[group_name] = msg_key

                    if not item.sender_name:
                        continue

                    # 分类发言者
                    now = time.time()
                    if self.classifier.is_customer(item.sender_name):
                        # 客户发言
                        customer_msg_times[group_name] = now
                        logger.info(f"[监控] 客户发言: {group_name} ← {item.sender_name}")

                        if self._on_customer_msg:
                            await self._on_customer_msg({
                                "group_name": group_name,
                                "sender": item.sender_name,
                                "timestamp": datetime.now().isoformat(),
                                "worker_id": self.worker_id,
                            })

                    elif self.classifier.is_staff(item.sender_name):
                        # 员工回复
                        staff_reply_times[group_name] = now
                        logger.info(f"[监控] 员工回复: {group_name} ← {item.sender_name}")

                        # 取消该群的预警
                        if group_name in alerted_groups:
                            alerted_groups.discard(group_name)

                        if self._on_staff_reply:
                            await self._on_staff_reply({
                                "group_name": group_name,
                                "sender": item.sender_name,
                                "timestamp": datetime.now().isoformat(),
                                "worker_id": self.worker_id,
                            })

                # 超时检测
                now = time.time()
                for group_name, last_customer_time in list(customer_msg_times.items()):
                    last_reply = staff_reply_times.get(group_name, 0)
                    # 客户发言后无回复，且超过阈值
                    if last_customer_time > last_reply and now - last_customer_time > alert_timeout:
                        if group_name not in alerted_groups:
                            alerted_groups.add(group_name)
                            logger.warning(f"[预警] {group_name} 客户发言 {int(now - last_customer_time)}s 未回复")
                            if self._on_alert:
                                await self._on_alert({
                                    "group_name": group_name,
                                    "elapsed_seconds": int(now - last_customer_time),
                                    "timestamp": datetime.now().isoformat(),
                                    "worker_id": self.worker_id,
                                })

            except Exception as e:
                logger.error(f"监控循环异常: {e}")

            await asyncio.sleep(poll_interval)

    # ==== 统计信息 ====

    def get_stats(self) -> dict:
        """获取监控统计。"""
        return {
            "assigned_groups": len(self._assigned_groups),
            "known_messages": len(self._known_messages),
            "running": self._running,
        }
