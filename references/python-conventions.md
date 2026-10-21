# Python 工程化约定

> 适用于所有 Python 项目（Flask / FastAPI / 标准库）。框架专属细节见 `python-flask.md` / `python-fastapi.md`（同目录）。
>
> **不提供 Django 参考文档**：Django 项目仍可用本文件的语言无关部分（工具链、测试、commit 规范、类型标注），但本 Skill 没有 Django 专属模板与分层约定，Django 的 ORM / middleware / settings 约定请对照买家项目现状判断。

## 一、工具链

| 工具 | 用途 | 安装 |
|---|---|---|
| ruff | lint + format（替代 flake8 + isort + black + pyupgrade） | `pip install ruff` |
| pytest | 测试框架 | `pip install pytest pytest-cov pytest-mock` |
| commitizen | commit message 交互式工具 | `pip install commitizen` |
| pre-commit | git 钩子框架 | `pip install pre-commit` |

## 二、pyproject.toml 工程化基线

```toml
[project]
name = "your-project"
version = "0.1.0"
requires-python = ">=3.11"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "UP", "N"]
ignore = [
    "E501",  # 行长由 line-length 控制
    "B008",  # Flask 常用 default 参数误报
]

[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["E402", "F401"]  # 标准包 init 模式
"tests/*" = ["E402"]

[tool.pytest.ini_options]
minversion = "7.0"
testpaths = ["tests"]
addopts = ["-v", "--strict-markers", "--tb=short"]

[tool.coverage.run]
source = ["your_package"]
branch = true

[tool.coverage.report]
show_missing = true
precision = 1
fail_under = 85

[tool.commitizen]
name = "cz_conventional_commits"
version = "0.1.0"
tag_format = "v$version"
```

## 三、Python 现代化要点

### 必须使用

- `class Foo:` 不用 `class Foo(object):`（Py3 现代化）
- datetime.UTC 不用 datetime.timezone.utc（Py3.11 新别名）
- `from __future__ import annotations` 推迟注解求值（如需要前向引用）
- pathlib.Path 不用 os.path 处理路径
- `f-string` 不用 `.format()` 或 `%`

### 必须避免

- `print()` —— 用 `logging` 或 `structlog`
- 全局可变状态 —— 用依赖注入
- `except:` 裸捕获 —— 至少 `except Exception:`
- `import *` —— 显式列出 import
- 字符串拼接 SQL —— 用参数化查询

## 四、测试规范

### 文件组织

```
tests/
├── conftest.py              # 全局 fixture
├── test_<module>_<feature>.py  # 按模块+功能组织
└── __init__.py
```

### 命名

- 文件：`test_<被测模块>_<功能>.py`
- 类：`Test<被测对象>`
- 函数：`test_<行为>_<场景>`，例如 `test_get_list_returns_user_owned_items`

### 必备 fixture

- `tmp_path` —— 测试隔离目录
- `monkeypatch` —— 替换外部依赖
- `capsys` —— 捕获 stdout/stderr
- `mocker`（pytest-mock）—— mock 任意对象

### conftest 模块缓存陷阱（重要）

conftest.py 的 `_purge_app_modules()` 会清掉模块缓存。如果测试文件顶部写 `from db import execute`，在 pytest 收集阶段就执行了，拿到的是**旧模块引用**——DB 操作落不到当前 test 的 `tmp_path` DB。

**正确写法**：每个 test 函数内重新 import：

```python
# ❌ 错误：顶部 import
from db import execute

def test_something(tmp_path):
    execute("...")  # 拿到旧引用，操作落不到 tmp_path

# ✅ 正确：函数内 import
def test_something(tmp_path):
    from db import execute  # 每次重新拿最新引用
    execute("...")
```

### 数据驱动

```python
import pytest

@pytest.mark.parametrize("input,expected", [
    ("normal", 200),
    ("empty", 400),
    ("too_long", 400),
    ("special_chars!@#", 400),
])
def test_endpoint(input, expected):
    assert call_endpoint(input).status_code == expected
```

## 五、日志规范

### 配置

```python
import logging
from logging.handlers import TimedRotatingFileHandler

handler = TimedRotatingFileHandler(
    "app.log",
    when="midnight",
    interval=1,
    backupCount=30,  # 保留 30 天
)
handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
))

logger = logging.getLogger(__name__)
```

### 使用

- 业务逻辑用 `logger.info()`
- 警告用 `logger.warning()`
- 异常用 `logger.exception()`（自动带 traceback）
- **绝不 print**

### 异常路径

异常路径**只回友好消息给前端**，日志记完整 traceback：

```python
try:
    do_something()
except (IntegrityError, RuntimeError) as e:
    logger.exception("Failed to do something")
    return {"code": -1, "msg": "操作失败，请稍后重试"}  # 不暴露内部异常
```

## 六、配置分场景

### 三套配置

```python
class DevConfig:
    DEBUG = True
    DB_PATH = "dev.db"

class TestConfig:
    TESTING = True
    DB_PATH = ":memory:"  # 内存 DB 速度快

class ProdConfig:
    DB_PATH = os.environ["DB_PATH"]  # 缺失抛 KeyError，绝不静默 fallback
    SECRET_KEY = os.environ["SECRET_KEY"]  # 缺失直接 RuntimeError
```

### 工厂函数

```python
def get_config():
    env = os.environ.get("APP_ENV", "development").lower()
    if env in ("dev", "development"):
        return DevConfig.as_dict()
    elif env in ("test", "testing"):
        return TestConfig.as_dict()
    elif env in ("prod", "production"):
        if "SECRET_KEY" not in os.environ:
            raise RuntimeError("SECRET_KEY must be set in production")
        return ProdConfig.as_dict()
```

**关键原则**：生产环境缺失关键配置**直接抛错**，绝不静默 fallback 到默认值。
