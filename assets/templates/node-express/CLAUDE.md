# CLAUDE.md

> 这是项目上下文模板。把它放在你的 Node Express 项目根目录，Claude Code 会自动读取并理解你的工程约定。

## 项目概况

- **项目类型**：Node.js Express API 服务
- **架构**：分层（routes / middleware / services / models）+ ES Modules
- **数据库**：PostgreSQL via `pg`
- **测试**：Vitest + Supertest，目标覆盖率 90%+
- **Node**：>= 20.0.0（ES Modules，package.json `"type": "module"`）

## 工程约定（Claude 必须遵守）

### 1. 代码风格

- 用 `eslint .` 做 lint，所有代码必须零 error 才能提交
- 格式化交给 Prettier（`.prettierrc` 已配好），不要手动调缩进/引号
- 单行不超过 100 字符（Prettier `printWidth: 100`）
- 用 `const` 优先，`let` 仅在需要重赋值时用，**禁止 `var`**
- 用模板字符串 `` `Hello ${name}` `` 不用字符串拼接
- 异步一律 `async/await`，**禁止裸 `.then()` 链**（除非在 pipeline 中间）

### 2. 目录结构

新增功能模块时，按以下结构组织：

```
src/
├── app.js               # Express 实例 + 中间件 + 路由挂载
├── config/
│   └── index.js          # 环境变量读取（dotenv）
├── routes/
│   └── <module>.routes.js    # 路由定义
├── middleware/
│   ├── auth.js           # JWT 认证中间件
│   └── errorHandler.js   # 统一错误处理（必须挂在最后）
├── services/
│   └── <module>.service.js   # 业务逻辑，不碰 req/res
├── models/
│   └── <module>.model.js     # 数据访问层
├── schemas/
│   └── <module>.schema.js    # Zod 请求校验
└── tests/
    └── <module>.test.js
```

- 路由用 `express.Router()`，挂载 `app.use('/api/v1/<module>', moduleRouter)`
- 请求体校验用 Zod，**不要手写 if 判空**
- 响应统一格式：`{ code: 0, data: ..., message: '' }`，错误 `{ code: -1, data: null, message: '...' }`
- 错误用 `next(err)` 传给 errorHandler，**不要在路由里 try-catch 后 res.status().send()**

### 3. 配置管理

- 所有配置走 `dotenv` + `process.env`，**不要硬编码**
- `JWT_SECRET` / `DATABASE_URL` 无默认值，生产缺失直接 `throw`，**绝不静默 fallback**
- 测试环境用 `.env.test`，CI 用 `.env.ci`
- 配置集中在 `src/config/index.js`，其他文件从这里 import，不直接读 `process.env`

### 4. 密码与认证

- **绝不明文存密码**。用 `bcryptjs` 的 `bcrypt.hash()`
- JWT 用 `jsonwebtoken`，HS256，过期时间从配置读
- 密码不放在 JWT payload 里
- 用户名枚举防御：用户不存在与密码错都返回 `401 Unauthorized`
- 需要认证的路由用 `authMiddleware` 中间件

### 5. 测试规范

- 用 `vitest` + `supertest` 测试 Express，**不要起真实 HTTP server**
- 测试隔离：每个 test 用独立事务或 mock，test 结束自动清理
- 每个 endpoint 至少覆盖：成功路径 + 错误路径 + 权限边界
- 测试文件放 `tests/<module>.test.js`，文件名必须含 `.test.js`
- 覆盖率低于 85% CI 会 fail（`vitest --coverage`）

### 6. Commit 规范

- 用 `npx cz` 替代 `git commit`（commitizen）
- type 选：`feat / fix / docs / style / refactor / test / chore`
- scope 用模块名：`route / middleware / service / model / auth / db`
- AI 辅助的 commit 加 `Co-Authored-By: Claude <noreply@anthropic.com>`

### 7. 安全

- 用 `helmet` 设置安全 HTTP 头
- 用 `cors` 白名单控制跨域
- 用 `express-rate-limit` 防暴力破解（如需要）
- SQL 用参数化查询（`pg` 的 `query(text, values)`），**禁止字符串拼接 SQL**
- 敏感信息（密码、token、key）不写日志

## 当前进度（Claude 需要知道的）

- ✅ 用户认证（JWT + bcrypt）
- ✅ [在这里写你已完成的功能]
- 🔲 下一步：[在这里写你当前要做的事]

## Claude 工作时的注意事项

1. **改代码前先看测试** —— `tests/` 目录反映当前行为契约
2. **新功能先写测试** —— TDD 节奏，先红后绿
3. **不要静默 fallback** —— 配置缺失、环境变量缺失全部 throw
4. **不要用 console.log** —— 用 morgan 记 HTTP 日志，业务日志用 winston/pino
5. **不要在 routes 里写业务逻辑** —— 业务逻辑放 services/
6. **不要拼接 SQL** —— 用 `pg` 参数化查询
7. **改完跑测试** —— `npm test` 必须全过且覆盖率不下降
8. **ES Modules** —— 用 `import/export` 不用 `require/module.exports`

## 项目专属术语

- [在这里写你的项目特有表名、模块名、内部黑话]
