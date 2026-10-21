---
name: ai-dev-workflow-langery
description: AI 辅助开发的工程化工作流配置 Skill。当用户想要规范项目工程化、搭建 AI 辅助开发工作流、配置 commit 规范、提升测试覆盖率、配置 pre-commit 钩子、配置 Claude/AI 上下文文件（CLAUDE.md / .cursorrules / AGENTS.md）、生成 AI 辅助开发 prompt 模板时使用。为 Python Flask、Python FastAPI、Node Express、Go、Rust 五种技术栈提供成套的 lint / test / commit / pre-commit 配置与 AI 上下文模板；检测脚本另可识别 Django / Koa / NestJS 并如实告知，但这三种栈不提供模板（降级说明见文末表格）。触发词：工程化、commit 规范、测试覆盖率、pre-commit、AI 辅助开发、Claude 上下文、Cursor 规则、工作流、代码规范、提效、Claude Code、Cursor。
description_zh: 为已有代码项目搭建「AI 辅助开发 + 工程化规范」工作流。自动检测项目语言与框架，落地 lint / test / commit / pre-commit 配置、AI 上下文文件（CLAUDE.md / .cursorrules / AGENTS.md）与 5 个核心 prompt 模板。提供 Flask、FastAPI、Express、Go、Rust 五种技术栈的开箱模板，已有文件不覆盖、先备份再合并。
description_en: Set up an AI-assisted development workflow on an existing codebase. Detects the project language and framework, then installs lint / test / commit / pre-commit configuration, an AI context file (CLAUDE.md / .cursorrules / AGENTS.md), and 5 core prompt templates. Ships ready-to-apply templates for Flask, FastAPI, Express, Go and Rust. Existing files are never overwritten — they are backed up for manual merge.
version: 1.3.1
author: Langery
---

# AI Dev Workflow

## 概述

为已有的代码项目搭建「AI 辅助开发 + 工程化规范」工作流。检测项目语言和框架，落地对应的 lint/test/commit/pre-commit 配置 + AI 上下文文件（CLAUDE.md / .cursorrules）+ 5 个核心 AI 辅助开发 prompt 模板。覆盖 Python Flask、Python FastAPI、Node Express、Go、Rust 五种技术栈。

## 何时触发

满足以下任一场景：

- 用户说"我想规范项目工程化"、"帮我搭一个 AI 辅助开发工作流"、"commit 怎么规范"、"测试覆盖率怎么拉到 90%"、"pre-commit 怎么配置"
- 用户提到 Claude Code / Cursor / Copilot 等 AI 编程助手，并询问如何接入项目
- 用户的项目工程化做得乱（无 lint、无测试、commit message 不规范），想要改进
- 用户想要为 AI 编程助手写项目上下文文件（CLAUDE.md / .cursorrules / AGENTS.md）

## 工作流程

### 第一步：检测项目类型

执行 `scripts/detect_project.py <项目根目录>` 自动识别：

- 语言：Python（pyproject.toml / requirements.txt / setup.py）/ Node（package.json）/ Go（go.mod）/ Rust（Cargo.toml）
- 框架：Flask / FastAPI / Express / Go / Rust 五种**有模板**的栈；Django / Koa / NestJS / 纯标准库会被如实检测出来但**不提供模板**（见文末「检测到但不支持的框架」）
- 现状：是否已 git 化、是否已有 lint 配置、是否已有测试目录、是否已有 pre-commit / commit 模板 / AI 上下文文件

脚本输出 JSON，包含 `language`、`framework`、`existing_config`、`recommendations` 字段，决定后续步骤。**`framework` 以脚本判定为准，不要自己另做一套判断**（自己看目录结构或凭印象猜会和脚本结论打架）。

> 检测结果里出现 Django / Koa / NestJS / Next / Fastify 不是脚本故障——脚本如实报告看到了什么。模板覆盖范围与处理方式见文末降级表。

### 检测输出字段怎么用

