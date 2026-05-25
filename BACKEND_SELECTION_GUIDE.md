# MinerU 后端模式选择指南

## ✅ 新功能说明

现在您可以在提交 OCR 任务时，为每个任务单独选择 MinerU 的后端模式，无需修改配置文件或重启服务。

## 🎯 三种后端模式

### 1. pipeline（标准流水线）

**特点**：
- 传统的 OCR 流水线处理
- 稳定可靠，适合大多数场景
- 资源占用适中
- 处理速度较快

**适用场景**：
- 标准格式的文档（PDF、图片）
- 文本清晰、排版规整的文档
- 对识别速度有要求的场景
- 资源有限的环境

**推荐用于**：
- 普通的文本文档
- 扫描质量较好的文件
- 批量处理任务

### 2. vlm-auto-engine（VLM 自动引擎）

**特点**：
- 基于视觉语言模型（Vision-Language Model）
- 更强的理解能力
- 可以处理复杂布局和混合内容
- 资源占用较高
- 处理速度较慢

**适用场景**：
- 复杂排版的文档
- 包含表格、图表的文档
- 多语言混合的文档
- 需要更高识别准确度的场景

**推荐用于**：
- 学术论文
- 技术文档
- 复杂的商业报告
- 包含大量图表的文档

**注意**：
- 需要更多的 GPU 内存
- 处理时间会更长
- 可能需要额外的依赖包

### 3. hybrid-auto-engine（混合自动引擎）

**特点**：
- 结合传统 OCR 和 VLM 的优势
- 自动选择最佳处理方式
- 平衡准确度和速度
- 智能适应不同类型的文档

**适用场景**：
- 文档类型多样的批量任务
- 不确定文档复杂度的场景
- 需要平衡速度和准确度
- 混合内容的文档

**推荐用于**：
- 混合类型的文档集合
- 不确定最佳模式的情况
- 需要自动优化的场景

## 📋 如何使用

### 在页面上选择

1. 打开 OCR 管理平台：http://服务器IP:8000
2. 切换到"文件列表"标签
3. 选择要处理的文件
4. 在提交按钮旁边找到"后端模式"下拉框
5. 选择以下选项之一：
   - **标准流水线（pipeline）**
   - **VLM自动引擎（vlm-auto-engine）**
   - **混合自动引擎（hybrid-auto-engine）**
6. 点击"提交 OCR 任务"

### 默认值

如果不选择，系统会使用 `config.yaml` 中配置的默认值：

```yaml
# config.yaml
mineru_backend: "hybrid-auto-engine"  # 默认值
```

### 每个任务独立设置

- 每个任务可以使用不同的后端模式
- 任务提交后，模式会保存在数据库中
- 可以在任务列表中查看每个任务使用的模式

## 🧪 测试建议

### 对比测试

使用同一个文件，分别用三种模式提交任务，对比结果：

1. **测试 pipeline 模式**
   - 选择后端：标准流水线（pipeline）
   - 提交任务
   - 记录处理时间和识别质量

2. **测试 vlm-auto-engine 模式**
   - 选择后端：VLM自动引擎（vlm-auto-engine）
   - 提交任务
   - 对比处理时间和识别质量

3. **测试 hybrid-auto-engine 模式**
   - 选择后端：混合自动引擎（hybrid-auto-engine）
   - 提交任务
   - 对比处理时间和识别质量

### 评估标准

- **识别准确度**：文字识别的正确率
- **处理速度**：完成时间
- **资源占用**：CPU/GPU/内存使用情况
- **特殊内容处理**：表格、公式、图表的识别效果

## 📊 性能对比参考

| 模式 | 速度 | 准确度 | 资源占用 | 复杂文档 |
|------|------|--------|----------|----------|
| pipeline | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ |
| vlm-auto-engine | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| hybrid-auto-engine | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |

**注意**：实际性能取决于文档类型、硬件配置和具体内容。

## 🔍 查看任务使用的模式

在任务列表中，可以通过以下方式查看：

