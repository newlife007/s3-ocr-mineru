"""ConfigLoader 单元测试。"""

import os
import tempfile

import pytest
import yaml

from src.config import AppConfig, ConfigLoader
from src.exceptions import ConfigError


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """清除所有相关环境变量，确保测试隔离。"""
    for var in [
        "SOURCE_BUCKET", "TARGET_BUCKET", "AWS_REGION",
        "SOURCE_PREFIX", "TARGET_PREFIX", "LOG_LEVEL",
        "MINERU_BACKEND", "MINERU_LANG",
    ]:
        monkeypatch.delenv(var, raising=False)


def test_config_missing_source_bucket():
    """缺少 SOURCE_BUCKET 时应抛出 ConfigError。"""
    loader = ConfigLoader()
    with pytest.raises(ConfigError, match="source_bucket"):
        loader.load()


def test_config_missing_target_bucket(monkeypatch):
    """缺少 TARGET_BUCKET 时应抛出 ConfigError。"""
    monkeypatch.setenv("SOURCE_BUCKET", "my-source")
    loader = ConfigLoader()
    with pytest.raises(ConfigError, match="target_bucket"):
        loader.load()


def test_config_from_env_vars(monkeypatch):
    """从环境变量正确加载所有配置项。"""
    monkeypatch.setenv("SOURCE_BUCKET", "src-bucket")
    monkeypatch.setenv("TARGET_BUCKET", "tgt-bucket")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
    monkeypatch.setenv("SOURCE_PREFIX", "input/")
    monkeypatch.setenv("TARGET_PREFIX", "output/")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("MINERU_BACKEND", "vlm")
    monkeypatch.setenv("MINERU_LANG", "en")

    config = ConfigLoader().load()

    assert config.source_bucket == "src-bucket"
    assert config.target_bucket == "tgt-bucket"
    assert config.aws_region == "ap-northeast-1"
    assert config.source_prefix == "input/"
    assert config.target_prefix == "output/"
    assert config.log_level == "DEBUG"
    assert config.mineru_backend == "vlm"
    assert config.mineru_lang == "en"


def test_yaml_overrides_env(monkeypatch, tmp_path):
    """YAML 文件中的值应覆盖环境变量中的值。"""
    monkeypatch.setenv("SOURCE_BUCKET", "env-source")
    monkeypatch.setenv("TARGET_BUCKET", "env-target")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(yaml.dump({
        "source_bucket": "yaml-source",
        "target_bucket": "yaml-target",
        "aws_region": "eu-west-1",
        "log_level": "WARNING",
    }))

    config = ConfigLoader().load(config_file=str(yaml_file))

    assert config.source_bucket == "yaml-source"
    assert config.target_bucket == "yaml-target"
    assert config.aws_region == "eu-west-1"
    assert config.log_level == "WARNING"
