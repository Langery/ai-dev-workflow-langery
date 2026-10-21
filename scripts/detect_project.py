#!/usr/bin/env python3
"""detect_project.py — 自动检测项目语言、框架与现有工程化配置，输出结构化 JSON。

用法:
    python detect_project.py <项目根目录>
    python detect_project.py --selftest

运行环境:
    Python 3.11+（使用标准库 tomllib 解析 pyproject.toml / Cargo.toml）
    零第三方依赖，见同级 requirements.txt。

输出契约（检测模式下，所有情况统一为 stdout 上的 JSON）:
    成功: {"ok": true,  ...}                            退出码 0
    失败: {"ok": false, "error": "...", "hint": "..."}  退出码 1
    stderr 不承载诊断信息；--selftest 为诊断模式，输出为人类可读文本。
"""

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

try:
    import tomllib  # Python 3.11+ 标准库
except ModuleNotFoundError:  # pragma: no cover - 低版本运行时才会走到
    tomllib = None

# ------------------------------------------------------------------ 常量

# 遍历时需要跳过的噪声目录：第三方依赖、构建产物、IDE 缓存、测试夹具目录
NOISE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "vendor", "__pycache__",
    ".venv", "venv", ".tox", ".nox", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "site-packages", "dist", "build", "target",
    ".next", ".nuxt", ".idea", ".vscode", ".gradle", "coverage",
    # Go 惯例在 testdata/ 放测试夹具（golden 文件、样本数据）而非测试代码，
    # 过滤它可避免 testdata/fixtures/** 里大量 helper 被误判成测试；
    # 若你的项目确实把 *_test.go 放在 testdata/ 下，请从本集合移除该项。
    "testdata", "testData", "third_party", ".terraform", ".cache",
}

MAX_SCAN_DEPTH = 15  # 目录扫描最大深度，防止异常深的目录树拖慢检测

# 各语言框架注册表：key 为输出用的框架名，value 为判定用的包名前缀
# 顺序即优先级（多个框架同时命中时，取列表靠前者），与历史版本行为保持一致
PY_FRAMEWORKS = ("fastapi", "django", "flask")
NODE_FRAMEWORKS = ("fastify", "nestjs", "koa", "express", "next")
RUST_FRAMEWORKS = ("actix-web", "axum", "rocket")

# 包名归一化：PEP 503 风格，把 - _ . 连续段统一成 -
def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip().lower())


# 这些包名虽以框架名开头，但属于测试插件而非框架本体，不作为框架证据
PY_FRAMEWORK_FALSE_PREFIX = ("pytest-", "pytest_", "test-", "test_")


def _package_name(spec: str) -> str:
    """从依赖声明里取出包名。

    支持: "flask" / "flask==3.0.0" / "flask[async]>=2" / "django-rest-framework"
    / "git+https://host/pkg.git#egg=flask" / "pkg @ https://host/pkg.whl"
    """
    s = spec.strip()
    if not s:
        return ""
    # PEP 508 直接依赖: name @ url
    s = re.split(r"\s+@\s+", s)[0]
    # 去掉 URL 片段 / 版本约束 / extras / 环境标记
    s = re.split(r"[#;<>=!~\[]", s, maxsplit=1)[0]
    # 保留首段的包名（去掉路径形式 ./pkg、git+https://host/…）
    s = s.strip().strip('"\'')
    if "/" in s:
        s = s.rsplit("/", 1)[-1]
    s = s.split("\\", 1)[-1]
    m = re.match(r"[A-Za-z0-9._-]+", s)
    return _norm(m.group(0)) if m else ""


def _framework_hit(pkg: str, framework: str) -> bool:
    """包名是否构成某框架的证据。

    精确命中（flask）或扩展包命中（flask-caching / django-rest-framework）
    算命中；pytest-flask 这类测试插件不算框架本体。
    """
    fw = _norm(framework)
    if not pkg or not fw:
        return False
    if pkg == fw:
        return True
    if not pkg.startswith(fw + "-"):
        return False
    # 命中的是框架的扩展包，排除测试插件前缀（pytest-flask / test-django）
    return not pkg.startswith(PY_FRAMEWORK_FALSE_PREFIX)


# ------------------------------------------------------------------ 文本工具

def _strip_comment(line: str, markers=("#",)) -> str:
    """去掉行尾注释。

    只有位于行首或前面是空白/分隔符的标记才算注释，
    避免误伤 git+https://host/pkg.git#egg=flask 这类 URL 片段。
    """
    for m in markers:
        idx = line.find(m)
        while idx != -1:
            if idx == 0 or line[idx - 1] in " \t,;(":
                return line[:idx]
            nxt = line.find(m, idx + 1)
            idx = nxt
    return line


def _iter_comment_lines(path: Path, markers=("#",)):
    """产出 (行号, 注释文本)，用于收集"注释里提到某框架"这类弱证据。"""
    if not path.exists():
        return
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return
    for lineno, raw in enumerate(text.splitlines(), start=1):
        s = raw.strip()
        if not s:
            continue
        stripped = _strip_comment(s, markers)
        rest = s[len(stripped):].strip()
        if rest:
            yield lineno, rest


def _iter_code_lines(path: Path, markers=("#",)):
    """产出 (行号, 去注释后的有效内容)，跳过整行注释与空行。"""
    if not path.exists():
        return
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw, markers).strip()
        if line and not line.startswith(("-r ", "--requirement", "-e ", "--index-url", "#")):
            yield lineno, line