1. 查看服务日志：
   ```bash
   tail -f /home/ubuntu/s3-ocr-mineru/service.log
   ```
   
   日志中会显示：
   ```
   INFO: Running OCR, job_id=xxx, lang=arabic, backend=pipeline, arabic_bidi_fix=auto
   ```

2. 查询数据库：
   ```bash
   sqlite3 /home/ubuntu/s3-ocr-mineru/jobs.db
   SELECT job_id, file_key, lang, backend, status FROM jobs ORDER BY submitted_at DESC LIMIT 10;
   ```

## 💡 选择建议

### 快速决策树

```
开始
  ↓
文档是否复杂？（包含表格、图表、复杂排版）
  ├─ 是 → 使用 vlm-auto-engine
  └─ 否 → 继续
      ↓
    是否需要快速处理？
      ├─ 是 → 使用 pipeline
      └─ 否 → 使用 hybrid-auto-engine（推荐）
```

### 具体场景推荐

| 文档类型 | 推荐模式 | 原因 |
|---------|---------|------|
| 普通文本 PDF | pipeline | 速度快，准确度足够 |
| 扫描件 | hybrid-auto-engine | 平衡质量和速度 |
| 学术论文 | vlm-auto-engine | 复杂公式和图表 |
| 商业报告 | hybrid-auto-engine | 混合内容 |
| 技术文档 | vlm-auto-engine | 代码块和图表 |
| 简单图片 | pipeline | 快速处理 |
| 阿拉伯语文档 | hybrid-auto-engine | 更好的 RTL 支持 |
| 混合语言 | vlm-auto-engine | 更强的理解能力 |

## ⚠️ 注意事项

### vlm-auto-engine 模式

1. **资源需求**：
   - 需要更多 GPU 内存（建议 8GB+）
   - CPU 和内存占用也会增加
   - 可能需要安装额外依赖

2. **处理时间**：
   - 比 pipeline 慢 3-5 倍
   - 适合小批量、高质量要求的任务

3. **依赖检查**：
   如果遇到错误，可能需要安装额外依赖：
   ```bash
   pip install transformers torch torchvision
   ```

### 并发限制

- 系统使用串行队列处理任务（避免 GPU 资源竞争）
- 同一时刻只有一个任务在运行
- 使用 vlm-auto-engine 时，后续任务等待时间会更长

## 🐛 故障排除

### 问题：vlm-auto-engine 模式失败

**可能原因**：
- GPU 内存不足
- 缺少依赖包
- 模型文件未下载

**解决方案**：
1. 检查 GPU 内存：`nvidia-smi`
2. 安装依赖：`pip install transformers torch`
3. 切换到其他模式

### 问题：处理速度很慢

**可能原因**：
- 使用了 vlm-auto-engine 模式
- 文档很大或很复杂
- 系统资源不足

**解决方案**：
1. 对于简单文档，使用 pipeline 模式
2. 检查系统资源使用情况
3. 考虑分批处理

### 问题：识别质量不理想

**可能原因**：
- 使用了 pipeline 模式处理复杂文档
- 文档质量较差
- 语言设置不正确

**解决方案**：
1. 尝试 vlm-auto-engine 或 hybrid-auto-engine
2. 确认语言设置正确
3. 检查原始文档质量

## 📝 配置文件说明

在 `config.yaml` 中可以设置默认后端：

```yaml
# MinerU 后端模式
# pipeline - 标准流水线模式（快速，适合简单文档）
# vlm-auto-engine - VLM 自动引擎（高质量，适合复杂文档）
# hybrid-auto-engine - 混合自动引擎（平衡，推荐）
mineru_backend: "hybrid-auto-engine"
```

页面上的选择会覆盖这个默认值。

## 🚀 最佳实践

1. **首次使用**：先用 hybrid-auto-engine 测试
2. **批量处理**：根据文档类型选择合适的模式
3. **质量优先**：使用 vlm-auto-engine
4. **速度优先**：使用 pipeline
5. **不确定时**：使用 hybrid-auto-engine

## 📚 更多信息

- MinerU 官方文档：https://github.com/opendatalab/MinerU
- 后端模式详细说明：查看 MinerU 文档中的 Backend 部分