`scripts/detect_project.py` 的输出就是后续动作的依据。**每个字段都有明确用途，照下表用，不要只挑 `framework` 看**：| 顶层字段 | 是什么 | 怎么用 |
|---|---|---|
| `ok` | 成功为 `true`；失败为 `false`，此时只有 `error` + `hint` | `false` 时**先按 `hint` 处置再重跑**，别继续往下走。失败输出的完整清单见 `references/troubleshooting.md` |
| `root` | 解析后的项目根目录绝对路径 | 确认脚本扫的是你以为的那个目录（macOS 上 `/tmp` 会显示成 `/private/tmp`） |
| `language` | 项目主语言（python / node / go / rust） | 决定读哪份语言约定文档，以及选哪套模板 |
| `language_evidence` | 命中了哪个标志文件（requirements.txt / package.json / go.mod …） | 跟用户核对「我按这个文件认的」 |
| `framework` | 判定出的框架名 | **仅当 `framework_needs_confirmation` 为 `false` 时才可当结论**。歧义时它仍会填某个候选值，照它走会套错栈 |
| `framework_candidates` | 全部候选，每个含 `name` / `confidence` / `source` / `evidence` | **念候选与依据给用户确认**。`evidence` 精确到「requirements.txt:1 依赖声明 flask==3.0.0」，比「你是 flask 项目」可信得多 |
| `framework_needs_confirmation` | `true` = 有歧义或杂音，需用户拍板 | `true` 时**禁止读 `framework` 当结论**（详见文末歧义行） |
| `existing_config` | 项目现状快照（10 个子键，见下表） | 决定「哪些要装、哪些别重复装」 |
| `recommendations` | **环境建议清单**（git init / 装 ruff / 装 pytest / 装 pre-commit / 配 commit 模板 / 建 CLAUDE.md） | 逐条征询用户后执行——**不是**「下一步跑 apply」。跑不跑 apply 由框架模板可用性决定，不由这份清单决定 |
| `warnings` | 解析失败、框架线索冲突等异常提示 | 有内容就要在给用户的总结里说一句，别静默忽略 |
| `meta` | 脚本名、schema 版本、`python_requires`、`toml_parser` | 解释器版本要求看 `meta.python_requires`（`>=3.11`）。注意 `meta` **只在成功输出里出现**——脚本报错时输出只有 ok / error / hint |

`existing_config` 的 10 个子键——**布尔值一律配证据字段用**：

| 子键 | 是什么 | 怎么用 |
|---|---|---|
| `is_git_repo` | 是否已 git 化 | 决定 `git init` 要不要提；也决定 commit 模板能不能生效 |
| `has_lint` | 是否已有 lint 配置 | `false` 才需要建议装 ruff / eslint |
| `lint_evidence` | lint 结论的**证据清单**（如 pyproject.toml 里的 [tool.ruff] 段） | **有内容就把证据念给用户**（「我看到 pyproject.toml 里已有 `[tool.ruff]`」），别只报一个 bool |
| `has_tests` | 是否已有测试 | `false` 才需要建议装 pytest / vitest |
| `test_evidence` | 测试结论的**证据清单**（如 tests/ 目录、tests/test_a.py） | 同上，念证据而不是只念 bool |
| `test_framework` | 识别出的测试框架（pytest / vitest / unittest / cargo test …） | 装测试框架时**先问现有的是什么，别覆盖**；也决定 02-test-generation prompt 的指令口径 |
| `has_pre_commit` | 是否已有 pre-commit 配置 | `false` 才需要装；且 `pre-commit install` 前必须问用户（会顶掉已有钩子） |
| `has_commit_template` | 是否已配 commit 模板 | `false` 才需要建议 `git config --local commit.template` |
| `has_claude_md` | 是否已有 CLAUDE.md | `true` 时改用「引导用户编辑」而不是「新建」 |
| `has_cursorrules` | 是否已有 .cursorrules | 同上，作为 AI 上下文文件的另一形态 |

> `lint_evidence` 里也会带 commit 模板的证据（形如 `.git/config commit.template = .gitmessage`）——commit 模板是记在 git 配置里而非独立文件，脚本统一归到证据清单。读证据时按内容判断即可。

