# 阿拉伯语 OCR 识别优化方案

## 📊 当前状态分析

根据您的测试结果：
- ✅ 使用 `never` 模式（不做 BiDi 转换）能让**大部分**阿拉伯语与原文一致
- ❌ 仍有**小部分**文本与原文不一致

这说明：
1. MinerU OCR 引擎输出的是正确的视觉顺序（不需要 BiDi 转换）
2. 不一致的部分可能是 OCR 识别错误，而不是文本方向问题

## 🎯 优化策略

### 策略 1：调整 MinerU 引擎参数（推荐）

MinerU 支持多种后端引擎，不同引擎对阿拉伯语的识别效果不同。

#### 1.1 尝试不同的后端引擎

在 `config.yaml` 中修改 `mineru_backend`：

```yaml
# 选项 1：标准流水线（默认）
mineru_backend: "pipeline"

# 选项 2：混合自动引擎（当前使用）
mineru_backend: "hybrid-auto-engine"

# 选项 3：VLM 模式（需要更多资源，但可能更准确）
mineru_backend: "vlm-transformers"
```

**建议测试顺序**：
1. 先试 `pipeline`（标准模式）
2. 如果效果不好，试 `vlm-transformers`（需要更多 GPU 内存）

#### 1.2 调整 OCR 引擎的环境变量

MinerU 支持通过环境变量调整 OCR 行为。在 `src/mineru_runner.py` 中已经设置了一些优化参数：

```python
env = {
    **os.environ,
    "MINERU_FORMULA_ENABLE": "true",
    "MINERU_FORMULA_CH_SUPPORT": "true",
}
```

我们可以添加更多阿拉伯语优化参数。

### 策略 2：添加阿拉伯语特定的 OCR 优化

#### 2.1 启用阿拉伯语优化环境变量

让我修改代码，添加阿拉伯语特定的优化参数：

```python
# 针对阿拉伯语的优化
if self.lang == 'arabic':
    env.update({
        "MINERU_ARABIC_OPTIMIZE": "true",
        "MINERU_RTL_SUPPORT": "true",
        "MINERU_ARABIC_LIGATURE": "true",  # 支持阿拉伯语连字
    })
```

#### 2.2 调整 OCR 置信度阈值

可以通过环境变量调整 OCR 的置信度阈值，提高识别准确度：

```python
env.update({
    "MINERU_OCR_THRESHOLD": "0.8",  # 提高置信度阈值（默认可能是 0.5）
})
```

### 策略 3：后处理优化

即使 OCR 引擎已经尽力，仍可能有小部分错误。我们可以添加后处理步骤。

#### 3.1 阿拉伯语字符规范化

某些阿拉伯语字符有多种 Unicode 表示形式，规范化可以提高一致性：

```python
def normalize_arabic_text(text: str) -> str:
    """规范化阿拉伯语文本"""
    import unicodedata
    
    # Unicode 规范化
    text = unicodedata.normalize('NFKC', text)
    
    # 阿拉伯语特定的字符替换
    replacements = {
        '\u0649': '\u064A',  # ى -> ي (Alef Maksura -> Yeh)
        '\u0623': '\u0627',  # أ -> ا (Alef with Hamza above -> Alef)
        '\u0625': '\u0627',  # إ -> ا (Alef with Hamza below -> Alef)
        '\u0622': '\u0627',  # آ -> ا (Alef with Madda above -> Alef)
    }
    
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    return text
```

#### 3.2 移除多余的空格和控制字符

```python
def clean_arabic_text(text: str) -> str:
    """清理阿拉伯语文本中的多余字符"""
    import re
    
    # 移除多余的空格
    text = re.sub(r'\s+', ' ', text)
    
    # 移除零宽字符
    text = re.sub(r'[\u200B-\u200D\uFEFF]', '', text)
    
    # 移除阿拉伯语标记符号（如果不需要）
    # text = re.sub(r'[\u064B-\u065F]', '', text)  # 移除 Tashkeel
    
    return text.strip()
```

### 策略 4：使用更高质量的 OCR 模型

#### 4.1 检查 MinerU 版本

确保使用最新版本的 MinerU：

```bash
pip show mineru
# 如果不是最新版，升级：
pip install --upgrade mineru
```

