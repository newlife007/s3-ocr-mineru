"""MinerU OCR 执行器模块 - 使用异步子进程避免僵尸进程。"""

import asyncio
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from src.exceptions import MinerUError, UnsupportedFormatError

# 使用当前运行的 Python 解释器
_PYTHON = sys.executable

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff"}


def _normalize_arabic_text(text: str) -> str:
    """
    规范化阿拉伯语文本。
    
    处理：
    1. Unicode 规范化
    2. 统一不同形式的阿拉伯语字符
    3. 处理连字
    """
    import unicodedata
    
    # Unicode 规范化（NFKC：兼容性分解后再组合）
    text = unicodedata.normalize('NFKC', text)
    
    # 阿拉伯语连字转换为标准形式
    ligatures = {
        '\uFEF5': '\u0644\u0627',  # ﻵ -> لا
        '\uFEF6': '\u0644\u0627',  # ﻶ -> لا
        '\uFEF7': '\u0644\u0627',  # ﻷ -> لا
        '\uFEF8': '\u0644\u0627',  # ﻸ -> لا
        '\uFEF9': '\u0644\u0627',  # ﻹ -> لا
        '\uFEFA': '\u0644\u0627',  # ﻺ -> لا
        '\uFEFB': '\u0644\u0627',  # ﻻ -> لا
        '\uFEFC': '\u0644\u0627',  # ﻼ -> لا
    }
    
    for ligature, standard in ligatures.items():
        text = text.replace(ligature, standard)
    
    return text


def _clean_arabic_text(text: str) -> str:
    """
    清理阿拉伯语文本中的多余字符。
    
    处理：
    1. 移除零宽字符
    2. 移除部分控制字符（保留换行、制表符等 Markdown 需要的字符）
    
    注意：保留 Markdown 格式所需的空格、制表符、换行符等
    """
    import re
    
    # 移除零宽字符（Zero-width characters）
    text = re.sub(r'[\u200B-\u200D\uFEFF]', '', text)
    
    # 只移除真正有问题的控制字符，保留换行(\n)、制表符(\t)、回车(\r)
    # 移除 \x00-\x08, \x0B-\x0C, \x0E-\x1F (保留 \t=\x09, \n=\x0A, \r=\x0D)
    text = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F-\x9F]', '', text)
    
    # 不再规范化空格和移除行首行尾空格，以保留 Markdown 格式
    # 原来的代码会破坏：
    # - 代码块的缩进
    # - 列表的缩进
    # - 表格的对齐
    # - 引用块的格式
    
    return text


def _post_process_arabic_text(text: str, normalize: bool = True, clean: bool = True) -> str:
    """
    阿拉伯语文本后处理。
    
    参数：
        text: 要处理的文本
        normalize: 是否规范化字符
        clean: 是否清理多余字符
    
    返回：
        处理后的文本
    """
    if not text:
        return text
    
    import logging
    logger = logging.getLogger(__name__)
    
    original_length = len(text)
    
    if normalize:
        logger.info("Normalizing Arabic text...")
        text = _normalize_arabic_text(text)
    
    if clean:
        logger.info("Cleaning Arabic text...")
        text = _clean_arabic_text(text)
    
    logger.info(f"Post-processing complete. Length: {original_length} -> {len(text)}")
    
    return text


