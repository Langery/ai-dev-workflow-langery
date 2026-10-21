# CLAUDE.md

> 项目上下文文件模板（Rust 版）。复制到项目根目录后，把 {占位符} 替换为实际内容，删掉本行提示。

## 项目概况

- **类型**：{命令行工具 / axum Web 服务 / actix Web 服务 / 库}
- **架构**：{一句话描述模块组织，如"lib.rs 承载业务，main.rs 只做启动"}
- **数据库**：{PostgreSQL(sqlx) / SQLite(diesel) / 无}
- **Rust 版本**：{edition 2021 / 2024，stable / nightly}

## 工程约定

### 代码风格

- rustfmt 强制执行（rustfmt.toml 已配置），提交前 `cargo fmt`
- clippy 规则全开（clippy.toml + pre-commit 钩子），`-D warnings` 不许带病提交
- 命名：类型和 trait 用 UpperCamelCase，函数和变量 snake_case，常量 SCREAMING_SNAKE_CASE

### 模块组织

- `main.rs` 保持极薄：读配置 → 建状态 → 启动服务，**不写业务逻辑**
- 需要被集成测试（tests/）调用的代码全部放 `lib.rs` 的模块树
- 业务逻辑与 HTTP handler 分离：`handlers/` 只做参数解析和响应组装，逻辑在 `services/`
- 统一错误类型 `src/error.rs`（thiserror），handler 返回 `impl IntoResponse` 的 AppError

### 安全规范

- **禁止 `unwrap()` / `expect()`** 出现在非测试代码（clippy.unwrap_used 已开）
- 数据库操作必须参数化（sqlx query 绑定），禁止字符串拼接 SQL
- 密钥/连接串从环境变量读（envy / figment），缺失时启动即报错，**禁止静默 fallback**
- 用户输入在边界处校验（validator crate 或手写），进入业务层后信任

### 测试规范

- 单元测试与代码同文件（`#[cfg(test)] mod tests`），覆盖业务逻辑
- 集成测试放 `tests/`，只通过 lib.rs 公开 API 测试
- 提交前 `cargo test` 必须全绿；新功能必须带测试
- 覆盖率用 `cargo tarpaulin` 或 `cargo llvm-cov` 查看，目标 {80}%+

### commit 规范

- Conventional Commits（feat/fix/docs/refactor/test/chore），scope 用模块名
- 模板见 .gitmessage（`git config --local commit.template .gitmessage`）

### 日志

- 用 `tracing`，不用 println!（clippy.print_stdout 已开）
- 级别约定：error=需要人工介入 / warn=自动恢复的异常 / info=关键路径 / debug=开发调试

## 当前进度

- 已完成：{模块列表}
- 进行中：{当前任务}
- 下一步：{计划}

## AI 工作注意事项

- 改代码前先看现有测试，改完必须 `cargo test` + `cargo clippy`
- 不要静默 fallback：错误要么传播要么记日志，不要吞掉
- 不写 unwrap/expect；新增依赖前先说明理由（编译时间成本）
- 不要动 Cargo.lock 的提交（由 maintainer 统一管理，除非是依赖升级的专门提交）

## 项目专属术语

- {内部模块名/表名/黑话，一行一个}