#### 4.2 使用专门的阿拉伯语 OCR 模型

MinerU 可能支持加载自定义模型。查看是否有专门针对阿拉伯语优化的模型。

### 策略 5：添加配置选项控制后处理

让用户可以选择是否启用后处理优化。

## 🛠️ 实施方案

让我为您实现以上优化：

### 第 1 步：添加后处理选项到配置

在 `config.yaml` 中添加：

```yaml
# 阿拉伯语后处理优化
arabic_post_process: true  # 是否启用阿拉伯语后处理优化
arabic_normalize: true     # 是否规范化阿拉伯语字符
arabic_clean: true         # 是否清理多余字符
```

### 第 2 步：实现后处理函数

在 `mineru_runner.py` 中添加后处理函数。

### 第 3 步：添加 OCR 引擎优化参数

在运行 OCR 时添加阿拉伯语特定的环境变量。

### 第 4 步：提供多个后端引擎选项

让用户可以在页面上选择不同的后端引擎。

## 📋 快速测试方案

### 方案 A：更换后端引擎（最简单）

1. 修改 `config.yaml`：
   ```yaml
   mineru_backend: "pipeline"  # 从 hybrid-auto-engine 改为 pipeline
   ```

2. 重启服务：
   ```bash
   pkill -f "uvicorn.*api_server"
   cd /home/ubuntu/s3-ocr-mineru
   nohup bash run.sh > service.log 2>&1 &
   ```

3. 重新识别测试文件，对比结果

### 方案 B：添加后处理优化（推荐）

我现在就为您实现这个方案。

## 🎯 预期效果

实施优化后，预期可以：
1. ✅ 提高阿拉伯语字符识别的准确度
2. ✅ 规范化不同形式的阿拉伯语字符
3. ✅ 清理 OCR 输出中的噪声字符
4. ✅ 保持文本方向的正确性（使用 never 模式）

## 📊 效果评估

优化后，建议：
1. 使用相同的测试文件重新识别
2. 对比优化前后的结果
3. 统计准确率的提升
4. 记录仍然不一致的部分，进一步分析原因

## 🔍 深入分析不一致的原因

如果优化后仍有不一致，可能的原因：

### 1. OCR 引擎的固有限制
- 某些字体或手写体难以识别
- 图像质量问题（模糊、倾斜、噪声）
- 复杂的排版（多栏、表格）

### 2. 阿拉伯语的特殊性
- **连字（Ligatures）**：阿拉伯语字符会根据位置改变形状
- **标记符号（Diacritics/Tashkeel）**：元音标记可能被识别或遗漏
- **数字方向**：阿拉伯数字在 RTL 文本中的方向处理

### 3. 混合文本
- 阿拉伯语和英语混合
- 阿拉伯语和数字混合
- 特殊符号和标点

## 💡 针对性解决方案

### 如果是连字问题
添加连字处理：
```python
def handle_arabic_ligatures(text: str) -> str:
    """处理阿拉伯语连字"""
    # 将连字形式转换为标准形式
    ligatures = {
        '\uFEF5': '\u0644\u0627',  # ﻵ -> لا
        '\uFEF6': '\u0644\u0627',  # ﻶ -> لا
        '\uFEF7': '\u0644\u0627',  # ﻷ -> لا
        '\uFEF8': '\u0644\u0627',  # ﻸ -> لا
    }
    for ligature, standard in ligatures.items():
        text = text.replace(ligature, standard)
    return text
```

### 如果是标记符号问题
提供选项移除或保留标记符号：
```python
def remove_arabic_diacritics(text: str) -> str:
    """移除阿拉伯语标记符号（Tashkeel）"""
    import re
    # 移除所有 Tashkeel 标记
    return re.sub(r'[\u064B-\u065F\u0670]', '', text)
```

### 如果是数字方向问题
规范化数字：
```python
def normalize_arabic_numbers(text: str) -> str:
    """规范化阿拉伯数字"""
    # 阿拉伯-印度数字 -> 西方数字
    arabic_to_western = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
    return text.translate(arabic_to_western)
```

## 🚀 下一步行动

我现在为您实现后处理优化方案。请稍等...
