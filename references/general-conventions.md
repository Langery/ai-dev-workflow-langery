# 通用工程化约定（语言无关）

> 本文件是 AI 辅助开发的工程化方法论，适用于任何语言/框架。具体语言的细节见对应的 `references/<language>-*.md`。

## 一、Commit 规范（Conventional Commits）

### Type 白名单

```
feat      新功能
fix       bug 修复
docs      文档
style     格式（不影响代码逻辑）
refactor  重构（既不是 feat 也不是 fix）
test      测试
chore     构建/依赖/配置
perf      性能优化
ci        CI 配置
```

### Scope 白名单（按项目模块划分）

每个项目应维护自己的 scope 白名单，写在 `.gitmessage` 注释里。例如按 Flask 分层的项目：
`blueprint / routes / service / model / schema / auth / config / db / test / ci`

### Subject 规则

- 祈使句，首字母小写（中文则直接动词开头）
- 不超过 50 字符
- 不加句号
- 一眼能看懂改了什么

### Body 规则

- 用 `-` 开头列要点
- 解释「**为什么改**」，不是「改了什么」（diff 已经能看出 what）
- 写清楚动机、权衡、踩过的坑
- 每行不超过 72 字符

### Footer 规则

- `BREAKING CHANGE: <描述>` —— 标记破坏性变更
- `Closes #<issue 编号>` —— 关闭 issue
- `Co-Authored-By: Claude <noreply@anthropic.com>` —— AI 辅助的 commit 加这行

### 工具链

- 用 `commitizen` 的 `git cz` 替代 `git commit`（交互式选 type/scope/subject）
- 在 pyproject.toml 的 `[tool.commitizen]` section 定义 type 和 scope 白名单
- 设 `git config --local commit.template .gitmessage` 让 `git commit` 也走模板

## 二、测试覆盖率方法论

### 目标

- **CI 门槛 85%**：低于此值拒绝合并（`pytest --cov-fail-under=85`）
- **目标 90%+**：新模块应达到此基线
- **不要追 100%**：过度 mock 让测试脆弱，边际收益递减

### 必覆盖的路径

每个 endpoint / 函数至少覆盖：

1. **成功路径**（happy path）—— 正常输入，期望输出
2. **错误路径** —— 参数缺失、权限不足、资源不存在、外部依赖失败
3. **边界情况** —— 空数据、超长字符串、特殊字符、并发请求

### 测试隔离

- 用 `tmp_path`（pytest）或 `tmpdir`（jest）做测试隔离，**每个 test 独立目录**
- **不要在文件顶部 import db helpers** —— conftest 会清模块缓存，顶部 import 拿到旧引用。**每个 test 函数内重新 import**
- 用 monkeypatch（pytest）或 vi.mock（vitest）替换外部依赖（时间、随机数、网络请求）

### 数据驱动

- 用 `@pytest.mark.parametrize`（pytest）或 it.each（jest）跑多组数据
- 不要写 5 个雷同的 test，用 parametrize 合并

### 速度

- 单个测试 < 1s
- 慢测试用 `@pytest.mark.slow` 标记，CI 可选跳过 `-m "not slow"`
- 测试总时长 < 30s（不然开发者会跳过跑测试）

## 三、Code Review 五维度

### 1. 静态规范（lint 工具能查的）

- import 排序
- 未使用变量
- 行长超限
- 类定义现代化
- 时间 API 现代化（如 Python 用 datetime.UTC 不用 datetime.timezone.utc）

### 2. 工程约定

- 是否符合模块分区（routes 不写业务逻辑，业务逻辑放 services）
- 返回格式是否统一
- 异常处理是否只回友好消息 + 日志记 traceback
- 配置是否走工厂函数，没有直接读 env
- 日志是否用 logger，没有 print

### 3. 安全性

- 密码是否哈希存储（绝不明文）
- SECRET_KEY 是否从 env 读，是否有静默 fallback
- 用户输入是否校验
- SQL 是否参数化（不用字符串拼接）
- 文件上传是否校验类型和大小
- 是否有 username enumeration 风险

### 4. 健壮性

- 边界情况处理（空数据、超长、特殊字符）
- 错误路径是否会导致部分写入（事务）
- 并发风险（共享状态、文件锁）
- 资源泄漏（连接、文件句柄）

### 5. 可维护性

- 命名是否清晰
- 函数长度是否合理（>50 行考虑拆）
- 重复代码（可抽函数）
- 注释是否解释 Why 不是 What

### Review 输出格式

按维度列出问题：
- 🔴 必改（阻塞合并）：行号 + 问题 + 修复建议
- 🟡 建议改（不阻塞）：行号 + 改进点 + 收益
- 🟢 可保持：好的实践（一句话肯定即可）

最后给一个总体评分（10 分制）和合并建议。

## 四、Pre-commit 钩子

### 必装钩子

1. **lint 工具** —— ruff（Python）/ eslint（Node）/ golangci-lint（Go）
2. **format 工具** —— ruff format / prettier / gofmt
3. **基础检查**：
   - `trailing-whitespace` 去行尾空格
   - `end-of-file-fixer` 文件末尾加换行
   - `check-yaml` / `check-toml` / `check-json` 配置文件语法
   - `check-merge-conflict` 合并冲突标记
   - `check-added-large-files` 阻止大文件提交（maxkb=500）
   - `detect-private-key` 检测私钥泄露

### pytest 钩子的速度取舍

- **commit 阶段**：只跑 lint + 基础检查（<5s），太慢会让人跳过
- **push 阶段**：跑 pytest + coverage（push 频率低，能容忍 30s）
- 配置：`stages: [push]` 让 pytest 钩子只在 push 触发

## 五、AI 上下文文件（CLAUDE.md / .cursorrules / AGENTS.md）

### 作用

让 AI 编程助手（Claude Code / Cursor / Continue 等）每次回答时按你的工程约定来。一个写得好的 CLAUDE.md 能让 AI 回答准确率从 60% 提到 90%+。

### 必含字段

1. **项目概况**：类型、架构、数据库、语言版本
2. **工程约定**：代码风格、模块组织模式、配置分场景、安全规范、测试规范、commit 规范、日志
3. **当前进度**：已完成的功能模块（✅）、下一步要做什么（🔲）
4. **AI 工作注意事项**：改代码前先看测试、不要静默 fallback、不要写 print、改完跑测试等
5. **项目专属术语**：表名、模块名、内部黑话

### 通用 AI 工作注意事项

无论什么语言/框架，AI 工作时都应遵守：

1. **改代码前先看测试** —— 测试目录反映当前行为契约，不要破坏现有测试
2. **新功能先写测试** —— TDD 节奏，先红后绿
3. **不要静默 fallback** —— 配置缺失、环境变量缺失、连接失败，全部抛错
4. **不要写 print / console.log** —— 用 logger
5. **不要在 routes / handlers 写业务逻辑** —— 业务逻辑放 services / lib
6. **改完跑测试** —— 全过且覆盖率不下降才能提交

详细填写指南见 `claude-md-template-guide.md`（同目录）。