def _fix_arabic_text_direction(text: str, mode: str = "auto") -> str:
    """
    智能修复阿拉伯语文本方向问题。
    
    阿拉伯语是从右到左（RTL）书写的。OCR 识别结果中，有些文本是逻辑顺序（存储顺序），
    有些已经是视觉顺序（显示顺序）。
    
    参数：
        text: 要处理的文本
        mode: 处理模式
            - "never": 不做任何处理，保持原样
            - "always": 总是应用 bidi 转换
            - "auto": 智能检测（默认，推荐）
    
    返回：
        处理后的文本
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"_fix_arabic_text_direction called with mode={mode}, text_length={len(text) if text else 0}")
    
    # never 模式：直接返回原文本
    if not text or mode == "never":
        logger.info(f"Mode is 'never' or text is empty, returning original text")
        return text
    
    # 检测是否包含阿拉伯语字符
    import re
    arabic_pattern = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]')
    has_arabic = arabic_pattern.search(text)
    logger.info(f"Arabic characters detected: {bool(has_arabic)}")
    
    if not has_arabic:
        return text
    
    try:
        from bidi.algorithm import get_display
        
        if mode == "always":
            # always 模式：总是应用 bidi 转换
            logger.info("Applying 'always' mode - will transform all Arabic lines")
            lines = text.split('\n')
            fixed_lines = []
            transformed_count = 0
            for line in lines:
                if arabic_pattern.search(line):
                    try:
                        fixed_line = get_display(line)
                        fixed_lines.append(fixed_line)
                        if fixed_line != line:
                            transformed_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to transform line: {e}")
                        fixed_lines.append(line)
                else:
                    fixed_lines.append(line)
            logger.info(f"Transformed {transformed_count} lines in 'always' mode")
            return '\n'.join(fixed_lines)
        
        elif mode == "auto":
            # auto 模式：目前与 always 相同，应用 bidi 转换
            logger.info("Applying 'auto' mode - will transform all Arabic lines")
            lines = text.split('\n')
            fixed_lines = []
            transformed_count = 0
            
            for line in lines:
                if not line.strip():
                    fixed_lines.append(line)
                    continue
                    
                if arabic_pattern.search(line):
                    try:
                        # 应用 bidi 转换
                        fixed_line = get_display(line)
                        fixed_lines.append(fixed_line)
                        if fixed_line != line:
                            transformed_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to transform line: {e}")
                        fixed_lines.append(line)
                else:
                    fixed_lines.append(line)
            
            logger.info(f"Transformed {transformed_count} lines in 'auto' mode")
            return '\n'.join(fixed_lines)
        
        else:
            # 未知模式，保持原样
            logger.warning(f"Unknown mode '{mode}', returning original text")
            return text
        
    except ImportError as e:
        # 如果没有安装 python-bidi，返回原文本
        logger.error(f"python-bidi not installed: {e}")
        return text


@dataclass
class OCRResult:
    """OCR 识别结果。"""

    md_content: str
    page_count: int
    images_dir: Path  # 图片目录，可能不存在


class MinerURunner:
    """通过异步 subprocess 调用 mineru CLI 执行 OCR。"""

    def __init__(self, backend: str = "pipeline", lang: str = "ch", arabic_bidi_fix: str = "auto", 
                 arabic_post_process: bool = True):
        self.backend = backend
        self.lang = lang
        self.arabic_bidi_fix = arabic_bidi_fix
        self.arabic_post_process = arabic_post_process

    async def run_async(self, input_path: Path, work_dir: Path) -> OCRResult:
        """
        异步执行 OCR，返回 OCRResult。
        
        使用 asyncio.create_subprocess_exec 避免僵尸进程问题。

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
        
        # 记录实际执行的命令（使用 StructuredLogger）
        from src.logger import StructuredLogger
        logger = StructuredLogger("mineru_runner")
        
        logger.info(
            "Executing MinerU command",
            backend=self.backend,
            lang=self.lang,
            input_path=str(input_path),
            output_dir=str(output_dir),
            arabic_bidi_fix=self.arabic_bidi_fix,
        )
        
        # 构建等效的命令行格式（方便调试）
        equivalent_cmd = (
            f"mineru -p '{input_path}' -o '{output_dir}' "
            f"-b '{self.backend}' -l '{self.lang}' -m 'ocr' -f 'true' -t 'true'"
        )
        logger.info("MinerU equivalent command", command=equivalent_cmd)
        
        # 开启中文公式识别优化（实验性功能，对中文文档有效）
        env = {
            **os.environ,
            "MINERU_FORMULA_ENABLE": "true",
            "MINERU_FORMULA_CH_SUPPORT": "true",
        }
        
        # 将 stdout/stderr 重定向到临时文件，而不是 PIPE
        # 这样可以避免 MinerU 的子进程导致 communicate() 卡住
        stdout_file = work_dir / f"{stem_md5}_stdout.log"
        stderr_file = work_dir / f"{stem_md5}_stderr.log"
        
        with open(stdout_file, 'w') as stdout_f, open(stderr_file, 'w') as stderr_f:
            # 使用 asyncio.create_subprocess_exec 创建异步子进程
            process = await asyncio.create_subprocess_exec(
                _PYTHON,
                "-c",
                mineru_cmd,
                stdout=stdout_f,
                stderr=stderr_f,
                env=env,
            )
            
            try:
                # 只等待进程结束，不读取输出
                returncode = await asyncio.wait_for(
                    process.wait(),
                    timeout=3600  # 1小时超时
                )
                
            except asyncio.TimeoutError:
                # 超时则终止进程
                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                raise MinerUError("OCR 处理超时（超过1小时）")
            
            except Exception:
                # 发生任何异常时，确保进程被终止
                if process.returncode is None:
                    try:
                        process.terminate()
                        await asyncio.wait_for(process.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
                raise
        
        # 读取输出文件
        stderr_text = stderr_file.read_text(encoding='utf-8', errors='replace') if stderr_file.exists() else ""

        if returncode != 0:
            raise MinerUError(stderr_text)

        md_content = self._read_markdown(actual_output_dir, stem_md5)
        
        # 如果是阿拉伯语，应用后处理和文本方向修复
        if self.lang == 'arabic':
            import logging
            logger = logging.getLogger(__name__)
            
            # 1. 后处理优化（规范化和清理）
            if self.arabic_post_process:
                logger.info("Applying Arabic post-processing...")
                md_content = _post_process_arabic_text(md_content, normalize=True, clean=True)
            
            # 2. 文本方向修复
            logger.info(f"Applying Arabic BiDi fix with mode: {self.arabic_bidi_fix}")
            original_length = len(md_content)
            md_content = _fix_arabic_text_direction(md_content, mode=self.arabic_bidi_fix)
            logger.info(f"Arabic BiDi fix applied. Original length: {original_length}, New length: {len(md_content)}")
        
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
