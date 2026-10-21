# Python Flask 工程化约定

> 供 ai-dev-workflow Skill 在检测到 Python + Flask 项目时加载。
> 本文件是 Flask 项目的工程化基线，所有配置均在一个持续维护多年的真实 Flask 项目中经过生产环境验证。

## 目录结构约定

Flask 项目采用**应用工厂 + 蓝图模块化**，不使用全局 Flask 实例：

```
project/
├── app/
│   ├── __init__.py          # create_app() 工厂函数
│   ├── config.py            # 配置类，按场景继承
│   ├── extensions.py        # 扩展实例化（db、migrate 等）
│   ├── models/              # 数据模型
│   ├── blueprints/          # 业务蓝图
│   │   ├── auth/
│   │   │   ├── __init__.py
│   │   │   ├── routes.py
│   │   │   └── service.py   # 业务逻辑与路由分离
│   │   └── ...
│   ├── services/            # 跨蓝图共享的业务逻辑
│   ├── utils/               # 工具函数
│   └── errors/              # 统一错误处理
├── tests/
│   ├── conftest.py          # pytest fixtures
│   ├── unit/
│   └── integration/
├── migrations/              # alembic
├── .env
├── .env.example
├── pyproject.toml
├── .pre-commit-config.yaml
└── CLAUDE.md
```

**关键规则**：
- 路由只做「解析请求 → 调 service → 返回响应」，业务逻辑一律放 service.py
- 模型定义不放路由文件里
- 跨蓝图复用的逻辑放 `app/services/`，不要跨蓝图直接 import

## 配置分场景（生产级硬要求）

config.py 按场景继承，**敏感配置缺失时直接启动失败**，不允许静默fallback：

```python
import os
from datetime import timedelta


class BaseConfig:
    """所有场景共用的配置"""
    SECRET_KEY = os.environ.get('SECRET_KEY')
    JSON_SORT_KEYS = False

    # 分页默认值，避免每个 view 重复写
    PAGE_SIZE_DEFAULT = 20
    PAGE_SIZE_MAX = 100

    # 会话配置
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('DEV_DATABASE_URL', 'sqlite:///dev.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TESTING = False


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'  # 测试用内存库
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'test-secret-key-not-used-in-prod'


class ProductionConfig(BaseConfig):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')

    # 生产必须显式注入 SECRET_KEY，缺失则拒绝启动
    if not SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY 必须通过环境变量注入，生产环境不接受默认值"
        )

    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,      # 避免使用已断开的连接
        'pool_recycle': 3600,
        'pool_size': 10,
        'max_overflow': 20,
    }
    SESSION_COOKIE_SECURE = True    # 生产只走 HTTPS
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'


config_map = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
}


def get_config(env=None):
    env = env or os.environ.get('FLASK_ENV', 'development')
    return config_map[env]
```

**这条规则为什么重要**：AI 辅助开发时最容易犯的错就是「为了跑通先写个默认值」。生产配置静默 fallback 是重大安全隐患 —— 上线后 SECRET_KEY 用的是硬编码默认值，所有 session 都可以被伪造。

## 应用工厂

```python
# app/__init__.py
from flask import Flask


def create_app(config_name=None):
    app = Flask(__name__)

    # 显式导入配置，避免 from app import config 造成循环引用
    from app.config import get_config
    app.config.from_object(get_config(config_name))

    # 显式导入扩展实例
    from app.extensions import db, migrate, cors

    db.init_app(app)
    migrate.init_app(app, db)
    cors.init_app(app, resources={r"/api/*": {"origins": app.config['CORS_ORIGINS']}})

    # 注册蓝图
    from app.blueprints.auth import auth_bp
    from app.blueprints.user import user_bp
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(user_bp, url_prefix='/api/user')

    # 注册统一错误处理
    from app.errors import register_error_handlers
    register_error_handlers(app)

    return app
```

**规则**：`create_app()` 是唯一入口，run.py 或 wsgi 入口只调用工厂，不做任何额外配置。

## 统一错误处理

```python
# app/errors/__init__.py
from flask import jsonify
from werkzeug.exceptions import HTTPException


class APIError(Exception):
    def __init__(self, message, status_code=400, code=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code or status_code


def register_error_handlers(app):
    @app.errorhandler(APIError)
    def handle_api_error(e):
        return jsonify({'error': e.message, 'code': e.code}), e.status_code

    @app.errorhandler(HTTPException)
    def handle_http_error(e):
        return jsonify({'error': e.description, 'code': e.code}), e.code

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        app.logger.exception('未捕获异常: %s', e)
        # 生产环境不返回堆栈，避免信息泄露
        return jsonify({'error': '服务器内部错误', 'code': 500}), 500
```

## 测试约定

- 所有业务逻辑必须有测试，**目标覆盖率 ≥ 90%**
- 路由测试用 `app.test_client()`
- 涉及数据库的测试用 pytest fixtures + 事务回滚，不要手动清库

```python
# tests/conftest.py
import pytest
from app import create_app
from app.extensions import db


@pytest.fixture
def app():
    """每个测试函数独立的 app + 数据库，避免状态污染"""
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
```

**踩坑警告（真实案例）**：在 conftest.py 中把 `db.session` 或 engine 做成**模块级单例缓存**，会导致多个测试文件共享连接、事务互相污染，表现为「单独跑某个测试通过，全量跑就挂」。正确做法是 fixture 级别隔离。

## pyproject.toml 要点

```toml
[project]
requires-python = ">=3.10"
dependencies = ["flask>=3.0"]

[tool.ruff]
line-length = 88
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "S", "C4"]
ignore = ["E501"]  # 行宽由 formatter 管

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S101"]  # 测试里允许 assert

[tool.pytest.ini_options]
addopts = "--cov=app --cov-report=term-missing --cov-fail-under=90"
testpaths = ["tests"]
```

**安全规则（S 系列）**：`S101` 在测试文件放行，业务代码里所有 `assert` 都应改成抛异常。`S105`/`S106`（硬编码密码/token）必须触发，这是 AI 写代码时的高频问题。

## AI 辅助开发注意事项

写 Flask 代码时让 AI 特别注意：

1. **不要在模块级创建 app 实例** —— 必须走工厂函数，否则测试无法隔离
2. **不要 `from app import db` 后直接用** —— 在工厂函数内 `init_app`
3. **业务逻辑不写在路由里** —— 保证可测试
4. **不静默 fallback** —— 配置缺失就 RuntimeError，不要 `os.environ.get('X', 'default')` 兜底
5. **不要用 `print` 替代日志** —— 统一走 app.logger
6. **改完跑测试** —— `pytest` 必须全绿再提交
7. **新接口同步写测试** —— 覆盖率门槛会拦住你