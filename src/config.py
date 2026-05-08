"""配置模块，定义 AppConfig dataclass 和 ConfigLoader 类。"""

import os
from dataclasses import dataclass
from typing import Optional

import yaml

from src.exceptions import ConfigError


@dataclass
class AppConfig:
    source_bucket: str
    target_bucket: str
    aws_region: str = "us-east-1"
    source_prefix: str = ""
    target_prefix: str = ""
    log_level: str = "INFO"
    mineru_backend: str = "pipeline"
    mineru_lang: str = "ch"


class ConfigLoader:
    def load(self, config_file: Optional[str] = None) -> AppConfig:
        """
        加载配置，优先级：YAML 文件 > 环境变量 > 默认值。
        若 source_bucket 或 target_bucket 缺失则抛出 ConfigError。
        """
        # 从环境变量读取
        values: dict = {
            "source_bucket": os.environ.get("SOURCE_BUCKET", ""),
            "target_bucket": os.environ.get("TARGET_BUCKET", ""),
            "aws_region": os.environ.get("AWS_REGION", "us-east-1"),
            "source_prefix": os.environ.get("SOURCE_PREFIX", ""),
            "target_prefix": os.environ.get("TARGET_PREFIX", ""),
            "log_level": os.environ.get("LOG_LEVEL", "INFO"),
            "mineru_backend": os.environ.get("MINERU_BACKEND", "pipeline"),
            "mineru_lang": os.environ.get("MINERU_LANG", "ch"),
        }

        # YAML 文件覆盖环境变量
        if config_file is not None:
            with open(config_file, "r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}
            field_map = {
                "source_bucket": "source_bucket",
                "target_bucket": "target_bucket",
                "aws_region": "aws_region",
                "source_prefix": "source_prefix",
                "target_prefix": "target_prefix",
                "log_level": "log_level",
                "mineru_backend": "mineru_backend",
                "mineru_lang": "mineru_lang",
            }
            for yaml_key, field in field_map.items():
                if yaml_key in yaml_data and yaml_data[yaml_key] is not None:
                    values[field] = str(yaml_data[yaml_key])

        if not values.get("source_bucket"):
            raise ConfigError("缺少必填配置项：source_bucket（环境变量 SOURCE_BUCKET）")
        if not values.get("target_bucket"):
            raise ConfigError("缺少必填配置项：target_bucket（环境变量 TARGET_BUCKET）")

        return AppConfig(**values)
