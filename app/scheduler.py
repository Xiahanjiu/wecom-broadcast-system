# 企业微信群发系统 — 定时任务调度

import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.shared.config import Config
from app.shared.state import get_state_store
from app.master.core import get_master_core

logger = logging.getLogger(__name__)


class TaskScheduler:
    """定时任务调度器。

    负责:
    - 定时群发（如每天 9:00）
    - 每日状态重置
    """

    def __init__(self):
        self.config = Config()
        self.scheduler = AsyncIOScheduler()
        self.core = get_master_core()
        self.store = get_state_store()

    def setup_jobs(self):
        """配置定时任务。"""
        # 定时群发
        send_cron = self.config.get("send.schedule_cron", "0 9 * * *")
        self.scheduler.add_job(
            self.scheduled_send,
            CronTrigger.from_crontab(send_cron),
            id="scheduled_send",
            name="定时群发",
            replace_existing=True,
        )
        logger.info(f"定时群发已配置: {send_cron}")

        # 每日状态重置（凌晨 0:01）
        self.scheduler.add_job(
            self.daily_reset,
            CronTrigger(hour=0, minute=1),
            id="daily_reset",
            name="每日状态重置",
            replace_existing=True,
        )

        # 每 10 秒检查超时预警（主控端集中检查）
        self.scheduler.add_job(
            self.check_timeout_alerts,
            "interval",
            seconds=10,
            id="timeout_check",
            name="超时预警检查",
            replace_existing=True,
        )

        logger.info("定时任务调度器配置完成")

    async def scheduled_send(self):
        """定时群发 - 由 Cron 触发。"""
        logger.info("=== 定时群发触发 ===")
        try:
            store = get_state_store()
            active_groups = store.get_active_groups()
            group_names = list(active_groups.keys())

            if not group_names:
                logger.info("今日无活跃群，跳过群发")
                return

            result = await self.core.dispatch_send_tasks(group_names)
            total = sum(len(v) for v in result.values())
            logger.info(f"定时群发完成: {len(group_names)} 个活跃群, {total} 个任务已下发")
        except Exception as e:
            logger.error(f"定时群发失败: {e}")

    async def daily_reset(self):
        """每日状态重置。"""
        logger.info("=== 每日状态重置 ===")
        try:
            self.store.reset_daily()
            logger.info("每日状态已重置")
        except Exception as e:
            logger.error(f"每日重置失败: {e}")

    async def check_timeout_alerts(self):
        """超时预警检查（主控端集中检查）。"""
        try:
            timeout = self.config.get("alert.timeout_seconds", 300)
            store = get_state_store()
            timeline = store.get_timeline()
            alerts = store.get_alerts()

            now = datetime.now()
            for group_name, times in list(timeline.items()):
                last_customer = times.get("last_customer_msg")
                last_staff = times.get("last_staff_reply")

                if not last_customer:
                    continue

                # 解析时间
                try:
                    customer_time = datetime.fromisoformat(last_customer)
                except (ValueError, TypeError):
                    continue

                staff_time = None
                if last_staff:
                    try:
                        staff_time = datetime.fromisoformat(last_staff)
                    except (ValueError, TypeError):
                        pass

                elapsed = (now - customer_time).total_seconds()

                # 客户发言后超过阈值且无员工回复
                if elapsed >= timeout:
                    has_reply = staff_time and staff_time > customer_time
                    if not has_reply:
                        # 检查是否已触发预警
                        existing = alerts.get(group_name, {})
                        if existing.get("acknowledged"):
                            continue  # 已确认，不重复

                        dedup_window = self.config.get("alert.dedup_window", 60)
                        alerted_at = existing.get("alerted_at")
                        if alerted_at:
                            try:
                                last_alert = datetime.fromisoformat(alerted_at)
                                if (now - last_alert).total_seconds() < dedup_window:
                                    continue  # 去重窗口内，不重复广播
                            except (ValueError, TypeError):
                                pass

                        # 触发预警
                        alert_data = {
                            "group_name": group_name,
                            "elapsed_seconds": int(elapsed),
                            "timestamp": now.isoformat(),
                            "level": "warning" if elapsed < 600 else "critical"
                        }
                        await self.core.broadcast_alert(alert_data)

        except Exception as e:
            logger.error(f"超时检查异常: {e}")

    def start(self):
        """启动调度器。"""
        self.setup_jobs()
        self.scheduler.start()
        logger.info("任务调度器已启动")

    def stop(self):
        """停止调度器。"""
        self.scheduler.shutdown()
        logger.info("任务调度器已停止")


# 全局单例
_scheduler = None

def get_scheduler():
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler()
    return _scheduler
