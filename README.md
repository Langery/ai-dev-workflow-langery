# ai-dev-workflow-langery

为**已有的代码项目**搭建「AI 辅助开发 + 工程化规范」工作流。自动检测项目语言与框架，落地 lint / test / commit / pre-commit 配置、AI 上下文文件与 5 个核心 prompt 模板。

不是给你讲工程化是什么，是直接把配置装进你的项目里。

## 为什么名字带 `-langery`

SkillHub 上的 `ai-dev-workflow` 这个 slug 已被另一位作者占用（归属 `@indiv-wangjiaocheng`，852 下载）。本仓库使用独立 slug `ai-dev-workflow-langery`，两边内容互不干扰。

## 技术栈覆盖

| 栈 | lint | 测试 | commit 模板 | pre-commit | AI 上下文 |
|---|---|---|---|---|---|
| Python Flask | ✓ | ✓ | ✓ | ✓ | ✓ |
| Python FastAPI | ✓ | ✓ | ✓ | ✓ | ✓ |
| Node Express | ✓ | ✓ | ✓ | ✓ | ✓ |
| Go | ✓ | — | ✓ | ✓ | ✓ |
| Rust | ✓ | — | ✓ | ✓ | ✓ |

**检测到但不支持模板**：Django / Koa / NestJS / Next / Fastify / 纯标准库——脚本会如实报告看到了什么，但本 Skill 不提供模板，会明确告知并建议走通用 prompt 路径。不做 silent fallback。

## 安全边界

- **已有文件绝不覆盖**，先备份再由用户手工合并
- `pre-commit install` 是**接管**已有钩子，原钩子备份到 `.git/hooks/pre-commit.legacy`
- 依赖声明文件（package.json / pyproject.toml 等）默认拒绝覆盖
- 框架判定歧义时**停下**，把判断依据念给用户确认，不擅自往下走

## 安装

```bash
# Claude Code
git clone https://github.com/Langery/ai-dev-workflow-langery.git ~/.claude/skills/ai-dev-workflow-langery

# WorkBuddy / OpenClaw 系变体
git clone https://github.com/Langery/ai-dev-workflow-langery.git ~/.workbuddy/skills/ai-dev-workflow-langery
```

## 使用

安装后在支持 Skill 的 Agent 里说人话即可：

- "帮我规范一下这个项目的工程化"
- "commit message 怎么统一"
- "给这个项目配一个 CLAUDE.md"
- "测试覆盖率怎么拉起来"

命令行直接跑：

```bash
# 检测项目（输出 JSON）
python scripts/detect_project.py /path/to/project

# 应用模板
python scripts/apply_templates.py --project /path/to/project --stack python-flask
```

## 目录结构

```
ai-dev-workflow-langery/
├── SKILL.md                        # 入口，四步工作流 + 降级说明
├── scripts/
│   ├── detect_project.py           # 语言/框架/现状检测
│   ├── apply_templates.py          # 模板落地（含改名映射）
│   └── _verify_gate.py             # 落地结果校验
├── references/                     # 各栈约定、排错手册、模板用法
├── assets/templates/               # 5 个栈的模板集 + 通用 prompt
└── requirements.txt
```

## 踩过的坑（已修，写在这里避免重犯）

- 早期版本引用过不存在的 `install_workflow.py`，v1.2.0 已删除该引用并砍掉 CI/CD、容器编排等无法兑现的承诺
- v1.2.0 两处描述与实现不符（低置信度框架的停手行为、`pre-commit install` 的接管语义），v1.3.0 已按实测修正
- SKILL.md 里形如 `_test.go`、`.env`、`golang.org/x/crypto/bcrypt` 的 token 是**命名约定与教学示例**，不是文件路径。校验器的断链告警在这类token 上是误报

## License

MIT