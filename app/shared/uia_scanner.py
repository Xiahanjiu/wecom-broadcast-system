# 企业微信群发系统 — 聊天列表 UIA 扫描器

import time
import logging
import re
from typing import List, Dict, Optional
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
    """

    def __init__(self):
        self._use_fallback = False
        self._ocr = None

    def scan(self) -> List[ChatListItem]:
        """扫描聊天列表，返回列表项。"""
        items = self._scan_uia()
        if items is None:
            logger.info("UIA 扫描失败，尝试 OCR 降级")
            items = self._scan_ocr()
        return items or []

    def _scan_uia(self) -> Optional[List[ChatListItem]]:
        """通过 UIA 扫描聊天列表。"""
        try:
            import uiautomation as auto

            # 查找企业微信窗口
            wecom = auto.WindowControl(Name="企业微信", searchDepth=1)
            if not wecom.Exists(maxSearchSeconds=2):
                logger.warning("未找到企业微信窗口")
                return None

            # 尝试多种方式定位聊天列表
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
        # 企微聊天列表通常是 ListControl 或 TreeControl
        # 尝试多种定位策略
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
        """解析单条聊天列表项文本。

        企微聊天列表项格式通常为:
        "群名\n发送者: 消息内容"
        或
        "群名 发送者: 消息"
        """
        if not raw_text.strip():
            return None

        lines = raw_text.strip().split("\n")
        if len(lines) < 2:
            # 可能只有群名，没有新消息
            return ChatListItem(
                group_name=lines[0].strip(),
                raw_text=raw_text
            )

        group_name = lines[0].strip()
        message_line = lines[1].strip() if len(lines) > 1 else ""

        # 解析 "发送者: 消息内容"
        sender_name = ""
        last_message = ""

        match = re.match(r"^(.+?)[:：]\s*(.*)", message_line)
        if match:
            sender_name = match.group(1).strip()
            last_message = match.group(2).strip()
        else:
            last_message = message_line

        # 检测是否有新消息特征
        has_unread = any(
            marker in raw_text
            for marker in ["[", "]", "条", "新消息"]
        )

        return ChatListItem(
            group_name=group_name,
            last_message=last_message,
            sender_name=sender_name,
            unread_count=0,  # UIA 难以精确获取未读数
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