> **布尔值 + 证据 = 说给用户听事实，不是说结论**。`has_lint: true` 单独抛给用户没有信息量，「你的 pyproject.toml 里已经有 `[tool.ruff]` 了，我就不装 ruff 了」才有。

### 第二步：读取对应框架的工程化约定

**按检测结果只读需要的那几个文件**，不要一次把所有 references 读进上下文（`references/` 共 10 个文件约 2100 行，全读会挤占大量上下文）：

| 检测到的项目类型 | 必读 | 按需加载 |
|---|---|---|
| Python + Flask | `references/python-conventions.md`、`references/python-flask.md` | `references/general-conventions.md` |
| Python + FastAPI | `references/python-conventions.md`、`references/python-fastapi.md` | `references/general-conventions.md` |
| Python + Django / 标准库 | `references/python-conventions.md` | `references/general-conventions.md` |
| Node + Express | `references/node-conventions.md` | `references/general-conventions.md` |
| Node + Koa / NestJS | `references/node-conventions.md` | `references/general-conventions.md` |
| Go | `references/go-conventions.md` | `references/general-conventions.md` |
| Rust | `references/rust-conventions.md` | `references/general-conventions.md` |
| 任意语言 | —— | `references/prompts-usage-guide.md`（要交付 prompt 时）、`references/claude-md-template-guide.md`（要定制 AI 上下文文件时）、`references/real-cases.md`（**按需加载**：买家想看真实案例或需要迁移踩坑细节时才读，332 行且不是配置依据） |

`references/general-conventions.md` 是 commit 规范 / 测试覆盖率方法论 / code review 五维度，**五种栈通用**，只在需要跨语言方法论时才追加读。

**脚本报错、结果不对劲、降级或歧义时**：读 `references/troubleshooting.md`（排错手册，含 5 类高频问题的真实输出与处置话术）。**它不是配置依据**，别在正常流程里预先加载——只在出错或遇到歧义时才读。

### 第三步：把工程化模板复制到项目

**先跑完第一步的 detect，再跑这一步。** 建议顺序：

```bash
python3 scripts/detect_project.py <项目根目录>          # 第一步：拿 recommendations / existing_config
python3 scripts/apply_templates.py <项目根目录> [--dry-run]   # 第三步：复制模板
```

`scripts/apply_templates.py` 内部会调用同目录的 `scripts/detect_project.py` 做框架推断（不跑第一步也能用），但**先跑 detect 能拿到 `recommendations` 与 `existing_config`——apply 不输出这两块**，而它们正是与用户确认的依据。

```bash
python3 scripts/apply_templates.py <项目根目录> [--framework flask|fastapi|express|go|rust] [--common] [--dry-run]
```

`scripts/apply_templates.py` 负责确定性的部分：调 detect 判定框架 → 选模板目录 → 复制 → 按内置映射表改名 → 建目标父目录 → 已存在的文件先备份为 .bak 再合并 → 给 git hook 加可执行权限。**框架推断的事实源是 `scripts/detect_project.py`，本脚本不自己另判**——所以两个脚本对同一项目必然给出同一个结论。

**模板文件名 → 项目内目标文件名**（脚本内置映射，照此执行）：

| 模板文件 | 复制到项目后改为 |
|---|---|
| gitmessage.txt | .gitmessage |
| claude-settings.json | .claude/settings.json（需先建 .claude 目录） |
| go.mod.txt | go.mod |
| golangci.yml | .golangci.yml |
| pre-commit-config.yaml | .pre-commit-config.yaml |
| prettierrc.json | .prettierrc |
| husky-pre-commit.txt | .husky/pre-commit（需先建 .husky 目录 + 加可执行权限） |
| rustfmt.toml | rustfmt.toml（**文件名不变**） |
| clippy.toml | clippy.toml（**文件名不变**） |

两条容易踩的规则：

