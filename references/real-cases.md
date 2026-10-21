# 真实案例

> 本文件是 ai-dev-workflow Skill 所有工程化约定的来源证明。
> 以下案例均来自一个持续维护多年、经过生产环境验证的真实 Flask 项目。案例中的覆盖率数字是该历史项目的当时实测值，不是本 Skill 的承诺。

---

## 案例 1：密码明文 → scrypt 哈希迁移（零停机）

### 问题
项目早期为了赶进度，数据库里用户密码是明文存储。这是定时炸弹。

### 常见的错误做法
最糟的迁移方式：一次性全表转 hash，然后要求所有人重新登录。
——线上直接崩，用户集体投诉。

### 本项目的做法（零停机、双写过渡）

**第一步：加字段，不动老数据**

```python
# models/user.py
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)

    password_hash = db.Column(db.String(128))  # 新字段，初期可空
```

**第二步：登录时惰性迁移（关键）**

```python
# services/auth_service.py
import hashlib
import hmac


def _hash_password(password: str) -> str:
    """使用 scrypt，不存明文、不存盐（盐由库内格式携带）"""
    salt = hashlib.salt  # 示意：实际用 os.urandom(16)
    dk = hashlib.scrypt(
        password.encode('utf-8'),
        salt=salt,
        n=2**14, r=8, p=1,
        dklen=64,
    )
    return f"scrypt$16384$8$1${salt.hex()}${dk.hex()}"


def verify_password(user: User, password: str) -> bool:
    stored = user.password_hash

    if stored is None:
        # 老用户：校验明文后立即升级，不需要用户重新登录
        if hmac.compare_digest(user.password_plain or '', password):
            user.password_hash = _hash_password(password)
            user.password_plain = None  # 立即清除
            db.session.commit()
            return True
        return False

    # 新用户：解析库内格式后校验
    try:
        algo, n, r, p, salt_hex, hash_hex = stored.split('$')
        if algo != 'scrypt':
            raise ValueError(f'未知算法: {algo}')
        dk = hashlib.scrypt(
            password.encode('utf-8'),
            salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p),
            dklen=len(bytes.fromhex(hash_hex)),
        )
        # 定长比较，防时序攻击
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, IndexError):
        return False
```

**第三步：统计迁移进度，再决定是否强制改密**

```sql
-- 定期跑，确认明文用户已清零
SELECT COUNT(*) FROM users WHERE password_hash IS NULL;
```

### 工程约定沉淀

| 约定 | 原因 |
|---|---|
| 哈希串自带算法与参数 | 参数升级时老哈希仍可校验，无需强制全量重置 |
| `hmac.compare_digest` 而非 `==` | 防时序攻击 |
| 迁移必须有中间态| 直接切换 = 线上事故 |
| 定时审计 SQL | 迁移完成的客观依据，不靠感觉 |

---

## 案例 2：配置分场景，生产缺失密钥直接崩溃

### 问题
早期用 `os.environ.get('SECRET_KEY', 'dev-secret')` 这类写法兜底，结果测试环境能跑，上线后忘了配真实密钥，**所有 session 都可以被伪造**。

### 真实事故
开发阶段和生产阶段用的是同一份 `.env`，某次清理环境变量时 SECRET_KEY 消失，应用用默认值启动，没人发现。两周后被安全扫描报出来。

### 修复后的写法

见 `python-flask.md` 的 config.py。核心是这段：

```python
class ProductionConfig(BaseConfig):
    SECRET_KEY = os.environ.get('DATABASE_URL') and os.environ.get('SECRET_KEY')

    if not SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY 必须通过环境变量注入，生产环境不接受默认值"
        )
```

**更好的做法**（FastAPI 版）：用 `pydantic-settings` 的必填字段，从类型层面消除这个风险，见 `python-fastapi.md`。

### 工程约定沉淀

| 约定 | 原因 |
|---|---|
| 敏感配置**不给默认值** | 兜底默认值 = 定时炸弹 |
| 生产配置缺失 → **启动失败** | 快速失败优于静默降级 |
| 明确 `raise RuntimeError`，不用 `assert` | `assert` 在 `python -O` 下会被移除 |
| `.env.example` 入库，`.env` 不入库 | 变量清单可追溯 |
| `SECRET_KEY` 至少 32 字节 | `secrets.token_hex(32)` |

---

## 案例 3：覆盖率 91% → 94.6% 的补测实战

### 背景
项目核心业务逻辑的覆盖率长期停在 91%。差了 6%一直不敢往上走，因为 CI 卡在 94%。

### 补测过程中发现的真实 bug

**现象**：单独跑某个测试文件全绿，跑全量测试随机失败。失败点在数据库连接。

**根因**：conftest.py 里的 engine 被写成了模块级变量：

```python
# ❌ 错误写法：模块级单例，所有测试文件共享
engine = create_engine('sqlite:///test.db')
SessionLocal = sessionmaker(bind=engine)
```

多个测试文件执行时，**事务互相回滚**，导致某个测试读不到另一个测试写入的数据。这个 bug 单独跑永远复现不了。

**修复**：降级为 fixture，让每个测试函数独立：

```python
# ✅ 正确写法
@pytest.fixture
def db_session(app):
    with app.app_context():
        db.create_all()
        yield db.session
        db.session.remove()
        db.drop_all()
```

