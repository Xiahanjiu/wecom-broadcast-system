# 企业微信群发系统 — 定时任务调度

import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.shared.config import Config
from app.shared.state import get_state_store
from app.shared.group_manager import get_group_manager
from app.master.core import get_master_core

logger = logging.getLogger(__name__)


class TaskScheduler:
    """定时任务调度器。

    负责:
    - 节假日全量群发（所有 700 个群）
    - 休息时段自动回复
    - 每日状态重置
    - 超时预警检查
    """

    def __init__(self):
        self.config = Config()
        self.scheduler = AsyncIOScheduler()
        self.core = get_master_core()
        self.store = get_state_store()
        self.group_mgr = get_group_manager()

    def setup_jobs(self):
        """配置定时任务。"""
        # 每日凌晨检查是否为节假日 → 触发全量群发
        holiday_cfg = self.config.get("holiday", {})
        if holiday_cfg.get("enabled", True):
            trigger_hour = holiday_cfg.get("trigger_hour", 9)
            trigger_min = holiday_cfg.get("trigger_minute", 0)
            self.scheduler.add_job(
                self.check_holiday_and_send,
                CronTrigger(hour=trigger_hour, minute=trigger_min),
                id="holiday_check",
                name="节假日检查与群发",
                replace_existing=True,
            )
            logger.info(f"节假日群发已配置: 每天 {trigger_hour:02d}:{trigger_min:02d} 检查")

        # 休息时段自动回复（每分钟检查）
        self.scheduler.add_job(
            self.check_rest_period,
            "interval",
            seconds=60,
            id="rest_period_check",
            name="休息时段自动回复",
            replace_existing=True,
        )
        logger.info("休息时段自动回复已配置")

        # 每日状态重置（凌晨 0:01）
        self.scheduler.add_job(
            self.daily_reset,
            CronTrigger(hour=0, minute=1),
            id="daily_reset",
            name="每日状态重置",
            replace_existing=True,
        )

        # 每 10 秒检查超时预警
        self.scheduler.add_job(
            self.check_timeout_alerts,
            "interval",
            seconds=10,
            id="timeout_check",
            name="超时预警检查",
            replace_existing=True,
        )

        logger.info("定时任务调度器配置完成")

    # ---- 节假日群发 ----

    async def check_holiday_and_send(self):
        """每日检查：如果今天是节假日，触发全量群发。"""
        holiday_cfg = self.config.get("holiday", {})
        if not holiday_cfg.get("enabled", True):
            return

        calendar = holiday_cfg.get("calendar", {})
        today = datetime.now()
        today_key = today.strftime("%m-%d")

        template_name = calendar.get(today_key)
        if not template_name:
            return  # 今天不是节日

        logger.info(f"=== 节假日群发触发: {today_key} → {template_name} ===")

        try:
            all_groups = self.group_mgr.get_all()
            if not all_groups:
                logger.warning("群列表为空，跳过节假日群发")
                return

            logger.info(f"全量群发: {len(all_groups)} 个群")

            # 节假日使用更长的延迟
            task_data = {
                "is_holiday": True,
                "template": template_name,
                "delay_min": holiday_cfg.get("delay_min", 5),
                "delay_max": holiday_cfg.get("delay_max", 15),
            }

            result = await self.core.dispatch_send_tasks(
                all_groups, extra=task_data
            )
            total = sum(len(v) for v in result.values())
            logger.info(f"节假日群发完成: {len(all_groups)} 个群, {total} 个任务已下发")

        except Exception as e:
            logger.error(f"节假日群发失败: {e}")

    # ---- 休息时段自动回复 ----

    async def check_rest_period(self):
        """检查当前是否在休息时段，如果是则对客户新消息自动回复。"""
        rest_cfg = self.config.get("rest_period", {})
        if not rest_cfg.get("enabled", True):
            return

        if not self._is_rest_time(rest_cfg):
            return

        # 获取有客户新发言且未回复的群
        store = get_state_store()
        timeline = store.get_timeline()
        alerts = store.get_alerts()

        auto_reply_text = rest_cfg.get("auto_reply", "").strip()
        if not auto_reply_text:
            return

        now = datetime.now()
        for group_name, times in list(timeline.items()):
            last_customer = times.get("last_customer_msg")
            last_staff = times.get("last_staff_reply")
            last_auto = times.get("last_auto_reply")

            if not last_customer:
                continue

            try:
                customer_time = datetime.fromisoformat(last_customer)
            except (ValueError, TypeError):
                continue

            # 已回复（人工或自动）则跳过
            if last_staff and last_staff > last_customer:
                continue
            if last_auto and last_auto > last_customer:
                continue

            # 检查是否在休息时段内发言
            if not self._is_time_in_periods(customer_time, rest_cfg):
                continue

            # 触发自动回复
            logger.info(f"[自动回复] {group_name} → 休息时段客户发言")

            # 渲染回复内容
            reply = auto_reply_text.replace("{{time}}", now.strftime("%H:%M"))
            reply = reply.replace("{{date}}", now.strftime("%Y-%m-%d"))
            reply = reply.replace("{{group_name}}", group_name)

            # 下发自动回复任务
            await self.core.dispatch_auto_reply(group_name, reply)

            # 记录已自动回复
            timeline[group_name]["last_auto_reply"] = now.isoformat()
            store.save("timeline", timeline)

    def _is_rest_time(self, rest_cfg: dict) -> bool:
        """判断当前是否在休息时段。"""
        now = datetime.now()

        # 周末全天
        if rest_cfg.get("weekend_all_day", True):
            if now.weekday() >= 5:  # 5=周六, 6=周日
                return True

        # 检查时段
        periods = rest_cfg.get("periods", [])
        for p in periods:
            if self._time_in_range(now, p.get("start"), p.get("end")):
                return True

        # 午休
        lunch = rest_cfg.get("lunch_break", {})
        if lunch.get("enabled", False):
            if self._time_in_range(now, lunch.get("start"), lunch.get("end")):
                return True

        return False

    def _is_time_in_periods(self, dt: datetime, rest_cfg: dict) -> bool:
        """检查指定时间是否在休息时段内。"""
        if rest_cfg.get("weekend_all_day", True):
            if dt.weekday() >= 5:
                return True
        periods = rest_cfg.get("periods", [])
        for p in periods:
            if self._time_in_range(dt, p.get("start"), p.get("end")):
                return True
        return False

    def _time_in_range(self, dt: datetime, start_str: str, end_str: str) -> bool:
        """检查时间是否在 HH:MM 范围内（支持跨日，如 22:00-07:00）。"""
        try:
            start_h, start_m = map(int, start_str.split(":"))
            end_h, end_m = map(int, end_str.split(":"))

            current_minutes = dt.hour * 60 + dt.minute
            start_minutes = start_h * 60 + start_m
            end_minutes = end_h * 60 + end_m

            if start_minutes <= end_minutes:
                # 不跨日
                return start_minutes <= current_minutes <= end_minutes
            else:
                # 跨日（如 22:00 - 07:00）
                return current_minutes >= start_minutes or current_minutes <= end_minutes
        except Exception:
            return False

    # ---- 每日重置 ----

    async def daily_reset(self):
        """每日状态重置。"""
        logger.info("=== 每日状态重置 ===")
        try:
            self.store.reset_daily()
            logger.info("每日状态已重置")
        except Exception as e:
            logger.error(f"每日重置失败: {e}")

    # ---- 超时预警 ----

    async def check_timeout_alerts(self):
        """超时预警检查。"""
        try:
            timeout = self.config.get("alert.timeout_seconds", 300)
            store = get_state_store()
            timeline = store.get_timeline()
            alerts = store.get_alerts()

            now = datetime.now()
            for group_name, times in list(timeline.items()):
                last_customer = times.get("last_customer_msg")
                last_staff = times.get("last_staff_reply")
                last_auto = times.get("last_auto_reply")

                if not last_customer:
                    continue

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

                # 自动回复也算回复，不触发预警
                if last_auto and last_auto > last_customer:
                    continue

                elapsed = (now - customer_time).total_seconds()

                if elapsed >= timeout:
                    has_reply = staff_time and staff_time > customer_time
                    if not has_reply:
                        existing = alerts.get(group_name, {})
                        if existing.get("acknowledged"):
                            continue

                        dedup_window = self.config.get("alert.dedup_window", 60)
                        alerted_at = existing.get("alerted_at")
                        if alerted_at:
                            try:
                                last_alert = datetime.fromisoformat(alerted_at)
                                if (now - last_alert).total_seconds() < dedup_window:
                                    continue
                            except (ValueError, TypeError):
                                pass

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