def _load_toml(path: Path):
    """用 tomllib 解析 TOML，返回 (data, error)。

    解析失败不抛异常，返回 error 供调用方降级处理——宁可报"无法判定"，
    也不要把语法错误的项目猜成"已配置"。
    """
    if tomllib is None:
        return None, "当前 Python 缺少标准库 tomllib（需 Python 3.11+）"
    if not path.exists():
        return None, None
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh), None
    except (tomllib.TOMLDecodeError, OSError, ValueError) as exc:
        return None, f"{path.name} 解析失败: {exc}"


# ------------------------------------------------------------------ 文件遍历

def _walk_files(root: Path, match):
    """递归产出匹配的文件，跳过噪声目录与过深目录。"""
    root_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        depth = len(here.parts) - root_depth
        if depth >= MAX_SCAN_DEPTH:
            dirnames[:] = []
            continue
        # 就地裁剪，阻止 os.walk 进入噪声目录
        dirnames[:] = sorted(
            d for d in dirnames if d not in NOISE_DIRS and not d.startswith(".git")
        )
        for fn in sorted(filenames):
            if match(fn):
                yield here / fn


def _has_file(root: Path, patterns) -> bool:
    """递归查找是否存在匹配任一 glob 模式的文件（跳过噪声目录）。"""
    pats = patterns if isinstance(patterns, (list, tuple, set)) else [patterns]
    for _ in _walk_files(root, lambda fn: any(re.fullmatch(p, fn) for p in pats)):
        return True
    return False


def _first_file(root: Path, patterns):
    pats = patterns if isinstance(patterns, (list, tuple, set)) else [patterns]
    for p in _walk_files(root, lambda fn: any(re.fullmatch(p, fn) for p in pats)):
        return p
    return None


# ------------------------------------------------------------------ 语言检测

