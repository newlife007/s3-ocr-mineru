# 阿拉伯语文本方向修复说明

## 问题描述

阿拉伯语是从右到左（RTL）书写的语言。在 OCR 识别过程中，可能会出现以下情况：
- 有些文本识别结果与原文一致（正确的视觉顺序）
- 有些文本的单词顺序是反的（逻辑顺序）

这是因为 OCR 引擎输出的文本可能是：
1. **逻辑顺序（存储顺序）**：字符按照内存中的存储顺序排列
2. **视觉顺序（显示顺序）**：字符按照在页面上的显示顺序排列

## 解决方案

我们提供了三种阿拉伯语文本处理模式，可以通过配置文件 `config.yaml` 中的 `arabic_bidi_fix` 参数来控制：

### 1. auto 模式（推荐，默认）

```yaml
arabic_bidi_fix: "auto"
```

**适用场景**：大多数情况，特别是识别结果中有些文本正确、有些反了的情况

**工作原理**：
- 自动检测文本中的阿拉伯语字符
- 使用 python-bidi 库的 BiDi 算法处理文本
- 将逻辑顺序转换为视觉顺序

**优点**：
- 智能处理，适合大多数场景
- 自动应用标准的 Unicode BiDi 算法

### 2. always 模式

```yaml
arabic_bidi_fix: "always"
```

**适用场景**：所有识别结果都是反的（逻辑顺序）

**工作原理**：
- 强制对所有包含阿拉伯语的文本行应用 BiDi 转换
- 不做任何智能判断

**优点**：
- 确保所有文本都经过转换
- 适合 OCR 引擎总是输出逻辑顺序的情况

**注意**：如果原文本已经是正确顺序，使用此模式会将其反转

### 3. never 模式

```yaml
arabic_bidi_fix: "never"
```

**适用场景**：所有识别结果都是正确的（视觉顺序）

**工作原理**：
- 完全不处理文本
- 直接使用 OCR 引擎的原始输出

**优点**：
- 保持原始输出，不做任何修改
- 适合 OCR 引擎已经正确处理了文本方向的情况

## 配置示例

在 `config.yaml` 中配置：

```yaml
# OCR 识别语言设置为阿拉伯语
mineru_lang: "arabic"

# 选择文本方向修复模式
arabic_bidi_fix: "auto"  # 可选值：auto, always, never
```

## 如何选择模式

### 步骤 1：使用默认的 auto 模式测试

```yaml
arabic_bidi_fix: "auto"
```

处理一些样本文件，检查结果。

### 步骤 2：根据结果调整

| 识别结果 | 推荐模式 |
|---------|---------|
| 大部分文本正确，少数反了 | `auto` |
| 所有文本都是反的 | `always` |
| 所有文本都是正确的 | `never` |
| 结果不一致，难以判断 | 先试 `auto`，不行再试 `always` |

### 步骤 3：重启服务应用配置

修改配置后，需要重启服务：

```bash
# 停止服务
pkill -f "uvicorn.*api_server"

# 启动服务
cd /home/ubuntu/s3-ocr-mineru
nohup bash run.sh > service.log 2>&1 &
```

## 技术细节

### BiDi 算法

我们使用 `python-bidi` 库实现 Unicode BiDi（双向文本）算法：

```python
from bidi.algorithm import get_display

# 将逻辑顺序转换为视觉顺序
visual_text = get_display(logical_text)
```

### 字符检测

阿拉伯语字符范围：
- U+0600 - U+06FF：阿拉伯语基本字符
- U+0750 - U+077F：阿拉伯语补充字符
- U+08A0 - U+08FF：阿拉伯语扩展-A
- U+FB50 - U+FDFF：阿拉伯语表现形式-A
- U+FE70 - U+FEFF：阿拉伯语表现形式-B

## 依赖

确保已安装 `python-bidi` 库（已包含在 `requirements.txt` 中）：

```bash
pip install python-bidi>=0.6.0
```

## 故障排除

### 问题：修改配置后没有生效

**解决方案**：确保重启了服务

```bash
pkill -f "uvicorn.*api_server"
cd /home/ubuntu/s3-ocr-mineru
nohup bash run.sh > service.log 2>&1 &
```

### 问题：文本还是反的

**解决方案**：尝试不同的模式

1. 如果使用 `auto` 模式文本还是反的，尝试 `always` 模式
2. 如果使用 `always` 模式文本变得更乱，尝试 `never` 模式

### 问题：部分文本正确，部分反了

**解决方案**：这可能是 OCR 引擎本身的问题

1. 保持使用 `auto` 模式（这是最佳选择）
2. 考虑调整 OCR 引擎的参数（如果可能）
3. 对于特别重要的文档，可能需要人工校对

## 环境变量配置

除了配置文件，也可以通过环境变量设置：

```bash
export ARABIC_BIDI_FIX="auto"  # 或 "always" 或 "never"
```

环境变量的优先级低于配置文件。

## 更新日志

- **2026-05-23**：添加阿拉伯语文本方向修复功能，支持三种模式（auto, always, never）