- **rustfmt.toml / clippy.toml 是「文件名不变」的例外**，别照抄通则生成 .rustfmt.toml / .clippy.toml——Rust 工具链不读点开头的这两个文件，生成等于配置失效。
- **上表不是全集**：未登记的条目一律**沿用模板原名**（CLAUDE.md、pyproject.toml、package.json、eslint.config.js、rustfmt.toml、clippy.toml 都走这条）。

各语言模板包含（以映射前的模板名表示）：

- python-flask / python-fastapi：pyproject.toml / pre-commit-config.yaml / gitmessage.txt / CLAUDE.md / claude-settings.json
- node-express：package.json / eslint.config.js / prettierrc.json / husky-pre-commit.txt / gitmessage.txt / CLAUDE.md / claude-settings.json
- go：go.mod.txt / golangci.yml / gitmessage.txt / CLAUDE.md / claude-settings.json
- rust：rustfmt.toml / clippy.toml / pre-commit-config.yaml / gitmessage.txt / CLAUDE.md / claude-settings.json

**三条安全边界（买家信任的关键，读脚本输出时要看）**：

1. **默认拒绝覆盖依赖声明**：pyproject.toml / package.json / go.mod.txt 的内容就是项目的依赖声明，复制过去等于清空买家已装的依赖。脚本默认**拒绝复制**（输出 `status=rejected`、`risk=destructive`），要覆盖必须显式加 `--force`。**不要为了「装全」而顺手加 `--force`**——先问买家，或按下一节手动合并工具配置。
2. **Rust 项目的 Cargo.toml 既不提供也不覆盖**：Rust 项目已有 Cargo.toml，模板不重复提供。
3. **降级时框架模板一张都不复制**：见文末「检测到但不支持的框架」。降级指 `degraded=true` + `notice` + 框架模板零复制，只在带 `--common` 时给 5 个通用 prompt。

**看到 `rejected` 不等于装完了**：即使输出里 `ok` 为 `true`，只要 `summary.rejected` 大于 0，就说明**有文件没落地**（被拒的是依赖声明类文件）。此时**必须**按下一节手动处理，不能跟用户说「配置已全部装好」。

### 工具配置需要手动合入（pyproject.toml 被拒时必做）

Python 项目的 lint / test / coverage / commit 工具配置**全在pyproject.toml 里**，而这个文件被默认拒绝复制（原因见上一节第1 条）。所以它**不会**被自动装上——需要你手动把配置合进买家自己的 pyproject.toml。

**1. 从哪取（唯一可复制的源）**

配置在**对应栈的模板文件**里，不在 references 的讲解文字里：

| 买家项目栈 | 配置源文件（唯一可复制源） | 含几段`[tool.*]` |
|---|---|---|
| Python Flask | `assets/templates/python-flask/pyproject.toml` | 10 |
| Python FastAPI | `assets/templates/python-fastapi/pyproject.toml` | 12（= Flask 10 + tool.mypy + tool.pydantic-mypy） |
| Node Express | `assets/templates/node-express/package.json` | — |
| Go | `assets/templates/go/go.mod.txt` | — |

> FastAPI 比 Flask 多 tool.mypy、tool.pydantic-mypy 两段是**有意为之**：pydantic-mypy 插件是 FastAPI 生态特有的，flask 不引入 pydantic，搬过去对 flask 买家无意义。**不要为了「段数对齐」把这两段加进 flask 模板。**

> **务必提醒买家**：工具配置**只以 `assets/templates/<框架>/pyproject.toml` 为准**。`references/` 下两份文档也贴了 `[tool.*]` 片段，但**都是讲解用节选，照抄会静默漏配置**：
> - `references/python-conventions.md` —— 7 段，缺 tool.ruff.format / tool.coverage.html / tool.commitizen.changelog（**少 3 段**）
> - `references/python-flask.md` —— 4 段，**只有 ruff 相关 3 段 + tool.pytest.ini_options，coverage 与 commitizen 全都没有**（**少 6 段**）
> python-flask.md 那份漏掉的是整个 coverage 与 commitizen——而 `pytest --cov` 和 `git cz` 正是 CLAUDE.md 里要求买家做的事，漏了会导致「文档要求与实际配置不一致」。

