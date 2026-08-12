# 企业微信群发系统 — 客户/员工识别分类器

import re
import logging
import yaml
from pathlib import Path

logger = logging.getLogger(__name__)


class StaffClassifier:
    """客户/员工发言者识别。

    基于配置的规则（正则 + 白名单 + 黑名单）判断发言者是员工还是客户。
    """

    def __init__(self, config_path=None):
        self._regex_patterns = []
        self._whitelist = set()
        self._blacklist = set()
        self._load_rules(config_path)

    def _load_rules(self, config_path=None):
        """加载识别规则。"""
        if config_path is None:
            config_path = Path(__file__).parent.parent.parent / "data" / "staff_patterns.yaml"

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                rules = yaml.safe_load(f) or {}

            self._regex_patterns = [
                re.compile(p) for p in rules.get("regex", [])
            ]
            self._whitelist = set(rules.get("whitelist", []))
            self._blacklist = set(rules.get("blacklist", []))

            logger.info(
                f"已加载识别规则: {len(self._regex_patterns)} 条正则, "
                f"{len(self._whitelist)} 个白名单, {len(self._blacklist)} 个黑名单"
            )
        except Exception as e:
            logger.error(f"加载识别规则失败: {e}")

    def is_staff(self, sender_name: str) -> bool:
        """判断发言者是否为员工。

        优先级: 黑名单 > 白名单 > 正则规则。
        """
        name = sender_name.strip()
        if not name:
            return False

        # 黑名单优先 — 强制视为客户
        if name in self._blacklist:
            return False

        # 白名单 — 明确是员工
        if name in self._whitelist:
            return True

        # 正则匹配
        for pattern in self._regex_patterns:
            if pattern.search(name):
                return True

        return False

    def is_customer(self, sender_name: str) -> bool:
        """判断发言者是否为客户。"""
        return not self.is_staff(sender_name)

    def classify(self, sender_name: str) -> str:
        """分类发言者，返回 'staff' 或 'customer'。"""
        return "staff" if self.is_staff(sender_name) else "customer"

    def add_whitelist(self, name: str):
        """动态添加白名单。"""
        self._whitelist.add(name)
        logger.info(f"白名单已添加: {name}")

    def add_blacklist(self, name: str):
        """动态添加黑名单。"""
        self._blacklist.add(name)
        logger.info(f"黑名单已添加: {name}")


# 全局单例
_classifier = None

def get_classifier():
    global _classifier
    if _classifier is None:
        _classifier = StaffClassifier()
    return _classifier
