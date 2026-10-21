# Prompt 04：Commit Message 生成

> 让 Claude 按 Conventional Commits 规范 + 项目专属 scope 生成 commit message。

## 使用场景

代码改完了，懒得纠结 commit message 怎么写。让 Claude 读 diff 自己写。

## Prompt

```
请为本次改动生成 commit message。

## 改动概览
<贴 git diff --staged 的输出，或让 Claude 自己跑 git diff>

## 要求

1. 严格按 Conventional Commits 规范：
   <type>(<scope>): <subject>

   <body，解释为什么改>

   <footer>

2. type 从以下选：
   feat / fix / docs / style / refactor / test / chore / perf / ci

3. scope 从以下选（按 Flask 分层）：
   blueprint / routes / service / model / schema / auth / config / db / test / ci

4. subject 要求：
   - 祈使句，首字母小写
   - 不超过 50 字符
   - 不加句号
   - 一眼能看懂改了什么

5. body 要求：
   - 用 - 开头列要点
   - 解释「为什么改」，不是「改了什么」（diff 已经能看出 what）
   - 写清楚动机、权衡、踩过的坑
   - 每行不超过 72 字符

6. footer（如有）：
   - BREAKING CHANGE: <描述破坏性变更>
   - Closes #<issue 编号>
   - 如果是 AI 辅助的 commit，加：
     Co-Authored-By: Claude <noreply@anthropic.com>

7. 自检清单：
   [ ] type 选对了吗
   [ ] scope 在白名单里吗
   [ ] subject 一眼能看懂吗
   [ ] body 写了 why 吗
   [ ] 跑过 pytest 吗
   [ ] ruff check . 全过吗

## 输出

直接给出完整的 commit message，markdown 代码块包裹。
不要解释，不要分析，只给结果。
```

## 实际案例

参考一个真实交付的 commit：

```
feat(auth): 密码 scrypt/pbkdf2 哈希 + 用户名/密码格式校验（明文存储 P0 修复）

- register: 密码用 werkzeug.security generate_password_hash（默认 scrypt, 16 字节 salt）存储，绝不明文
- login: check_password_hash 校验；老 plaintext 用户首次登录后自动升级为 hash（零停机迁移）
- 输入校验：用户名 3-20 位字母/数字/下划线，昵称 1-30 位非空，密码 ≥6 位
- register 异常路径（IntegrityError / RuntimeError）只回友好消息，日志带 traceback
- username enumeration 防御：用户不存在与密码错都返回 backData=False，不区分

测试：18 个新 case（test_auth_password.py），auth/routes.py 覆盖率 100%，总 86 用例 95.1%

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

## 反例

❌ 不带 diff —— Claude 凭空写，subject 会泛化
❌ 让 Claude "随便写" —— scope 会乱用，破坏白名单
❌ 不要求 body —— 没了 why，半年后看不懂为什么这么改
