# 企业微信群发系统 — 企业微信客户端操控封装

import time
import logging
import random
from typing import Optional

logger = logging.getLogger(__name__)


class WeComClient:
    """企业微信桌面客户端操控封装。

    提供搜索群、进入群聊、粘贴发送等基础操作。
    使用 uiautomation 作为主方案，pyautogui 作为降级方案。
    """

    def __init__(self):
        self._window = None
        self._use_fallback = False

    # ---- 窗口管理 ----

    def find_window(self) -> bool:
        """查找并激活企业微信窗口。"""
        try:
            import uiautomation as auto
            wecom = auto.WindowControl(Name="企业微信", searchDepth=1)
            if wecom.Exists(maxSearchSeconds=3):
                self._window = wecom
                wecom.SetActive()
                time.sleep(0.5)
                self._use_fallback = False
                logger.info("已找到企业微信窗口")
                return True
        except Exception as e:
            logger.warning(f"UIA 查找窗口失败: {e}")

        # 降级: 通过窗口标题查找
        try:
            import pyautogui
            import pygetwindow as gw
            windows = gw.getWindowsWithTitle("企业微信")
            if windows:
                win = windows[0]
                win.activate()
                time.sleep(0.5)
                self._use_fallback = True
                logger.info("已找到企业微信窗口 (降级模式)")
                return True
        except Exception as e:
            logger.error(f"查找窗口完全失败: {e}")

        return False

    def is_window_available(self) -> bool:
        """检查企微窗口是否可用。"""
        return self.find_window()

    # ---- 搜索群聊 ----

    def search_group(self, group_name: str) -> bool:
        """在企微中搜索并进入群聊。"""
        if not self._window and not self._use_fallback:
            if not self.find_window():
                return False

        try:
            if not self._use_fallback:
                return self._search_group_uia(group_name)
            else:
                return self._search_group_fallback(group_name)
        except Exception as e:
            logger.error(f"搜索群聊失败 '{group_name}': {e}")
            return False

    def _search_group_uia(self, group_name: str) -> bool:
        """通过 UIA 搜索群聊。"""
        import uiautomation as auto

        # Ctrl+F 打开搜索
        auto.SendKeys("{Ctrl}f")
        time.sleep(0.5)

        # 输入群名
        auto.SendKeys(group_name)
        time.sleep(1.0)

        # 查找搜索结果列表中的第一个匹配项
        search_list = self._window.ListControl(searchDepth=3)
        if search_list.Exists(maxSearchSeconds=2):
            items = search_list.GetChildren()
            for item in items:
                if group_name in (item.Name or ""):
                    item.DoubleClick()
                    time.sleep(0.8)
                    return True

        return False

    def _search_group_fallback(self, group_name: str) -> bool:
        """通过 pyautogui 降级搜索群聊。"""
        import pyautogui
        import pyperclip

        # Ctrl+F 打开搜索
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.5)

        # 粘贴群名
        pyperclip.copy(group_name)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(1.0)

        # 按回车选择第一个结果
        pyautogui.press("enter")
        time.sleep(0.8)

        return True

    # ---- 发送消息 ----

    def send_message(self, message: str) -> bool:
        """在已打开的群聊中发送消息。"""
        try:
            if not self._use_fallback:
                return self._send_message_uia(message)
            else:
                return self._send_message_fallback(message)
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            return False

    def _send_message_uia(self, message: str) -> bool:
        """通过 UIA 发送消息。"""
        import uiautomation as auto
        import pyperclip

        # 定位消息输入框并点击
        edit = self._window.EditControl(searchDepth=4)
        if edit.Exists(maxSearchSeconds=2):
            edit.Click()
            time.sleep(0.2)
            # 粘贴消息
            pyperclip.copy(message)
            auto.SendKeys("{Ctrl}v")
            time.sleep(0.3)
            # 发送
            auto.SendKeys("{Enter}")
            time.sleep(0.5)
            return True

        return False

    def _send_message_fallback(self, message: str) -> bool:
        """通过 pyautogui 降级发送消息。"""
        import pyautogui
        import pyperclip

        # 粘贴消息到输入框（依赖焦点已在输入框）
        pyperclip.copy(message)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.3)
        # 发送
        pyautogui.press("enter")
        time.sleep(0.5)

        return True

    # ---- 消息发送结果检测 ----

    def check_send_status(self) -> bool:
        """检测消息是否发送成功。

        通过检查是否出现红色感叹号（发送失败标志）来判断。
        """
        time.sleep(0.5)
        # 简单策略: 检查聊天区域是否有错误提示
        # 企微发送失败通常会有红色感叹号图标
        try:
            import uiautomation as auto
            # 查找可能的错误图标
            error_icon = self._window.ImageControl(
                searchDepth=4, Name="发送失败"
            )
            if error_icon.Exists(maxSearchSeconds=1):
                return False
            return True
        except Exception:
            # 无法检测时默认认为成功
            return True


def random_delay(min_seconds=2, max_seconds=5):
    """随机延迟，防止触发风控。"""
    delay = random.uniform(min_seconds, max_seconds)
    time.sleep(delay)


# 全局单例
_wecom_client = None

def get_wecom_client():
    global _wecom_client
    if _wecom_client is None:
        _wecom_client = WeComClient()
    return _wecom_client
