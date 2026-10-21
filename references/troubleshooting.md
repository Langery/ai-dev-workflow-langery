# 排错手册

买家实测最常撞上的 5 类问题及处置。每条都写明**脚本的真实输出**（不是推测），照着念给用户即可。

**读之前先确认**：本文只覆盖「脚本跑完了但结果不对劲」和「脚本报错了」两类。配置怎么落地看 SKILL.md 第三步；技术栈约定看各语言文档。

---

## 1. 脚本类错误

`../scripts/detect_project.py` 与 `../scripts/apply_templates.py` 出错时都输出 JSON、退出码 1，`ok` 为 `false`。**先看 `error` 字段定位原因，`hint` 字段是脚本给出的处置建议**。

### 1.1 Python 版本过低

`../scripts/detect_project.py` 依赖标准库 `tomllib`（Python 3.11+）解析 pyproject.toml / Cargo.toml。低版本解释器跑不动：

```json
{
  "ok": false,
  "error": "当前 Python 缺少标准库 tomllib",
  "hint": "本脚本需要 Python 3.11+（用于结构化解析 pyproject.toml / Cargo.toml），请升级解释器后重试"
}
```

**处置**：换 3.11+ 解释器重跑，别改脚本。注意这条失败输出**只有 ok / error / hint 三个字段，没有 meta**——`meta` 只在成功输出里出现。成功时 `meta.python_requires` 会写明 `"python_requires": ">=3.11"`。

### 1.2 路径不存在 / 路径不是目录

路径不存在：

```json
{
  "ok": false,
  "error": "路径不存在: /private/tmp/aidw_fx/does_not_exist",
  "hint": "确认项目根目录路径拼写正确"
}
```

误传了目录里的**某个文件**（而不是根目录）：

```json
{
  "ok": false,
  "error": "路径不是目录: /private/tmp/aidw_fx/flask_app/requirements.txt",
  "hint": "请传入项目根目录，而不是其中的某个文件"
}
```

**处置**：路径拼错或目录真不存在。注意 `error` 里的路径是**解析后的绝对路径**（macOS 上 `/tmp` 会显示成 `/private/tmp`），别被这个前缀晃到。

### 1.3 未识别出项目语言（空目录 / 指错层级）

**这是空目录的真实报错，不是「路径不对」**——两者是不同错误，靠 `error` 字段区分：

```json
{
  "ok": false,
  "error": "未识别出项目语言",
  "hint": "项目根目录下找不到 pyproject.toml / requirements.txt / package.json / go.mod / Cargo.toml。确认路径是否指向项目根目录；若是语言无关项目，直接参考 references/general-conventions.md"
}
```

**处置**：确认路径指向的是**项目根目录**而不是它的子目录——脚本只在根目录找标志文件（pyproject.toml / requirements.txt / setup.py / setup.cfg / Pipfile / package.json / go.mod / Cargo.toml）。指向子目录时**同样报这个错**，不是「路径不存在」。

传空目录、传子目录、完全不存在的路径，三种情况分别是：未识别出项目语言 / 未识别出项目语言 / 路径不存在。脚本不传路径时默认当前目录。

### 1.4 `../scripts/apply_templates.py` 找不到 `../scripts/detect_project.py`

`../scripts/apply_templates.py` 靠同目录的 `../scripts/detect_project.py` 做框架推断（单一事实源）。该文件缺失时报错并给出绕过办法：

```json
{
  "ok": false,
  "error": "框架推断失败：未找到 /private/tmp/.../scripts/detect_project.py",
  "hint": "本脚本依赖同目录的 scripts/detect_project.py 做框架推断（单一事实源）。未找到 ...。请确认该文件存在且完整（必要时重新安装本 Skill），或用 --framework <express / fastapi / flask / go / rust> 显式指定框架绕过推断。"
}
```

**处置**：重新安装本 Skill；或加 `--framework <框架>` 显式指定绕过推断（实测可正常复制）。

