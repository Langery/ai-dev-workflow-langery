# 5 个核心 Prompt 使用指南

> 本文件说明 `assets/templates/common/prompts/` 下 5 个 prompt 模板的适用场景、调用时机、以及常见误用。
> **这是提升付费体验的关键** —— 买家最容易犯的错是「装了不用」。

## 核心原则：Prompt 不是工具调用，是上下文工程

多数人用 AI 编程的最大浪费是：**每次都从零解释一遍项目背景**。

这 5 个 prompt 的真正价值不在「生成代码」，而在**把项目上下文固化下来，让每次对话都从同一个已知基线开始**。

---

## 何时使用哪个prompt

| Prompt | 触发时机 | 频率 |
|---|---|---|
| 01-new-feature.md | 要加新功能/新接口/新页面 | 每天 |
| 02-test-generation.md | 写完代码要补测试 | 每次提交前 |
| 03-code-review.md | 提交前自查 / PR 前 | 每次提交前 |
| 04-commit-message.md | 写 commit message 时 | 每次提交 |
| 05-doc-generation.md | 写 README / API 文档 / CHANGELOG | 每周 |

**推荐使用顺序**：01 → 02 → 03 → 04，五个串起来是一条完整的开发流水线。

---

## 01-new-feature.md —— 新功能开发

### 使用场景
新增接口、数据模型、页面、业务模块。

### 使用前必须做的事
1. **先填好 CLAUDE.md** —— 这个 prompt 会引用项目概况和工程约定。不填 = 效果减半
2. 确认测试框架已知（pytest / jest / go test）

### 调用方式

```
复制 01-new-feature.md 的完整 prompt 内容
+
追加你的具体需求："为用户模块新增邮箱验证码登录接口，需要限流，验证码 5 分钟过期"
```

### 反例（效果差）

```
帮我写个登录接口
```

**问题**：AI 不知道你的项目结构、不知道有没有现成的 service 层、不知道密码用什么哈希、不知道响应格式统一是什么。结果一定是「能跑但风格完全不一致」的代码。

### 正例

```
[01-new-feature.md 的 prompt]
+
需求：用户表新增 email_verified 字段和邮箱验证码登录接口
约束：
- 验证码 6 位数字，有效期 5 分钟，同邮箱 60 秒内只能发 1 条
- 复用 app/services/user_service.py，不要新建文件
- 响应格式用现有的 {code, message, data} 结构
- 补充对应测试到 tests/integration/test_auth.py
```

**收益**：AI 会自动沿用你既有的目录结构、响应格式、service 分层，产出代码风格一致。

---

## 02-test-generation.md —— 测试生成

### 使用场景
写完功能后补测试，或覆盖率不达标时集中补测。

### 为什么单独做这个 prompt
AI 写测试有两个常见问题：
- **覆盖率够但没测到关键分支**（只测了 happy path）
- **测试本身是错的**（断言了实现细节而非行为）

这个 prompt 明确要求覆盖边界条件和异常路径。

### 调用方式

```
[02-test-generation.md 的 prompt]
+
目标文件：app/services/auth_service.py
当前覆盖率 82%，目标 95%
已知未覆盖：
- 验证码过期分支
- 邮箱格式非法的边界
- 并发发送的锁竞争
```

### 关于覆盖率陷阱（真实教训）

> 补测实战：91% → 94.6%
>
> 难点不是写测试，是发现一个真实 bug：**conftest.py 里 db.engine 被做成模块级缓存**，导致多个测试文件共享连接，单独跑全过、全量跑随机失败。
>
> 这个 bug 是被覆盖率工具的「随机失败」暴露出来的，不是被断言发现的。

**所以**：补测时遇到莫名其妙的随机失败，先怀疑测试基础设施本身有问题，不要急着改业务代码。

---

## 03-code-review.md —— 代码审查

### 使用场景
**提交前自查** —— 不要等别人给你 code review，自己先跑一遍。

