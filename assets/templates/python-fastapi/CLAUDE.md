# CLAUDE.md

> 这是项目上下文模板。把它放在你的 FastAPI 项目根目录，Claude Code 会自动读取并理解你的工程约定。

## 项目概况

- **项目类型**：FastAPI 异步 API 服务
- **架构**：分层（routers / services / models / schemas）+ 依赖注入
- **数据库**：PostgreSQL（async via SQLAlchemy 2.0 async）
- **测试**：pytest + httpx.AsyncClient，目标覆盖率 90%+
- **Python**：3.11+

## 工程约定（Claude 必须遵守）

### 1. 代码风格

- 用 `ruff check .` 做 lint，所有代码必须 `All checks passed` 才能提交
- 单行不超过 100 字符
- import 排序由 ruff 自动处理，不要手动调整
- 类用 `class Foo:` 不用 `class Foo(object):`（Py3 现代化）
- 时间用 `datetime.UTC` 不用 `datetime.timezone.utc`（Py3.11 新别名）
- 异步函数一律 `async def`，IO 操作必须 `await`，**禁止在异步函数里写同步阻塞调用**

### 2. 目录结构

新增功能模块时，按以下结构组织：

```
app/
├── main.py              # FastAPI 实例 + 中间件 + 路由注册
├── core/
│   ├── config.py        # Pydantic Settings 配置管理
│   ├── security.py      # JWT + 密码哈希
│   └── deps.py          # 依赖注入（DB session / 当前用户）
├── routers/
│   └── <module>.py      # 路由定义，用 APIRouter
├── services/
│   └── <module>.py      # 业务逻辑，不碰 HTTP 层
├── models/
│   └── <module>.py      # SQLAlchemy ORM 模型
├── schemas/
│   └── <module>.py      # Pydantic 请求/响应模型
└── tests/
    └── test_<module>.py
```

- 路由用 `APIRouter(prefix="/api/v1/<module>", tags=["<module>"])`
- 响应统一用 Pydantic schema，**不要返回裸 dict**
- 错误用 `HTTPException` 或自定义异常处理器，返回 `{"detail": "..."}`

### 3. 配置管理

- 用 `pydantic-settings` 的 `BaseSettings`，**所有配置从环境变量读**
- `Settings` 类里定义默认值，生产环境用 `.env` 或真实环境变量
- `SECRET_KEY` / `DATABASE_URL` 无默认值，生产缺失直接抛错，**绝不静默 fallback**
- 测试用 `APP_ENV=testing`，自动切到测试数据库

### 4. 密码与认证

- **绝不明文存密码**。用 `passlib[bcrypt]` 的 `CryptContext`
- JWT 用 `python-jose`，HS256，过期时间从配置读
- 密码不放在 JWT payload 里
- 用户名枚举防御：用户不存在与密码错都返回 `401 Unauthorized`
- 需要认证的路由用 `Depends(get_current_user)` 注入

### 5. 测试规范

- 用 `httpx.AsyncClient` + `ASGITransport` 测试 FastAPI，**不要起真实 uvicorn**
- 测试隔离：每个 test 用独立事务，test 结束自动 rollback
- 每个 endpoint 至少覆盖：成功路径 + 错误路径 + 权限边界
- 异步测试用 `@pytest.mark.asyncio`（asyncio_mode=auto 时可省略）
- 覆盖率低于 85% CI 会 fail

### 6. Commit 规范

- 用 `git cz` 替代 `git commit`（commitizen）
- type 选：`feat / fix / docs / style / refactor / test / chore`
- scope 用模块名：`auth / user / router / model / schema / db`
- AI 辅助的 commit 加 `Co-Authored-By: Claude <noreply@anthropic.com>`

### 7. 数据库迁移

- 用 Alembic 管理 schema 变更
- **不要在代码里 `Base.metadata.create_all()`**（生产环境必须走 migration）
- 每次 schema 变更：`alembic revision --autogenerate -m "描述"` → 检查生成的 migration → `alembic upgrade head`

## 当前进度（Claude 需要知道的）

- ✅ 用户认证（JWT + bcrypt）
- ✅ [在这里写你已完成的功能]
- 🔲 下一步：[在这里写你当前要做的事]

## Claude 工作时的注意事项

1. **改代码前先看测试** —— `tests/` 目录反映当前行为契约
2. **新功能先写测试** —— TDD 节奏，先红后绿
3. **不要静默 fallback** —— 配置缺失、环境变量缺失全部抛错
4. **不要写 print** —— 用 `logging` 或 FastAPI 的 logger
5. **不要在 routers 里写业务逻辑** —— 业务逻辑放 services/
6. **异步函数不要写同步阻塞** —— DB 用 async session，HTTP 用 httpx.AsyncClient
7. **改完跑测试** —— `pytest --cov` 必须全过且覆盖率不下降

## 项目专属术语

- [在这里写你的项目特有表名、模块名、内部黑话]
