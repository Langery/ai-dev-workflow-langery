#!/usr/bin/env python3
"""
apply_templates.py - 把本 Skill 自带的工程化模板复制到目标项目（改名 + 建目录 + 备份 + 授权）

Usage:
    apply_templates.py <项目根目录> [options]

Options:
    --framework <flask|fastapi|express|go|rust>   指定框架；不给则按项目清单文件存在性推断
    --common                额外复制 assets/templates/common/prompts/ 下 5 个 prompt 模板
    --dry-run               只输出计划，绝不写盘
    --force                 允许覆盖已存在文件（先备份），并放行危险文件
    --selftest              运行内置自检（不需要项目目录）

Output:
    统一 JSON 到 stdout，结构见 README 说明。退出码：成功 0，失败 1。

设计边界（重要，不要在后续迭代中悄悄推翻）：
    本脚本只做「确定性文件搬运」——复制、改名、建目录、不覆盖备份、chmod。
    本脚本【不装任何依赖】、不改 git config、不跑 pre-commit install、不执行项目内任何脚本。
    原因：包管理器形态不可预测（poetry/uv/pipx vs 裸 pip、pnpm/yarn vs npm），
    `go install` 可能成功但 GOPATH/bin 不在 PATH（比失败更糟），离线/内网环境无解，
    pre-commit install 可能静默覆盖用户已有钩子。这些失败模式对付费用户不可预测且成本不对称。
    装依赖 / git config / pre-commit install 一律降级为「由模型逐条征询用户后执行」。

    同理，框架判定【一律以 detect_project.py 的 framework_for_templates() 为准】，
    本脚本不保留任何自己的推断逻辑——两份逻辑必然漂移，漂移会让买家拿到与
    检测结论互相矛盾的模板。detect 给出 needs_confirmation=True 时【一律停手】：
    返回 ok:false 且 framework=null（刻意置空，别让调用方读到一个候选值当结论），
    不复制任何文件，要求把候选与证据念给用户确认后用 --framework 显式指定。
    危害不对称——误拦只是多打一个参数，猜错则是一整套错模板。

    另：依赖/模块声明类文件（pyproject.toml / package.json / go.mod.txt）默认拒绝
    复制，副作用是【工具配置也没落地】。此时顶层会给 rejected_files +
    requires_manual_merge + manual_merge_notice，而不是把这句话只藏在逐条
    reason 里——实测买家不逐条读 reasons 就发现不了，表现是「拿到 CLAUDE.md
    但第一步就卡住」。这与「校验器无报错≠ 东西是对的」是同型问题。

    依赖：同目录 scripts/detect_project.py（框架推断的唯一事实源）。
    该依赖缺失时【显式报错】，不降级为自己的猜测；
    「目标目录没有清单文件」与「脚本缺失」是两类不同错误，提示分别给出。

路径约定：
    模板目录通过脚本自身位置解析（SCRIPT_DIR.parent / "assets" / "templates"），
    绝不依赖当前工作目录——买家装到 ~/.workbuddy/skills/ 后 cwd 是他自己的项目目录。
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量：路径解析（不依赖 cwd）
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
TEMPLATES_ROOT = SKILL_DIR / "assets" / "templates"
DETECT_SCRIPT = SCRIPT_DIR / "detect_project.py"

# CLI --framework 取值 -> 模板子目录名
FRAMEWORK_TO_TEMPLATE_DIR = {
    "flask": "python-flask",
    "fastapi": "python-fastapi",
    "express": "node-express",
    "go": "go",
    "rust": "rust",
}

# detect_project.py 能识别、但本 Skill 不提供模板的框架 -> 降级说明。
# 必须与 detect 的 PY_FRAMEWORKS / NODE_FRAMEWORKS 保持并集齐全：
# 漏掉任何一个都会走到下面的「fw 为真值但不在表里」兜底分支（仍会降级，
# 但 notice 会丢失框架名，对买家的可读性变差）。
UNSUPPORTED_FRAMEWORKS = {
    "django": "Django",
    "koa": "Koa",
    "nestjs": "NestJS",
    "next": "Next.js",
    "fastify": "Fastify",
}

# 识别不出具体框架的标准库项目 -> 降级说明。
# 与 UNSUPPORTED_FRAMEWORKS 同路径处理：本 Skill 只有 flask / fastapi / express 三套
# 框架模板，纯标准库项目【不能】被静默套上其中一套（会把 blueprint / app.logger
# 这类框架特有约定塞给不需要它的买家）。缺省时只给通用 prompt 模板 + 提示 --framework。
#
# 注意：这里只放 python-stdlib / node-stdlib。go-stdlib / rust-stdlib / rust-web
# 不会出现在这里——detect 的 TEMPLATE_VOCAB 已把它们映射成 go / rust，
# 而 go / rust 是本 Skill 确实有模板的框架。
STDLIB_FRAMEWORKS = {
    "python-stdlib": "纯 Python 标准库项目（未识别出 Flask / FastAPI / Django）",
    "node-stdlib": "纯 Node 标准库项目（未识别出 Express / Koa / NestJS）",
    "unknown": "未识别语言的项目",
}

# 降级时提示买家可以显式指定的目标框架（值已含 --framework 前缀，可直接拼进 notice）
STDLIB_SUGGESTION = {
    "python-stdlib": "--framework flask 或 --framework fastapi",
    "node-stdlib": "--framework express",
}

# ---------------------------------------------------------------------------
# 常量：模板改名映射表
# ---------------------------------------------------------------------------
# 模板内一律不用点开头的文件名（点开头文件在打包/分发/跨平台同步时容易被漏掉），
# 复制到项目时按本表改名。
#
# rename 为 None 表示【目标文件名与模板文件名完全一致】——这类条目必须显式写 None，
# 不能省略，否则「照抄通则」会生成 .rustfmt.toml / .clippy.toml（错误：Rust 工具链
# 不会去读点开头的这两个文件）。
#
# 本表【只登记需要改名的条目】。不在表中的模板（CLAUDE.md / pyproject.toml /
# package.json / eslint.config.js 等）一律沿用原名复制——见 resolve_target_name()。
RENAME_MAP: dict[str, str | None] = {
    # ---- 需改名的条目 ----
    "gitmessage.txt": ".gitmessage",
    "claude-settings.json": ".claude/settings.json",
    "go.mod.txt": "go.mod",
    "golangci.yml": ".golangci.yml",
    "pre-commit-config.yaml": ".pre-commit-config.yaml",
    "prettierrc.json": ".prettierrc",
    "husky-pre-commit.txt": ".husky/pre-commit",
    # ---- 唯二文件名不变的条目（rename 必须为 None）----
    "rustfmt.toml": None,
    "clippy.toml": None,
}

# 目标路径含子目录、复制前必须先建父目录的条目（键为模板文件名）
NEED_PARENT_DIR = {
    "claude-settings.json": ".claude",
    "husky-pre-commit.txt": ".husky",
}

# 复制后需要 chmod +x 的条目（git hooks 必须可执行，否则 husky 直接静默不生效）
NEED_EXECUTABLE = {
    "husky-pre-commit.txt",
}

# 危险文件：内容就是项目的依赖/模块声明，复制等价于清空买家项目的依赖声明。
# 默认拒绝复制；必须 --force 且输出里标 risk=destructive 显式化。
DESTRUCTIVE_TEMPLATES = {
    "package.json",   # Node 依赖 + scripts + type:"module"，覆盖会让项目直接跑不起来
    "pyproject.toml", # Python 依赖 + 构建后端 + 工具配置，覆盖会清空依赖声明
    "go.mod.txt",     # Go module 声明（含 module path / go 版本 / 依赖），与上面同类
}

# status 五态
ST_CREATED = "created"      # 新建成功（目标文件名与模板同名）
ST_RENAMED = "renamed"      # 新建成功（目标文件名与模板不同）
ST_SKIPPED = "skipped"      # 未复制：已存在且未 --force / 模板为空
ST_BACKED_UP = "backed-up"  # 已存在且 --force：先备份为 .bak 再写入
ST_REJECTED = "rejected"    # 危险文件被拒（未 --force）

RISK_SAFE = "safe"
RISK_DESTRUCTIVE = "destructive"


# ---------------------------------------------------------------------------
# 框架推断：复用 detect_project.py 的 framework_for_templates()（单一事实源）
# ---------------------------------------------------------------------------
# 【为什么不再自己推断】
#本脚本早期自带一份 detect_framework()，用「整份文件小写子串匹配」找框架名。
# 那份实现已被 detect_project.py 修复的两个 Bug 作废：
#   1) 注释里的框架名会被误当成真实依赖
#      （requirements.txt 里 `flask==3.0.0` + 一行 `# TODO: maybe fastapi later`
#        →旧实现判fastapi，把FastAPI 模板写进真Flask 项目）
#   2) package.json 的 description 等非依赖字段里出现 koa/express 会被误判
# 两份推断逻辑必然漂移，且漂移会让买家拿到与检测结论互相矛盾的模板。
# detect_project.py 已提供 framework_for_templates() 作为模板选择的唯一入口，
# 本脚本改为调用它——这是「单一事实源」的正解，也消除了当初那条 TODO。

class DetectUnavailable(Exception):
    """detect_project.py 不可用（缺失 / 加载失败 / 接口不符）。"""


def _load_detect_module():
    """按文件路径动态加载 detect_project.py，避免两脚本产生包级耦合。"""
    if not DETECT_SCRIPT.is_file():
        raise DetectUnavailable(f"未找到 {DETECT_SCRIPT}")
    spec = importlib.util.spec_from_file_location("_aiwf_detect_project", DETECT_SCRIPT)
    if spec is None or spec.loader is None:
        raise DetectUnavailable(f"无法为 {DETECT_SCRIPT} 创建导入规格")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "framework_for_templates"):
        raise DetectUnavailable("detect_project.py 缺少 framework_for_templates() 接口")
    return mod


class DetectError(DetectUnavailable):
    """detect_project.py 自身出了状况（缺失 / 加载失败 / 内部异常）。

    与「项目目录里没有清单文件」严格区分——两者都表现为 SystemExit，
    但给买家的处置建议完全相反：前者让人去修Skill，后者让人确认路径。
    """


class ProjectFilesNotFound(DetectUnavailable):
    """目标目录里找不到任何项目清单文件——是【路径给错了】，不是 Skill 坏了。"""


def _classify_detect_exit(buf_text: str, code) -> DetectUnavailable:
    """把 detect 的失败出口分类，避免把「路径给错」误报成「脚本缺失」。

    detect 失败时把 {"ok": false, "error": ..., "hint": ...} 打到 stdout
    （已被我们 redirect 到 buf）。先解析它，再按 error 内容分类：

    1) 合法 JSON 且 error 指向「找不到项目清单文件」
       -> ProjectFilesNotFound：真解法是「你可能指错目录了」
    2) 合法 JSON 的其它 error（如 TOML 解析异常）
       -> DetectError：把 detect 自己的话原样带出去
    3) buf 里没有合法 JSON（脚本自己崩了 / 结构异常）
       -> DetectError：才是「脚本缺失或损坏」

    不做这个分类的后果很实际：空目录会被报成「请重新安装本 Skill」，
    买家会去重装一个根本没坏的 Skill，而真正该做的是确认路径。
    这是 skill-developer-detect 实测发现并建议的修法。
    """
    raw = buf_text.strip()
    payload, err_text = None, ""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            payload = parsed
            err_text = str(parsed.get("error", ""))
    except (json.JSONDecodeError, ValueError):
        payload = None

    detect_hint = ""
    if payload is not None and payload.get("hint"):
        detect_hint = f"（detect 提示：{payload['hint']}）"

    if err_text:
        if any(k in err_text for k in
               ("未识别出项目语言", "找不到 pyproject.toml", "未找到任何项目清单",
                "pyproject.toml / package.json")):
            return ProjectFilesNotFound(f"目标目录不像项目根目录：{err_text}{detect_hint}")
        return DetectError(f"detect_project.py 判定失败：{err_text}{detect_hint}")
    return DetectError(
        f"detect_project.py 异常退出（退出码 {code}）且未给出可解析的错误信息："
        f"{raw[:200] or '无输出'}；该脚本可能已损坏，请重新安装本 Skill"
    )


def detect_framework(root: Path) -> dict:
    """推断框架，返回 detect_project.py 的原始判定结果（含候选与置信度）。

    返回 dict:
        framework            模板口径的框架名（flask/fastapi/express/go/rust/…）
        has_template         是否有模板可复制
        needs_confirmation   存在歧义，应先与用户确认
        candidates           完整候选列表（含 evidence / confidence / source）
        language             项目语言

    注意：本函数【不做任何自己的兜底猜测】。识别不出就如实返回 detect 的结论，
    由调用方按「降级」处理。宁可少复制，也不能给买家一套与项目不符的模板。

    ⚠ detect_project.py 在识别失败时会往 stdout 打印 JSON 并抛 SystemExit。
    本脚本的输出契约是「stdout 上只有一个 JSON」，因此这里必须把它的输出
    全部吞掉并转成异常——否则 detect 的错误 JSON 会和本脚本的结果 JSON 一起
    涌到 stdout，调用方 json.loads 直接炸。这是踩过的坑，不要去掉 redirect。
    """
    mod = _load_detect_module()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            result = mod.framework_for_templates(root)
    except SystemExit as exc:
        raise _classify_detect_exit(buf.getvalue(), exc.code) from exc
    except DetectUnavailable:
        raise
    except Exception as exc:                      # detect 内部异常也不静默吞掉
        raise DetectError(f"detect_project.py 推断失败：{exc}") from exc
    if not isinstance(result, dict) or "framework" not in result:
        raise DetectError("detect_project.py 返回结构不符合预期")
    return result




# ---------------------------------------------------------------------------
# 结果构造辅助
# ---------------------------------------------------------------------------

def _result(template: str, target: str, status: str, risk: str, reason: str) -> dict:
    return {"template": template, "target": target, "status": status, "risk": risk, "reason": reason}


def _summarize(results: list[dict]) -> dict:
    """汇总计数。renamed 是 created 的子集（改名成功也是新建成功），单列一个字段便于人工核对。"""
    created = sum(1 for r in results if r["status"] in (ST_CREATED, ST_RENAMED))
    return {
        "created": created,
        "skipped": sum(1 for r in results if r["status"] == ST_SKIPPED),
        "backed_up": sum(1 for r in results if r["status"] == ST_BACKED_UP),
        "rejected": sum(1 for r in results if r["status"] == ST_REJECTED),
        "renamed": sum(1 for r in results if r["status"] == ST_RENAMED),
        "total": len(results),
    }


def _fail(error: str, hint: str) -> int:
    print(json.dumps({"ok": False, "error": error, "hint": hint}, ensure_ascii=False, indent=2))
    return 1


def resolve_target_name(template: str) -> tuple[str, bool]:
    """算出模板应复制成的目标相对路径。

    返回 (目标相对路径, 是否命中改名映射表)。
    - 命中且值为字符串 -> 用该值（改名）
    - 命中且值为 None  -> 文件名不变（rustfmt.toml / clippy.toml）
    - 未命中           -> 沿用模板原名（CLAUDE.md / pyproject.toml / eslint.config.js 等）
    """
    if template in RENAME_MAP:
        rename = RENAME_MAP[template]
        return (rename if rename is not None else template), True
    return template, False


# ---------------------------------------------------------------------------
# 核心：备份路径 / 单文件复制
# ---------------------------------------------------------------------------

def resolve_backup_path(target: Path) -> Path:
    """为已存在文件找一个不撞车的备份名：<file>.bak -> <file>.bak.1 -> <file>.bak.2 ...

    绝不能覆盖旧 .bak——旧 .bak 是买家上一次合并前的原始文件，覆盖它等于静默丢数据。
    """
    candidate = target.parent / (target.name + ".bak")
    if not candidate.exists():
        return candidate
    i = 1
    while True:
        candidate = target.parent / f"{target.name}.bak.{i}"
        if not candidate.exists():
            return candidate
        i += 1


def _skill_rel(path: Path) -> str:
    """把技能内的绝对路径转成「相对 skills 根」的展示路径。

    刻意【不用】相对技能目录（那会得到 assets/templates/...，买家按 skills 根
    一拼就找错），也不直接给绝对路径（换机器/换安装位置就失效）。
    相对 skills 根（形如 ai-dev-workflow/assets/templates/...）与 SKILL.md 里
    写路径的基准一致，读起来能直接定位。
    """
    parts = path.resolve().parts
    if "skills" in parts:
        idx = len(parts) - 1 - parts[::-1].index("skills")
        return "/".join(parts[idx + 1:])
    return path.as_posix()


def _copy_one(src: Path, target: Path, *, template: str, display: str,
              dry_run: bool, force: bool, git_ready: bool = True) -> tuple[dict, str | None]:
    """搬运单个文件，返回 (结果条目, 错误信息)。错误信息非 None 时整轮 ok=False。

    display 是对外展示的目标路径（相对项目根），target 是真实落盘路径。
    git_ready=False 表示项目还不是 git 仓库，仅影响 .gitmessage 的提示语。
    """
    risk = RISK_DESTRUCTIVE if template in DESTRUCTIVE_TEMPLATES else RISK_SAFE
    # 目标文件名与模板文件名不同 -> renamed（改名落地），相同 -> created（原名落地）
    status_created = ST_RENAMED if Path(display).name != template else ST_CREATED

    # 1) 空模板保护：0 字节模板一定是模板损坏/被清空，复制过去等于给买家一个空配置
    try:
        if src.stat().st_size == 0:
            return (
                _result(template, display, ST_SKIPPED, risk,
                        "模板文件为 0 字节（疑似模板损坏或被清空），已跳过，未复制空配置"),
                None,
            )
    except OSError as exc:
        return (_result(template, display, ST_SKIPPED, risk, f"无法读取模板：{exc}"), None)

    # 2) 危险文件默认拒绝
    if risk == RISK_DESTRUCTIVE and not force:
        #必须给出「配置从哪拿」，不能只说「被拒了」。
        # 实测（skill-developer-tpl 走查）：pyproject.toml 被拒后，买家手上只有
        # 自己那份没有 [tool.ruff]/[tool.pytest]/[tool.coverage]/[tool.commitizen] 的
        # pyproject.toml，而落位的 CLAUDE.md 正用命令口吻要求他跑
        # `ruff check .` / `pytest --cov-fail-under=85` / `git cz`——
        # 四段配置全部拿不到，买家第一步就卡住。
        # 只说「请手动合并」等于让买家自己去找源；给出模板路径他才知道去哪拿。
        return (
            _result(template, display, ST_REJECTED, risk,
                    "该文件即项目依赖/模块声明，覆盖会清空现有依赖，已拒绝复制。"
                    "⚠ 依赖它才能生效的工具配置因此【没有落地】："
                    "若 CLAUDE.md 要求执行 ruff / pytest / coverage / git cz / "
                    "golangci-lint 等命令，而你的项目里尚无对应配置，它们会直接报错。"
                    "请打开 skills 下的 " + _skill_rel(src) + " 里的工具配置段"
                    "（[tool.*] 等），手动合并进你自己的同名文件"
                    "（只合并工具配置段，不要合并 [project] / module / dependencies 段）；"
                    "确认要整份覆盖请加 --force（原文件会先备份为 .bak）"),
            None,
        )

    # 3) 已存在文件的处理
    if target.exists():
        if not force:
            return (
                _result(template, display, ST_SKIPPED, risk,
                        "目标文件已存在且未指定 --force，未覆盖；如需合并请手动处理"),
                None,
            )
        backup = resolve_backup_path(target)
        if dry_run:
            return (
                _result(template, display, ST_BACKED_UP, risk,
                        f"[dry-run] 将先把现有文件备份为 {backup.name} 再写入"),
                None,
            )
        try:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
        except OSError as exc:
            return (_result(template, display, ST_SKIPPED, risk, f"备份失败，已放弃覆盖：{exc}"),
                    f"备份 {target} 失败：{exc}")
        status = ST_BACKED_UP
        reason = f"目标已存在，先备份为 {backup.name} 再写入，请手动 diff 并合并"
    else:
        status = status_created
        reason = "复制完成"

    # 3b) .gitmessage 落位前置条件：非 git 仓库里它是一份暂时用不上的资产。
    #     实测（skill-developer-tpl 走查）：非 git 仓库执行
    #     `git config --local commit.template .gitmessage` 会 fatal: not a git repository。
    #     这里只做「重申detect 已经给过的第一条建议」，不新增约束。
    if template == "gitmessage.txt" and not git_ready:
        reason += ("；⚠ 当前项目还不是 git 仓库，本模板暂时无法生效，"
                   "需先 git init 再执行 git config --local commit.template .gitmessage")

    # 4) dry-run 到此为止，绝不写盘（只把 reason 改成「将要」的口吻）
    if dry_run:
        reason = reason.replace("复制完成", "[dry-run] 将复制")

    # 5) 真正写盘
    if not dry_run:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            if template in NEED_EXECUTABLE:
                mode = os.stat(target).st_mode
                os.chmod(target, mode | 0o111)  # 与 umask 无关地补齐三个执行位
        except OSError as exc:
            return (
                _result(template, display, ST_SKIPPED, risk, f"写入失败：{exc}"),
                f"写入 {target} 失败：{exc}",
            )
    return _result(template, display, status, risk, reason), None


# ---------------------------------------------------------------------------
# 核心：规划 + 执行一轮复制
# ---------------------------------------------------------------------------

def apply_templates(root: Path, *, framework: str | None, common: bool,
                    dry_run: bool, force: bool,
                    templates_root: Path | None = None) -> dict:
    """返回完整结果 dict。模板根目录可注入，便于 --selftest 用临时夹具跑。"""
    troot = templates_root or TEMPLATES_ROOT
    mode = "dry-run" if dry_run else "copy"

    if not troot.is_dir():
        return {
            "ok": False, "mode": mode, "framework": framework,
            "results": [], "summary": _summarize([]),
            "error": f"模板目录不存在：{troot}",
            "hint": "确认本 Skill 的 assets/templates/ 是否完整（重新安装本 Skill），"
                    "或用 --framework 显式指定框架后再试。",
        }

    # ---- 框架确定 ----
    # 推断结果全部来自 detect_project.py 的framework_for_templates()，
    # 本脚本不再自己猜——两份推断逻辑必然漂移，漂移会让买家拿到与检测结论矛盾的模板。
    detection: dict | None = None
    fw: str | None = framework
    if fw is None:
        try:
            detection = detect_framework(root)
        except DetectUnavailable as exc:
            # 按异常类型给不同的处置建议：
            #   ProjectFilesNotFound -> 大概率是路径给错了（让人去确认目录）
            #   DetectError           -> detect 自身异常（让人去修/重装 Skill）
            # 两者混为一谈会让买家去重装一个根本没坏的 Skill。
            if isinstance(exc, ProjectFilesNotFound):
                hint = (f"{exc}。请确认路径指向的是项目根目录"
                        f"（应含 pyproject.toml / requirements.txt / setup.py / "
                        f"package.json / go.mod / Cargo.toml 之一）；"
                        f"若项目是空的或只有代码没有依赖声明，"
                        f"可用 --framework <{' / '.join(sorted(FRAMEWORK_TO_TEMPLATE_DIR))}> "
                        f"显式指定框架绕过推断。")
            else:
                hint = (f"本脚本依赖同目录的 scripts/detect_project.py 做框架推断（单一事实源）。"
                        f"{exc}。请确认该文件存在且完整（必要时重新安装本 Skill），"
                        f"或用 --framework <{' / '.join(sorted(FRAMEWORK_TO_TEMPLATE_DIR))}> "
                        f"显式指定框架绕过推断。")
            return {
                "ok": False, "mode": mode, "framework": None,
                "results": [], "summary": _summarize([]),
                "error": f"框架推断失败：{exc}",
                "hint": hint,
            }
        fw = detection["framework"]

    results: list[dict] = []
    errors: list[str] = []
    degraded = False
    notice = None
    template_dir_used = None
    # .gitmessage 的前置条件：非 git 仓库里它落位了也用不上（见 _copy_one 的说明）
    git_ready = (root / ".git").exists()
    # 自动推断时的判定依据，原样透传给模型，便于把证据念给用户确认
    framework_candidates = detection.get("candidates", []) if detection else []
    needs_confirmation = bool(detection.get("needs_confirmation")) if detection else False

    # 显式 --framework 时不做歧义拦截：用户已经拍板了
    if framework is not None:
        needs_confirmation = False

    # 【歧义即停手】
    # detect 只要给出 needs_confirmation=True，就说明「这个项目的框架需要人来拍板」。
    # 此时【一律不复制任何框架模板】，返回 ok:false 要求调用方用 --framework 显式指定。
    #
    # 为什么不再区分「1 个 high + 若干 low」和「多个 high」：
    #   前者例如 requirements.txt 里 `flask==3.0.0` + 一行 `# TODO: maybe fastapi later`，
    #   detect 已用 high 证据选定 flask，看起来「判定了也不抄」是误伤；
    #   但危害是【不对称】的——误伤只让买家多打一个 --framework 参数，
    #   而猜错会让买家拿到一整套错模板（CLAUDE.md / pre-commit 全是别的框架的约定），
    #   且第一份拿到的东西就是错的，信任链直接断。
    #   保守一侧的成本远低于冒险一侧，所以统一停手。
    #
    # 实测依据（与 detect_project.py 的跨脚本核对）：
    #   纯 flask 依赖            -> needs_confirmation=False -> 正常复制 flask 模板
    #   flask + 注释提 fastapi    -> needs_confirmation=True  -> 停手，要求显式指定
    #   同时声明 flask + fastapi  -> needs_confirmation=True  -> 停手，要求显式指定
    if framework is None and needs_confirmation:
        cand_names = [c["name"] for c in framework_candidates]
        shown = " / ".join(dict.fromkeys(cand_names)) or "（无明确候选）"
        evidence = "；".join(
            f"{c['name']}[{c['confidence']}] 依据 {c['evidence'][0]}"
            for c in framework_candidates[:4]
        )[:400]
        return {
            "ok": False, "mode": mode,
            # 【关键】framework 字段刻意置 null，而不是回填 detect 选中的那个候选。
            # detect 在歧义时仍会填一个值（例如同时声明 flask+fastapi 会填 "fastapi"），
            # 若原样透出，调用方很可能顺手读 framework 就去套模板 ——
            # 那正是本函数要防的错模板事故，只是换了个入口。
            # 置 null 让「歧义时没有结论」在数据上就是自明的，别靠读文档才能知道。
            "framework": None,
            "framework_detected_but_ambiguous": fw,
            "results": [], "summary": _summarize([]),
            "needs_confirmation": True,
            "framework_candidates": framework_candidates,
            "degraded": True,
            "error": f"框架判定存在歧义（{detection.get('language')} 项目），已停止复制框架模板",
            "hint": f"检测到多个框架候选（{shown}），无法确定该套哪套模板，已【不复制任何模板】"
                    f"（未写入任何文件）。判定依据：{evidence}。"
                    f"注意 framework 字段为 null 即表示「判定未完成」，请勿据其它字段推断。"
                    f"请先把候选与依据念给用户确认，再用 "
                    f"--framework <{' / '.join(dict.fromkeys(cand_names)) or 'flask'}> "
                    f"显式指定后重试；确认后如需 5 个通用 prompt 模板可加 --common。",
        }

    # ---- 不提供模板 / 识别不出框架：如实降级，绝不套不匹配的模板 ----
    # 两类降级共用同一条路径，语义一致：
    #   a) 明确检测到但本 Skill 没模板的框架（django / koa / nestjs / next / fastify…）
    #   b) 识别不出具体框架的标准库项目（python-stdlib / node-stdlib）
    #   c) 两者都【不复制任何框架模板】，只保留 --common 的通用 prompt 模板
    if fw in UNSUPPORTED_FRAMEWORKS:
        degraded = True
        name = UNSUPPORTED_FRAMEWORKS[fw]
        notice = (
            f"检测到 {name} 项目，但本 Skill 不提供 {name} 的模板，"
            f"已降级为「通用约定」：未复制任何框架模板。"
            f"请改为读取 references/ 下的通用与语言约定文档手工落地配置。"
        )
        template_dir_used = None
    elif fw in STDLIB_FRAMEWORKS:
        # 未识别出具体框架 —— 绝不静默套用最主流的那套模板。
        # 静默降级比报错更有害：买家拿到的是一堆自己项目里根本用不上的框架约定。
        degraded = True
        name = STDLIB_FRAMEWORKS[fw]
        notice = (
            f"检测到{name}，但本 Skill 不提供标准库模板，"
            f"已降级为通用约定：未复制任何框架模板。"
            f"请读取 references/ 下的通用与语言约定文档手工落地配置；"
            f"若项目确实使用 {STDLIB_SUGGESTION[fw]}，显式指定后重跑即可。"
        )
        template_dir_used = None
    elif fw in FRAMEWORK_TO_TEMPLATE_DIR:
        template_dir_used = FRAMEWORK_TO_TEMPLATE_DIR[fw]
    elif fw:
        # detect 认识但本 Skill 没模板（如 next / fastify / rust-web 之外的新框架）：
        # 降级而不是报错——模型可能仍想复制通用 prompt 模板。
        degraded = True
        notice = (
            f"检测到 {fw} 项目，但本 Skill 不提供该框架的模板，"
            f"已降级为「通用约定」：未复制任何框架模板。"
            f"请改为读取 references/ 下的通用与语言约定文档手工落地配置。"
        )
        template_dir_used = None
    else:
        return {
            "ok": False, "mode": mode, "framework": fw,
            "results": [], "summary": _summarize([]),
            "error": f"未能识别项目框架：{root} 下找不到 pyproject.toml / requirements.txt / "
                     f"setup.py / package.json / go.mod / Cargo.toml",
            "hint": "用 --framework <" + " / ".join(sorted(FRAMEWORK_TO_TEMPLATE_DIR)) + "> 显式指定框架后重试。",
        }

    # ---- 框架模板 ----
    if template_dir_used:
        tdir = troot / template_dir_used
        if not tdir.is_dir():
            return {
                "ok": False, "mode": mode, "framework": fw,
                "results": [], "summary": _summarize([]),
                "error": f"框架模板目录不存在：{tdir}",
                "hint": f"assets/templates/ 下缺少 {template_dir_used}/，请重新安装本 Skill 或改用其他框架。",
            }
        for src in sorted(tdir.iterdir()):
            if not src.is_file():
                continue
            name = src.name
            target_rel, was_mapped = resolve_target_name(name)
            target = root / target_rel
            res, err = _copy_one(src, target, template=name, display=target_rel,
                                 dry_run=dry_run, force=force, git_ready=git_ready)
            if not was_mapped:
                # 未登记 = 沿用原名。这是预期路径（CLAUDE.md / pyproject.toml 等），
                # 但 reason 里点明，方便买家核对「这个文件确实该叫这个名字」。
                res["reason"] = f"{res['reason']}；未登记改名规则，沿用模板原名"
            results.append(res)
            if err:
                errors.append(err)

    # ---- 通用 prompt 模板 ----
    if common:
        cdir = troot / "common" / "prompts"
        if not cdir.is_dir():
            results.append(_result("common/prompts", "prompts/", ST_SKIPPED, RISK_SAFE,
                                   "通用 prompt 模板目录不存在，已跳过"))
        else:
            for src in sorted(cdir.iterdir()):
                if not src.is_file():
                    continue
                target = root / "prompts" / src.name
                res, err = _copy_one(src, target, template=src.name,
                                     display=f"prompts/{src.name}",
                                     dry_run=dry_run, force=force,
                                     git_ready=git_ready)
                results.append(res)
                if err:
                    errors.append(err)

    out = {
        "ok": not errors,
        "mode": mode,
        "framework": fw,
        "results": results,
        "summary": _summarize(results),
    }
    if template_dir_used:
        out["template_dir"] = template_dir_used
    if detection is not None:
        # 原样透传 detect 的判定依据：模型据此把证据念给用户确认，而不是自己再猜一次。
        # 只在自动推断时输出；显式 --framework 时不需要（用户已拍板）。
        out["language"] = detection.get("language")
        out["needs_confirmation"] = needs_confirmation
        if framework_candidates:
            out["framework_candidates"] = framework_candidates
    if degraded:
        out["degraded"] = True
        out["notice"] = notice

    # 【顶层显式提醒】rejected > 0 时必须在 summary 层就说出来，不能只藏在逐条 reason 里。
    # 实测（skill-developer-tpl 走查）：pyproject.toml 被拒后整体 ok=true，
    # 买家拿到 CLAUDE.md，而那份 CLAUDE.md 正用命令口吻要求跑
    # `ruff check .` / `pytest --cov-fail-under=85` / `git cz`——
    # 而这四段配置全在pyproject.toml 里、已落地失败。
    # 不逐条读 results[i].reason 的买家根本发现不了，表现为「第一步就卡住」。
    # 这是「校验器无报错 ≠ 东西是对的」的同型案例，故提升为顶层字段。
    rejected_items = [r for r in results if r["status"] == ST_REJECTED]
    if rejected_items:
        out["rejected_files"] = [
            {"template": r["template"], "target": r["target"], "risk": r["risk"]}
            for r in rejected_items
        ]
        out["requires_manual_merge"] = True
        out["manual_merge_notice"] = (
            f"有 {len(rejected_items)} 个依赖/模块声明文件被拒绝复制（"
            + "、".join(r["target"] for r in rejected_items)
            + "）。这不是可选提示：依赖它们的配置【没有落地】。"
            "落位的 CLAUDE.md 若要求执行 ruff / pytest / coverage / git cz / "
            "golangci-lint / rustfmt / clippy 等命令，而项目里尚无对应配置，它们会直接报错。"
            "请按下方 rejected_files 定位原因，并按各条 results[].reason 里给出的"
            "模板路径，手动把工具配置段（[tool.*] 等）合并进你自己的同名文件"
            "——只合并工具配置段，不要合并 [project] / module / dependencies 段。"
        )
    if errors:
        out["error"] = errors[0]
        out["hint"] = "部分文件写入失败，请检查目标目录权限与磁盘空间后重跑；本脚本可安全重复执行（已存在的文件不会被覆盖）。"
    return out


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def selftest() -> int:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        checks.append((name, bool(cond), detail))

    # A1 路径解析不依赖 cwd
    check("A1 模板目录由脚本自身位置解析且存在（SCRIPT_DIR 不依赖 cwd）",
          SCRIPT_DIR.name == "scripts" and TEMPLATES_ROOT.is_dir(),
          f"SCRIPT_DIR={SCRIPT_DIR} TEMPLATES_ROOT={TEMPLATES_ROOT}")

    # A2 改名映射表逐条符合规格
    expected = {
        "gitmessage.txt": ".gitmessage",
        "claude-settings.json": ".claude/settings.json",
        "go.mod.txt": "go.mod",
        "golangci.yml": ".golangci.yml",
        "pre-commit-config.yaml": ".pre-commit-config.yaml",
        "prettierrc.json": ".prettierrc",
        "husky-pre-commit.txt": ".husky/pre-commit",
    }
    bad = {k: v for k, v in expected.items() if RENAME_MAP.get(k) != v}
    check("A2 七个需改名条目与规格逐条一致", not bad, f"不符项={bad or '无'}")

    # A3 rustfmt / clippy 必须是 rename=None（否则会生成 .rustfmt.toml 这种错名文件）
    check("A3 rustfmt.toml / clippy.toml 的 rename 均为 None（文件名不变）",
          RENAME_MAP.get("rustfmt.toml", "missing") is None
          and RENAME_MAP.get("clippy.toml", "missing") is None,
          f"rustfmt={RENAME_MAP.get('rustfmt.toml')!r} clippy={RENAME_MAP.get('clippy.toml')!r}")

    # A4 需要建目录 / 需要可执行位的条目登记齐全
    check("A4 .claude 与 .husky 目录、pre-commit 可执行位均已登记",
          NEED_PARENT_DIR == {"claude-settings.json": ".claude", "husky-pre-commit.txt": ".husky"}
          and NEED_EXECUTABLE == {"husky-pre-commit.txt"},
          f"NEED_PARENT_DIR={NEED_PARENT_DIR} NEED_EXECUTABLE={NEED_EXECUTABLE}")

    # A5 危险文件集合
    check("A5 危险文件含 package.json / pyproject.toml / go.mod.txt",
          {"package.json", "pyproject.toml", "go.mod.txt"} <= DESTRUCTIVE_TEMPLATES,
          f"DESTRUCTIVE={sorted(DESTRUCTIVE_TEMPLATES)}")

    # A6 每个模板文件都能解析出目标名，且点开头模板绝不会被生成
    bad_names: list[str] = []
    for sub in FRAMEWORK_TO_TEMPLATE_DIR.values():
        d = TEMPLATES_ROOT / sub
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if not f.is_file():
                continue
            rel, mapped = resolve_target_name(f.name)
            # 唯二允许「点开头」的例外是 None 映射（文件名不变），其余改名结果必须与映射表一致
            if not rel or rel.startswith(".") and RENAME_MAP.get(f.name) is None:
                bad_names.append(f"{sub}/{f.name} -> {rel}")
    check("A6 五个框架模板目录中每个模板都能解析出合法目标名", not bad_names,
          f"异常={bad_names or '无'}")

    # A6b 模板目录里存在原名条目（CLAUDE.md 等），必须走「沿用原名」而不是被丢弃
    unmapped_expected = {"CLAUDE.md", "pyproject.toml", "package.json", "eslint.config.js"}
    check("A6b 原名条目（CLAUDE.md 等）解析为沿用原名",
          all(resolve_target_name(n) == (n, False) for n in unmapped_expected),
          f"检查={sorted(unmapped_expected)}")

    # ---- 端到端（用临时夹具，真实跑主流程）----
    tmp = Path(tempfile.mkdtemp(prefix="apply_tpl_selftest_"))
    try:
        # B1 危险文件默认被拒
        p = tmp / "flask_app"
        p.mkdir()
        (p / "pyproject.toml").write_text('[project]\nname="demo"\n', encoding="utf-8")
        r1 = apply_templates(p, framework="flask", common=False, dry_run=False, force=False)
        by_t = {r["template"]: r for r in r1["results"]}
        check("B1 pyproject.toml 默认被拒（status=rejected, risk=destructive）",
              by_t["pyproject.toml"]["status"] == ST_REJECTED
              and by_t["pyproject.toml"]["risk"] == RISK_DESTRUCTIVE,
              f"实际={by_t['pyproject.toml']}")
        check("B1b 被拒时买家原文件内容未被改动",
              (p / "pyproject.toml").read_text(encoding="utf-8") == '[project]\nname="demo"\n',
              "原 pyproject.toml 应保持不变")
        check("B1c .gitmessage 改名到位", (p / ".gitmessage").is_file())
        check("B1d .claude/settings.json 自动建目录并改名到位", (p / ".claude" / "settings.json").is_file())

        # B2 幂等：第二次全部 skipped，且不产生新的 .bak
        snapshot_before = sorted(x.name for x in p.rglob("*"))
        r2 = apply_templates(p, framework="flask", common=False, dry_run=False, force=False)
        snapshot_after = sorted(x.name for x in p.rglob("*"))
        non_skipped = [r["template"] for r in r2["results"] if r["status"] not in (ST_SKIPPED, ST_REJECTED)]
        check("B2 幂等：第二次无非 skipped/rejected 的条目", not non_skipped, f"例外={non_skipped or '无'}")
        check("B2b 幂等：第二次不产生任何磁盘变化（无新增 .bak）",
              snapshot_before == snapshot_after,
              f"before={snapshot_before} after={snapshot_after}")

        # B3 dry-run 零磁盘变化
        p3 = tmp / "dry_app"
        p3.mkdir()
        (p3 / "package.json").write_text('{"name":"demo"}\n', encoding="utf-8")
        snap = sorted(x.name for x in p3.rglob("*"))
        r3 = apply_templates(p3, framework="express", common=True, dry_run=True, force=False)
        snap2 = sorted(x.name for x in p3.rglob("*"))
        check("B3 --dry-run 连续执行不产生任何磁盘变化", snap == snap2 and r3["mode"] == "dry-run",
              f"before={snap} after={snap2} mode={r3['mode']}")
        check("B3b --dry-run 下 package.json 仍被拒绝且未落盘",
              any(r["template"] == "package.json" and r["status"] == ST_REJECTED for r in r3["results"])
              and not (p3 / ".gitmessage").exists(),
              "dry-run 不应创建任何文件")

        # B4 已存在 .bak 时不覆盖旧 .bak
        p4 = tmp / "bak_app"
        p4.mkdir()
        (p4 / ".gitmessage").write_text("OLD-1\n", encoding="utf-8")
        (p4 / ".gitmessage.bak").write_text("OLD-BAK\n", encoding="utf-8")
        r4 = apply_templates(p4, framework="go", common=False, dry_run=False, force=True)
        check("B4 已存在 .bak 时改用 .bak.1，不覆盖旧 .bak",
              (p4 / ".gitmessage.bak").read_text(encoding="utf-8") == "OLD-BAK\n"
              and (p4 / ".gitmessage.bak.1").is_file()
              and any(r["status"] == ST_BACKED_UP for r in r4["results"]),
              "旧 .bak 内容必须保持不变")

        # B5 rust：rustfmt.toml / clippy.toml 不被改成点开头
        p5 = tmp / "rust_app"
        p5.mkdir()
        (p5 / "Cargo.toml").write_text('[package]\nname="demo"\n', encoding="utf-8")
        r5 = apply_templates(p5, framework="rust", common=False, dry_run=False, force=False)
        check("B5 rustfmt.toml / clippy.toml 文件名不变",
              (p5 / "rustfmt.toml").is_file() and (p5 / "clippy.toml").is_file()
              and not (p5 / ".rustfmt.toml").exists() and not (p5 / ".clippy.toml").exists(),
              "不得生成 .rustfmt.toml / .clippy.toml")

        # B6 go：golangci.yml 改名 + go.mod.txt 被判危险
        p6 = tmp / "go_app"
        p6.mkdir()
        (p6 / "go.mod").write_text("module demo\n\ngo 1.22\n", encoding="utf-8")
        r6 = apply_templates(p6, framework="go", common=False, dry_run=False, force=False)
        check("B6 golangci.yml -> .golangci.yml 改名到位", (p6 / ".golangci.yml").is_file())
        check("B6b go.mod.txt 默认被拒（不覆盖 module 声明）",
              any(r["template"] == "go.mod.txt" and r["status"] == ST_REJECTED for r in r6["results"]),
              f"结果={[r['template'] + ':' + r['status'] for r in r6['results']]}")

        # B7 node：husky pre-commit 落位且可执行
        p7 = tmp / "node_app"
        p7.mkdir()
        (p7 / "package.json").write_text('{"name":"demo","devDependencies":{"express":"^4"}}\n', encoding="utf-8")
        r7 = apply_templates(p7, framework=None, common=True, dry_run=False, force=False)
        hp = p7 / ".husky" / "pre-commit"
        check("B7 从 package.json 推断出 express", r7["framework"] == "express", f"framework={r7['framework']}")
        check("B7b .husky/pre-commit 已创建且带可执行位",
              hp.is_file() and os.access(hp, os.X_OK),
              f"存在={hp.is_file()} 可执行={hp.is_file() and os.access(hp, os.X_OK)}")
        check("B7c --common 复制 5 个 prompt 模板到 prompts/",
              len(list((p7 / "prompts").glob("*.md"))) == 5,
              f"实际={len(list((p7 / 'prompts').glob('*.md')))}")

        # B8 不支持的框架如实降级，绝不复制不匹配模板
        p8 = tmp / "django_app"
        p8.mkdir()
        (p8 / "pyproject.toml").write_text('[project]\ndependencies=["django"]\n', encoding="utf-8")
        r8 = apply_templates(p8, framework=None, common=False, dry_run=False, force=False)
        check("B8 Django 降级为通用约定且零文件复制",
              r8.get("degraded") is True and r8["framework"] == "django"
              and r8["results"] == [] and sorted(x.name for x in p8.iterdir()) == ["pyproject.toml"],
              f"degraded={r8.get('degraded')} results={len(r8['results'])}")

        # B9 无法推断框架时报错并给 hint
        p9 = tmp / "empty_app"
        p9.mkdir()
        r9 = apply_templates(p9, framework=None, common=False, dry_run=False, force=False)
        check("B9 无法推断框架时 ok=false 且带中文 hint",
              r9["ok"] is False and "hint" in r9 and "--framework" in r9["hint"],
              f"ok={r9['ok']} hint={r9.get('hint', '')[:40]}")

        # B10 纯 Python 项目（未识别出框架）必须降级，绝不静默套用 Flask 模板
        p10 = tmp / "stdlib_py"
        p10.mkdir()
        (p10 / "pyproject.toml").write_text('[project]\nname="demo"\n', encoding="utf-8")
        r10 = apply_templates(p10, framework=None, common=False, dry_run=False, force=False)
        check("B10 纯 Python 项目推断为 python-stdlib 而非默认 flask",
              r10["framework"] == "python-stdlib",
              f"framework={r10['framework']}")
        check("B10b 纯 Python 项目降级：degraded=true 且零文件复制",
              r10.get("degraded") is True and r10["results"] == []
              and sorted(x.name for x in p10.iterdir()) == ["pyproject.toml"],
              f"degraded={r10.get('degraded')} 落盘={sorted(x.name for x in p10.iterdir())}")
        check("B10c 纯 Python 项目未被套用任何 python-flask 模板",
              not any((p10 / f).exists() for f in
                      (".gitmessage", "CLAUDE.md", ".pre-commit-config.yaml", ".claude", "prompts")),
              "不得出现 flask 模板里的任何文件")

        # B10d 纯 Python 项目 + --common：只复制 5 个通用 prompt，不碰框架模板
        p10b = tmp / "stdlib_py_common"
        p10b.mkdir()
        (p10b / "pyproject.toml").write_text('[project]\nname="demo"\n', encoding="utf-8")
        r10b = apply_templates(p10b, framework=None, common=True, dry_run=False, force=False)
        check("B10d 纯 Python + --common 只复制 5 个通用 prompt",
              r10b.get("degraded") is True
              and len(list((p10b / "prompts").glob("*.md"))) == 5
              and not (p10b / ".gitmessage").exists()
              and not (p10b / "CLAUDE.md").exists()
              and sorted(x.name for x in p10b.iterdir()) == ["prompts", "pyproject.toml"],
              f"落盘={sorted(x.name for x in p10b.iterdir())}")
        check("B10e 降级 notice 含 --framework 显式覆盖提示与中文说明",
              "--framework" in r10b.get("notice", "") and "不提供标准库模板" in r10b.get("notice", ""),
              f"notice={r10b.get('notice', '')[:70]}")

        # B10f 纯 Node 项目（未识别出框架）同样降级，绝不静默套 Express 模板
        p10c = tmp / "stdlib_node"
        p10c.mkdir()
        (p10c / "package.json").write_text('{"name":"demo"}\n', encoding="utf-8")
        r10c = apply_templates(p10c, framework=None, common=False, dry_run=False, force=False)
        check("B10f 纯 Node 项目降级为 node-stdlib 且零文件复制",
              r10c["framework"] == "node-stdlib" and r10c.get("degraded") is True
              and r10c["results"] == []
              and not (p10c / ".prettierrc").exists() and not (p10c / ".husky").exists(),
              f"framework={r10c['framework']} degraded={r10c.get('degraded')}")

        # B10g 显式 --framework 覆盖降级判定（降级逻辑不得误伤覆盖路径）
        p10d = tmp / "explicit_flask"
        p10d.mkdir()
        (p10d / "pyproject.toml").write_text('[project]\nname="demo"\n', encoding="utf-8")
        r10d = apply_templates(p10d, framework="flask", common=False, dry_run=False, force=False)
        check("B10g 纯 Python 项目 --framework flask 显式覆盖后正常复制",
              r10d.get("degraded") is not True and r10d["template_dir"] == "python-flask"
              and (p10d / ".gitmessage").is_file() and (p10d / "CLAUDE.md").is_file(),
              f"template_dir={r10d.get('template_dir')} degraded={r10d.get('degraded')}")

        # B10h 降级路径也是幂等的
        snap10 = sorted(x.name for x in p10b.rglob("*"))
        apply_templates(p10b, framework=None, common=True, dry_run=False, force=False)
        check("B10h 降级路径幂等（第二次无磁盘变化）",
              snap10 == sorted(x.name for x in p10b.rglob("*")),
              f"before={snap10}")

        # ---- C 组：与 detect_project.py 的集成契约 ----
        # C1 detect_project.py 存在且提供 framework_for_templates（单一事实源入口）
        check("C1 detect_project.py 存在且提供 framework_for_templates()",
              DETECT_SCRIPT.is_file() and hasattr(_load_detect_module(), "framework_for_templates"),
              f"DETECT_SCRIPT={DETECT_SCRIPT}")

        # C2 【最贵的用例】注释里的框架名不得让脚本复制错模板。
        #    fixture 是 team-lead 与 detect 成员都复现过的那条：
        #      requirements.txt = flask==3.0.0 + 一行 # TODO: maybe fastapi later
        #    改前：本脚本整份文件子串匹配 -> 判fastapi -> 静默复制 4 个 FastAPI 文件、ok:true、零警告
        #    改后：走 detect 的 confidence 语义 -> 判定存在歧义 -> 停手要求显式指定
        pc = tmp / "comment_trap"
        pc.mkdir()
        (pc / "requirements.txt").write_text(
            "flask==3.0.0\n# TODO: maybe fastapi later\n", encoding="utf-8")
        rc = apply_templates(pc, framework=None, common=False, dry_run=False, force=False)
        check("C2 【最贵用例】注释里的 fastapi 不导致复制错模板：停手且零文件落盘",
              rc["ok"] is False
              and rc["results"] == []
              and rc.get("template_dir") is None
              and sorted(x.name for x in pc.iterdir()) == ["requirements.txt"],
              f"ok={rc['ok']} template_dir={rc.get('template_dir')} "
              f"落盘={sorted(x.name for x in pc.iterdir())}")
        # 歧义时 framework 必须为 null：调用方最可能顺手读它去套模板，
        # 回填候选值等于换个入口重现「错模板」事故。原始值另存供排查。
        check("C2b 歧义返回 needs_confirmation + 候选证据 + framework 置 null + 要求 --framework",
              rc.get("needs_confirmation") is True
              and rc.get("framework") is None
              and rc.get("framework_detected_but_ambiguous") == "flask"
              and isinstance(rc.get("framework_candidates"), list)
              and len(rc["framework_candidates"]) == 2
              and "--framework" in rc.get("hint", "")
              and "framework 字段为 null" in rc.get("hint", ""),
              f"framework={rc.get('framework')!r} "
              f"原始值={rc.get('framework_detected_but_ambiguous')!r} "
              f"候选={[(c['name'], c['confidence']) for c in rc.get('framework_candidates', [])]}")

        # C3 package.json 的 description 里有 koa，devDeps 只有 express -> 不得判成 koa
        pn = tmp / "desc_trap"
        pn.mkdir()
        (pn / "package.json").write_text(
            json.dumps({"name": "demo", "description": "a koa-style service",
                        "devDependencies": {"express": "^4.18.0"}}),
            encoding="utf-8")
        rn = apply_templates(pn, framework=None, common=False, dry_run=False, force=False)
        check("C3 description 里的 koa 不误导：devDeps 有 express 时套 express 模板",
              rn["framework"] == "express" and rn.get("template_dir") == "node-express"
              and (pn / ".prettierrc").is_file(),
              f"framework={rn['framework']} template_dir={rn.get('template_dir')}")

        # C4 多框架 high 并存时【不猜】：ok=false 且零复制
        pm = tmp / "ambiguous"
        pm.mkdir()
        (pm / "requirements.txt").write_text("flask==3.0.0\nfastapi==0.100\n", encoding="utf-8")
        rm_ = apply_templates(pm, framework=None, common=False, dry_run=False, force=False)
        check("C4 多框架并存时不猜：ok=false 且零文件落盘",
              rm_["ok"] is False and rm_["results"] == []
              and rm_.get("template_dir") is None
              and rm_.get("framework") is None
              and sorted(x.name for x in pm.iterdir()) == ["requirements.txt"],
              f"ok={rm_['ok']} framework={rm_.get('framework')!r} "
              f"落盘={sorted(x.name for x in pm.iterdir())}")
        check("C4b 歧义时输出候选与证据，供模型念给用户确认",
              rm_.get("needs_confirmation") is True
              and isinstance(rm_.get("framework_candidates"), list)
              and len(rm_.get("framework_candidates", [])) >= 2
              and all("evidence" in c and "confidence" in c
                      for c in rm_["framework_candidates"])
              and "--framework" in (rm_.get("hint", "") + rm_.get("error", "")),
              f"候选={[(c['name'], c['confidence']) for c in rm_.get('framework_candidates', [])]}")

        # C4c 纯注释项目（无真实依赖声明）不得谎报「检测到某不支持的框架」
        pj = tmp / "comment_only"
        pj.mkdir()
        (pj / "requirements.txt").write_text(
            "gunicorn==21.2.0\n# 也许以后换成 django\n", encoding="utf-8")
        rj = apply_templates(pj, framework=None, common=False, dry_run=False, force=False)
        check("C4c 纯注释项目不谎报不支持的框架：零复制且不声称检测到 django",
              rj["results"] == []
              and sorted(x.name for x in pj.iterdir()) == ["requirements.txt"]
              and "Django" not in (rj.get("notice", "") + rj.get("error", "")
                                   + rj.get("hint", "")),
              f"framework={rj.get('framework')} 落盘={sorted(x.name for x in pj.iterdir())}")

        # C5 歧义 + 显式 --framework：用户拍板后必须能正常复制
        rm2 = apply_templates(pm, framework="flask", common=False, dry_run=False, force=False)
        check("C5 歧义项目经 --framework flask 拍板后正常复制",
              rm2["ok"] is True and rm2.get("template_dir") == "python-flask"
              and rm_.get("needs_confirmation") is True
              and (pm / ".gitmessage").is_file(),
              f"ok={rm2['ok']} template_dir={rm2.get('template_dir')}")

        # C5b 歧义项目 + --framework + --common：显式指定后通用 prompt 仍可用
        rm3 = apply_templates(pm, framework="fastapi", common=True, dry_run=False, force=False)
        check("C5b 歧义项目经 --framework fastapi 拍板后复制 fastapi 模板",
              rm3["ok"] is True and rm3.get("template_dir") == "python-fastapi"
              and (pm / "CLAUDE.md").is_file(),
              f"template_dir={rm3.get('template_dir')}")

        # C6 显式 --framework 时不输出候选（用户已拍板，再问一遍是噪音）
        check("C6 显式 --framework 时不输出 framework_candidates",
              "framework_candidates" not in rm2 and "needs_confirmation" not in rm2,
              f"输出键={sorted(rm2.keys())}")

        # C7 输出契约：stdout 必须只有一个可 json.loads 的 JSON（detect 的输出已被吞掉）
        import subprocess
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "apply_templates.py"), str(tmp / "comment_trap")],
            capture_output=True, text=True)
        try:
            parsed = json.loads(proc.stdout)
            pure = True
        except json.JSONDecodeError:
            parsed, pure = None, False
        # C7 输出契约：stdout 必须只有一个可 json.loads 的 JSON。
        # 该 fixture 是「注释里有 fastapi」的歧义项目，正确行为是 ok=false + 零落盘，
        # 所以这里只断言【输出是合法单一 JSON 且带结构化 ok 字段】——
        # 不绑定 ok 的取值，因为判定对错由 C2b/C2d 单独断言。
        check("C7 stdout 是单一合法 JSON（detect 的错误输出不会污染本脚本输出）",
              pure and isinstance(parsed, dict) and "ok" in parsed,
              f"returncode={proc.returncode} stdout前80字={proc.stdout[:80]!r}")

        # C8 detect 缺失时显式报错，不降级为自己的猜测
        saved, missing_root = DETECT_SCRIPT, tmp / "no_detect" / "scripts"
        missing_root.mkdir(parents=True)
        try:
            globals()["DETECT_SCRIPT"] = missing_root / "detect_project.py"
            rd = apply_templates(tmp / "comment_trap", framework=None,
                                 common=False, dry_run=False, force=False)
        finally:
            globals()["DETECT_SCRIPT"] = saved
        check("C8 detect_project.py 缺失时显式报错（ok=false）而非自行猜测",
              rd["ok"] is False and "detect" in rd.get("error", "").lower()
              and "--framework" in rd.get("hint", ""),
              f"ok={rd['ok']} error={rd.get('error', '')[:48]}")
        check("C8b detect 缺失的提示指向「修/重装 Skill」而非「确认路径」",
              "重新安装" in rd.get("hint", "") and "不像项目根目录" not in rd.get("hint", ""),
              f"hint前60={rd.get('hint', '')[:60]}")

        # ---- D 组：失败分类（skill-developer-detect 实测发现的误导）----
        # 空目录会被 detect 判为「未识别出项目语言」，此前被本脚本误报成
        # 「脚本缺失/请重装 Skill」，会让买家去重装一个根本没坏的 Skill。
        p_empty = tmp / "empty_dir"
        p_empty.mkdir()
        (p_empty / "readme.md").write_text("hi\n", encoding="utf-8")
        r_empty = apply_templates(p_empty, framework=None, common=False,
                                  dry_run=False, force=False)
        check("D1 空目录：提示「确认路径指向项目根」而非「重装 Skill」",
              r_empty["ok"] is False
              and "项目根目录" in r_empty.get("hint", "")
              and "重新安装" not in r_empty.get("hint", ""),
              f"hint前70={r_empty.get('hint', '')[:70]}")
        check("D2 空目录与 detect 缺失两类失败的提示可区分",
              r_empty.get("hint", "") != rd.get("hint", ""),
              "两条 hint 文本必须不同，否则分类未生效")

        # ---- E 组：rejected 顶层提醒（skill-developer-tpl 走查发现）----
        # pyproject.toml 被拒 -> 工具配置没落地 -> 买家拿到 CLAUDE.md 却跑不了
        # ruff / pytest / git cz。不逐条读 reason 的买家发现不了。
        p_rej = tmp / "rejected_case"
        p_rej.mkdir()
        (p_rej / "pyproject.toml").write_text(
            '[project]\nname="my-shop-backend"\ndependencies=["flask>=3.0"]\n',
            encoding="utf-8")
        r_rej = apply_templates(p_rej, framework=None, common=False,
                                dry_run=False, force=False)
        check("E1 rejected>0 时顶层给出 rejected_files + requires_manual_merge",
              r_rej["ok"] is True
              and isinstance(r_rej.get("rejected_files"), list)
              and r_rej["rejected_files"][0]["target"] == "pyproject.toml"
              and r_rej.get("requires_manual_merge") is True,
              f"rejected_files={r_rej.get('rejected_files')}")
        check("E2 manual_merge_notice 说明配置未落地 + 覆盖非 Python 栈 + 给出合并方法",
              "没有落地" in r_rej.get("manual_merge_notice", "")
              and "golangci-lint" in r_rej.get("manual_merge_notice", "")
              and "不要合并 [project] / module / dependencies 段"
              in r_rej.get("manual_merge_notice", ""),
              f"notice前60={r_rej.get('manual_merge_notice', '')[:60]}")
        rej_entry = [r for r in r_rej["results"] if r["status"] == ST_REJECTED]
        check("E3 rejected 条目 reason 给出可定位的模板来源路径",
              bool(rej_entry) and "请打开 skills 下的" in rej_entry[0]["reason"]
              and "assets/templates/" in rej_entry[0]["reason"],
              f"reason前80={rej_entry[0]['reason'][:80] if rej_entry else '(无)'}")
        check("E3b reason 里给的模板路径真实存在（提示不能是假的）",
              bool(rej_entry)
              and (SKILL_DIR / "assets" / "templates" / "python-flask"
                   / "pyproject.toml").is_file(),
              "模板源文件必须真实存在")

        # ---- F 组：.gitmessage 的 git 前置条件 ----
        p_nogit = tmp / "nogit"
        p_nogit.mkdir()
        (p_nogit / "requirements.txt").write_text("flask==3.0.0\n", encoding="utf-8")
        r_nogit = apply_templates(p_nogit, framework=None, common=False,
                                  dry_run=False, force=False)
        gm_nogit = [r for r in r_nogit["results"] if r["template"] == "gitmessage.txt"]
        check("F1 非 git 仓库：.gitmessage 注明需先 git init（否则模板无法生效）",
              bool(gm_nogit) and "git init" in gm_nogit[0]["reason"],
              f"reason={gm_nogit[0]['reason'][:70] if gm_nogit else '(无)'}")

        p_git = tmp / "withgit"
        p_git.mkdir()
        (p_git / "requirements.txt").write_text("flask==3.0.0\n", encoding="utf-8")
        (p_git / ".git").mkdir()          # 只需目录存在即可，不做真实 git init
        r_git = apply_templates(p_git, framework=None, common=False,
                                dry_run=False, force=False)
        gm_git = [r for r in r_git["results"] if r["template"] == "gitmessage.txt"]
        check("F2 已 git 化：.gitmessage 不带 git init 警告（不制造无谓摩擦）",
              bool(gm_git) and "git init" not in gm_git[0]["reason"],
              f"reason={gm_git[0]['reason'][:50] if gm_git else '(无)'}")

        # ---- G 组：Go 也会触发 rejected（notice 文案须覆盖，不只 Python 栈）----
        p_go = tmp / "go_reject"
        p_go.mkdir()
        (p_go / "go.mod").write_text("module d\n\ngo 1.22\n", encoding="utf-8")
        r_go = apply_templates(p_go, framework=None, common=False,
                               dry_run=False, force=False)
        check("G1 Go 项目 go.mod 同样 rejected 且触发顶层提醒",
              r_go["summary"]["rejected"] == 1
              and r_go.get("requires_manual_merge") is True
              and r_go["rejected_files"][0]["target"] == "go.mod",
              f"rejected={r_go['summary']['rejected']} "
              f"files={[x['target'] for x in r_go.get('rejected_files', [])]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- 输出 ----
    passed = sum(1 for _, ok, _ in checks if ok)
    for name, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  |  {detail}" if detail else ""))
    print(f"\n自检结果：{passed}/{len(checks)} 通过")
    return 0 if passed == len(checks) else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="apply_templates.py",
        description="把本 Skill 的工程化模板复制到目标项目（改名/建目录/不覆盖备份/chmod）。不装任何依赖。",
    )
    p.add_argument("root", nargs="?", help="项目根目录")
    p.add_argument("--framework", choices=sorted(FRAMEWORK_TO_TEMPLATE_DIR),
                   help="指定框架；不给则按项目清单文件存在性推断")
    p.add_argument("--common", action="store_true", help="额外复制 5 个通用 prompt 模板到项目 prompts/")
    p.add_argument("--dry-run", action="store_true", help="只输出计划，绝不写盘")
    p.add_argument("--force", action="store_true", help="允许覆盖已存在文件（先备份为 .bak）并放行危险文件")
    p.add_argument("--selftest", action="store_true", help="运行内置自检")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.selftest:
        return selftest()

    if not args.root:
        print(build_parser().format_help())
        return _fail("缺少参数：项目根目录",
                    "用法：apply_templates.py <项目根目录> [--framework <框架>] [--common] [--dry-run] [--force]")

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        return _fail(f"项目根目录不存在或不是目录：{root}",
                    "请传入一个已存在的项目目录，例如 apply_templates.py ~/code/my-project")

    out = apply_templates(root, framework=args.framework, common=args.common,
                          dry_run=args.dry_run, force=args.force)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())