**2. 合什么、从哪一行开始**

模板里 `[project]` 段在最前面，**它后面全部 `[tool.*]` 段就是要合入的工具配置**。给买家的操作边界：

- **从 `[tool.ruff]` 那一行开始**，一直复制到**文件末尾**
- Flask 栈 10 段：tool.ruff / tool.ruff.lint / tool.ruff.lint.per-file-ignores / tool.ruff.format / tool.pytest.ini_options / tool.coverage.run / tool.coverage.report / tool.coverage.html / tool.commitizen / tool.commitizen.changelog
- FastAPI 栈 12 段：上面 10 段 + tool.mypy / tool.pydantic-mypy

**3. 别动什么**

**`[project]` 段必须保留买家自己的值**——`name` / `version` / `requires-python` / `dependencies`（含全部依赖清单）。模板里那些是占位值（如 `name = "flask-app"`），覆盖上去等于把买家项目的名字和依赖清空，这正是脚本拒绝复制的原因。

**4. 怎么合（已有同名段时）**

若买家 pyproject.toml 里已经有 `[tool.xxx]` 段，**把模板里的子项并进去，不要整段覆盖**——否则会丢掉买家已有的配置值。

**5. 合完怎么校验**

```bash
grep -c '^\[tool\.' pyproject.toml     # 应 > 0（Flask 模板全量 10，FastAPI 12）
ruff check .                # 能跑通即配置生效；报未安装则先 pip install ruff
```

> `grep -c` 数的是段数。合并后可能少于模板全量（若买家本来就没配commitizen / mypy），只要 `ruff check .` 能跑通即视为成功。

**6. 顶层提醒怎么给**

若 apply_templates.py 的输出里有 `rejected` 条目或顶层 `notice` 提示，**要在给用户的总结里明确说**：本项目的工具配置（ruff / pytest / coverage / commitizen）需要按本节手动合并，已装好的是哪些、还差哪些。不要含糊地说「已完成配置」。

其他参数：

- `--dry-run` 只打印计划、**不写盘（实测磁盘零变化）**，**建议买家先跑一次**看清楚了再实跑
- 不给 `--framework` 时脚本按 detect 的判定结果行动；**识别不出具体框架时不会套用任何框架模板**（纯标准库项目同样降级），此时改读 `references/` 下的通用与语言约定文档手工落地；若项目确实用了 Flask/FastAPI/Express，可显式 `--framework <框架>` 覆盖后重跑

**框架判定有歧义时会停下不复制**（`degraded: true` + `needs_confirmation: true`，框架模板一张都不复制）：

项目里出现**多个框架候选**时（两个及以上高置信度，或高置信度之外还有低置信度杂音），脚本**不猜**，改为把候选和依据交给用户确认。此时：

1. **不要读 `framework` 字段当结论** —— `scripts/detect_project.py` 歧义时它仍会填其中一个候选值（实测：同时声明 flask+fastapi 会返回 `framework: fastapi`），照着它走会把模板配错栈。**以 `needs_confirmation: true` + `framework_candidates` 为准。**（`scripts/apply_templates.py` 的输出更严格：歧义时它把 `framework` 置为 `null`，原始值另存到 `framework_detected_but_ambiguous`。）
2. 把 `framework_candidates` 里的候选与依据**念给用户**确认。每项含 `name` / `confidence` / `source` / `evidence`，例如「依据 requirements.txt:1 依赖声明 flask==3.0.0」——买家看到依据比看到「你是 flask 项目」可信得多。
3. 用户确认后用 `--framework <框架>` 显式指定重跑（实测可正常复制）。

**注释里提到另一个框架也会停手**（实测，别当成杂音放过）：`requirements.txt` 里 `flask==3.0.0` 加一行注释 `# TODO: maybe fastapi later`，fastapi 只是 **low**（仅注释提及），但 `framework_needs_confirmation` 仍为 `true`，`scripts/apply_templates.py` 会输出 `ok: false` / `framework: null` / 零复制并要求显式指定。判定依据看 high 候选数，**不等于**只有多个 high 才拦。

