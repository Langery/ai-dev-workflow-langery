# Go 工程化约定

> 本文件覆盖 Go 项目的工程化方法论。配合 `assets/templates/go/` 使用。

## 工具链

| 工具 | 用途 | 说明 |
|---|---|---|
| **gofmt / goimports** | 格式化 | Go 内置，无争议 |
| **golangci-lint** | lint | 聚合 50+ linter，errcheck/govet/staticcheck/gosec 必开 |
| **标准 testing** | 测试 | Go 内置，配合 testify/assert |
| **testify** | 断言库 | `assert`/`require`/`mock`，Go 社区主流 |
| **golang-migrate** | 数据库迁移 | up/down SQL 文件管理 schema |
| **pgx v5** | PostgreSQL driver | 比标准 database/sql 更快更全 |

## 关键约定

### 1. Error 处理（Go 最重要的一条）

Go 没有 try-catch，error 是返回值。**每个可能返回 error 的调用都必须检查**：

```go
// 正确
result, err := doSomething()
if err != nil {
    return fmt.Errorf("do something: %w", err)
}

// 错误（禁止）
result, _ := doSomething()  // 忽略 error

// 错误（禁止）
result, err := doSomething()
if err != nil {
    log.Println(err)  // 只记日志不返回，调用方不知道出错了
    // ...
}
```

- error 包装用 `fmt.Errorf("context: %w", err)`，保留调用链
- 自定义 error 类型用于可恢复的错误：
  ```go
  var ErrUserNotFound = errors.New("user not found")
  
  func FindUser(id int) (*User, error) {
      // ...
      return nil, ErrUserNotFound
  }
  
  // 调用方
  user, err := FindUser(1)
  if errors.Is(err, ErrUserNotFound) {
      // 处理特定错误
  }
  ```

### 2. Context 传递

context 是 Go 并发控制的标配，**所有可能阻塞的函数都应接受 ctx 作为第一参数**：

```go
func (s *UserService) FindByID(ctx context.Context, id int) (*User, error) {
    ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
    defer cancel()
    
    return s.repo.FindByID(ctx, id)
}
```

- HTTP handler 从 `r.Context()` 取 context
- DB 查询传 ctx，超时自动取消
- **不要把 context 存在 struct 里**——context 应在函数间传递，不持久化

### 3. 并发安全

- 共享状态必须用 mutex 或 channel 保护
- goroutine 必须有退出机制：
  ```go
  ctx, cancel := context.WithCancel(context.Background())
  go func() {
      for {
          select {
          case <-ctx.Done():
              return
          case item := <-ch:
              // 处理 item
          }
      }
  }()
  // 需要停止时：
  cancel()
  ```
- **资源必须 defer Close()**——`defer resp.Body.Close()`

### 4. 目录布局

Go 标准布局（参考社区通行的 golang-standards/project-layout 约定）：

```
cmd/server/main.go          # 入口
internal/                    # 内部包，外部不可 import
pkg/                         # 可复用公共包
migrations/                  # SQL 迁移
```

- **业务代码放 `internal/`**，Go 编译器强制外部项目不能 import
- cmd/ 下的 main.go 只做初始化和依赖注入，不写业务逻辑
- `pkg/` 放可被其他项目复用的通用代码

### 5. 测试（表驱动）

Go 惯用法是表驱动测试：

```go
func TestCreateUser(t *testing.T) {
    tests := []struct {
        name    string
        input   CreateUserInput
        wantErr bool
        wantID  int
    }{
        {
            name: "valid input",
            input: CreateUserInput{Username: "alice", Password: "pass123"},
            wantErr: false,
            wantID: 1,
        },
        {
            name: "empty username",
            input: CreateUserInput{Username: "", Password: "pass123"},
            wantErr: true,
        },
    }
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            id, err := CreateUser(tt.input)
            if tt.wantErr {
                require.Error(t, err)
                return
            }
            require.NoError(t, err)
            assert.Equal(t, tt.wantID, id)
        })
    }
}
```

- HTTP handler 用 `httptest`：
  ```go
  req := httptest.NewRequest("POST", "/api/v1/users", body)
  w := httptest.NewRecorder()
  handler.ServeHTTP(w, req)
  assert.Equal(t, 201, w.Code)
  ```
- 测试文件（_test.go 后缀）和被测文件**同目录**
- 覆盖率门槛 75%（Go 社区标准比 Python/Node 低，因为 Go 类型系统已经挡掉很多问题）

### 6. SQL 安全

用 `pgx` 参数化查询，**禁止字符串拼接 SQL**：

```go
// 正确
row := pool.QueryRow(ctx, "SELECT id, username FROM users WHERE username = $1", username)

// 错误（SQL 注入）
query := fmt.Sprintf("SELECT id FROM users WHERE username = '%s'", username)
```

### 7. 数据库迁移

用 `golang-migrate`：

```bash
# 创建迁移
migrate create -ext sql -dir migrations -seq add_users_table

# 生成的文件：
# migrations/000001_add_users_table.up.sql
# migrations/000001_add_users_table.down.sql

# 执行
migrate -path migrations -database "postgres://..." up
```

- **不要在代码里 `CREATE TABLE`**（生产环境必须走 migration）
- 每次变更写 up（执行）和 down（回滚）

### 8. 资源管理

```go
// HTTP response body 必须 Close
resp, err := http.Get(url)
if err != nil {
    return err
}
defer resp.Body.Close()

// DB 连接必须归还
conn, err := pool.Acquire(ctx)
if err != nil {
    return err
}
defer conn.Release()

// 文件必须 Close
f, err := os.Open(path)
if err != nil {
    return err
}
defer f.Close()
```
