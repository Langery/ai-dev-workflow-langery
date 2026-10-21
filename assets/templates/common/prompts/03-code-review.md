# Prompt 03：代码 Review

> 让 Claude 按 ruff 规范 + 工程约定审查代码，找潜在 bug 和改进点。

## 使用场景

提交前自查、Pull Request 评审、老代码重构前的盘点。

## Prompt

```
请 review 以下代码，按 5 个维度审查：

## 待 review 代码
<贴代码，或指定文件路径让 Claude 读>

## 审查维度

### 1. 静态规范（ruff 能查的）
- import 排序
- 未使用变量
- 行长超限
- 类定义现代化（class Foo: 不是 class Foo(object):）
- datetime.UTC 替代 datetime.timezone.utc

### 2. 工程约定
- 是否符合 Blueprint 分区（routes.py 里有没有写业务逻辑）
- 返回格式是否统一 {"code":0,"data":...,"msg":...}
- 异常处理是否只回友好消息 + 日志记 traceback
- 配置是否走 get_config()，没有直接读 env
- 日志是否用 app.logger，没有 print

### 3. 安全性
- 密码是否哈希存储（绝不明文）
- SECRET_KEY 是否从 env 读，是否有静默 fallback
- 用户输入是否校验（用户名 3-20 位、密码 ≥6 位）
- SQL 是否参数化（不用字符串拼接）
- 文件上传是否校验类型和大小
- 是否有 username enumeration 风险（用户不存在和密码错要返回相同消息）

### 4. 健壮性
- 边界情况处理（空数据、超长、特殊字符）
- 错误路径是否会导致部分写入（事务）
- 并发风险（共享状态、文件锁）
- 资源泄漏（连接、文件句柄）

### 5. 可维护性
- 命名是否清晰
- 函数长度是否合理（>50 行考虑拆）
- 重复代码（可抽函数）
- 注释是否解释 Why 不是 What

## 输出格式

按维度列出问题：
- 🔴 必改（阻塞合并）：行号 + 问题 + 修复建议
- 🟡 建议改（不阻塞）：行号 + 改进点 + 收益
- 🟢 可保持：好的实践（一句话肯定即可）

最后给一个总体评分（10 分制）和合并建议。
```

## 实际案例

参考一个真实交付：发现密码明文存储（P0 安全漏洞），修复方案用 werkzeug.security generate_password_hash，默认 scrypt + 16 字节 salt，老用户首次登录后零停机迁移为 hash。同时加了 username enumeration 防御。修复后 blueprints/auth/routes.py 覆盖率 100%。

## 反例

❌ "帮我看看这段代码怎么样" —— 维度不清，Claude 会泛泛而谈
❌ 不带待 review 文件 —— Claude 凭记忆审查，结果不可靠
❌ 只问 "有什么问题" —— Claude 不会主动建议改进，只指出错误
