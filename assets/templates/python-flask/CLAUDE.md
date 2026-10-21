# CLAUDE.md

> 这是项目上下文模板。把它放在你的 Flask 项目根目录，Claude Code 会自动读取并理解你的工程约定。

## 项目概况

- **项目类型**：Flask 后台管理系统
- **架构**：Blueprint 分区 + common/ 公共类
- **数据库**：SQLite（开发）/ MySQL（生产），通过 DB_PATH env 切换
- **测试**：pytest，目标覆盖率 90%+
- **Python**：3.11+

## 工程约定（Claude 必须遵守）

### 1. 代码风格

- 用 `ruff check .` 做 lint，所有代码必须 `All checks passed` 才能提交
- 单行不超过 100 字符（ruff 配置 `line-length = 100`）
- import 排序由 ruff 自动处理，不要手动调整
- 类用 `class Foo:` 不用 `class Foo(object):`（Py3 现代化）
- 时间用 `datetime.UTC` 不用 `datetime.timezone.utc`（Py3.11 新别名）

### 2. Blueprint 模式

新增功能模块时，按以下结构组织：

```
blueprints/
└── <module_name>/
    ├── __init__.py        # Blueprint 实例化 + 注册
    ├── routes.py          # 路由 + 视图函数
    ├── models.py          # 数据模型（如需要）
    └── services.py        # 业务逻辑（如需要）
```

- 所有接口统一 `/api/<module>/<action>` 路径
- 返回统一 `{"code": 0, "data": ..., "msg": ...}` 格式
- 错误返回 `{"code": -1, "data": None, "msg": "..."}`，不暴露内部异常

### 3. 配置分场景

- `DevConfig` / `TestConfig` / `ProdConfig` 三套配置
- `ProdConfig` 缺 `SECRET_KEY` 直接 `RuntimeError`，**绝不静默 fallback**
- 测试用 `APP_ENV=testing`，所有 test 自动走 `TestConfig`
- 用 `get_config()` 工厂函数返回 dict，不靠 class attribute

### 4. 密码与认证

- **绝不明文存密码**。用 `werkzeug.security.generate_password_hash`
- 默认 scrypt 算法，16 字节 salt
- 老明文用户首次登录后自动升级为 hash（零停机迁移）
- 用户名 3-20 位字母/数字/下划线，密码 ≥6 位
- username enumeration 防御：用户不存在与密码错都返回相同消息

### 5. 测试规范

- 测试文件放 `tests/test_<module>_<feature>.py`
- 每个 endpoint 至少覆盖：成功路径 + 错误路径 + 边界情况
- 用 `tmp_path` fixture 做测试隔离，**每个 test 函数内重新 import db helpers**
  （conftest 会清模块缓存，顶部 import 会拿到旧引用）
- 覆盖率低于 85% CI 会 fail（`pytest --cov-fail-under=85`）

### 6. Commit 规范

- 用 `git cz` 替代 `git commit`（commitizen）
- type 选：`feat / fix / docs / style / refactor / test / chore`
- scope 用分层名：`blueprint / routes / service / model / schema / auth / config / db / test / ci`
- AI 辅助的 commit 加 `Co-Authored-By: Claude <noreply@anthropic.com>`

### 7. 日志

- 用 `TimedRotatingFileHandler` 按天切，保留 30 天
- 生产环境可选 JSON 格式
- 异常路径只回友好消息给前端，日志带完整 traceback

## 当前进度（Claude 需要知道的）

- ✅ 用户认证（scrypt 哈希 + JWT）
- ✅ <业务实体> CRUD + owner 隔离
- ✅ <用户偏好> 存储
- ✅ <内容数据> 接口
- ✅ Docker 部署
- ✅ 配置分场景
- ✅ CI（GitHub Actions）
- 🔲 下一步：[在这里写你当前要做的事]

## Claude 工作时的注意事项

1. **改代码前先看测试** —— `tests/` 目录反映当前行为契约，不要破坏现有测试
2. **新功能先写测试** —— TDD 节奏，先红后绿
3. **不要静默 fallback** —— 配置缺失、环境变量缺失、DB 连不上，全部抛错
4. **不要写 print** —— 用 `app.logger`
5. **不要在 routes.py 写业务逻辑** —— 业务逻辑放 services.py
6. **改完跑测试** —— `pytest --cov` 必须全过且覆盖率不下降

## 项目专属术语

> 这一节用于登记「Claude 看代码猜不出来」的项目内黑话，让它别把术语用错。
> 下面三条是**格式示例**，请替换成你自己项目的真实对象名。

- `<主表名>`：核心业务表，含 owner 字段做用户隔离
- `<偏好表名>`：用户偏好表，一行 per user，upsert 语义
- `<日志段前缀>`：commit prefix，按功能模块划分的变更日志段