> **另一种形态：文件在但损坏**（语法错误）——此时脚本**抛 Python traceback 而非输出 JSON**。看到 traceback 就说明 `../scripts/detect_project.py` 本身坏了，重装 Skill；`--framework` 同样能绕过（实测 `--framework flask` 在该状态下正常出结果）。

### 1.5 `../scripts/apply_templates.py` 找不到模板目录

```json
{
  "ok": false,
  "error": "模板目录不存在：/private/tmp/.../assets/templates",
  "hint": "确认本 Skill 的 assets/templates/ 是否完整（重新安装本 Skill），或用 --framework 显式指定框架后再试。"
}
```

**处置**：重装 Skill。这与 1.4 是两回事：1.4 缺的是推断脚本，本条缺的是模板资产，**重装能同时修好两者**。

---

## 2. 降级场景（识别到框架但没有模板）

`django` / `koa` / `nestjs` / `next` / `fastify` / 纯标准库项目，脚本**如实报出识别结果**，但本 Skill 没有对应模板。

### 2.1 降级时的输出长什么样

`../scripts/apply_templates.py` 输出 `degraded: true` + `notice`，**框架模板零复制**（`results` 为空数组，summary.total 为 0）：

```json
{
  "ok": true,
  "mode": "copy",
  "framework": "django",
  "results": [],
  "summary": { "created": 0, "skipped": 0, "backed_up": 0, "rejected": 0, "renamed": 0, "total": 0 },
  "degraded": true,
  "notice": "检测到 Django 项目，但本 Skill 不提供 Django 的模板，已降级为「通用约定」：未复制任何框架模板。请改为读取 references/ 下的通用与语言约定文档手工落地配置。"
}
```

各框架的 `notice` 文案实测如下（措辞随框架名变，结构一致）：

| 识别结果 | notice 开头 |
|---|---|
| django | 检测到 Django 项目，但本 Skill 不提供 Django 的模板 |
| koa | 检测到 Koa 项目，但本 Skill 不提供 Koa 的模板 |
| nestjs / next / fastify | 同上，框架名替换 |
| python-stdlib | 检测到纯 Python 标准库项目（未识别出 Flask / FastAPI / Django） |
| node-stdlib | 检测到纯 Node 标准库项目（未识别出 Express / Koa / NestJS） |

### 2.2 `--common` 在降级下仍可用

降级只砍框架模板，**通用 prompt 模板照发**：

```json
{ "ok": true, "degraded": true, "summary": { "created": 5, "total": 5 } }
```

5 个 prompt 落在项目 `prompts/` 目录（01-new-feature / 02-test-generation / 03-code-review / 04-commit-message / 05-doc-generation）。

### 2.3 怎么跟用户说

**这是能力边界，不是检测失败。** 脚本工作正常——它看到了本 Skill 没有模板的框架。照实说：

> 「检测到你这是 Django 项目。本 Skill 的模板覆盖 Flask / FastAPI / Express / Go / Rust 五种栈，没有 Django 模板，所以没有复制任何框架文件。lint / 测试 / commit 规范这些是语言级的、与框架无关，我按 `python-conventions.md` 的通用部分给你手工落地。Django 的分层与 ORM 约定需要你对照自己项目现状判断。」

**别说成**「没检测出来」「检测失败」——那会让买家以为装坏了。

---

## 3. 歧义场景（框架判不出来）

### 3.1 两个框架都是真依赖

requirements.txt 同时写 `flask==3.0.0` 和 `fastapi==0.111.0`，`../scripts/detect_project.py` 输出：

```json
{
  "ok": true,
  "framework": "fastapi",
  "framework_candidates": [
    { "name": "fastapi", "evidence": ["requirements.txt:2 依赖声明 fastapi==0.111.0"], "confidence": "high", "source": "requirements.txt" },
    { "name": "flask", "evidence": ["requirements.txt:1 依赖声明 flask==3.0.0"], "confidence": "high", "source": "requirements.txt" }
  ],
  "framework_needs_confirmation": true,
  "recommendations": ["框架判定有歧义（候选：fastapi/flask）：先与用户确认用哪套，再 --framework <框架> 显式指定后跑 ...；判定未完成前不要假定某个候选就是正确框架"],
  "warnings": ["除已选框架 fastapi 外，还有其它框架线索（flask[high]），请与用户确认后再选模板"]
}
```

