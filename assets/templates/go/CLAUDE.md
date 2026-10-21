# CLAUDE.md

> 这是项目上下文模板。把它放在你的 Go 项目根目录，Claude Code 会自动读取并理解你的工程约定。

## 项目概况

- **项目类型**：Go HTTP API 服务
- **架构**：分层（handlers / services / repositories / models）
- **数据库**：PostgreSQL via pgx v5
- **测试**：标准 `testing` + `testify`，目标覆盖率 80%+（Go 社区标准比 Python/Node 略低）
- **Go 版本**：1.22+

## 工程约定（Claude 必须遵守）

### 1. 代码风格

- 用 `gofmt` 格式化，所有代码必须 `gofmt -l .` 无输出才能提交
- import 用 `goimports` 自动排序（标准库 / 第三方 / 项目内部，三组分开）
- 用 `golangci-lint run` 做 lint，所有代码必须零 error 才能提交
- **Error 是值不是异常**——每个可能返回 error 的调用都必须检查，**禁止 `_ = err` 或忽略 error**
- context 必须作为第一个参数传递：`func DoSomething(ctx context.Context, ...) error`
- error 用 `fmt.Errorf("...: %w", err)` 包装，保留调用链

### 2. 目录结构

新增功能模块时，按以下结构组织（Go 标准布局）：

```
.
├── cmd/
│   └── server/
│       └── main.go          # 入口，只做初始化和依赖注入
├── internal/                 # internal 包外部不可 import（Go 编译器强制）
│   ├── handler/
│   │   └── <module>.go       # HTTP handler，解析请求 + 调 service
│   ├── service/
│   │   └── <module>.go       # 业务逻辑，不碰 HTTP 层
│   ├── repository/
│   │   └── <module>.go       # 数据访问，执行 SQL
│   ├── model/
│   │   └── <module>.go       # 数据结构定义
│   └── middleware/
│       └── auth.go           # 中间件
├── pkg/                      # 可被外部项目复用的公共代码
│   └── response/
│       └── response.go       # 统一响应格式
├── migrations/               # SQL 迁移文件
├── go.mod
└── go.sum
```

- 业务代码放 `internal/`，Go 编译器强制外部包不可 import
- `cmd/server/main.go` 只做初始化和依赖注入，**不要写业务逻辑**
- 响应统一格式：`{"code": 0, "data": ..., "message": ""}`
- 错误返回合适的 HTTP status + `{"code": -1, "data": null, "message": "..."}`
- 路由用 Go 1.22+ 内置的 `http.ServeMux`（已支持 method+pattern），或 chi

### 3. 配置管理

- 用 `viper` 或 `os.Getenv`，**不要硬编码**
- 所有配置从环境变量读，`JWT_SECRET` / `DATABASE_URL` 无默认值
- 生产缺失关键配置直接 `log.Fatal`，**绝不静默 fallback**
- 配置集中在 `internal/config/`，其他包从这里读，不直接调 `os.Getenv`

### 4. 密码与认证

- **绝不明文存密码**。用 `golang.org/x/crypto/bcrypt` 的 `GenerateFromPassword`
- JWT 用 `golang-jwt/jwt/v5`，HS256，过期时间从配置读
- 密码不放在 JWT payload 里
- 用户名枚举防御：用户不存在与密码错都返回 `401 Unauthorized`
- 需要认证的路由用 auth middleware

### 5. 测试规范

- 用标准 `testing` + `testify/assert` + `testify/mock`
- 表驱动测试是 Go 惯用法，优先用：
  ```go
  tests := []struct {
      name    string
      input   string
      want    int
      wantErr bool
  }{
      {"valid", "abc", 3, false},
      {"empty", "", 0, true},
  }
  for _, tt := range tests {
      t.Run(tt.name, func(t *testing.T) {
          // ...
      })
  }
  ```
- HTTP handler 用 `httptest.NewRecorder` + `httptest.NewRequest` 测试，**不要起真实 server**
- 测试文件 `_test.go` 和被测文件同目录，测试函数 `func TestXxx(t *testing.T)`
- 覆盖率检查：`go test -cover ./...`，CI 门槛 75%（Go 社区标准）

### 6. Commit 规范

- 用 Conventional Commits 格式，type 选：`feat / fix / docs / style / refactor / test / chore`
- scope 用模块名：`handler / service / repo / model / auth / db`
- AI 辅助的 commit 加 `Co-Authored-By: Claude <noreply@anthropic.com>`

### 7. 数据库迁移

- 用 `golang-migrate` 管理 schema 变更
- **不要在代码里自动建表**（生产环境必须走 migration）
- 每次 schema 变更：`migrate create -ext sql -dir migrations -seq 描述` → 写 up/down SQL → `migrate up`

### 8. 并发安全

- 共享状态必须用 mutex 或 channel 保护，**不要裸读写共享变量**
- goroutine 必须有退出机制（context cancel 或 done channel），**不要泄漏 goroutine**
- 资源（DB 连接、HTTP body、文件）必须 `defer Close()`

## 当前进度（Claude 需要知道的）

- ✅ 用户认证（JWT + bcrypt）
- ✅ [在这里写你已完成的功能]
- 🔲 下一步：[在这里写你当前要做的事]

## Claude 工作时的注意事项

1. **改代码前先看测试** —— `_test.go` 反映当前行为契约
2. **新功能先写测试** —— TDD 节奏，先红后绿
3. **不要静默 fallback** —— 配置缺失、error 全部处理
4. **不要用 fmt.Println** —— 用 `zerolog` 或标准 `log`
5. **不要在 handler 里写业务逻辑** —— 业务逻辑放 service/
6. **每个 error 必须检查** —— 禁止 `_ = someFunc()` 忽略 error
7. **context 必须传递** —— 所有可能阻塞的函数接受 ctx 作为第一参数
8. **改完跑测试** —— `go test ./...` 必须全过且覆盖率不下降
9. **改完跑 lint** —— `golangci-lint run` 必须零 error
10. **改完 tidy** —— `go mod tidy` 后检查 go.mod/go.sum 无多余 diff

## 项目专属术语

- [在这里写你的项目特有表名、模块名、内部黑话]
