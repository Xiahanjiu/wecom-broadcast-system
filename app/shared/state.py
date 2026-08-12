# 企业微信群发系统 — 状态持久化

import json
import os
import threading
from pathlib import Path
from datetime import datetime

class StateStore:
    """轻量级 JSON 状态持久化，线程安全。"""

    def __init__(self, base_dir=None):
        if base_dir is None:
            base_dir = Path(__file__).parent.parent.parent / "data" / "state"
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cache = {}

    def _path(self, name):
        return self._base_dir / f"{name}.json"

    def load(self, name, default=None):
        """加载状态文件。"""
        path = self._path(name)
        with self._lock:
            if name in self._cache:
                return self._cache[name]
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._cache[name] = data
                    return data
                except (json.JSONDecodeError, IOError):
                    pass
            data = default if default is not None else {}
            self._cache[name] = data
            return data

    def save(self, name, data):
        """保存状态文件。"""
        path = self._path(name)
        with self._lock:
            self._cache[name] = data
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    def get_active_groups(self):
        """获取今日活跃群。"""
        return self.load("active_groups", {})

    def set_active_group(self, group_name, data):
        """设置单个群的活跃状态。"""
        groups = self.get_active_groups()
        groups[group_name] = data
        self.save("active_groups", groups)

    def get_timeline(self):
        """获取群消息时间线。"""
        return self.load("timeline", {})

    def set_timeline(self, group_name, timeline_data):
        """设置某个群的时间线。"""
        timeline = self.get_timeline()
        timeline[group_name] = timeline_data
        self.save("timeline", timeline)

    def get_alerts(self):
        """获取预警记录。"""
        return self.load("alerts", {})

    def set_alert(self, group_name, alert_data):
        """记录预警。"""
        alerts = self.get_alerts()
        alerts[group_name] = alert_data
        self.save("alerts", alerts)

    def get_tasks(self):
        """获取发送任务。"""
        return self.load("tasks", {"pending": [], "completed": [], "failed": []})

    def set_tasks(self, tasks_data):
        """更新发送任务。"""
        self.save("tasks", tasks_data)

    def reset_daily(self):
        """重置每日状态（活跃群、时间线、预警）。"""
        today = datetime.now().strftime("%Y%m%d")
        last_reset = self.load("_last_reset", "")
        if last_reset != today:
            self.save("active_groups", {})
            self.save("timeline", {})
            self.save("alerts", {})
            self.save("_last_reset", today)

# 全局单例
_state_store = None

def get_state_store():
    global _state_store
    if _state_store is None:
        _state_store = StateStore()
    return _state_store
