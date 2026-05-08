"""MinerU OCR 执行器模块。"""

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from src.exceptions import MinerUError, UnsupportedFormatError

# 使用当前运行的 Python 解释器
_PYTHON = sys.executable

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff"}


@dataclass
class OCRResult:
    """OCR 识别结果。"""

    md_content: str
    page_count: int
    images_dir: Path  # 图片目录，可能不存在


class MinerURunner:
    """通过 subprocess 调用 mineru CLI 执行 OCR。"""

    def __init__(self, backend: str = "pipeline", lang: str = "ch"):
        self.backend = backend
        self.lang = lang

    def run(self, input_path: Path, work_dir: Path) -> OCRResult:
        """
        对 input_path 执行 OCR，返回 OCRResult。

        若文件格式不支持则抛出 UnsupportedFormatError。
        若 mineru 返回非零退出码则抛出 MinerUError。
        """
        if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise UnsupportedFormatError(
                f"不支持的文件格式：{input_path.suffix}"
            )

        # 用文件名 MD5 作为目录名，避免长文件名/特殊字符导致路径问题
        stem_md5 = hashlib.md5(input_path.stem.encode()).hexdigest()
        output_dir = work_dir / stem_md5
        actual_output_dir = output_dir / stem_md5

        mineru_cmd = (
            f"from mineru.cli.client import main; import sys; "
            f"sys.argv = ['mineru', '-p', r'{input_path}', '-o', r'{output_dir}', "
            f"'-b', '{self.backend}', '-l', '{self.lang}', '-m', 'ocr', "
            f"'-f', 'true', '-t', 'true']; main()"
        )
        # 开启中文公式识别优化（实验性功能，对中文文档有效）
        env = {
            **os.environ,
            "MINERU_FORMULA_ENABLE": "true",
            "MINERU_FORMULA_CH_SUPPORT": "true",
        }
        result = subprocess.run(
            [_PYTHON, "-c", mineru_cmd],
            capture_output=True,
            text=True,
            env=env,
        )

        if result.returncode != 0:
            raise MinerUError(result.stderr)

        md_content = self._read_markdown(actual_output_dir, stem_md5)
        page_count = self._extract_page_count(actual_output_dir, stem_md5)
        images_dir = self._find_images_dir(actual_output_dir)

        return OCRResult(md_content=md_content, page_count=page_count, images_dir=images_dir)

    def _extract_page_count(self, output_dir: Path, stem: str) -> int:
        """从 middle.json 中提取页数，失败时返回 0。自动搜索实际文件位置。"""
        # 先按预期路径找
        middle_json = output_dir / f"{stem}_middle.json"
        if not middle_json.exists():
            # 自动搜索父目录下所有 *_middle.json 文件
            parent = output_dir.parent
            candidates = list(parent.rglob("*_middle.json"))
            if not candidates:
                return 0
            middle_json = candidates[0]
        try:
            data = json.loads(middle_json.read_text(encoding="utf-8"))
            return len(data.get("pdf_info", []))
        except (FileNotFoundError, json.JSONDecodeError):
            return 0

    def _read_markdown(self, output_dir: Path, stem: str) -> str:
        """读取 OCR 输出的 Markdown 文件内容，自动搜索实际位置。"""
        # 先按预期路径找
        md_file = output_dir / f"{stem}.md"
        if md_file.exists():
            return md_file.read_text(encoding="utf-8")
        # 自动搜索 output_dir 父目录下所有 .md 文件
        parent = output_dir.parent
        md_files = list(parent.rglob("*.md"))
        if md_files:
            return md_files[0].read_text(encoding="utf-8")
        raise FileNotFoundError(f"找不到 Markdown 输出文件，已搜索：{parent}")

    def _find_images_dir(self, output_dir: Path) -> Path:
        """返回图片目录路径（不保证存在）。"""
        # MinerU 输出图片到 output_dir/images/
        images_dir = output_dir / "images"
        if images_dir.exists():
            return images_dir
        # 自动搜索父目录下的 images 子目录
        parent = output_dir.parent
        for candidate in parent.rglob("images"):
            if candidate.is_dir():
                return candidate
        return images_dir  # 返回预期路径，即使不存在
