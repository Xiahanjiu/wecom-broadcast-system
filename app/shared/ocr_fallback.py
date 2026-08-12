# 企业微信群发系统 — OCR 降级扫描器

import logging
import subprocess
import sys
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


class OCRScanner:
    """OCR 扫描器，当 UIA 无法读取聊天列表时作为降级方案。

    截取企业微信聊天列表区域 → OCR 识别 → 解析为结构化数据。
    支持 PaddleOCR（优先）和 Tesseract（备选）。
    """

    def __init__(self):
        self._ocr = None
        self._engine = None

    def scan_chat_list(self) -> List:
        """扫描聊天列表，返回 ChatListItem 列表。"""
        screenshot = self._capture_chat_list()
        if screenshot is None:
            return []

        text = self._ocr_image(screenshot)
        if not text:
            return []

        return self._parse_ocr_result(text)

    def _capture_chat_list(self):
        """截取聊天列表区域。"""
        try:
            from PIL import ImageGrab
            # 聊天列表通常在企微窗口左侧，约占窗口 30% 宽度
            import pyautogui

            # 尝试定位企微窗口
            try:
                import pygetwindow as gw
                windows = gw.getWindowsWithTitle("企业微信")
                if not windows:
                    logger.warning("未找到企业微信窗口用于截图")
                    return None

                win = windows[0]
                # 截取左侧聊天列表区域
                list_width = int(win.width * 0.35)
                bbox = (
                    win.left,
                    win.top + 50,  # 跳过标题栏
                    win.left + list_width,
                    win.top + win.height - 50
                )
                screenshot = ImageGrab.grab(bbox)
                return screenshot
            except ImportError:
                # 降级: 截取整个屏幕左侧区域
                screen_width, screen_height = pyautogui.size()
                bbox = (0, 0, int(screen_width * 0.3), screen_height)
                screenshot = ImageGrab.grab(bbox)
                return screenshot

        except Exception as e:
            logger.error(f"截图失败: {e}")
            return None

    def _ocr_image(self, image) -> str:
        """对图像执行 OCR 识别。"""
        if image is None:
            return ""

        engine = self._get_ocr_engine()

        if engine == "paddle":
            return self._ocr_paddle(image)
        elif engine == "tesseract":
            return self._ocr_tesseract(image)
        else:
            logger.error("无可用的 OCR 引擎")
            return ""

    def _get_ocr_engine(self):
        """检测可用的 OCR 引擎。"""
        if self._engine is not None:
            return self._engine

        # 优先 PaddleOCR
        try:
            import paddleocr
            self._engine = "paddle"
            logger.info("使用 PaddleOCR 引擎")
            return self._engine
        except ImportError:
            pass

        # 备选 Tesseract
        try:
            result = subprocess.run(
                ["tesseract", "--version"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                self._engine = "tesseract"
                logger.info("使用 Tesseract OCR 引擎")
                return self._engine
        except FileNotFoundError:
            pass

        logger.error("未找到可用的 OCR 引擎 (paddleocr / tesseract)")
        self._engine = None
        return None

    def _ocr_paddle(self, image) -> str:
        """使用 PaddleOCR 识别。"""
        try:
            import numpy as np
            from paddleocr import PaddleOCR

            if self._ocr is None:
                self._ocr = PaddleOCR(
                    use_angle_cls=True,
                    lang='ch',
                    show_log=False
                )

            img_array = np.array(image)
            result = self._ocr.ocr(img_array, cls=True)

            if not result or not result[0]:
                return ""

            # 按 y 坐标排序（从上到下），合并各行文本
            lines = []
            for line_info in result[0]:
                if line_info and len(line_info) >= 2:
                    text = line_info[1][0]
                    bbox = line_info[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                    y_center = (bbox[0][1] + bbox[2][1]) / 2
                    lines.append((y_center, text))

            lines.sort(key=lambda x: x[0])
            return "\n".join(text for _, text in lines)

        except Exception as e:
            logger.error(f"PaddleOCR 识别失败: {e}")
            return ""

    def _ocr_tesseract(self, image) -> str:
        """使用 Tesseract OCR 识别。"""
        try:
            import pytesseract
            text = pytesseract.image_to_string(image, lang='chi_sim+eng')
            return text.strip()
        except Exception as e:
            logger.error(f"Tesseract OCR 识别失败: {e}")
            return ""

    def _parse_ocr_result(self, text: str) -> List:
        """解析 OCR 识别结果，转换为 ChatListItem 列表。"""
        from .uia_scanner import ChatListItem

        items = []
        lines = text.strip().split("\n")

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            # 群名行（通常包含群名和一些特殊字符）
            group_name = line

            # 下一行可能是最后消息
            last_message = ""
            if i + 1 < len(lines):
                last_message = lines[i + 1].strip()
                i += 1

            items.append(ChatListItem(
                group_name=group_name,
                last_message=last_message,
                raw_text=f"{group_name}\n{last_message}"
            ))
            i += 1

        logger.info(f"OCR 扫描完成: {len(items)} 个聊天项")
        return items
