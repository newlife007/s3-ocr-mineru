"""MinerURunner 单元测试。"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.exceptions import MinerUError, UnsupportedFormatError
from src.mineru_runner import MinerURunner, OCRResult


def test_unsupported_format_raises_error(tmp_path):
    """不支持的文件格式应抛出 UnsupportedFormatError。"""
    runner = MinerURunner()
    input_file = tmp_path / "document.txt"
    input_file.touch()

    with pytest.raises(UnsupportedFormatError):
        runner.run(input_file, tmp_path)


def test_mineru_failure_raises_error(tmp_path):
    """mineru CLI 返回非零退出码时应抛出 MinerUError。"""
    runner = MinerURunner()
    input_file = tmp_path / "document.pdf"
    input_file.touch()

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "mineru processing failed"

    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(MinerUError, match="mineru processing failed"):
            runner.run(input_file, tmp_path)


def test_extract_page_count_from_middle_json(tmp_path):
    """从 middle.json 中正确提取页数。"""
    runner = MinerURunner()
    output_dir = tmp_path / "document"
    output_dir.mkdir()

    middle_json = output_dir / "document_middle.json"
    middle_json.write_text(
        json.dumps({"pdf_info": [{}, {}, {}]}), encoding="utf-8"
    )

    assert runner._extract_page_count(output_dir, "document") == 3


def test_extract_page_count_missing_file_returns_zero(tmp_path):
    """middle.json 不存在时应返回 0。"""
    runner = MinerURunner()
    output_dir = tmp_path / "document"
    output_dir.mkdir()

    assert runner._extract_page_count(output_dir, "document") == 0


def test_run_success(tmp_path):
    """成功运行时应返回包含正确内容和页数的 OCRResult。"""
    runner = MinerURunner()
    input_file = tmp_path / "report.pdf"
    input_file.touch()

    output_dir = tmp_path / "report"
    output_dir.mkdir()

    md_file = output_dir / "report.md"
    md_file.write_text("# OCR Result\n\nSome content.", encoding="utf-8")

    middle_json = output_dir / "report_middle.json"
    middle_json.write_text(
        json.dumps({"pdf_info": [{}, {}]}), encoding="utf-8"
    )

    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        result = runner.run(input_file, tmp_path)

    assert isinstance(result, OCRResult)
    assert result.md_content == "# OCR Result\n\nSome content."
    assert result.page_count == 2

    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert "mineru" in call_args
    assert str(input_file) in call_args
    assert str(output_dir) in call_args