### 另一个补测难点：边界条件枚举不全

漏掉的分支里有两个是真正有风险的：
- 密码长度恰好等于最小值（边界 off-by-one）
- 验证码在第59 秒和第 61 秒调用（时间边界）

**这两个都没被测出来过**，直到补测才暴露。

### 工程约定沉淀

| 约定 | 原因 |
|---|---|
| 测试基础设施 **fixture 级隔离**，禁止模块级单例 | 随机失败的根因 |
| `pytest` 加 `-p no:randomly` 定位问题 | 先固定顺序复现，再修根因 |
| 边界值必测：min-1 / min / min+1 | off-by-one 的主要来源 |
| 时间相关逻辑**注入时钟**，不用 `datetime.now()` | 测试不可控 |
| CI 卡覆盖率门槛，不卡绝对值 | `fail_under=94`，涨了要主动提 |

---

## 案例 4：Docker + Compose 一键部署

### 问题
每次新同事入职，搭环境要半天。手动部署容易漏步骤。

### 关键决策

| 决策 | 理由 |
|---|---|
| 镜像内跑 **非 root 用户** | 容器逃逸时权限最小化 |
| **多阶段构建** | 最终镜像不含编译工具链 |
| 配置全部走**环境变量注入** | 同一镜像跑 dev/staging/prod |
| 迁移单独一个容器，**不放在启动脚本里** | 避免并发启动时重复迁移 |
| `HEALTHCHECK` 真实探活 | 不是 `curl localhost`，要打业务接口 |

### Dockerfile 要点

```dockerfile
# 多阶段构建
FROM python:3.12-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.12-slim
# 非 root
RUN groupadd -r app && useradd -r -g app app
WORKDIR /app

COPY --from=builder /root/.local /home/app/.local
COPY --chown=app:app . .

USER app
ENV PYTHONPATH=/home/app/.local/lib/python3.12/site-packages

# 真实健康检查
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready')"

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "app.main:create_app()"]
```

### 工程约定沉淀

-镜像内**不写死任何密钥**，全部运行时注入
- `create_app()` 必须能被字符串方式引用（`app.main:create_app()`），这限制了它的实现方式
-迁移与启动分离：`python -m flask db upgrade` 是独立部署步骤
- 健康检查分两级：`/health/live`（进程活着）+ `/health/ready`（依赖可用）

---

## 案例 5：conftest 模块缓存陷阱的完整复现

这是案例 3 里提到的那个 bug，单独展开，因为它足够隐蔽。

### Bug 表现

```
$ pytest tests/test_a.py        # 通过
$ pytest tests/test_b.py        # 通过
$ pytest                        # 随机失败 30%
```

失败信息毫无规律，且换个顺序就好。

### 排查过程

1. `--randomly-seed` 固定随机顺序 → 100% 复现
2. 单独跑失败用例 → 通过（说明不是用例本身的问题）
3. 加 `--setup-show` 看fixture 执行顺序 → 发现 `db_session` 的**清理没执行**
4. 打印 engine id → 发现整个测试进程只有一个 engine 实例

### 根因

```python
# conftest.py —— 模块级初始化，只执行一次
import pytest
from app import create_app
from app.extensions import db

app = create_app('testing')      # ← 全局单例
db.init_app(app)


@pytest.fixture
def client():
    return app.test_client()


@pytest.fixture
def db_session():
    yield db.session
    db.session.rollback()        # 只回滚事务，不重置状态
```

问题在于 `db.session` 是 Flask-SQLAlchemy 的** scoped session**，绑定在 app context 上。多个测试共用一个 app context，事务边界混乱，**一个测试的回滚会把另一个测试的数据也回滚掉**。

### 正确写法

```python
@pytest.fixture
def app():
    """每个测试独立 app + 独立 context"""
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()# 关键：把 session 移出 scope
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    yield db.session
    db.session.rollback()
```

关键区别：
1. **app 是 fixture，不是模块级** —— 每个测试全新实例
2. **每个测试用`with app.app_context()`** —— context 随测试结束自动销毁
3. **`db.session.remove()` 在 teardown** —— 把 session 从 scope 里摘掉，避免污染下一个测试

### 工程约定沉淀

| 约定 | 原因 |
|---|---|
| **禁止在 conftest.py 做模块级 app 实例化** | 随机失败的根源 |
| fixture 层级：app → context → db → client | 每层依赖上一层，teardown 逐层清理 |
| 测试文件之间**绝不能共享状态** | 包括缓存、模块级变量 |
| 用 `pytest -p no:randomly` 定位随机失败 | 先稳定复现 |
| CI 跑全量而非分文件跑 | 否则这个问题永远发现不了 |

---

## 这五个案例说明了什么

这些约定的共同点：

1. **都来自真实踩坑**，不是从文档抄的
2. **每条约定背后都有一个「不这么写会出事」的具体场景**
3. **AI 辅助开发会成倍放大这些坑** —— 因为 AI 倾向于生成「能跑通」的代码，而工程化要求的是「长期不出事」

所以这个 Skill 的价值不在于提供配置模板，在于**把这些「只有踩过坑才知道」的判断固化下来**。