def detect_language(root: Path):
    """检测项目主语言，返回 (language, evidence) 或 (None, None)。"""
    table = [
        ("python", ["pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "Pipfile"]),
        ("node", ["package.json"]),
        ("go", ["go.mod"]),
        ("rust", ["Cargo.toml"]),
    ]
    for lang, names in table:
        hit = next((n for n in names if (root / n).exists()), None)
        if hit:
            return lang, hit
    return None, None


# ------------------------------------------------------------------ 框架检测

def _push_candidate(store, name, evidence, confidence, source):
    """登记一个框架候选（同框架保留置信度更高 / 证据更多的一条）。"""
    if not name:
        return
    for c in store:
        if c["name"] == name:
            c["evidence"].append(evidence)
            if confidence == "high":
                c["confidence"] = "high"
            c["source"] = source
            return
    store.append({
        "name": name,
        "evidence": [evidence],
        "confidence": confidence,
        "source": source,
    })


def detect_framework(root: Path, language: str) -> dict:
    """检测框架，返回候选列表 + 向后兼容的单一 framework 字段。

    置信度规则:
        high —— 来自真实依赖声明（requirements.txt / pyproject / package.json / Cargo.toml）
        low  —— 仅出现在注释里，需要用户或模型二次确认，不得据此直接选模板
    """
    candidates = []
    notes = []

    if language == "python":
        # 1) requirements.txt：剥离注释后的依赖声明
        req = root / "requirements.txt"
        for lineno, line in _iter_code_lines(req):
            pkg = _package_name(line)
            for fw in PY_FRAMEWORKS:
                if _framework_hit(pkg, fw):
                    _push_candidate(candidates, fw, f"requirements.txt:{lineno} 依赖声明 {line}",
                                    "high", "requirements.txt")
        # 2) pyproject.toml：优先用 tomllib 读结构化依赖
        pyproject = root / "pyproject.toml"
        data, err = _load_toml(pyproject)
        if err:
            notes.append(err)
        if isinstance(data, dict):
            project = data.get("project") or {}
            for spec in project.get("dependencies") or []:
                pkg = _package_name(str(spec))
                for fw in PY_FRAMEWORKS:
                    if _framework_hit(pkg, fw):
                        _push_candidate(candidates, fw, f"pyproject.toml project.dependencies: {spec}",
                                        "high", "pyproject.toml")
            for group, specs in (project.get("optional-dependencies") or {}).items():
                for spec in specs or []:
                    pkg = _package_name(str(spec))
                    for fw in PY_FRAMEWORKS:
                        if _framework_hit(pkg, fw):
                            _push_candidate(candidates, fw,
                                            f"pyproject.toml optional-dependencies.{group}: {spec}",
                                            "high", "pyproject.toml")
            poetry = ((data.get("tool") or {}).get("poetry") or {}).get("dependencies") or {}
            for pkg, ver in poetry.items():
                for fw in PY_FRAMEWORKS:
                    if _framework_hit(_norm(str(pkg)), fw):
                        _push_candidate(candidates, fw,
                                        f"pyproject.toml tool.poetry.dependencies: {pkg}",
                                        "high", "pyproject.toml")
        # 3) 注释里的弱证据（low）
        for src in (req, pyproject):
            for lineno, comment in _iter_comment_lines(src):
                low = _norm(comment)
                for fw in PY_FRAMEWORKS:
                    if re.search(rf"(?<![a-z0-9]){re.escape(fw)}(?![a-z0-9])", low):
                        _push_candidate(candidates, fw,
                                        f"{src.name}:{lineno} 仅注释提及: {comment[:80]}",
                                        "low", "comment")
        stdlib = "python-stdlib"

    elif language == "node":
        pkg_json = root / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                notes.append(f"package.json 解析失败: {exc}")
                data = None
            if isinstance(data, dict):
                for fw, key in (("fastify", "fastify"), ("nestjs", "@nestjs/core"),
                                ("koa", "koa"), ("express", "express"), ("next", "next")):
                    for section in ("dependencies", "devDependencies"):
                        if key in (data.get(section) or {}):
                            _push_candidate(candidates, fw,
                                            f"package.json {section}.{key} 依赖声明",
                                            "high", "package.json")
                            break
        stdlib = "node-stdlib"

    elif language == "rust":
        cargo = root / "Cargo.toml"
        data, err = _load_toml(cargo)
        if err:
            notes.append(err)
        if isinstance(data, dict):
            deps = data.get("dependencies") or {}
            for pkg in deps:
                low = _norm(str(pkg))
                for fw in RUST_FRAMEWORKS:
                    if _framework_hit(low, fw):
                        _push_candidate(candidates, "rust-web",
                                        f"Cargo.toml [dependencies].{pkg}",
                                        "high", "Cargo.toml")
        for lineno, comment in _iter_comment_lines(cargo):
            low = _norm(comment)
            for fw in RUST_FRAMEWORKS:
                if fw in low:
                    _push_candidate(candidates, "rust-web",
                                    f"Cargo.toml:{lineno} 仅注释提及: {comment[:80]}",
                                    "low", "comment")
        stdlib = "rust-stdlib"

    else:
        stdlib = f"{language or 'unknown'}-stdlib" if language else "unknown"
        if language == "go":
            stdlib = "go-stdlib"

    # 排序：high 在前，其次按注册表优先级，最后按名称保证可复现
    order = {n: i for i, n in enumerate(
        list(PY_FRAMEWORKS) + list(NODE_FRAMEWORKS) + ["rust-web"])}
    candidates.sort(key=lambda c: (0 if c["confidence"] == "high" else 1,
                                   order.get(c["name"], 99), c["name"]))

    # framework 只从 high 候选里取——low 证据不足以驱动模板选择
    high = [c["name"] for c in candidates if c["confidence"] == "high"]
    framework = high[0] if high else stdlib
    # 存在 low 证据、或多个 high 框架并存时，都要请用户确认后再套模板
    needs_confirm = bool(candidates) and (len(high) != 1 or len(high) < len(candidates))

    return {
        "framework": framework,
        "framework_candidates": candidates,
        "framework_needs_confirmation": needs_confirm,
        "framework_stdlib_fallback": stdlib,
        "_notes": notes,
    }


# ------------------------------------------------------------------ 工程化现状

def detect_existing_config(root: Path, language: str) -> dict:
    """检测现有工程化配置。"""
    config = {
        "is_git_repo": (root / ".git").exists(),
        "has_lint": False,
        "has_tests": False,
        "has_pre_commit": (root / ".pre-commit-config.yaml").exists(),
        "has_commit_template": False,
        "has_claude_md": (root / "CLAUDE.md").exists(),
        "has_cursorrules": (root / ".cursorrules").exists(),
        "test_framework": None,
        "lint_evidence": [],
        "test_evidence": [],
    }
    notes = []

    if language == "python":
        # lint：独立配置文件
        for name in (".ruff.toml", "ruff.toml", ".flake8", ".pylintrc", "pylintrc",
                     ".isort.cfg", "mypy.ini", ".pylintrc.toml"):
            if (root / name).exists():
                config["has_lint"] = True
                config["lint_evidence"].append(name)
        # lint：pyproject.toml 的 tool 表（tomllib 结构化判定，不再裸子串）
        data, err = _load_toml(root / "pyproject.toml")
        if err:
            notes.append(err)
        if isinstance(data, dict):
            tool = data.get("tool") or {}
            for key in ("ruff", "black", "isort", "flake8", "pylint", "mypy"):
                if key in tool:
                    config["has_lint"] = True
                    config["lint_evidence"].append(f"pyproject.toml [tool.{key}]")
        # tests：目录 / 配置文件 / 真实测试文件
        if (root / "tests").is_dir() or (root / "test").is_dir():
            config["has_tests"] = True
            config["test_evidence"].append("tests/ 目录")
        if isinstance(data, dict) and "pytest" in ((data.get("tool") or {})):
            config["has_tests"] = True
            config["test_framework"] = "pytest"
            config["test_evidence"].append("pyproject.toml [tool.pytest]")
        for name in ("pytest.ini", "tox.ini"):
            if (root / name).exists():
                config["has_tests"] = True
                config["test_framework"] = config["test_framework"] or "pytest"
                config["test_evidence"].append(name)
        found = _first_file(root, [r"test_[^/]*\.py", r"[^/]*_test\.py"])
        if found:
            config["has_tests"] = True
            config["test_evidence"].append(str(found.relative_to(root)))
        # pytest 是否在依赖里声明
        for spec in _python_declared_deps(root):
            if _package_name(spec) == "pytest":
                config["test_framework"] = "pytest"
        if config["has_tests"] and not config["test_framework"]:
            config["test_framework"] = "unittest"

    elif language == "node":
        pkg_json = root / "package.json"
        data = None
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                notes.append(f"package.json 解析失败: {exc}")
        if isinstance(data, dict):
            deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
            if "eslint" in deps or "@biomejs/biome" in deps:
                config["has_lint"] = True
                config["lint_evidence"].append("package.json eslint / biome 依赖")
            for name in ("eslint.config.js", "eslint.config.mjs", ".eslintrc",
                         ".eslintrc.json", ".eslintrc.js", ".eslintrc.cjs",
                         "biome.json", "prettier.config.js", ".prettierrc"):
                if (root / name).exists():
                    config["has_lint"] = True
                    config["lint_evidence"].append(name)
            for name, label in (("jest", "jest"), ("vitest", "vitest"), ("mocha", "mocha")):
                if name in deps:
                    config["test_framework"] = label
                    config["test_evidence"].append(f"package.json 依赖 {name}")
                    break
        found = _first_file(root, [r"[^/]*\.(test|spec)\.(js|jsx|ts|tsx|mjs|cjs)"])
        if found:
            config["has_tests"] = True
            config["test_evidence"].append(str(found.relative_to(root)))
            if not config["test_framework"]:
                config["test_framework"] = "node-stdlib-test"
        config["has_tests"] = config["has_tests"] or bool(config["test_framework"])

    elif language == "go":
        for name in (".golangci.yml", ".golangci.yaml", ".golangci.toml"):
            if (root / name).exists():
                config["has_lint"] = True
                config["lint_evidence"].append(name)
        # Go 的测试惯例就是放在子目录（internal/、pkg/…），必须递归找
        found = _first_file(root, [r"[^/]*_test\.go"])
        if found:
            config["has_tests"] = True
            config["test_framework"] = "go test"
            config["test_evidence"].append(str(found.relative_to(root)))

    elif language == "rust":
        for name in ("rustfmt.toml", ".rustfmt.toml", "clippy.toml", ".clippy.toml"):
            if (root / name).exists():
                config["has_lint"] = True
                config["lint_evidence"].append(name)
        if (root / "tests").is_dir():
            config["has_tests"] = True
            config["test_framework"] = "cargo test"
            config["test_evidence"].append("tests/ 目录")
        found = _first_file(root, [r"[^/]*_test\.rs"])
        if found:
            config["has_tests"] = True
            config["test_framework"] = "cargo test"
            config["test_evidence"].append(str(found.relative_to(root)))

    # git commit message 模板
    # 注意：git 配置是 [section] + key = value 的分段格式，并不存在
    # "commit.template" 这个字面串，必须按段解析（旧实现用裸子串，
    # 对任何真实 git 仓库都判不出来）
    config["has_commit_template"], tmpl = _detect_commit_template(root / ".git" / "config")
    if tmpl:
        config["lint_evidence"].append(f".git/config commit.template = {tmpl}")

    config["_notes"] = notes
    return config


def _detect_commit_template(git_config: Path):
    """解析 .git/config 的 [commit] 段，返回 (是否配置, 模板路径)。"""
    if not git_config.exists():
        return False, None
    try:
        text = git_config.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False, None
    section = None
    for raw in text.splitlines():
        line = _strip_comment(raw, ("#", ";")).strip()
        if not line:
            continue
        if line.startswith("["):
            section = line.strip("[]").split()[0].strip('"').lower() if line.strip("[]").split() else ""
            continue
        if section == "commit" and "=" in line:
            key, _, val = line.partition("=")
            if key.strip().lower() == "template" and val.strip():
                return True, val.strip()
    return False, None


def _python_declared_deps(root: Path):
    """汇总 Python 项目声明过的依赖（requirements.txt + pyproject 结构化字段）。"""
    specs = []
    for _lineno, line in _iter_code_lines(root / "requirements.txt"):
        specs.append(line)
    data, _err = _load_toml(root / "pyproject.toml")
    if isinstance(data, dict):
        project = data.get("project") or {}
        specs += [str(s) for s in (project.get("dependencies") or [])]
        for group in (project.get("optional-dependencies") or {}).values():
            specs += [str(s) for s in (group or [])]
        poetry = ((data.get("tool") or {}).get("poetry") or {}).get("dependencies") or {}
        specs += [str(k) for k in poetry]
    return specs


# ------------------------------------------------------------------ 推荐步骤

def make_recommendations(language, framework_info, existing) -> list:
    """基于检测结果生成推荐步骤。"""
    recs = []

    # 衔接下一脚本：确有模板可复制时，先提示去跑 apply_templates.py 把模板落进来。
    # 放在最前面是因为它决定了后续所有工程化配置的落点（先有模板，再装工具）。
    # 只用静态文案，不反向引用 apply 模块 —— 依赖方向是 apply -> detect，
    # 反向引用会形成循环依赖，破坏单一事实源设计。
    # 仅在【确有模板】时提示：降级场景（无模板 / 不支持的框架）提了也只会让买家
    # 空跑一趟，必须让 recommendations 指向 references/ 而不是 apply。
    #
    # 歧义场景（framework_needs_confirmation）必须【先于】模板判断处理：
    # 此时 framework 字段仍有值（歧义时由调用方置 null），若直接判 _fw 会把某个
    # 候选当定论推给买家，而 apply 对歧义会返回 ok=false + 零落盘 —— 买家白跑一趟，
    # 且 recommendations 与 apply 的结论自相矛盾。
    _fw = TEMPLATE_VOCAB.get(framework_info.get("framework", ""),
                            framework_info.get("framework", ""))
    if framework_info.get("framework_needs_confirmation"):
        _cands = "/".join(
            c.get("name", "") for c in (framework_info.get("framework_candidates") or [])
            if c.get("name")
        )
        recs.append(
            "框架判定有歧义"
            + (f"（候选：{_cands}）" if _cands else "")
            + "：先与用户确认用哪套，再 --framework <框架> 显式指定后跑 "
              "python3 scripts/apply_templates.py <项目根目录>；"
              "判定未完成前不要假定某个候选就是正确框架"
        )
    elif _fw in TEMPLATES_AVAILABLE:
        recs.append(
            f"把 {_fw} 工程化模板复制进项目："
            "python3 scripts/apply_templates.py <项目根目录> [--dry-run] 先看将复制哪些文件")

    if not existing["is_git_repo"]:
        recs.append("初始化 git 仓库：git init")

    if language == "python":
        if not existing["has_lint"]:
            recs.append("安装 ruff 作为 lint 和 formatter：pip install ruff")
        if not existing["has_tests"]:
            recs.append("安装 pytest + pytest-cov：pip install pytest pytest-cov")
        if not existing["has_pre_commit"]:
            recs.append("安装 pre-commit 框架：pip install pre-commit && pre-commit install")

    elif language == "node":
        if not existing["has_lint"]:
            recs.append("安装 eslint：npm install -D eslint")
        if not existing["has_tests"]:
            recs.append("安装 vitest：npm install -D vitest")
        if not existing["has_pre_commit"]:
            recs.append("安装 husky + lint-staged：npm install -D husky lint-staged")

    elif language == "go":
        if not existing["has_lint"]:
            recs.append("安装 golangci-lint：go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest")
        if not existing["has_tests"]:
            recs.append("补充测试：Go 测试文件必须命名为 *_test.go 并与被测代码同目录"
                        "（如 internal/service/service_test.go），然后 go test ./...")

    elif language == "rust":
        if not existing["has_lint"]:
            recs.append("安装 rustfmt + clippy：rustup component add rustfmt clippy")
        if not existing["has_tests"]:
            recs.append("补充测试：在 tests/ 目录或模块内写 #[cfg(test)] 单元测试，cargo test")

    if not existing["has_commit_template"]:
        recs.append("配置 commit message 模板：git config --local commit.template .gitmessage")

    if not existing["has_claude_md"] and not existing["has_cursorrules"]:
        recs.append("创建 CLAUDE.md 项目上下文文件")

    return recs


# ------------------------------------------------------------------ 模板口径归一

# apply_templates.py 的 FRAMEWORK_TO_TEMPLATE_DIR 用的是「模板目录口径」：
# 语言只有 go / rust，不带 -stdlib 后缀。此表把本脚本的检测口径翻译过去，
# 保证两个脚本对同一个项目得出同一个模板决策。
TEMPLATE_VOCAB = {
    "go-stdlib": "go",
    "rust-stdlib": "rust",
    "rust-web": "rust",      # 本 skill 只有一个 rust 模板集
}

# apply_templates.py 未提供模板的框架：识别到就必须降级提示，不能套用别的模板
TEMPLATES_UNSUPPORTED = ("django", "koa", "nestjs", "fastify", "next")

# 确有模板可复制的框架（apply_templates.py 的 FRAMEWORK_TO_TEMPLATE_DIR 的 key）。
# recommendations 里提示「去跑 apply」时以本集合为准，避免在没有模板的降级场景
# 反而把买家引向 apply_templates（那会让他以为能复制到模板，实则必然降级）。
TEMPLATES_AVAILABLE = ("flask", "fastapi", "express", "go", "rust")


def framework_for_templates(root: Path) -> dict:
    """返回模板选择决策，供 apply_templates.py 直接复用（单一事实源）。

    这是 scripts/apply_templates.py 做模板推断时【应当调用】的入口，
    不要在那边再复制一份框架推断逻辑——两份逻辑必然漂移，且漂移会让买家
    拿到与检测结论矛盾的模板。

    needs_confirmation 的准确语义（易误读，务必按此理解）：
        它表示「存在歧义或杂音，值得提醒模型/用户」，**不是**「判定不可信、
        请勿使用」。具体分两类：
        A. 1 个 high 候选 + 若干 low 杂音（例如 requirements 里 flask 是真依赖，
           但注释里提了一句 fastapi）——判定本身可信，framework 已由 high 证据
           选定。此时【不应】拦截复制，否则一个纯 Flask 项目会因为某天有人在
           注释里写了句 TODO 就拿不到模板，属于误伤。
        B. 2 个及以上 high 候选（两个框架都是真依赖）——真歧义，判定不可信，
           应当拦下来让用户先确认。
    因此判断是否拦截，建议按 high 候选数 > 1 来做，而不是直接照抄本字段。

    返回:
        framework        模板口径的框架名（flask/fastapi/express/go/rust/…）
        has_template      是否有模板可复制
        needs_confirmation存在歧义或杂音，需提醒用户确认（语义见上，勿直接当拦截条件）
        candidates        完整候选列表（含证据与置信度）
    """
    result = analyze(root)
    raw = result["framework"]
    fw = TEMPLATE_VOCAB.get(raw, raw)
    return {
        "framework": fw,
        "has_template": fw in TEMPLATES_AVAILABLE,
        "needs_confirmation": result["framework_needs_confirmation"],
        "candidates": result["framework_candidates"],
        "language": result["language"],
    }


# ------------------------------------------------------------------ 输出封装

def out(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def fail(error: str, hint: str = "") -> None:
    """统一失败出口：JSON 写 stdout，退出码 1。"""
    out({"ok": False, "error": error, "hint": hint})
    sys.exit(1)


# ------------------------------------------------------------------ 主流程

def analyze(root: Path) -> dict:
    """执行检测，返回完整的成功结果对象。"""
    language, marker = detect_language(root)
    if not language:
        fail("未识别出项目语言",
             "项目根目录下找不到 pyproject.toml / requirements.txt / package.json / "
             "go.mod / Cargo.toml。确认路径是否指向项目根目录；若是语言无关项目，"
             "直接参考 references/general-conventions.md")

    fw = detect_framework(root, language)
    existing = detect_existing_config(root, language)
    recommendations = make_recommendations(language, fw, existing)

    warnings = list(fw.get("_notes") or []) + list(existing.get("_notes") or [])
    candidates = fw["framework_candidates"]
    if fw["framework_needs_confirmation"]:
        if not fw["framework"].endswith("-stdlib"):
            # 有 high 框架，但同时存在其它框架线索：提示确认，不推翻已选结果
            warnings.append(
                "除已选框架 " + fw["framework"] + " 外，还有其它框架线索（"
                + " / ".join(
                    f"{c['name']}[{c['confidence']}]" for c in candidates
                    if c["name"] != fw["framework"])
                + "），请与用户确认后再选模板")
        else:
            warnings.append(
                "框架线索只出现在注释里（"
                + " / ".join(f"{c['name']}({c['source']})" for c in candidates)
                + "），未作为 framework 采用，请与用户确认真实框架")
            recommendations.insert(
                0, "与用户确认真实框架后再复制 templates/<language>-<framework>/ 模板")

    return {
        "ok": True,
        "root": str(root),
        "language": language,
        "language_evidence": marker,
        "framework": fw["framework"],
        "framework_candidates": candidates,
        "framework_needs_confirmation": fw["framework_needs_confirmation"],
        "existing_config": {k: v for k, v in existing.items() if not k.startswith("_")},
        "recommendations": recommendations,
        "warnings": warnings,
        "meta": {
            "script": "detect_project.py",
            "schema_version": 2,
            "python_requires": ">=3.11",
            "toml_parser": "tomllib" if tomllib is not None else "unavailable",
        },
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description="检测项目语言/框架/工程化配置，输出结构化 JSON")
    p.add_argument("root", nargs="?", help="项目根目录（默认当前目录）")
    p.add_argument("--selftest", action="store_true",
                   help="运行内置自测（不依赖真实项目，需 Python 3.11+）")
    args = p.parse_args()

    if args.selftest:
        sys.exit(run_selftest())

    if tomllib is None:
        fail("当前 Python 缺少标准库 tomllib",
             "本脚本需要 Python 3.11+（用于结构化解析 pyproject.toml / Cargo.toml），"
             "请升级解释器后重试")

    root = Path(args.root).expanduser() if args.root else Path.cwd()
    try:
        root = root.resolve()
    except OSError as exc:
        fail(f"路径解析失败: {exc}", "检查路径是否包含非法字符或失效的软链接")
    if not root.exists():
        fail(f"路径不存在: {root}", "确认项目根目录路径拼写正确")
    if not root.is_dir():
        fail(f"路径不是目录: {root}", "请传入项目根目录，而不是其中的某个文件")

    try:
        out(analyze(root))
    except SystemExit:
        raise
    except Exception as exc:  # 兜底：任何意外都必须是 JSON，不是裸 traceback
        fail(f"检测过程出错: {type(exc).__name__}: {exc}",
             "请确认项目目录可读；若为权限问题请修正后重试")


# ------------------------------------------------------------------ 自测

def _mk(root: Path, rel: str, content: str) -> None:
    """在临时项目里写文件（自动建父目录）。"""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def run_selftest() -> int:
    """内置自测：覆盖 4 类修复点 + 幂等性。退出码 0 = 全通过。"""
    if tomllib is None:
        print("[FAIL] 需要 Python 3.11+（标准库 tomllib 缺失）")
        return 1

    cases = []

    def check(name, cond, detail=""):
        cases.append((name, bool(cond), detail))

    with tempfile.TemporaryDirectory(prefix="detect_project_selftest_") as tmp:
        base = Path(tmp)

        # --- 用例 1：Go 测试放在 internal/service/ 子目录（非递归 glob 会漏）
        go = base / "go_proj"
        _mk(go, "go.mod", "module example.com/demo\n\ngo 1.22\n")
        _mk(go, "main.go", "package main\n\nfunc main() {}\n")
        _mk(go, "internal/service/service.go", "package service\n\nfunc Do() {}\n")
        _mk(go, "internal/service/service_test.go", "package service\n\nimport \"testing\"\n\nfunc TestDo(t *testing.T) {}\n")
        _mk(go, "vendor/github.com/x/y/y_test.go", "package y\n")  # 噪声目录，应被跳过
        cfg = analyze(go)["existing_config"]
        check("Go 子目录测试检出 has_tests=true", cfg["has_tests"] is True,
              f"evidence={cfg['test_evidence']}")
        check("Go test_framework=go test", cfg["test_framework"] == "go test")
        check("Go 噪声目录 vendor 不影响结果",
              not any("vendor" in e for e in cfg["test_evidence"]))

        # --- 用例 2：pyproject 注释提到 tool.ruff，但无真实 [tool.ruff] 表
        py = base / "py_proj"
        _mk(py, "requirements.txt", "flask==3.0.0\nrequests>=2.31\n")
        _mk(py, "pyproject.toml", (
            "[project]\n"
            'name = "demo"\n'
            'version = "0.1.0"\n'
            'dependencies = ["flask==3.0.0"]\n'
            "\n"
            "# TODO: 以后考虑接入 tool.ruff 做统一格式化\n"
            "# 现在先不管 tool.black 和 tool.isort\n"
        ))
        _mk(py, "app.py", "app = 1\n")
        res = analyze(py)
        ec = res["existing_config"]
        check("注释提及 tool.ruff 不算已配置 lint", ec["has_lint"] is False,
              f"lint_evidence={ec['lint_evidence']}")
        check("无 lint 时给出安装建议",
              any("ruff" in r for r in res["recommendations"]))

        # 真实 [tool.ruff] 存在时应判定为已配置
        py2 = base / "py_proj2"
        _mk(py2, "requirements.txt", "flask==3.0.0\n")
        _mk(py2, "pyproject.toml",
            "[project]\nname = \"demo\"\n\n[tool.ruff]\nline-length = 100\n")
        _mk(py2, "tests/test_app.py", "def test_x():\n    assert True\n")
        ec2 = analyze(py2)["existing_config"]
        check("真实 [tool.ruff] 表判定 has_lint=true", ec2["has_lint"] is True,
              f"lint_evidence={ec2['lint_evidence']}")
        check("tests/ 目录 + 测试文件判定 has_tests=true", ec2["has_tests"] is True,
              f"test_evidence={ec2['test_evidence']}")

        # --- 用例 3：requirements 里 flask 是真依赖，fastapi 只在注释里
        mixed = base / "mixed_proj"
        _mk(mixed, "requirements.txt", (
            "flask==3.0.0\n"
            "# TODO: maybe fastapi later\n"
        ))
        _mk(mixed, "pyproject.toml", "[project]\nname = \"demo\"\n")
        r3 = analyze(mixed)
        by_name = {c["name"]: c for c in r3["framework_candidates"]}
        check("flask 候选存在且 confidence=high",
              by_name.get("flask", {}).get("confidence") == "high",
              str(r3["framework_candidates"]))
        check("fastapi 仅注释命中 → confidence=low",
              by_name.get("fastapi", {}).get("confidence") == "low",
              str(r3["framework_candidates"]))
        check("framework 取高置信度候选 flask", r3["framework"] == "flask", r3["framework"])
        check("有 low 候选时提示需确认",
              r3["framework_needs_confirmation"] is True and
              any("确认" in w for w in r3["warnings"]), str(r3["warnings"]))

        # --- 用例 4：只有注释提到框架时，不得据此选定框架
        only_comment = base / "comment_only"
        _mk(only_comment, "requirements.txt", "# 也许以后会换成 django\ngunicorn==21.2.0\n")
        _mk(only_comment, "pyproject.toml", "[project]\nname = \"demo\"\n")
        r4 = analyze(only_comment)
        check("纯注释框架不驱动 framework 选择",
              r4["framework"] == "python-stdlib" and
              all(c["confidence"] == "low" for c in r4["framework_candidates"]),
              f"framework={r4['framework']} candidates={r4['framework_candidates']}")

        # --- 用例 5：pyproject.toml 语法错误 → 降级为"无法判定"而非误判
        broken = base / "broken_proj"
        _mk(broken, "requirements.txt", "flask==3.0.0\n")
        _mk(broken, "pyproject.toml", "[project\nname = = broken\n")
        r5 = analyze(broken)
        check("TOML 语法错误不误判 has_lint",
              r5["existing_config"]["has_lint"] is False)
        check("TOML 语法错误产生 warning",
              any("解析失败" in w for w in r5["warnings"]), str(r5["warnings"]))
        check("TOML 语法错误时仍能从 requirements 判出框架",
              r5["framework"] == "flask", r5["framework"])

        # --- 用例 6：失败路径统一为 JSON（stdout 可解析 + 含 hint）
        err_payload, err_code = _capture_failure(base / "not_exist_dir")
        check("失败路径退出码为 1", err_code == 1, str(err_code))
        check("失败路径 ok=false", err_payload.get("ok") is False, str(err_payload))
        check("失败路径含 hint", bool(err_payload.get("hint")), str(err_payload))

        no_lang, no_lang_code = _capture_failure(base)
        check("未识别语言时 ok=false + exit 1",
              no_lang.get("ok") is False and no_lang_code == 1, str(no_lang))

        # --- 用例 7：幂等性（同一输入两次执行结果逐字节一致）
        first = json.dumps(analyze(py), ensure_ascii=False, sort_keys=True, default=str)
        second = json.dumps(analyze(py), ensure_ascii=False, sort_keys=True, default=str)
        check("同一输入两次执行输出一致（幂等）", first == second)

        # --- 用例 8：Node 框架依赖识别未被破坏
        node = base / "node_proj"
        _mk(node, "package.json", json.dumps({
            "name": "demo", "dependencies": {"express": "^4.18.0"},
            "devDependencies": {"vitest": "^1.0.0", "eslint": "^9.0.0"}}, indent=2))
        _mk(node, "src/app.test.js", "test('x', () => {})\n")
        rn = analyze(node)
        check("Node framework=express", rn["framework"] == "express", rn["framework"])
        check("Node test_framework=vitest",
              rn["existing_config"]["test_framework"] == "vitest")
        check("Node 子目录测试文件被检出", rn["existing_config"]["has_tests"] is True,
              str(rn["existing_config"]["test_evidence"]))

        # --- 用例 10：模板口径归一（apply_templates.py 的单一事实源入口）
        t_go = base / "t_go"
        _mk(t_go, "go.mod", "module demo\n\ngo 1.22\n")
        d_go = framework_for_templates(t_go)
        check("Go 归一为模板口径 go（而非 go-stdlib）",
              d_go["framework"] == "go" and d_go["has_template"] is True, str(d_go))
        t_rs = base / "t_rust"
        _mk(t_rs, "Cargo.toml", "[package]\nname = \"demo\"\n")
        d_rs = framework_for_templates(t_rs)
        check("Rust 归一为模板口径 rust",
              d_rs["framework"] == "rust" and d_rs["has_template"] is True, str(d_rs))
        # 注释线索不得驱动模板选择
        t_cm = base / "t_comment"
        _mk(t_cm, "requirements.txt", "gunicorn==21.2.0\n# 也许以后换成 django\n")
        _mk(t_cm, "pyproject.toml", "[project]\nname = \"demo\"\n")
        d_cm = framework_for_templates(t_cm)
        check("注释线索不选中模板（python-stdlib / has_template=False）",
              d_cm["framework"] == "python-stdlib" and d_cm["has_template"] is False
              and d_cm["needs_confirmation"] is True, str(d_cm))
        # 真依赖 flask 时可选模板，且标记需确认（因存在 low 线索）
        t_fl = base / "t_flask"
        _mk(t_fl, "requirements.txt", "flask==3.0.0\n# TODO: maybe fastapi later\n")
        _mk(t_fl, "pyproject.toml", "[project]\nname = \"demo\"\n")
        d_fl = framework_for_templates(t_fl)
        check("flask 选中模板且标记需确认",
              d_fl["framework"] == "flask" and d_fl["has_template"] is True
              and d_fl["needs_confirmation"] is True, str(d_fl))
        # Django：无模板可复制
        t_dj = base / "t_django"
        _mk(t_dj, "requirements.txt", "django==5.0\n")
        _mk(t_dj, "pyproject.toml", "[project]\nname = \"demo\"\n")
        d_dj = framework_for_templates(t_dj)
        check("Django 识别到但 has_template=False（不得套用 flask 模板）",
              d_dj["framework"] == "django" and d_dj["has_template"] is False, str(d_dj))

        # --- 用例 11：recommendations 必须衔接下一脚本 apply_templates.py
        def _recs(p):
            return "\n".join(analyze(p)["recommendations"])

        # 有模板时：提示跑 apply
        check("flask 项目的 recommendations 提示跑 apply_templates",
              "apply_templates.py" in _recs(t_fl), _recs(t_fl))
        check("go 项目的 recommendations 提示跑 apply_templates",
              "apply_templates.py" in _recs(t_go), _recs(t_go))
        # 降级场景（t_dj Django）：绝不能提示跑 apply（无模板，跑了必然降级 = 空跑）
        check("Django 项目不提示跑 apply（无 Django 模板）",
              "apply_templates.py" not in _recs(t_dj), _recs(t_dj))
        # 歧义场景（t_cm）：允许提到 apply（要告诉买家先确认再显式指定），
        # 但绝不能出现「把 X 工程化模板复制进项目」这种把候选当定论的断言式文案。
        _cm_recs = _recs(t_cm)
        check("歧义场景不把某个候选框架当定论（无「把X 模板复制进项目」）",
              "工程化模板复制进项目" not in _cm_recs, _cm_recs)
        check("歧义场景提示先确认框架并显式指定 --framework",
              "歧义" in _cm_recs and "--framework" in _cm_recs, _cm_recs)
        # 提示语不得反向 import apply_templates（避免循环依赖）
        src = Path(__file__).read_text(encoding="utf-8")
        rec_fn = src[src.index("def make_recommendations"):src.index("def analyze")]
        check("recommendations 生成处未 import apply_templates（无循环依赖）",
              "import apply_templates" not in rec_fn,
              [l for l in rec_fn.splitlines() if "import" in l])
        gitp = base / "git_proj"
        _mk(gitp, "requirements.txt", "flask==3.0.0\n")
        _mk(gitp, ".git/config",
            "[core]\n\trepositoryformatversion = 0\n[commit]\n\ttemplate = .gitmessage\n")
        ec9 = analyze(gitp)["existing_config"]
        check("git [commit] template 段被识别",
              ec9["has_commit_template"] is True, str(ec9["lint_evidence"]))
        gitp2 = base / "git_proj2"
        _mk(gitp2, "requirements.txt", "flask==3.0.0\n")
        _mk(gitp2, ".git/config", "[core]\n\tbare = false\n")
        check("未配置模板时 has_commit_template=false",
              analyze(gitp2)["existing_config"]["has_commit_template"] is False)

    # --- 汇总
    failed = [c for c in cases if not c[1]]
    for name, ok, detail in cases:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    print(f"\n自测用例 {len(cases)} 个，通过 {len(cases) - len(failed)} 个，失败 {len(failed)} 个")
    if failed:
        print("失败用例：")
        for name, _ok, detail in failed:
            print(f"  - {name}  {detail}")
        return 1
    print("自测全部通过（Python 3.11+，tomllib 可用）")
    return 0


def _capture_failure(target: Path):
    """在子进程里跑一次检测失败路径，返回 (stdout 解析结果, 退出码)。"""
    import subprocess
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), str(target)],
        capture_output=True, text=True,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {"_unparsable_stdout": proc.stdout, "_stderr": proc.stderr}
    return payload, proc.returncode


if __name__ == "__main__":
    main()