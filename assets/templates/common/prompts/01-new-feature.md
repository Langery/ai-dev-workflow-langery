# Prompt 01：新功能开发

> 教 Claude 按 Blueprint 模式实现新功能，遵循现有工程约定。

## 使用场景

需要新增一个功能模块（比如：消息通知、文件管理、数据导出），希望 Claude 按本项目既有模式实现，而不是写一坨乱七八糟的代码。

## Prompt

```
我要新增一个功能模块「<module_name>」，请你按 blueprints/ 下既有模块的模式来实现。

## 功能描述
<具体功能说明>

## 需要实现的 endpoint
- GET  /api/<module>/list        列表查询，支持分页和模糊搜索
- GET  /api/<module>/get?id=     单条查询
- POST /api/<module>/save        新增/更新（upsert 语义）
- POST /api/<module>/delete?id=  软删除

## 工程约定（必须遵守）
1. Blueprint 分区结构：
   blueprints/<module_name>/
   ├── __init__.py    # Blueprint 实例化
   ├── routes.py      # 路由
   ├── models.py      # 数据结构
   └── services.py    # 业务逻辑

2. 返回格式：
   {"code": 0, "data": ..., "msg": ""}
   错误：{"code": -1, "data": None, "msg": "..."}

3. owner 隔离：所有查询和写入都要带 user_id（从 token 解析）

4. 配置：从 get_config() 读，不直接读 env

5. 异常：只回友好消息，app.logger 记 traceback

## 输出要求
1. 先列出涉及哪些文件，让我确认
2. 写完代码后，同步生成 tests/test_<module>_endpoints.py
3. 测试覆盖：成功路径 + 错误路径 + owner 隔离验证
4. 跑 ruff check . 确保全过
5. 跑 pytest 确保新测试全过且不影响老测试
```

## 实际案例

参考一个真实交付：实现某业务模块，含 4 个 endpoint + owner 隔离 + sort 白名单 + uuid 生成。这个模块从设计到测试通过，用 Claude 辅助大约 4 小时完成，覆盖率 92.1%。

## 反例（不要这样问）

❌ "帮我写一个用户管理功能" —— 太模糊，Claude 会写出你不想要的东西
❌ "在 routes.py 里加几个接口" —— 违反 Blueprint 分区
❌ "随便写，能跑就行" —— 不写测试、不管覆盖率，注定技术债
