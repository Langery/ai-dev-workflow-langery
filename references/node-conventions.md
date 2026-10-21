# Node.js 工程化约定

> 本文件覆盖 Node.js（含 Express / Koa / Fastify）项目的工程化方法论。配合 `assets/templates/node-express/` 使用。

## 工具链

| 工具 | 用途 | 现代替代 |
|---|---|---|
| **ESLint 9** | lint | flat config（eslint.config.js），替代 .eslintrc |
| **Prettier** | 格式化 | 和 ESLint 配合，格式规则交给 Prettier |
| **Vitest** | 测试 | Jest 的现代替代，ESM 原生支持，快 3-5 倍 |
| **Husky 9** | Git 钩子 | 提交前自动跑 lint-staged |
| **lint-staged** | 暂存区检查 | 只检查改动文件，不跑全量 |
| **commitizen** | commit 规范 | `npx cz` 交互式生成 Conventional Commits |

## 关键约定

### 1. ES Modules

Node 20+ + ES Modules 是现代标准：

```json
// package.json
{
  "type": "module"
}
```

- 用 import/export 不用 require/module.exports
- 用 `__dirname` 的替代：
  ```js
  import { fileURLToPath } from 'url';
  import { dirname } from 'path';
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);
  ```

### 2. 异步处理

- 一律 async/await，**禁止裸 .then() 链**
- Express 4 的 async 路由需要包装（Express 5 原生支持）：
  ```js
  // Express 4 的 async wrapper
  const asyncHandler = (fn) => (req, res, next) => {
    Promise.resolve(fn(req, res, next)).catch(next);
  };
  
  router.get('/users/:id', asyncHandler(async (req, res) => {
    const user = await userService.findById(req.params.id);
    res.json({ code: 0, data: user });
  }));
  ```
- **每个 async 函数必须有 error 处理路径**——要么 try-catch，要么交给 errorHandler 中间件

### 3. 错误处理

- 统一 errorHandler 中间件（必须挂在路由之后）：
  ```js
  app.use((err, req, res, next) => {
    logger.error(err);
    if (res.headersSent) return next(err);
    res.status(err.status || 500).json({
      code: -1,
      data: null,
      message: err.message || 'Internal Server Error',
    });
  });
  ```
- 业务错误用自定义 class，带 status：
  ```js
  class AppError extends Error {
    constructor(message, status) {
      super(message);
      this.status = status;
    }
  }
  ```
- **不要在路由里 try-catch + res.send**——用 `next(err)` 传给 errorHandler

### 4. 请求校验

用 Zod 替代手写 if 判空：

```js
import { z } from 'zod';

const createUserSchema = z.object({
  username: z.string().min(3).max(20),
  password: z.string().min(6),
  email: z.string().email(),
});

// 中间件
const validate = (schema) => (req, res, next) => {
  const result = schema.safeParse(req.body);
  if (!result.success) {
    return next(new AppError(JSON.stringify(result.error.flatten()), 400));
  }
  req.body = result.data;
  next();
};
```

### 5. 安全

- `helmet` 设置安全 HTTP 头
- `cors` 白名单控制跨域
- `express-rate-limit` 防暴力破解
- **SQL 参数化查询**——`pg` 的 `query(text, values)`，禁止字符串拼接
- 敏感信息（密码、token、key）不写日志
- `bcryptjs` 哈希密码，**绝不明文存**

### 6. 日志

- HTTP 请求日志用 `morgan`
- 业务日志用 `winston` 或 `pino`，**不要用 console.log**
- 生产环境日志 JSON 格式，便于收集

### 7. 测试

```js
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import request from 'supertest';
import app from '../src/app.js';

describe('POST /api/v1/users', () => {
  it('should create user with valid input', async () => {
    const res = await request(app)
      .post('/api/v1/users')
      .send({ username: 'testuser', password: 'pass123' });
    
    expect(res.status).toBe(201);
    expect(res.body.code).toBe(0);
    expect(res.body.data).toHaveProperty('id');
  });
  
  it('should reject duplicate username', async () => {
    // ...
  });
});
```

- 用 `supertest` 测试 Express，**不需要起真实 HTTP server**
- 测试隔离：mock 外部依赖或用独立数据库
- 覆盖率门槛 85%