**三个要点**：

1. `../scripts/detect_project.py` 的 `framework` 字段**仍会填一个候选**（实测填 `fastapi`，按注册表优先级排第一个 high 候选）——**不能读它当结论**。判据是 `framework_needs_confirmation: true` + `framework_candidates`。
2. `recommendations` 的**第一条变成歧义提示**，不再是「把 X 模板复制进项目」。这正是脚本防止模型顺着 `framework` 字段走错栈的机制。
3. `../scripts/apply_templates.py` 在这一步**停手不复制**，且把 `framework` 字段**置 null**、原始值另存到 `framework_detected_but_ambiguous`：

```json
{
  "ok": false,
  "framework": null,
  "framework_detected_but_ambiguous": "fastapi",
  "needs_confirmation": true,
  "degraded": true,
  "results": [],
  "summary": { "created": 0, "skipped": 0, "backed_up": 0, "rejected": 0, "renamed": 0, "total": 0 },
  "error": "框架判定存在歧义（python 项目），已停止复制框架模板",
  "hint": "检测到多个框架候选（fastapi / flask），无法确定该套哪套模板，已【不复制任何模板】（未写入任何文件）。..."
}
```

> **两个脚本的字段名不一样，别混**：`../scripts/detect_project.py` 用 `framework_needs_confirmation`；`../scripts/apply_templates.py` 用 `needs_confirmation`（多一个 `framework_detected_but_ambiguous` 字段）。**`framework` 置 null 只发生在 `../scripts/apply_templates.py` 的输出里**——`../scripts/detect_project.py` 的 `framework` 仍有值。

**处置**：把 `framework_candidates` 里的候选与依据**念给用户**确认（每项含 `name` / `confidence` / `source` / `evidence`，如「依据 requirements.txt:1 依赖声明 flask==3.0.0」）。用户拍板后用 `--framework <框架>` 显式指定重跑（实测可正常复制）。

### 3.2 注释里提到另一个框架

requirements.txt 写 `flask==3.0.0`，下面一行 `# TODO: maybe fastapi later`：

```json
{
  "framework": "flask",
  "framework_candidates": [
    { "name": "flask", "confidence": "high", "source": "requirements.txt" },
    { "name": "fastapi", "evidence": ["requirements.txt:2 仅注释提及: # TODO: maybe fastapi later"], "confidence": "low", "source": "comment" }
  ],
  "framework_needs_confirmation": true,
  "warnings": ["除已选框架 flask 外，还有其它框架线索（fastapi[low]），请与用户确认后再选模板"]
}
```

**同样会停手**。`../scripts/apply_templates.py` 实测输出 `ok: false` / `framework: null` / `framework_detected_but_ambiguous: "flask"` / `degraded: true` / 零复制，`hint` 里同时列出 `flask[high]` 与 `fastapi[low]` 两条依据。

**处置**：同 3.1——念候选与依据，用户确认后 `--framework flask` 重跑。`low` 置信度**不参与模板选择**（`framework` 仍取 high 那条），但**足以触发停手**：猜错的代价（发一整套错栈的 CLAUDE.md / pre-commit）远大于多问一句的代价。

### 3.3 三种判定的对照

| 依赖声明 | 候选 | `framework` | `framework_needs_confirmation` | `../scripts/apply_templates.py` 行为 |
|---|---|---|---|---|
| 只有 `flask==3.0.0` | flask[high] | flask | false | 正常复制 flask 模板 |
| flask + 注释提 fastapi | flask[high] + fastapi[low] | flask | **true** | **停手，零复制** |
| flask + fastapi 都声明 | flask[high] + fastapi[high] | fastapi（取第一个 high） | **true** | **停手，零复制** |

---

## 4. 配置不落地（最高频卡点）

### 4.1 现象：`ok` 是 `true`，但工具配置没装上

