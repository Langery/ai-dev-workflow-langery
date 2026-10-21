# Python FastAPI 工程化约定

> 供 ai-dev-workflow Skill 在检测到 Python + FastAPI 项目时加载。

## 目录结构约定

```
project/
├── app/
│   ├── main.py              # FastAPI 实例 + app 创建
│   ├── core/
│   │   ├── config.py        # pydantic-settings 配置
│   │   ├── security.py      # 密码哈希、JWT
│   │   └── logging.py       # 日志配置
│   ├── api/
│   │   ├── deps.py          # 依赖注入（get_db、get_current_user）
│   │   └── v1/
│   │       ├── router.py# v1 路由聚合
│   │       └── endpoints/   # 具体接口
│   ├── models/              # SQLAlchemy 模型
│   ├── schemas/             # Pydantic 模型（请求/响应）
│   ├── services/            # 业务逻辑层
│   └── db/                  # 会话与Base 定义
├── alembic/
├── alembic.ini
├── tests/
├── pyproject.toml
├── .pre-commit-config.yaml
└── CLAUDE.md
```

**分层规则（FastAPI 最容易乱的地方）**：
- `schemas/` 只做数据校验和序列化，**不含业务逻辑**
- `endpoints/` 只做「取参数 → 调 service → 返回」，**不写 SQL**
- `services/` 承载业务逻辑，**允许复用依赖注入**
- SQL 只出现在 `models/` 和 `services/`

## 配置管理（pydantic-settings）

```python
# app/core/config.py
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

    APP_NAME: str = 'FastAPI App'
    DEBUG: bool = False

    # 必填项：不提供默认值，缺失时启动即失败
    SECRET_KEY: str
    DATABASE_URL: str

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    CORS_ORIGINS: list[str] = ['http://localhost:3000']


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
```

**核心规则**：`SECRET_KEY` 和 `DATABASE_URL` **不给默认值**。这是 pydantic-settings 相比 `os.environ.get()` 的最大优势 —— 缺失时直接 `ValidationError`，不可能静默 fallback。

`@lru_cache` 保证只实例化一次，避免每次请求重复读文件。

## 依赖注入模式

这是 FastAPI 的核心，**所有共享资源必须走Depends，不要在函数内部创建**：

```python
# app/api/deps.py
from typing import Annotated, Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

# Annotated 写法（FastAPI 推荐，比老的 Depends() 更清晰）
DbSession = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str, Depends(oauth2_scheme)]


def get_current_user(auth: TokenDep, db: DbSession) -> User:
    """JWT 解码 → 查用户 → 不存在或未激活则 401"""
    from app.core.security import decode_token
    payload = decode_token(auth)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, '凭证无效')

    user = db.get(User, payload.get('sub'))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, '用户不存在或已停用')
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
```

用法：

```python
@router.post('/users', response_model=UserRead)
def create_user(payload: UserCreate, db: DbSession, current_user: CurrentUser):
    """创建用户。需要显式声明依赖，即使业务上用不到 user 也可去掉。"""
    service = UserService(db)
    return service.create(payload)
```

## Pydantic 校验

**Query / Path 参数用 `Query` / `Path` 显式约束，不要裸着写**：

```python
from typing import Annotated
from fastapi import Query, Path


@router.get('/items/{item_id}')
def read_item(
    item_id: Annotated[int, Path(gt=0, description='物品 ID')],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    ...
```

**响应必须声明 `response_model`**，否则数据库对象直接序列化会泄露内部字段：

```python
class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    is_active: bool
    # 注意：password_hash 绝不能出现在这里


class UserCreate(BaseModel):
    username: Annotated[str, Field(min_length=3, max_length=50)]
    email: EmailStr
    # 明文口令，service 层哈希后才入库；字段名用 passphrase 避免与 ORM 的 password_hash 混淆
    passphrase: Annotated[str, Field(min_length=8)]
```

`from_attributes=True` 是从 ORM 对象序列化的必需项，漏了会报 `ValueError`。

## 异常处理

```python
# app/main.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError


class BusinessError(Exception):
    """业务异常基类"""
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code


@app.exception_handler(BusinessError)
async def business_error_handler(request: Request, exc: BusinessError):
    return JSONResponse(
        status_code=exc.status_code,
        content={'error': exc.message},
    )


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    """唯一约束冲突等数据库错误——必须显式处理，不能 500"""
    return JSONResponse(
        status_code=409,
        content={'error': '数据冲突，请检查输入'},
    )
```

## 测试约定

```python
# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def db_session(app) -> Generator[Session, None, None]:
    """事务回滚模式：测完自动回滚，不留脏数据"""
    with app.state.db.session() as session:
        yield session
        session.rollback()
```

**关键**：用 `dependency_overrides` 覆盖鉴权依赖，测试时不需要真实登录：

```python
app.dependency_overrides[get_current_user] = lambda: User(id=1, username='test', is_active=True)
```

## AI 辅助开发注意事项

1. **不要在endpoint 里写 SQL** —— 一律下沉到 `services/`
2. **不要漏 `response_model`** —— 会泄露 password_hash 等敏感字段
3. **Pydantic 模型分Read/Create/Update 三个**，不要复用
4. **配置不给默认值** —— 靠 pydantic-settings 的必填校验，不要手动 `os.getenv(..., 'dev')`
5. **共享依赖用 Depends，不要全局单例** —— 否则测试无法隔离
6. **`AsyncClient` 只在真正用了 async 依赖时用** —— 混用 sync/async 依赖会报运行时错误
7. **改完跑 pytest** —— 覆盖率门槛 ≥ 90%