# CLAUDE.md 模板填写指南

> 引导用户为 AI 编程助手写一份高质量的项目上下文文件。一个写得好的 CLAUDE.md 能让 AI 回答准确率从 60% 提到 90%+。

## 文件位置

- **Claude Code** → 项目根目录的 CLAUDE.md
- **Cursor** → 项目根目录的 .cursorrules
- **Continue** → 项目根目录的 .continuerc.json
- **通用** → AGENTS.md（被多个工具识别）

## 必含字段

### 1. 项目概况（一段话）

```markdown
## 项目概况

- **项目类型**：Flask 后台管理系统
- **架构**：Blueprint 分区 + blueprints/ 目录按业务模块划分
- **数据库**：SQLite（开发）/ MySQL（生产），通过 DB_PATH env 切换
- **测试**：pytest，目标覆盖率 90%+
- **Python**：3.11+
```

### 2. 工程约定（按节写，每节 3-5 条）

```markdown
## 工程约定（Claude 必须遵守）

### 1. 代码风格
- 用 `ruff check .` 做 lint，所有代码必须 `All checks passed` 才能提交
- 单行不超过 100 字符
- import 排序由 ruff 自动处理，不要手动调整
- 类用 `class Foo:` 不用 `class Foo(object):`
- 时间用 `datetime.UTC` 不用 `datetime.timezone.utc`

### 2. 模块组织模式
<按你的实际架构写，例如 Blueprint 分区、MVC、模块化目录等>

### 3. 配置分场景
<Dev/Test/Prod 三套配置的约定，SECRET_KEY 缺失如何处理>

### 4. 安全规范
<密码哈希算法、用户输入校验规则、SQL 参数化要求>

### 5. 测试规范
<测试文件位置、命名、覆盖率门槛、conftest 陷阱避免>

### 6. Commit 规范
<Conventional Commits、type/scope 白名单>

### 7. 日志
<用 logger 不用 print、按天切、异常路径只回友好消息>
```

### 3. 当前进度（让 AI 知道项目处于什么阶段）

```markdown
## 当前进度（Claude 需要知道的）

- ✅ 用户认证（scrypt 哈希 + JWT）
- ✅ 用户 CRUD + 多租户数据隔离
- ✅ 日志按天切割 + 异常路径只回友好消息
- 🔲 下一步：[在这里写你当前要做的事]
```

### 4. AI 工作注意事项（关键！这部分决定 AI 行为）

```markdown
## Claude 工作时的注意事项

1. **改代码前先看测试** —— `tests/` 目录反映当前行为契约，不要破坏现有测试
2. **新功能先写测试** —— TDD 节奏，先红后绿
3. **不要静默 fallback** —— 配置缺失、环境变量缺失、DB 连不上，全部抛错
4. **不要写 print** —— 用 `logger`
5. **不要在 routes/handlers 写业务逻辑** —— 业务逻辑放 services/lib
6. **改完跑测试** —— `pytest --cov` 必须全过且覆盖率不下降
```

### 5. 项目专属术语（让 AI 懂你的内部黑话）

```markdown
## 项目专属术语

<写你项目里的表名、模块名、内部黑话。举例：>
- users：用户表，owner_id 字段做数据归属隔离
- order_service：订单业务逻辑层，路由不写业务
- 「工单」：内部指售后问题单，对应表 tickets
```

## 真实案例

参考 `../assets/templates/python-flask/CLAUDE.md` —— 这是一份从持续维护多年的真实 Flask 项目提炼的完整 CLAUDE.md，含所有字段的真实填写示例。

## 反例（不要这样写）

❌ **空泛的 CLAUDE.md**：
```
这是一个 Python 项目，用 Flask 写的。
```
→ AI 不知道你的工程约定，每次回答都要重新猜。

❌ **太长的 CLAUDE.md**（>2000 字）：
→ AI 上下文被占用，回答会变慢且容易遗漏。

❌ **只写"What"不写"Why"**：
```
用 Blueprint 分区。
```
→ AI 不知道为什么这么组织，遇到边界情况会乱拆。

❌ **不复盘更新**：
→ 项目演进后 CLAUDE.md 落后于实际，AI 回答越来越不准。建议每月或大版本后更新一次。
