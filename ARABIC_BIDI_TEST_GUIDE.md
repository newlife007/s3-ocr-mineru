# 阿拉伯语文本方向修复 - 测试指南

## ✅ 已完成的功能

### 1. 页面UI改进
- ✅ 在文件列表页面添加了"阿语文本修复"下拉选项
- ✅ 该选项只在选择"阿拉伯语（arabic）"时显示
- ✅ 提供三个选项：
  - **自动（auto）** - 默认，应用 BiDi 转换
  - **总是转换（always）** - 强制应用 BiDi 转换
  - **从不转换（never）** - 保持 OCR 原始输出

### 2. 后端支持
- ✅ 数据库已支持 `arabic_bidi_fix` 字段
- ✅ API 接口接受 `arabic_bidi_fix` 参数
- ✅ 每个任务可以单独设置文本方向修复模式
- ✅ 添加了详细的日志记录

### 3. 处理逻辑
- ✅ `never` 模式：完全不处理，返回原始文本
- ✅ `always` 模式：对所有阿拉伯语行应用 BiDi 转换
- ✅ `auto` 模式：目前与 `always` 相同（未来可扩展）

## 🧪 如何测试

### 步骤 1：准备测试文件
准备一个阿拉伯语 PDF 文件用于测试。

### 步骤 2：使用不同模式提交任务

#### 测试 never 模式（不转换）
1. 打开页面：http://服务器IP:8000
2. 切换到"文件列表"标签
3. 选择语言：**阿拉伯语（arabic）**
4. 阿语文本修复：选择 **从不转换（never）**
5. 选择测试文件，点击"提交 OCR 任务"
6. 等待任务完成，查看结果

#### 测试 always 模式（总是转换）
1. 再次选择同一个文件
2. 选择语言：**阿拉伯语（arabic）**
3. 阿语文本修复：选择 **总是转换（always）**
4. 提交任务
5. 等待完成，查看结果

#### 测试 auto 模式（自动）
1. 再次选择同一个文件
2. 选择语言：**阿拉伯语（arabic）**
3. 阿语文本修复：选择 **自动（auto）**
4. 提交任务
5. 等待完成，查看结果

### 步骤 3：对比结果

在"任务列表"中，点击每个任务的"查看"按钮，对比三种模式的输出：

- **never 模式**：应该保持 OCR 引擎的原始输出
- **always 模式**：应该对所有阿拉伯语文本应用 BiDi 转换
- **auto 模式**：目前与 always 相同

### 步骤 4：查看日志

查看服务日志以确认参数被正确传递和使用：

```bash
tail -f /home/ubuntu/s3-ocr-mineru/service.log
```

日志中应该包含类似以下内容：

```
INFO: Running OCR, job_id=xxx, lang=arabic, backend=xxx, arabic_bidi_fix=never
INFO: _fix_arabic_text_direction called with mode=never, text_length=xxx
INFO: Mode is 'never' or text is empty, returning original text
```

或者：

```
INFO: Running OCR, job_id=xxx, lang=arabic, backend=xxx, arabic_bidi_fix=always
INFO: _fix_arabic_text_direction called with mode=always, text_length=xxx
INFO: Arabic characters detected: True
INFO: Applying 'always' mode - will transform all Arabic lines
INFO: Transformed X lines in 'always' mode
```

## 🔍 预期结果

### never 模式
- 文本应该与 OCR 引擎的原始输出完全一致
- 如果原始输出中某些单词是反的，结果中也应该是反的

### always 模式
- 所有阿拉伯语文本都会经过 BiDi 转换
- 如果原始输出是逻辑顺序（反的），转换后应该变成视觉顺序（正的）
- 如果原始输出已经是视觉顺序（正的），转换后可能会变成逻辑顺序（反的）

### auto 模式
- 目前与 always 模式行为相同
- 未来可以添加更智能的检测逻辑

## ❓ 如果三种模式结果都一样

如果您发现三种模式的结果都一样，可能的原因：

### 1. OCR 引擎没有输出阿拉伯语字符
检查日志中是否有：
```
INFO: Arabic characters detected: False
```

如果是这样，说明 OCR 没有识别出阿拉伯语字符，BiDi 转换不会被应用。

### 2. 文本已经是最终形式
如果 OCR 输出的文本已经是正确的视觉顺序，BiDi 转换可能不会改变它。

### 3. 检查日志
查看日志中的 `Transformed X lines` 信息：
- 如果 X = 0，说明没有行被转换
- 如果 X > 0，说明有行被转换了

### 4. 检查原始文本
在 never 模式下，查看原始 OCR 输出，确认：
- 是否包含阿拉伯语字符
- 文本方向是否正确

## 🐛 调试步骤

### 1. 检查参数是否传递
在浏览器开发者工具的 Network 标签中，查看提交任务时的请求：

```json
{
  "file_keys": ["xxx.pdf"],
  "lang": "arabic",
  "arabic_bidi_fix": "never"  // 应该看到这个参数
}
```

### 2. 检查数据库
连接到数据库查看任务记录：

```bash
sqlite3 /home/ubuntu/s3-ocr-mineru/jobs.db
SELECT job_id, file_key, lang, arabic_bidi_fix FROM jobs ORDER BY submitted_at DESC LIMIT 5;
```

### 3. 检查日志级别
确保日志级别设置为 INFO：

```yaml
# config.yaml
log_level: "INFO"
```

### 4. 手动测试 BiDi 转换
创建一个测试脚本：

```python
from bidi.algorithm import get_display

# 测试文本（阿拉伯语）
text = "مرحبا بك"
print(f"Original: {text}")
print(f"After BiDi: {get_display(text)}")
```

## 📊 结果对比示例

假设 OCR 识别出的原始文本是：

```
كلمة1 كلمة2 كلمة3
```

### never 模式输出
```
كلمة1 كلمة2 كلمة3
```
（保持原样）

### always/auto 模式输出
```
3ةملك 2ةملك 1ةملك
```
（应用 BiDi 转换后）

**注意**：实际的转换结果取决于原始文本的编码方式和 Unicode BiDi 算法的处理。

## 📝 报告问题

如果测试中发现问题，请提供以下信息：

1. 使用的模式（never/always/auto）
2. 测试文件的特征（语言、格式等）
3. 服务日志的相关部分
4. 预期结果 vs 实际结果
5. 浏览器开发者工具中的网络请求详情

## 🎯 下一步改进

如果当前的实现不能满足需求，可以考虑：

1. **改进 auto 模式**：添加智能检测逻辑，判断文本是否需要转换
2. **添加更多模式**：如 `reverse`（反转）、`smart`（智能）等
3. **支持混合文本**：更好地处理阿拉伯语和其他语言混合的文本
4. **字符级别控制**：提供更细粒度的控制选项
