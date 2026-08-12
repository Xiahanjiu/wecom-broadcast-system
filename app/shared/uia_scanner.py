# 企业微信群发系统 — 聊天列表 UIA 扫描器

import time
import logging
import re
from typing import List, Dict, Optional, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ChatListItem:
    """聊天列表项数据结构。"""
    group_name: str
    last_message: str = ""
    sender_name: str = ""
    unread_count: int = 0
    is_active: bool = False
    raw_text: str = ""


class ChatListScanner:
    """企业微信聊天列表扫描器。

    通过 Windows UIA (无障碍 API) 读取聊天列表，
    提取群名、最后消息、发送者、未读数等信息。
    当 UIA 不可用时自动降级为 OCR 方案。

    同时支持扫描群成员面板，识别标记为"客户"的成员。
    """

    def __init__(self):
        self._use_fallback = False
        self._ocr = None

    # ---- 聊天列表扫描 ----

    def scan(self) -> List[ChatListItem]:
        """扫描聊天列表，返回列表项。"""
        items = self._scan_uia()
        if items is None:
            logger.info("UIA 扫描失败，尝试 OCR 降级")
            items = self._scan_ocr()
        return items or []

    # ---- 群成员面板扫描 ----

    def scan_customers_in_group(self, group_name: str) -> Set[str]:
        """扫描指定群聊的成员面板，返回标记为"客户"的成员名称集合。

        企微外部群成员面板中，客户名称右侧有灰色"客户"标签。
        UIA 可读取该标签文本。
        """
        customers = set()
        try:
            import uiautomation as auto

            wecom = auto.WindowControl(Name="企业微信", searchDepth=1)
            if not wecom.Exists(maxSearchSeconds=2):
                logger.warning("未找到企业微信窗口")
                return customers

            # 在聊天列表中点击目标群
            chat_list = self._find_chat_list(wecom)
            if not chat_list:
                return customers

            # 查找并点击目标群
            for child in chat_list.GetChildren():
                name = child.Name or ""
                if group_name in name:
                    child.Click()
                    time.sleep(0.5)
                    break

            # 查找群成员面板
            # 企微右侧面板通常包含成员列表
            member_panel = self._find_member_panel(wecom)
            if not member_panel:
                logger.info(f"未找到群 '{group_name}' 的成员面板")
                return customers

            # 遍历成员列表，识别"客户"标签
            for member_item in member_panel.GetChildren():
                member_text = member_item.Name or ""

                # 企微群成员中，客户会在名称旁显示"客户"标签
                # 格式通常为: "成员名" 后面紧跟一个 "客户" 文本控件
                if "客户" in member_text:
                    # 提取成员名称（"客户"之前的文本）
                    name_part = member_text.replace("客户", "").strip()
                    if name_part:
                        customers.add(name_part)
                        logger.debug(f"  识别客户: {name_part}")

                # 也检查子控件（有些版本"客户"是独立子控件）
                for sub in member_item.GetChildren():
                    sub_text = sub.Name or ""
                    if sub_text == "客户":
                        name_part = member_text.strip()
                        if name_part:
                            customers.add(name_part)

            logger.info(f"群 '{group_name}' 扫描完成: {len(customers)} 个客户")

        except Exception as e:
            logger.warning(f"群成员扫描异常: {e}")

        return customers

    def scan_all_group_customers(self, group_names: List[str]) -> Dict[str, Set[str]]:
        """批量扫描多个群的客户成员。

        Returns:
            {group_name: {customer_name1, customer_name2, ...}}
        """
        result = {}
        for name in group_names:
            customers = self.scan_customers_in_group(name)
            if customers:
                result[name] = customers
            time.sleep(1)  # 群间延迟，避免过快操作
        return result

    # ---- 内部方法 ----

    def _find_member_panel(self, wecom_window):
        """在企微窗口中定位群成员面板。"""
        strategies = [
            # 右侧面板区域
            lambda: wecom_window.PaneControl(searchDepth=4, ClassName="ChatMembersPanel"),
            lambda: wecom_window.PaneControl(searchDepth=5, ClassName="ChatMembersPanel"),
            # 通用右侧面板
            lambda: wecom_window.ListControl(searchDepth=5, Name=lambda n: n and "成员" in n),
            lambda: wecom_window.ListControl(searchDepth=6),
            # 按名称查找
            lambda: wecom_window.Control(searchDepth=4, Name=lambda n: n and "群成员" in n),
        ]

        for strategy in strategies:
            try:
                control = strategy()
                if control.Exists(maxSearchSeconds=1):
                    return control
            except Exception:
                pass

        return None

    def _scan_uia(self) -> Optional[List[ChatListItem]]:
        """通过 UIA 扫描聊天列表。"""
        try:
            import uiautomation as auto

            wecom = auto.WindowControl(Name="企业微信", searchDepth=1)
            if not wecom.Exists(maxSearchSeconds=2):
                logger.warning("未找到企业微信窗口")
                return None

            chat_list = self._find_chat_list(wecom)
            if not chat_list:
                logger.warning("未找到聊天列表控件")
                return None

            items = []
            children = chat_list.GetChildren()
            for child in children:
                name = child.Name or ""
                if not name.strip():
                    continue

                item = self._parse_list_item(name)
                if item:
                    items.append(item)

            logger.info(f"UIA 扫描完成: {len(items)} 个聊天项")
            self._use_fallback = False
            return items

        except Exception as e:
            logger.warning(f"UIA 扫描异常: {e}")
            return None

    def _find_chat_list(self, wecom_window):
        """在企微窗口中定位聊天列表控件。"""
        strategies = [
            lambda: wecom_window.ListControl(searchDepth=3),
            lambda: wecom_window.TreeControl(searchDepth=3),
            lambda: wecom_window.ListControl(searchDepth=4),
            lambda: wecom_window.ListControl(searchDepth=5),
        ]

        for strategy in strategies:
            try:
                control = strategy()
                if control.Exists(maxSearchSeconds=1):
                    return control
            except Exception:
                pass

        return None

    def _parse_list_item(self, raw_text: str) -> Optional[ChatListItem]:
        """解析单条聊天列表项文本。"""
        if not raw_text.strip():
            return None

        lines = raw_text.strip().split("\n")
        if len(lines) < 2:
            return ChatListItem(
                group_name=lines[0].strip(),
                raw_text=raw_text
            )

        group_name = lines[0].strip()
        message_line = lines[1].strip() if len(lines) > 1 else ""

        sender_name = ""
        last_message = ""

        match = re.match(r"^(.+?)[:：]\s*(.*)", message_line)
        if match:
            sender_name = match.group(1).strip()
            last_message = match.group(2).strip()
        else:
            last_message = message_line

        has_unread = any(
            marker in raw_text
            for marker in ["[", "]", "条", "新消息"]
        )

        return ChatListItem(
            group_name=group_name,
            last_message=last_message,
            sender_name=sender_name,
            unread_count=0,
            is_active=has_unread,
            raw_text=raw_text
        )

    # ---- OCR 降级方案 ----

    def _scan_ocr(self) -> List[ChatListItem]:
        """通过截图 + OCR 扫描聊天列表。"""
        try:
            from .ocr_fallback import OCRScanner
            if self._ocr is None:
                self._ocr = OCRScanner()
            items = self._ocr.scan_chat_list()
            self._use_fallback = True
            return items
        except Exception as e:
            logger.error(f"OCR 扫描失败: {e}")
            return []


# 全局单例
_scanner = None

def get_scanner():
    global _scanner
    if _scanner is None:
        _scanner = ChatListScanner()
    return _scanner