Python 项目的 lint / test / coverage / commit 工具配置**全在 pyproject.toml 里**，而这个文件是项目的依赖声明，脚本**默认拒绝复制**：

```json
{
  "template": "pyproject.toml",
  "target": "pyproject.toml",
  "status": "rejected",
  "risk": "destructive",
  "reason": "该文件即项目依赖/模块声明，覆盖会清空现有依赖，已拒绝复制。⚠ 依赖它才能生效的工具配置因此【没有落地】：..."
}
```

**注意 `ok` 仍然是 `true`**——这最容易骗过买家。顶层三个字段专门用来暴露这件事：

| 字段 | 实测值 | 怎么读 |
|---|---|---|
| `rejected_files` | `[{"template": "pyproject.toml", "target": "pyproject.toml", "risk": "destructive"}]` | 哪些文件被拒了 |
| `requires_manual_merge` | `true` | 需要手动合入 |
| `manual_merge_notice` | 「有 1 个依赖/模块声明文件被拒绝复制（pyproject.toml）。这不是可选提示：依赖它们的配置【没有落地】。落位的 CLAUDE.md 若要执行 ruff / pytest / coverage / git cz / golangci-lint / rustfmt / clippy 等命令，而项目里尚无对应配置，它们会直接报错。请按下方 rejected_files 定位原因...只合并工具配置段（[tool.*] 等），不要合并 [project] / module / dependencies 段。」 | 完整处置说明 |

**判定口诀：`summary.rejected > 0` ⇒ 有文件没落地。** 此时**必须**按 SKILL.md「工具配置需要手动合入」小节处理，**不能跟用户说「配置已全部装好」**。

### 4.2 各栈实际段数（真值）

**唯一可复制源是 `../assets/templates/<栈>/pyproject.toml` 里的 `[tool.*]` 段。** 逐行数 `startswith("[tool.")` 得到的真实段数：

| 来源 | `[tool.*]` 段数 | 说明 |
|---|---|---|
| `../assets/templates/python-flask/pyproject.toml` | **10** | tool.ruff / tool.ruff.lint / tool.ruff.lint.per-file-ignores / tool.ruff.format / tool.pytest.ini_options / tool.coverage.run / tool.coverage.report / tool.coverage.html / tool.commitizen / tool.commitizen.changelog |
| `../assets/templates/python-fastapi/pyproject.toml` | **12** | 上面 10 段 + tool.mypy / tool.pydantic-mypy |
| `python-conventions.md` 围栏内 | **7** | 讲解节选，**缺 3 段**（tool.ruff.format / tool.coverage.html / tool.commitizen.changelog） |
| `python-flask.md` 围栏内 | **4** | 只有 ruff 相关 3 段 + tool.pytest.ini_options，**coverage 与 commitizen 一段都没有**（少 6 段） |
| `python-fastapi.md` 围栏内 | **0** | 该文**不含任何 `[tool.*]` 段**，FastAPI 买家别去这里找配置 |

> `references/` 下那几份文档贴的 `[tool.*]` 都是**讲解用节选，照抄会静默漏配置**。python-flask.md 那份漏掉整个 coverage 与 commitizen——而 `pytest --cov` 和 `git cz` 正是 CLAUDE.md 里要求做的事，漏了会导致「文档要求与实际配置不一致」。

### 4.3 合并时只碰工具段

- **从 `[tool.ruff]` 那一行开始，复制到文件末尾。**
- **`[project]` 段必须保留买家自己的值**——`name` / `version` / `requires-python` / `dependencies`（含全部依赖清单）。模板里那些是占位值（如 `name = "flask-app"`），覆盖上去等于把买家项目的名字和依赖清空——这正是脚本拒绝复制的原因。
- 买家已有的同名 `[tool.xxx]` 段：**把模板里的子项并进去，不要整段覆盖**，否则会丢掉买家已有的配置值。

---

## 5. 环境类问题

以下三类**脚本都不管**——`../scripts/apply_templates.py` 不会碰 `.git/hooks`，也不会执行任何安装命令。必须你逐条征询用户后再执行。