| 情况 | confidence | 脚本行为 |
|---|---|---|
| 真依赖声明里的框架名 | high | 参与框架判定 |
| 注释 / description 里提到的框架名 | low | **不参与框架选定**，但**足以触发停手**，仅在候选列表里留痕供你参考 |

**装依赖 / 配 git / 装钩子不归脚本做**，请逐条征询用户后再执行：

| 动作 | 命令 | 征询要点 |
|---|---|---|
| 装 lint + format | `pip install ruff` / `npm i -D eslint prettier` / `go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest` | 确认包管理器（pip / poetry / uv / pnpm / yarn）与是否允许联网 |
| 装测试框架 | `pip install pytest pytest-cov` / `npm i -D vitest` | 问清现有测试框架，不要覆盖 |
| 启用 commit 模板 | `git config --local commit.template .gitmessage` | `--local` 只影响当前仓库 |
| 装 pre-commit 钩子 | `pre-commit install` | **会接管用户已有钩子，必须先问**（实测 pre-commit 4.x 把原钩子挪到 `.git/hooks/pre-commit.legacy`，加 `-f` 会连 legacy 一起删掉） |

> 为什么不写进脚本：包管理器形态不可预测（poetry/uv vs 裸 pip、pnpm/yarn vs npm），`go install` 可能成功但 GOPATH/bin 不在 PATH（比失败更糟），离线或内网环境无解。这些失败模式对付费用户不可预测，所以一律由你逐条确认。

### 第四步：定制 AI 上下文文件

引导用户编辑复制过去的 CLAUDE.md（工具不认这个文件名时改用 .cursorrules 或 AGENTS.md），按以下结构填入项目实际情况：

1. **项目概况**：类型、架构、数据库、语言版本
2. **工程约定**：代码风格、模块组织模式、配置分场景、安全规范、测试规范、commit 规范、日志
3. **当前进度**：已完成的功能模块、下一步要做什么
4. **AI 工作注意事项**：改代码前先看测试、不要静默 fallback、不要写 print、改完跑测试等
5. **项目专属术语**：表名、模块名、内部黑话

参考 `references/claude-md-template-guide.md` 获取每个字段的填写指南和真实案例。

### 第五步：交付 5 个核心 AI 辅助开发 Prompt

从 `assets/templates/common/prompts/` 复制 5 个 prompt 模板到项目的 `prompts/` 目录（`scripts/apply_templates.py --common` 可代劳）：

1. 01-new-feature.md —— 新功能开发 prompt（按检测到的框架给具体指令）
2. 02-test-generation.md —— 测试生成 prompt（按检测到的测试框架给指令）
3. 03-code-review.md —— 代码 review prompt（语言无关，5 维度审查）
4. 04-commit-message.md —— commit message 生成 prompt（按 Conventional Commits）
5. 05-doc-generation.md —— 文档生成 prompt（README/API/CHANGELOG 三种）

这 5 个是**语言无关**的，**降级状态下（django / koa / nestjs / 纯标准库）`--common` 依然可用**——降级只意味着框架模板一张不复制。

每个 prompt 文件含：使用场景、完整 prompt 模板、真实案例、反例。引导用户阅读 `references/prompts-usage-guide.md` 了解何时用哪个。

## 核心能力

1. **五种技术栈开箱模板** —— Python Flask / Python FastAPI / Node Express / Go / Rust，各含 lint、test、commit、pre-commit、AI 上下文全套配置
2. **一键检测** —— 自动识别项目语言与框架，不需要用户告诉
3. **零覆盖安装** —— 已有配置文件先备份为 `.bak` 再合并，不破坏用户现有设置
4. **AI 上下文定制** —— 引导用户写一份让 Claude/Cursor 立刻懂项目规矩的 CLAUDE.md
5. **5 个核心 prompt** —— 覆盖新功能 / 测试 / review / commit / 文档五大场景

**框架判定只认真实依赖声明**——注释和描述字段里出现的框架名不会误导模板选择。举两个买家真会踩的例子：

