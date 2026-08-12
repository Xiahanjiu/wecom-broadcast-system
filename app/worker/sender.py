# 企业微信群发系统 — 执行端 RPA 发送引擎

import asyncio
import logging
import time
import random
from datetime import datetime
from typing import List, Dict, Optional

from app.shared.config import Config
from app.shared.wecom import get_wecom_client, random_delay
from app.shared.template_engine import get_template_engine

logger = logging.getLogger(__name__)


class SendEngine:
    """执行端 RPA 发送引擎。

    接收主控下发的发送任务，按群逐个自动发送消息。
    支持断点续传 — 每发完一个群立即记录进度。
    """

    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        self.config = Config()
        self.wecom = get_wecom_client()
        self.template_engine = get_template_engine()

        # 当前任务状态
        self._current_task: Optional[dict] = None
        self._progress: dict = {}  # task_id -> progress info
        self._on_result = None

        # 自定义备注缓存 (group_name -> custom_note)
        self._custom_notes: dict = {}

    def on_result(self, callback):
        """发送结果回调。"""
        self._on_result = callback

    async def execute_task(self, task: dict) -> dict:
        """执行发送任务。

        Args:
            task: {
                "task_id": "...",
                "groups": ["群A", "群B", ...],
                "template": "default.j2",
                "common_content": "通用内容"
            }
        Returns:
            {"completed": N, "failed": N, "details": [...]}
        """
        task_id = task.get("task_id", f"task_{int(time.time())}")
        groups = task.get("groups", [])
        template_name = task.get("template", "default.j2")
        common_content = task.get("common_content", "")

        self._current_task = task
        self._progress[task_id] = {
            "task_id": task_id,
            "total": len(groups),
            "completed": 0,
            "failed": 0,
            "started_at": datetime.now().isoformat(),
            "status": "running"
        }

        logger.info(f"开始执行发送任务: {task_id}, {len(groups)} 个群")

        # 确保企微窗口可用
        window_ok = await asyncio.to_thread(self.wecom.find_window)
        if not window_ok:
            logger.error("未找到企业微信窗口，发送中止")
            self._progress[task_id]["status"] = "failed"
            return self._progress[task_id]

        completed = 0
        failed = 0
        details = []

        for i, group_name in enumerate(groups):
            try:
                # 渲染消息
                custom_note = self._custom_notes.get(group_name, "")
                message = await asyncio.to_thread(
                    self.template_engine.render_for_group,
                    template_name=template_name,
                    group_name=group_name,
                    custom_note=custom_note,
                    common_content=common_content
                )

                # 搜索并进入群聊
                found = await asyncio.to_thread(
                    self.wecom.search_group, group_name
                )
                if not found:
                    raise Exception(f"无法找到群: {group_name}")

                # 发送消息
                sent = await asyncio.to_thread(
                    self.wecom.send_message, message
                )
                if not sent:
                    raise Exception("发送失败")

                # 检测发送状态
                ok = await asyncio.to_thread(self.wecom.check_send_status)
                if not ok:
                    raise Exception("发送可能失败")

                completed += 1
                details.append({
                    "group_name": group_name,
                    "status": "success",
                    "timestamp": datetime.now().isoformat()
                })
                logger.info(f"发送成功 [{i+1}/{len(groups)}]: {group_name}")

            except Exception as e:
                failed += 1
                details.append({
                    "group_name": group_name,
                    "status": "failed",
                    "error": str(e),
                    "timestamp": datetime.now().isoformat()
                })
                logger.error(f"发送失败 [{i+1}/{len(groups)}]: {group_name} - {e}")

            # 更新进度（断点续传）
            self._progress[task_id].update({
                "completed": completed,
                "failed": failed,
                "current": i + 1,
                "last_group": group_name,
                "details": details,
            })

            # 上报中间结果
            if self._on_result:
                await self._on_result({
                    "task_id": task_id,
                    "worker_id": self.worker_id,
                    "completed": completed,
                    "failed": failed,
                    "total": len(groups),
                    "current": i + 1,
                    "finished": False,
                })

            # 群间随机延迟
            if i < len(groups) - 1 and sent:
                delay = random.uniform(
                    task.get("delay_min", self.config.get("send.delay_min", 2)),
                    task.get("delay_max", self.config.get("send.delay_max", 5))
                )
                await asyncio.sleep(delay)

        # 任务完成
        self._progress[task_id].update({
            "status": "completed",
            "finished_at": datetime.now().isoformat(),
        })

        logger.info(f"发送任务完成: {task_id}, 成功 {completed}, 失败 {failed}")

        # 上报最终结果
        if self._on_result:
            await self._on_result({
                "task_id": task_id,
                "worker_id": self.worker_id,
                "completed": completed,
                "failed": failed,
                "total": len(groups),
                "finished": True,
            })

        return self._progress[task_id]

    def set_custom_note(self, group_name: str, note: str):
        """设置群的自定义备注。"""
        self._custom_notes[group_name] = note

    def set_custom_notes(self, notes: dict):
        """批量设置自定义备注。"""
        self._custom_notes.update(notes)

    def get_progress(self, task_id: str = None) -> dict:
        """获取发送进度。"""
        if task_id:
            return self._progress.get(task_id, {})
        return {
            "current_task": self._current_task,
            "progress": self._progress,
        }

    
    async def send_auto_reply(self, group_name: str, reply_text: str) -> bool:
        """ִ���Զ��ظ� - ���ض�Ⱥ����ָ�����ı���"""
        try:
            window_ok = await asyncio.to_thread(self.wecom.find_window)
            if not window_ok:
                logger.error("δ�ҵ���ҵ΢�Ŵ��ڣ��Զ��ظ�ʧ��")
                return False

            found = await asyncio.to_thread(self.wecom.search_group, group_name)
            if not found:
                logger.error(f"�޷��ҵ�Ⱥ: {group_name}")
                return False

            sent = await asyncio.to_thread(self.wecom.send_message, reply_text)
            if not sent:
                return False

            logger.info(f"�Զ��ظ��ɹ�: {group_name}")
            return True

        except Exception as e:
            logger.error(f"�Զ��ظ�ʧ��: {group_name} - {e}")
            return False

    def resume_task(self, task_id: str) -> Optional[dict]:
        """恢复中断的任务（断点续传）。"""
        progress = self._progress.get(task_id)
        if not progress:
            return None
        if progress.get("status") == "completed":
            return None

        # 构建剩余任务
        remaining = progress.get("details", [])
        failed_groups = [
            d["group_name"] for d in remaining
            if d.get("status") == "failed"
        ]

        if progress.get("current_task"):
            task = dict(progress["current_task"])
            task["groups"] = failed_groups
            task["task_id"] = f"{task_id}_retry"
            return task

        return None