### 5.1 `pre-commit install` 会顶掉已有钩子

实测 pre-commit 4.7.0 的行为：它**把已有钩子迁移到 `.git/hooks/pre-commit.legacy`**，然后自己接管 `.git/hooks/pre-commit`，并打印：

```
Running in migration mode with existing hooks at .git/hooks/pre-commit.legacy
Use -f to use only pre-commit.
```

所以**原钩子不会丢**（留在 `.legacy` 里），但**从此你的钩子不再执行**。加 `-f`（`--overwrite`）会**连 `.legacy` 一起删掉**，原钩子彻底没了。

**处置**：**必须先问用户**。说明「pre-commit 会接管 pre-commit 钩子，原有的挪到 `.git/hooks/pre-commit.legacy` 保留着；要彻底丢弃请加 `-f`」，让用户选。

### 5.2 `.gitmessage` 落位了但 `git config` 会失败

非 git 仓库里 `git config --local commit.template .gitmessage` 直接报错（实测退出码 128）：

```
fatal: --local can only be used inside a git repository
```

`.gitmessage` 文件本身**照常落位**（`../scripts/apply_templates.py` 复制它不依赖 git），但没有 git 仓库时它是一张废纸。脚本在 `results[].reason` 里已注明：

> 复制完成；⚠ 当前项目还不是 git 仓库，本模板暂时无法生效，需先 git init 再执行 git config --local commit.template .gitmessage

**处置**：先 `git init`，再执行 `git config --local commit.template .gitmessage`。

### 5.3 coverage 的 source 写死了目录名

Flask 栈模板里 `source = ["blueprints", "common"]`、FastAPI 栈是 `source = ["app"]`——都是**照着原项目目录结构写死的**。买家项目没有这些目录时，`pytest --cov` 会连报三条**警告**（不是错误，**测试仍判通过、退出码 0**）：

```
CoverageWarning: Module blueprints was never imported. (module-not-imported)
CoverageWarning: Module common was never imported. (module-not-imported)
CoverageWarning: No data was collected. (no-data-collected)
CovReportWarning: Failed to generate report: No data to report.
```

**处置**：把 `source` 改成买家项目真实的包目录名（如 `["src"]`）。**注意这不会让测试变红**——测试照样 PASS，只是不产出覆盖率报告。别把「测试通过」当成「覆盖率配置生效了」。

---

## 6. 快速索引

| 现象 | 根因 | 处置 | 详见 |
|---|---|---|---|
| `error: 当前 Python 缺少标准库 tomllib` | 解释器 < 3.11 | 换 3.11+ 重跑 | 1.1 |
| `error: 路径不存在: …` | 路径拼错 | 核对路径 | 1.2 |
| `error: 路径不是目录: …` | 误传了目录里的文件 | 改传项目根目录 | 1.2 |
| `error: 未识别出项目语言` | 路径不是项目根目录 | 指向根目录（不是子目录） | 1.3 |
| `error: 框架推断失败：未找到 …/detect_project.py` | 推断脚本缺失 | 重装 Skill 或 `--framework` | 1.4 |
| Python traceback（无 JSON） | 推断脚本损坏 | 重装 Skill 或 `--framework` | 1.4 |
| `error: 模板目录不存在: …` | 模板资产缺失 | 重装 Skill | 1.5 |
| `degraded: true` + 零复制 | 框架无模板 | 能力边界说明 + 读语言约定文档 | 2 |
| `framework_needs_confirmation: true` | 框架判定有歧义 | 念候选与依据，用户确认后 `--framework` | 3 |
| `ok: true` 但 `summary.rejected > 0` | 依赖声明文件被拒 | 手动合入 `[tool.*]` 段 | 4 |
| `pytest --cov` 报 No data was collected | coverage source 目录名对不上 | 改 `source` 为真实包目录 | 5.3 |
| `git config --local` 报 `--local can only be used inside a git repository` | 项目还没 git init | 先 `git init` | 5.2 |
| 原有 pre-commit 钩子不跑了 | 被 pre-commit 接管 | 问用户是否用 `-f` | 5.1 |