- `requirements.txt` 写着 `flask==3.0.0`，下面一行注释 `# TODO: maybe fastapi later` → 仍正确判为 Flask，套 Flask 模板（若按注释判成 FastAPI，会把满是 FastAPI 术语的 CLAUDE.md 写进真Flask 项目）
- package.json 的 `description` 写着 "a koa-style service"，实际 devDependencies 是 express → 正确判为 Express

判定依据会随 `framework_candidates` 一并输出（含 `source` 与 `evidence`，精确到「requirements.txt:2 依赖声明 fastapi==0.111.0」），你可以直接把它念给用户。

## 真实背景

本 Skill 的工程化约定提炼自一个**持续维护多年、经过生产环境验证的真实 Flask 项目**——约定来自实际跑通的工程实践，不是从文档抄来的理想清单。具体案例见 `references/real-cases.md`，包含：

- 密码明文 → scrypt 哈希迁移（零停机）
- 配置分场景 Dev/Test/Prod（SECRET_KEY 缺失直接抛错，不静默 fallback）
- 覆盖率补测实战（含 conftest 模块缓存陷阱这个真实 bug）

> 案例中的覆盖率数字是该历史项目的当时实测值，不是本 Skill 的承诺，也与模板无关——模板里的 coverage 配置按买家项目自己的目录自适应。

## 不在本 Skill 范围

- 不替用户写业务代码（这是 AI 编程助手的活，本 Skill 只搭工作流）
- 不提供具体语言的教程（用户应已会基础语法）
- 不做 CI/CD 流水线与容器编排（不提供 GitHub Actions / Dockerfile / docker-compose 模板，这类基础设施请交给现有 DevOps 方案）
- 不装依赖、不改 git config、不执行 `pre-commit install`（这些动作由你逐条征询用户后执行，理由见第三步）

## 检测到但不支持的框架（降级说明）

检测脚本会如实报告它看到的框架。**只有下面五种栈有模板**：

| 检测到的 framework | 有模板？ | 脚本行为 | 该怎么告诉用户 |
|---|---|---|---|
| flask / fastapi / express / go / rust | ✅ 有 | 正常复制该栈模板 | 正常走第三步 `scripts/apply_templates.py` |
| django | ❌ 无 | `degraded=true`，框架模板零复制 | 直说「识别到 Django，本 Skill 不提供 Django 模板」，然后只用 `references/python-conventions.md` 的语言无关部分（工具链、测试、commit 规范）；Django 的分层与 ORM 约定请用户对照自己项目现状判断 |
| koa / nestjs / next / fastify | ❌ 无 | `degraded=true`，框架模板零复制 | 直说「识别到 Koa/NestJS/Next/Fastify，本 Skill 不提供对应模板」，只用 `references/node-conventions.md`（lint / test / commit / pre-commit 均与框架无关，可直接用） |
| python-stdlib / node-stdlib（纯标准库，未识别出具体框架） | ❌ 无 | `degraded=true`，框架模板零复制 | 直说「未识别出具体框架，脚本没有套用任何框架模板」，按 `references/python-conventions.md` / `references/node-conventions.md` 的通用部分手工落地。**若项目确实用了 Flask/FastAPI/Express**，可显式 `--framework <框架>` 覆盖后重跑 |
| 多个候选并存（歧义，含 low 置信度杂音） | ❌ 暂停 | `degraded=true` + `needs_confirmation=true`，框架模板零复制 | **别读 `framework` 字段**（detect 歧义时它仍填某个候选值，apply 置 null），把 `framework_candidates` 的候选与依据念给用户确认，再用 `--framework <框架>` 重跑。见第三步「框架判定有歧义时会停下不复制」 |

> Go / Rust 项目即使不用标准库框架（gin、echo、axum、actix-web、rocket 等），也归入 `go` / `rust` 栈照常套模板——那些栈的工程约定是语言级、与具体框架无关。

**关键**：这是**能力边界，不是检测失败**。不要说成「没检测出来」或「检测失败」——脚本工作正常，它只是看到了本 Skill 没有模板的框架。含糊其辞会让买家以为装坏了。

