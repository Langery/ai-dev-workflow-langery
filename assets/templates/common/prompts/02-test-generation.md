# Prompt 02：测试生成

> 让 Claude 为既有代码补测试，把覆盖率拉到 90%+。

## 使用场景

老代码覆盖率低，想批量补测试。或者新功能写完了，想让 Claude 补齐边界情况。

## Prompt

```
请为以下文件写 pytest 测试，目标覆盖率 90%+。

## 目标文件
<文件路径，例如：blueprints/<module_name>/routes.py>

## 当前覆盖率
- 文件总行数：<N>
- 已覆盖：<M>
- 覆盖率：<X>%
- 未覆盖的行号：<列出，例如 45-58, 102-115>

## 测试要求
1. 测试文件路径：tests/test_<module>_<feature>.py
2. 命名：test_<被测行为>_<场景>，例如 test_get_list_returns_user_owned_items
3. 每个 endpoint 至少覆盖：
   - 成功路径（happy path）
   - 错误路径（参数缺失、权限不足、资源不存在）
   - 边界情况（空列表、超长字符串、特殊字符）
4. 用 tmp_path 做测试隔离，**每个 test 函数内重新 import db helpers**
   （不要在文件顶部 import，conftest 会清模块缓存）
5. 用 monkeypatch 替换外部依赖（如时间、随机数）
6. 用 parametrize 跑多组数据，不要写 5 个雷同的 test
7. 测试要快，单个测试 < 1s

## 输出
1. 先列出要写的测试 case 清单，让我确认覆盖面
2. 写完后跑 pytest --cov=<module> 确认覆盖率达标
3. 跑 ruff check . 确认测试代码也过 lint
```

## 实际案例

参考一个真实交付：把 blueprints/<module_a>/routes.py 覆盖率从 39% 拉到 92.1%，blueprints/<module_b>/routes.py 从 62% 拉到 91.1%，整体从 91% 拉到 94.6%。补了 16 个测试，关键 bug 发现：conftest 的 _purge_app_modules() 会清掉模块缓存，但 test 文件顶部的 `from db import execute` 在 pytest 收集阶段就执行，拿到的是旧模块引用 → DB 操作落不到当前 test 的 tmp_path DB。修复方法：db helpers 在每个 test 函数内重新 import。

## 反例

❌ "给这个文件加几个测试" —— 没说覆盖率目标，Claude 会写最低限度的测试糊弄
❌ "覆盖率越高越好" —— 100% 不是目标，过度 mock 反而让测试脆弱
❌ 不带未覆盖行号 —— Claude 不知道重点补哪，会均匀分布精力浪费时间