### 五个审查维度

1. **正确性** —— 边界条件、空值处理、并发安全
2. **安全性** —— SQL 注入、硬编码密钥、权限校验缺失
3. **可维护性** —— 命名、函数长度、圈复杂度
4. **测试完整性** —— 有没有覆盖新分支
5. **性能** —— N+1 查询、无界循环、缺索引的查询

### 调用方式

```
[03-code-review.md 的 prompt]
+
审查范围：本次改动的 3 个文件（git diff 贴入）
重点：这次改了密码哈希逻辑，检查迁移是否安全
```

### 高价值用法：安全维度专项审查

```
只用维度 2（安全性）审查 git diff，重点看：
- 有没有硬编码的密钥/密码
- SQL 是否参数化
- 权限校验是否覆盖新接口
```

**这是最实用的用法** —— 全面审查 AI 容易走过场，单维度深挖才有价值。

---

## 04-commit-message.md —— Commit Message

### 使用场景
每次 `git commit` 前。

### 为什么值得单独做
AI 帮你写 commit message 有两种坏结果：
- 写得跟没写一样（"fix bug"）
- 格式不符合规范，污染历史

这个 prompt 会强制 Conventional Commits 格式，并要求带上改动范围。

### 调用方式

```
[04-commit-message.md 的 prompt]
+
git diff --staged 的输出
```

### 产出示例

```text
feat(auth): add email verification login flow

- add email_verified column to users table
- add EmailVerificationService with 5min expiry
- add rate limit (1 req/min per email)
- add integration tests covering expiry and duplicate paths
```

配套项目根目录的 `.gitmessage` 模板，AI 会自动遵循你的提交规范。

---

## 05-doc-generation.md —— 文档生成

### 使用场景
写README / API 文档 / CHANGELOG。

### 三种模式

| 模式 | 用途 | 调用提示 |
|---|---|---|
| README | 项目首次对外 | "为这个项目写 README，包含功能、技术栈、快速开始" |
| API 文档 | 接口变更后 | "为 app/api/v1/endpoints/ 下的接口生成 API 文档" |
| CHANGELOG | 发版前 | "根据 v1.2.0 到 v1.3.0 的 git log 生成 CHANGELOG" |

### 关键提醒
文档必须**基于真实代码生成**，不要让 AI 凭想象写。调用前先让它读代码：

```
先读 app/api/v1/endpoints/ 下的所有文件，
然后基于实际代码生成 API 文档，标注每个接口的请求方法、路径、参数、返回结构、错误码。
不确定的地方标注 TODO，不要编造。
```

---

## 提升效果的三个技巧

### 1. 一次只问一件事
不要在一次对话里同时要求「新功能 + 测试 + 文档 + commit」。拆开，每个 prompt 单独一轮。

### 2. 强制它读代码再动手
在 prompt 末尾加一句：**「动手前先读相关文件，列出你的改动计划，我确认后再写代码。」**

这一步能拦掉大部分「不了解项目就乱改」的问题。

### 3. 保留对话上下文
同一功能的连续修改**在同一个会话里进行**，不要开新对话。AI 对上下文的利用效率远高于你重新解释的成本。

---

## 反模式清单

| 现象 | 原因 | 正确做法 |
|---|---|---|
| AI 写的代码风格和项目不一致 | 没填 CLAUDE.md，或没让它读现有代码 | 先填 CLAUDE.md，强制先读后写 |
| 测试覆盖率上不去| 只测 happy path | 指定补测边界和异常分支 |
| 每次都要重新解释项目 | 没有固化上下文 | CLAUDE.md + 本套 prompt |
| code review 走过场 | 范围太大 | 单维度深挖，尤其安全维度 |
| commit message 没信息量 | 直接让AI 猜 | 喂 `git diff --staged` |
| 文档和代码对不上 | 让 AI 凭记忆写 | 强制先读代码，基于实际生成 |