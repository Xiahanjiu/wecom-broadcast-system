# 企业微信群发系统 — 客户/员工识别分类器
# 优先使用 UIA 扫描的群成员客户标签，降级使用规则

import re
import logging
import yaml
from pathlib import Path
from typing import Set, Optional

logger = logging.getLogger(__name__)


class StaffClassifier:
    """客户/员工发言者识别。

    优先方案: 通过 UIA 扫描群成员面板获取客户标签
    降级方案: 基于配置的正则 + 白名单 + 黑名单
    """

    def __init__(self, config_path=None):
        self._regex_patterns = []
        self._whitelist = set()
        self._blacklist = set()
        # UI 扫描注入的客户名称集合（优先级最高）
        self._known_customers: Set[str] = set()
        # 员工统一前缀（如公司简称）
        self._staff_prefix: Optional[str] = None
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
            self._staff_prefix = rules.get("staff_prefix", None)

            logger.info(
                f"已加载识别规则: {len(self._regex_patterns)} 条正则, "
                f"{len(self._whitelist)} 个白名单, {len(self._blacklist)} 个黑名单, "
                f"已知客户 {len(self._known_customers)} 个, "
                f"员工前缀: {self._staff_prefix or '未设置'}"
            )
        except Exception as e:
            logger.error(f"加载识别规则失败: {e}")

    # ---- UI 扫描注入接口 ----

    def load_customers_from_scan(self, customer_names: Set[str]):
        """从群成员面板 UIA 扫描结果注入客户名称集合。

        企微群成员面板中标记为"客户"的所有名称。
        """
        self._known_customers = customer_names
        logger.info(f"已注入 {len(customer_names)} 个客户名称 (来自 UI 扫描)")

    def add_customer(self, name: str):
        """动态添加单个客户名称。"""
        self._known_customers.add(name)

    def set_staff_prefix(self, prefix: str):
        """设置员工统一前缀。"""
        self._staff_prefix = prefix
        logger.info(f"员工前缀已设置: {prefix}")

    # ---- 判断逻辑 ----

    def is_staff(self, sender_name: str) -> bool:
        """判断发言者是否为员工。

        优先级:
        1. UI 扫描的已知客户集合 → 直接排除
        2. 员工前缀匹配 → 直接确认
        3. 黑名单 > 白名单 > 正则规则
        """
        name = sender_name.strip()
        if not name:
            return False

        # 1. UI 扫描已知客户 → 直接排除
        if name in self._known_customers:
            return False

        # 2. 员工前缀匹配 → 直接确认
        if self._staff_prefix and name.startswith(self._staff_prefix):
            return True

        # 3. 黑名单优先 — 强制视为客户
        if name in self._blacklist:
            return False

        # 4. 白名单 — 明确是员工
        if name in self._whitelist:
            return True

        # 5. 正则匹配
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

    @property
    def known_customer_count(self) -> int:
        return len(self._known_customers)


# 全局单例
_classifier = None

def get_classifier():
    global _classifier
    if _classifier is None:
        _classifier = StaffClassifier()
    return _classifier
