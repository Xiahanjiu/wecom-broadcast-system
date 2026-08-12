# 企业微信群发系统 — 配置管理

import os
import yaml
from pathlib import Path

class Config:
    """全局配置管理，支持从 YAML 文件加载和环境变量覆盖。"""

    _instance = None
    _data = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def load(cls, config_path=None):
        """加载配置文件。"""
        if config_path is None:
            config_path = Path(__file__).parent.parent.parent / "config.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            cls._data = yaml.safe_load(f) or {}
        # 环境变量覆盖
        cls._apply_env_overrides()
        return cls._data

    @classmethod
    def _apply_env_overrides(cls):
        """用环境变量覆盖配置，格式: WECOM_SECTION__KEY=value。"""
        for key, val in os.environ.items():
            if key.startswith("WECOM_"):
                parts = key[6:].lower().split("__")
                if len(parts) == 2:
                    section, option = parts
                    if section in cls._data:
                        cls._data[section][option] = cls._coerce(val)

    @classmethod
    def get(cls, key, default=None):
        """获取配置项，支持点号路径如 'alert.timeout_seconds'。"""
        keys = key.split(".")
        value = cls._data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value

    @classmethod
    def get_all(cls):
        """获取全部配置。"""
        return cls._data

    @staticmethod
    def _coerce(val):
        """尝试将字符串转为适当的类型。"""
        if val.lower() in ("true", "yes", "1"):
            return True
        if val.lower() in ("false", "no", "0"):
            return False
        try:
            return int(val)
        except ValueError:
            pass
        try:
            return float(val)
        except ValueError:
            pass
        return val


# 便捷函数
def load_config(path=None):
    return Config.load(path)
