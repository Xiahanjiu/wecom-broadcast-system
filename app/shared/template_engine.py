# 企业微信群发系统 — Jinja2 消息模板引擎

import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

from jinja2 import Environment, FileSystemLoader, Template

logger = logging.getLogger(__name__)


class MessageTemplateEngine:
    """消息模板引擎。

    基于 Jinja2，支持从文件加载模板和字符串模板两种模式。
    支持变量: 群名、日期、自定义备注、通用内容等。
    """

    def __init__(self, template_dir=None):
        if template_dir is None:
            template_dir = Path(__file__).parent.parent.parent / "data" / "templates"
        self._template_dir = Path(template_dir)
        self._template_dir.mkdir(parents=True, exist_ok=True)

        self._env = Environment(
            loader=FileSystemLoader(str(self._template_dir)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        # 内置过滤器
        self._env.filters["date"] = self._format_date

        logger.info(f"模板引擎已初始化, 模板目录: {self._template_dir}")

    def render_file(self, template_name: str, context: Dict) -> str:
        """从文件渲染模板。

        Args:
            template_name: 模板文件名 (如 'default.j2')
            context: 变量上下文
        Returns:
            渲染后的消息文本
        """
        try:
            template = self._env.get_template(template_name)
            return template.render(**context)
        except Exception as e:
            logger.error(f"模板渲染失败 '{template_name}': {e}")
            return f"[模板渲染错误: {e}]"

    def render_string(self, template_str: str, context: Dict) -> str:
        """从字符串渲染模板。"""
        try:
            template = self._env.from_string(template_str)
            return template.render(**context)
        except Exception as e:
            logger.error(f"字符串模板渲染失败: {e}")
            return f"[模板渲染错误: {e}]"

    def render_for_group(
        self,
        template_name: str,
        group_name: str,
        custom_note: str = "",
        common_content: str = "",
        extra: Optional[Dict] = None
    ) -> str:
        """为指定群渲染消息。

        Args:
            template_name: 模板文件名
            group_name: 群名
            custom_note: 该群的自定义备注
            common_content: 通用内容
            extra: 额外变量
        """
        context = {
            "group_name": group_name,
            "date": datetime.now(),
            "custom_note": custom_note,
            "common_content": common_content,
        }
        if extra:
            context.update(extra)

        return self.render_file(template_name, context)

    def save_template(self, name: str, content: str):
        """保存模板到文件。"""
        path = self._template_dir / name
        path.write_text(content, encoding="utf-8")
        logger.info(f"模板已保存: {name}")

    def list_templates(self):
        """列出所有模板文件。"""
        return [
            f.name for f in self._template_dir.glob("*.j2")
        ]

    def get_template_content(self, name: str) -> str:
        """获取模板内容。"""
        path = self._template_dir / name
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    @staticmethod
    def _format_date(dt, fmt="%Y年%m月%d日"):
        """日期格式化过滤器。"""
        if isinstance(dt, str):
            return dt
        return dt.strftime(fmt)


def create_default_template():
    """创建默认消息模板。"""
    template_dir = Path(__file__).parent.parent.parent / "data" / "templates"
    template_dir.mkdir(parents=True, exist_ok=True)

    default_template = """【{{ common_content or '通知' }}】
各位{{ group_name }}的朋友们大家好！

{{ common_content }}

{% if custom_note %}
📌 {{ custom_note }}
{% endif %}

---
{{ date | date }}
"""

    path = template_dir / "default.j2"
    path.write_text(default_template, encoding="utf-8")
    logger.info(f"默认模板已创建: {path}")


# 全局单例
_engine = None

def get_template_engine():
    global _engine
    if _engine is None:
        _engine = MessageTemplateEngine()
        # 确保默认模板存在
        default_path = _engine._template_dir / "default.j2"
        if not default_path.exists():
            create_default_template()
    return _engine
