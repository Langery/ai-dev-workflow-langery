# Rust 工程化约定

> 供 ai-dev-workflow Skill 在检测到 Rust 项目（Cargo.toml）时加载。

## 目录结构约定

```
project/
├── Cargo.toml
├── Cargo.lock
├── clippy.toml
├── rustfmt.toml
├── .pre-commit-config.yaml
├── src/
│   ├── main.rs# 入口，只负责启动与配置
│   ├── lib.rs               # 库入口，供集成测试引用
│   ├── config.rs            # 配置（figment / envy / 自写）
│   ├── error.rs             # 统一错误类型
│   ├── models/              # 领域模型
│   ├── routes/或 handlers/  # HTTP 路由（axum / actix）
│   ├── services/            # 业务逻辑
│   └── db/                  # sqlx / diesel
├── tests/                   # 集成测试（只能访问 lib.rs 的公开 API）
├── benches/                 # 基准测试
└── migrations/
```

**关键规则**：
- main.rs 保持极薄：读配置 → 建状态 → 启动服务 → 无业务逻辑
- 需要被集成测试调用的代码放 lib.rs 的模块树里，main.rs 只调用
- 业务逻辑与 HTTP handler 分离，保证业务逻辑可脱离网络层测试

## 错误处理：禁止 unwrap / expect

Rust 与 Python 最大的工程差异 —— **错误必须显式处理**：

```rust
// src/error.rs
use thiserror::Error;

#[derive(Debug, Error)]
pub enum AppError {
    #[error("数据库错误: {0}")]
    Database(#[from] sqlx::Error),

    #[error("未找到资源: {0}")]
    NotFound(String),

    #[error("参数无效: {0}")]
    InvalidInput(String),

    #[error("未授权")]
    Unauthorized,

    #[error(transparent)]
    Other(#[from] anyhow::Error),
}

impl axum::response::IntoResponse for AppError {
    fn into_response(self) -> axum::response::Response {
        let (status, message) = match &self {
            AppError::NotFound(_) => (StatusCode::NOT_FOUND, self.to_string()),
            AppError::InvalidInput(_) => (StatusCode::BAD_REQUEST, self.to_string()),
            AppError::Unauthorized => (StatusCode::UNAUTHORIZED, "未授权".to_string()),
            _ => (
                StatusCode::INTERNAL_SERVER_ERROR,
                // 生产环境不暴露内部错误细节
                "服务器内部错误".to_string(),
            ),
        };

        (status, Json(ErrorResponse { error: message })).into_response()
    }
}
```

**规则**：
- lib.rs / main.rs 及任何被库代码引用的路径，**禁止 `unwrap()` / `expect()`**（clippy `unwrap_used` 为 deny）
- 单元测试和 main.rs 的确有把握的地方可以用 `expect()`，`unwrap()` 一律不用
- 生产路径的错误必须落到 `AppError`，用 `?` 传播，不允许 panic

## lib.rs / main.rs 分离

```rust
// src/lib.rs
pub mod config;
pub mod error;
pub mod models;
pub mod routes;
pub mod services;

pub use config::Config;
pub use error::AppError;
```

```rust
// src/main.rs
use myapp::{Config, run};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // 配置缺失直接退出，不使用默认值兜底
    let config = Config::from_env()?;
    run(config).await?;
    Ok(())
}
```

好处：集成测试（`tests/` 目录）通过 `myapp::` 命名空间访问内部逻辑，无需启动整个服务。

## Cargo.toml 要点

```toml
[package]
name = "myapp"
version = "0.1.0"
edition = "2021"
rust-version = "1.75"

[dependencies]
tokio = { version = "1", features = ["full"] }
axum = "0.7"
sqlx = { version = "0.7", features = ["runtime-tokio", "postgres", "macros"] }
serde = { version = "1", features = ["derive"] }
thiserror = "1"
tracing = "0.1"
tracing-subscriber = "0.3"

[dev-dependencies]
cargo-llvm-cov = "0.6"

[profile.release]
lto = true                # 链接时优化
codegen-units = 1         # 单编译单元，更好的优化
panic = "abort"            # release 下中止而非 unwind，减小体积
strip = true
```

**规则**：`panic = "abort"` 与测试冲突，因此 Cargo 默认在 `test` profile 下覆盖。生产镜像体积敏感时开启。

## 日志：用 tracing，不要 println!

```rust
use tracing::{info, warn, error, instrument};

#[tracing::instrument(skip(self, password))]
pub async fn login(&self, username: &str, password: &str) -> Result<User, AppError> {
    info!(username = %username, "开始登录");

    match self.verify(username, password).await {
        Ok(user) => {
            //密码绝不能进日志，即使 debug 级别
            info!(user_id = user.id, "登录成功");
            Ok(user)
        }
        Err(e) => {
            warn!(username = %username, error = %e, "登录失败");
            Err(e)
        }
    }
}
```

`#[instrument]` 的 `skip` 是关键 —— **默认会记录所有参数，包括密码字段**，必须显式 skip 敏感数据。

## 测试与覆盖率

```rust
// src/services/user.rs 中的单元测试
#[cfg(test)]
mod tests {
    use super::*;
    use mockall::mock;

    mock! {
        pub UserRepo {}
        impl UserRepo for UserRepo {
            async fn find_by_name(&self, name: &str) -> Result<Option<User>, sqlx::Error>;
        }
    }

    #[tokio::test]
    async fn test_login_invalid_password() {
        let mut repo = MockUserRepo::new();
        repo.expect_find_by_name()
            .returning(|_| Ok(Some(User::test_user())));

        let service = UserService::new(repo);
        let result = service.login("alice", "wrong-password").await;

        assert!(matches!(result, Err(AppError::Unauthorized)));
    }
}
```

**覆盖率命令**：

```bash
cargo llvm-cov --workspace --all-features --html
```

`#[tokio::test]` 用于异步测试，普通 `#[test]` 不能调 async fn。

## Clippy 配置

```toml
# clippy.toml
msrv = "1.75"
```

关键 lint 设置（放在 main.rs 顶部或 lib.rs）：

```rust
#![warn(clippy::unwrap_used, clippy::expect_used)]
#![warn(clippy::todo, clippy::dbg_macro, clippy::print_stdout)]
```

**对 AI 生成代码尤其重要**：`clippy::dbg_macro` 会拦住 AI 遗留的 `dbg!()` 调试代码，`print_stdout` 会拦住 `println!` 混进业务代码。

## AI 辅助开发注意事项

1. **绝不 `unwrap()`** —— 用 `?` + `AppError`
2. **配置缺失直接 `?` 返回错误**，不要 `unwrap_or_default()`
3. **不用 `println!`** —— 统一 `tracing`，级别要显式指定
4. **`#[instrument]` 必须 `skip` 敏感字段** —— 密码、token绝不能进日志
5. **业务逻辑放 lib.rs 模块树**，保持可测试
6. **改动后跑 `cargo clippy -- -D warnings`** —— 警告当错误处理
7. **改完跑 `cargo test`** —— 覆盖率目标 ≥ 80%（Rust 生态惯例低于 Python）