# 企业微信群发系统 — 群列表管理器

import logging
from pathlib import Path
from typing import List, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

DEFAULT_GROUPS_FILE = Path(__file__).parent.parent.parent / "data" / "groups.yaml"


class GroupManager:
    """群列表管理器。管理所有需要监控的客户群列表。"""

    def __init__(self, file_path: str = None):
        self._file = Path(file_path) if file_path else DEFAULT_GROUPS_FILE
        self._groups: List[str] = []
        self._metadata: Dict[str, dict] = {}
        self._load()

    def _load(self):
        """从 YAML 文件加载群列表。"""
        if not self._file.exists():
            logger.warning(f"群列表文件不存在: {self._file}")
            self._groups = []
            self._metadata = {}
            return

        try:
            with open(self._file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self._groups = list(data.get("groups", []))
            self._metadata = data.get("metadata", {}) or {}
            logger.info(f"已加载 {len(self._groups)} 个群")
        except Exception as e:
            logger.error(f"加载群列表失败: {e}")
            self._groups = []
            self._metadata = {}

    def _save(self):
        """保存群列表到 YAML 文件。"""
        self._file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "groups": self._groups,
            "metadata": self._metadata
        }
        with open(self._file, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    # ---- 群列表操作 ----

    def get_all(self) -> List[str]:
        """获取所有群名称。"""
        return list(self._groups)

    def get_count(self) -> int:
        """获取群数量。"""
        return len(self._groups)

    def add_group(self, group_name: str) -> bool:
        """添加单个群。"""
        name = group_name.strip()
        if not name or name in self._groups:
            return False
        self._groups.append(name)
        self._save()
        logger.info(f"已添加群: {name}")
        return True

    def remove_group(self, group_name: str) -> bool:
        """移除单个群。"""
        if group_name in self._groups:
            self._groups.remove(group_name)
            self._metadata.pop(group_name, None)
            self._save()
            logger.info(f"已移除群: {group_name}")
            return True
        return False

    def import_groups(self, names: List[str]) -> int:
        """批量导入群（去重追加）。

        Returns:
            新增的群数量
        """
        added = 0
        existing = set(self._groups)
        for name in names:
            name = name.strip()
            if name and name not in existing:
                self._groups.append(name)
                existing.add(name)
                added += 1
        if added > 0:
            self._save()
            logger.info(f"批量导入 {added} 个群 (总共 {len(self._groups)} 个)")
        return added

    def import_from_text(self, text: str) -> int:
        """从文本导入群列表（每行一个群名）。"""
        names = [line.strip() for line in text.strip().split("\n") if line.strip()]
        return self.import_groups(names)

    def replace_all(self, names: List[str]) -> int:
        """替换整个群列表。"""
        cleaned = [n.strip() for n in names if n.strip()]
        self._groups = cleaned
        self._save()
        logger.info(f"群列表已替换为 {len(self._groups)} 个群")
        return len(self._groups)

    # ---- 元数据 ----

    def set_metadata(self, group_name: str, meta: dict):
        """设置群元数据。"""
        if group_name not in self._groups:
            return False
        self._metadata[group_name] = meta
        self._save()
        return True

    def get_metadata(self, group_name: str) -> Optional[dict]:
        """获取群元数据。"""
        return self._metadata.get(group_name)

    # ---- 导出 ----

    def export_as_text(self) -> str:
        """导出为纯文本（每行一个群名）。"""
        return "\n".join(self._groups)

    def get_unassigned(self, assigned: Dict[str, str]) -> List[str]:
        """获取尚未分配执行端的群。"""
        return [g for g in self._groups if g not in assigned]


# 全局单例
_manager = None

def get_group_manager():
    global _manager
    if _manager is None:
        _manager = GroupManager()
    return _manager