## 校验说明（给后续维护者，勿据此删反引号）

链接检查工具会扫描行内代码里的 token，只要含 `/` 或带文件扩展名就尝试按路径解析。这对本Skill 的**教学性内容**会产生系统性误报。

以下写法是**有意为之，请勿"修复"**：

| 现象 | 例子 | 为什么必须保留反引号 |
|---|---|---|
| 代码符号被误判为文件 | os.Getenv、process.env、app.logger、log.Fatal、datetime.UTC、datetime.timezone.utc | 教 Go/Node/Python 项目怎么写代码，去掉代码格式等于降低教学价值 |
| 带扩展名的裸标识符 | _test.go、lib.rs、main.rs、.env、.bak | 是 Go/Rust 的文件命名约定说明，不是路径引用 |
| 第三方模块路径 | golang.org/x/crypto/bcrypt、golang-jwt/jwt/v5、testify/assert、testify/mock | **核心教学内容**：告诉买家 Go 项目怎么引 bcrypt 与 JWT |
| JS 语法名 | async/await、import/export、require/module.exports | 是语法术语，不是路径 |
| 项目内示意路径 | /health/live、/health/ready、src/config/index.js | 给买家示例项目结构用，本就不存在于本 Skill 内 |

判断标准很简单：**`(本技能目录 / token)` 不存在，且该token 是代码标识符或示例路径 → 是误报，保留原样**。反之若它确实是本 Skill 内的文件却写错了路径，那才是真断链，必须改。

> 校验器现状：`excel-to-report` 0 error / 0 warning；`ai-dev-workflow` 的历史 24 条 E-BROKEN-LINK 经逐条核实**全部属于上表误报**，已确认无需修改文档。

## 更新记录

- **v1.3.1（2026-10-21）**：SkillHub 上的 `ai-dev-workflow` slug 已被他人占用（归属 `@indiv-wangjiaocheng`，852 下载），故本仓库与后续上架统一改用 `ai-dev-workflow-langery`；内容与 v1.3.0 一致
- **v1.3.0（2026-10-21）**：新增 `references/troubleshooting.md` 排错手册（脚本错误 / 降级 / 歧义 / 配置不落地 / 环境类 5 类问题的真实输出与处置话术）；第一步后补「检测输出字段怎么用」小节（顶层 11 键 + `existing_config` 10 子键逐字段说明，强调布尔值要配证据字段念给用户、`recommendations` 是环境建议清单而非「下一步跑 apply」）；修正 v1.2.0 两处与实现不符的描述——低置信度注释框架**也会**触发停手（实测 `ok: false` / 零复制，非「仍正常复制 5 个文件」）、`pre-commit install` 是**接管**已有钩子并备份到 `.git/hooks/pre-commit.legacy`（非「静默覆盖」）；补 references/python-fastapi.md 围栏内 `[tool.*]` 段数为 0 的事实
- **v1.2.0（2026-10-19）**：能力与实现对齐——检测到的 Django / Koa / NestJS / Next / Fastify / 纯标准库明确降级为「不提供模板」并给出话术；删除不存在的 install_workflow.py 与 CI/CD、容器编排承诺；删除脚本不支持的覆盖率宣称；补 `scripts/apply_templates.py` 真实用法、完整改名映射表（含 rustfmt/clippy 文件名不变的例外）、依赖声明默认拒绝覆盖的安全边界、降级时 `--common` 仍可用；新增框架判定歧义时停下并念依据给用户的处理规范、注释里的框架名不参与判定的说明；新增 references 加载矩阵表；补齐 marketplace 发布字段
- **v1.1（2026-10-16）**：新增 Rust 模板集（rustfmt/clippy/pre-commit/gitmessage/CLAUDE.md/claude-settings，对齐 references/rust-conventions.md 约定）；SKILL.md 第三步补齐 rust 映射；明确 Rust 项目不覆盖已有 Cargo.toml
- **v1.0（2026-10-12）**：首发。多语言检测 + 四框架模板 + 5 个核心 prompt
