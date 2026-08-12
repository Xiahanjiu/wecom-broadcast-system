# 企业微信群发系统 — 主控端服务核心

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Dict, Set, Optional

from app.shared.config import Config
from app.shared.state import get_state_store

logger = logging.getLogger(__name__)


class MasterCore:
    """主控端核心逻辑。

    管理所有执行端的连接状态、心跳检测、离线接管、
    任务分配、预警广播等核心业务。
    """

    def __init__(self):
        self.config = Config()
        self.store = get_state_store()

        # 已连接的 WebSocket 客户端: worker_id -> websocket
        self._clients: Dict[str, any] = {}
        # 在线执行端信息: worker_id -> WorkerInfo
        self._workers: Dict[str, dict] = {}
        # 心跳记录: worker_id -> last_heartbeat_timestamp
        self._heartbeats: Dict[str, float] = {}
        # 群分配表: group_name -> worker_id
        self._group_assignment: Dict[str, str] = {}
        # 发送结果收集
        self._send_results: Dict[str, dict] = {}

        # 心跳检测任务
        self._heartbeat_task: Optional[asyncio.Task] = None

    # ==== 客户端连接管理 ====

    async def register_worker(self, worker_id: str, websocket, info: dict = None):
        """注册执行端。"""
        self._clients[worker_id] = websocket
        self._workers[worker_id] = {
            "id": worker_id,
            "name": info.get("name", worker_id) if info else worker_id,
            "online_since": datetime.now().isoformat(),
            "status": "online",
            "group_count": 0,
            **(info or {})
        }
        self._heartbeats[worker_id] = time.time()

        logger.info(f"执行端已注册: {worker_id} (当前在线: {len(self._clients)})")

        # 广播在线状态变化
        await self._broadcast_worker_status()

    async def unregister_worker(self, worker_id: str):
        """注销执行端（断连处理）。"""
        self._clients.pop(worker_id, None)
        if worker_id in self._workers:
            self._workers[worker_id]["status"] = "offline"
        self._heartbeats.pop(worker_id, None)

        logger.info(f"执行端已离线: {worker_id} (当前在线: {len(self._clients)})")

        # 触发离线接管
        await self._handle_worker_offline(worker_id)

        # 广播状态变化
        await self._broadcast_worker_status()

    # ==== 心跳检测 ====

    async def handle_heartbeat(self, worker_id: str, data: dict):
        """处理执行端心跳。"""
        timestamp = time.time()
        self._heartbeats[worker_id] = timestamp

        if worker_id in self._workers:
            self._workers[worker_id]["status"] = "online"
            self._workers[worker_id]["last_heartbeat"] = datetime.now().isoformat()

        # 更新心跳中携带的附加信息
        if "monitor_stats" in data:
            self._workers[worker_id]["monitor_stats"] = data["monitor_stats"]
        if "send_progress" in data:
            self._workers[worker_id]["send_progress"] = data["send_progress"]

    async def start_heartbeat_check(self):
        """启动心跳检测循环。"""
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self):
        """心跳检测循环。"""
        offline_threshold = self.config.get("monitor.offline_threshold", 30)
        check_interval = self.config.get("monitor.heartbeat_interval", 10)

        while True:
            await asyncio.sleep(check_interval)
            now = time.time()
            offline_workers = []

            for worker_id, last_hb in list(self._heartbeats.items()):
                if now - last_hb > offline_threshold:
                    offline_workers.append(worker_id)

            for worker_id in offline_workers:
                logger.warning(f"执行端心跳超时: {worker_id}")
                await self.unregister_worker(worker_id)

    # ==== 离线接管 ====

    async def _handle_worker_offline(self, worker_id: str):
        """执行端离线后，将其负责的群重新分配。"""
        # 查找该执行端负责的群
        assigned_groups = [
            g for g, w in self._group_assignment.items()
            if w == worker_id
        ]

        if not assigned_groups:
            return

        online_workers = [
            wid for wid, info in self._workers.items()
            if info.get("status") == "online"
        ]

        if not online_workers:
            logger.warning(f"执行端 {worker_id} 离线，但无在线执行端可接管")
            return

        # 均匀分配：轮流分配给在线执行端
        for i, group_name in enumerate(assigned_groups):
            target_worker = online_workers[i % len(online_workers)]
            self._group_assignment[group_name] = target_worker
            logger.info(f"群 '{group_name}' 已从 {worker_id} 重新分配给 {target_worker}")

        # 通知接管的执行端
        for target_worker in online_workers:
            takeover_groups = [
                g for g in assigned_groups
                if self._group_assignment.get(g) == target_worker
            ]
            if takeover_groups:
                await self._send_to_worker(target_worker, {
                    "type": "takeover",
                    "groups": takeover_groups
                })

    # ==== 群分配管理 ====

    def assign_group(self, group_name: str, worker_id: str):
        """将群分配给指定执行端。"""
        self._group_assignment[group_name] = worker_id
        if worker_id in self._workers:
            assigned = len([
                g for g, w in self._group_assignment.items()
                if w == worker_id
            ])
            self._workers[worker_id]["group_count"] = assigned

    def get_group_worker(self, group_name: str) -> Optional[str]:
        """获取负责指定群的执行端。"""
        return self._group_assignment.get(group_name)

    def get_worker_groups(self, worker_id: str):
        """获取执行端负责的群列表。"""
        return [
            g for g, w in self._group_assignment.items()
            if w == worker_id
        ]

    # ==== 任务分配 ====

    async def dispatch_send_tasks(self, active_groups: list, extra: dict = None):
        """根据活跃群列表向在线执行端分配发送任务。"""

        extra = extra or {}
        is_holiday = extra.get("is_holiday", False)
        # 按分配关系组织任务
        worker_tasks: Dict[str, list] = {}

        for group_name in active_groups:
            worker_id = self._group_assignment.get(group_name)
            if not worker_id:
                continue
            if worker_id not in self._workers:
                continue
            if self._workers[worker_id].get("status") != "online":
                # 分配的执行端离线，找替代
                online_workers = [
                    wid for wid, info in self._workers.items()
                    if info.get("status") == "online"
                ]
                if online_workers:
                    worker_id = online_workers[0]
                else:
                    continue

            if worker_id not in worker_tasks:
                worker_tasks[worker_id] = []
            worker_tasks[worker_id].append(group_name)

        # 下发任务
        for worker_id, groups in worker_tasks.items():
            task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{worker_id}"
            task_data = {
                "type": "send_task",
                "task_id": task_id,
                "groups": groups,
                "template": extra.get("template", "default.j2"),
            }
            success = await self._send_to_worker(worker_id, task_data)
            if success:
                logger.info(f"发送任务已下发: {worker_id} → {len(groups)} 个群")
                self._send_results[task_id] = {
                    "worker_id": worker_id,
                    "total": len(groups),
                    "completed": 0,
                    "failed": 0,
                    "status": "dispatched"
                }

        return worker_tasks

    async def handle_send_result(self, worker_id: str, result: dict):
        """处理执行端上报的发送结果。"""
        task_id = result.get("task_id")
        if task_id and task_id in self._send_results:
            task_result = self._send_results[task_id]
            task_result["completed"] = result.get("completed", task_result["completed"])
            task_result["failed"] = result.get("failed", task_result["failed"])
            if result.get("finished"):
                task_result["status"] = "completed"
                logger.info(f"任务完成: {task_id}, 成功 {task_result['completed']}, 失败 {task_result['failed']}")

    # ==== 预警广播 ====


    async def dispatch_auto_reply(self, group_name: str, reply_text: str):
        """���Ϣʱ���Զ��ظ�����"""
        worker_id = self._group_assignment.get(group_name)
        if not worker_id:
            logger.warning(f"�Զ��ظ�ʧ��: {group_name} δ����ִ�ж�")
            return
        if worker_id not in self._workers:
            logger.warning(f"�Զ��ظ�ʧ��: {worker_id} δע��")
            return
        if self._workers[worker_id].get("status") != "online":
            online = [w for w in self._workers if self._workers[w].get("status") == "online"]
            if online:
                worker_id = online[0]
            else:
                logger.warning("�Զ��ظ�ʧ��: ������ִ�ж�")
                return

        task_data = {
            "type": "auto_reply",
            "group_name": group_name,
            "reply_text": reply_text,
        }
        await self._send_to_worker(worker_id, task_data)
        logger.info(f"自动回复任务已下发: {group_name} -> {worker_id}")

    async def broadcast_alert(self, alert_data: dict):
        """向所有在线执行端广播预警。"""
        message = {
            "type": "alert",
            **alert_data
        }
        await self._broadcast(message)
        logger.info(f"预警已广播: {alert_data.get('group_name')}")

        # 记录预警
        store = get_state_store()
        alerts = store.get_alerts()
        group_name = alert_data.get("group_name", "unknown")
        alerts[group_name] = {
            **alert_data,
            "alerted_at": datetime.now().isoformat(),
            "acknowledged": False
        }
        store.save("alerts", alerts)

    # ==== 内部通信 ====

    async def _send_to_worker(self, worker_id: str, data: dict) -> bool:
        """向指定执行端发送消息。"""
        ws = self._clients.get(worker_id)
        if not ws:
            return False
        try:
            message = json.dumps(data, ensure_ascii=False, default=str)
            await ws.send_text(message)
            return True
        except Exception as e:
            logger.error(f"发送给 {worker_id} 失败: {e}")
            return False

    async def _broadcast(self, data: dict):
        """向所有在线执行端广播消息。"""
        message = json.dumps(data, ensure_ascii=False, default=str)
        disconnected = []
        for worker_id, ws in list(self._clients.items()):
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(worker_id)

        for worker_id in disconnected:
            await self.unregister_worker(worker_id)

    async def _broadcast_worker_status(self):
        """广播执行端在线状态变化。"""
        await self._broadcast({
            "type": "worker_status_update",
            "workers": list(self._workers.values())
        })

    # ==== 仪表盘数据 ====

    def get_dashboard_data(self) -> dict:
        """获取仪表盘聚合数据。"""
        store = get_state_store()
        active_groups = store.get_active_groups()
        alerts = store.get_alerts()
        tasks = store.get_tasks()

        return {
            "online_workers": len(self._clients),
            "total_workers": len(self._workers),
            "worker_list": list(self._workers.values()),
            "active_groups_count": len(active_groups),
            "active_groups": list(active_groups.values()),
            "alerts_count": len([a for a in alerts.values() if not a.get("acknowledged")]),
            "alerts": list(alerts.values()),
            "send_tasks": {
                "pending": len(tasks.get("pending", [])),
                "completed": len(tasks.get("completed", [])),
                "failed": len(tasks.get("failed", [])),
            },
            "group_assignment": self._group_assignment,
        }

    def get_unassigned_groups(self, all_groups: list) -> list:
        """获取尚未分配执行端的群。"""
        return [g for g in all_groups if g not in self._group_assignment]


# 全局单例
_master_core = None

def get_master_core():
    global _master_core
    if _master_core is None:
        _master_core = MasterCore()
    return _master_core




