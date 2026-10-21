"""detect_project.py 门控逻辑的离线验证脚本（供 QA 与维护者使用）。

用途：在无法创建临时目录的环境下，验证 make_recommendations() 里
「只在确有模板时提示跑 apply_templates.py」这条门控的真值表。

用法:
    python3 scripts/_verify_gate.py     # 退出码 0 = 门控符合预期

它不 import detect_project（避免触发 tomllib 探测与 tempfile 依赖），
而是用 AST 从源码里抽出 TEMPLATE_* 常量后复刻同一套门控表达式。
若有人改了 TEMPLATE_VOCAB / TEMPLATES_AVAILABLE，本脚本的预期值需要同步更新——
它锁的是「有模板才提示」这条不变量，不是具体框架名单。
"""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parent / "detect_project.py"

# 门控真值表：(detect_project 口径的 framework, 是否应在 recommendations 里提示 apply)
CASES = [
    # 有模板 -> 提示
    ("flask", True), ("fastapi", True), ("express", True),
    ("go-stdlib", True), ("rust-stdlib", True), ("rust-web", True),
    # 无模板 / 不支持 / 识别不出 -> 不提示
    ("django", False), ("koa", False), ("nestjs", False),
    ("next", False), ("fastify", False),
    ("python-stdlib", False), ("node-stdlib", False), ("unknown", False),
]


def main() -> int:
    src = SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)

    vals = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and node.targets):
            continue
        name = getattr(node.targets[0], "id", None)
        if name in ("TEMPLATE_VOCAB", "TEMPLATES_AVAILABLE", "TEMPLATES_UNSUPPORTED"):
            vals[name] = ast.literal_eval(node.value)

    missing = {"TEMPLATE_VOCAB", "TEMPLATES_AVAILABLE"} - set(vals)
    if missing:
        print("FAIL 源码中找不到常量: %s" % ", ".join(sorted(missing)))
        return 1

    vocab = vals["TEMPLATE_VOCAB"]
    avail = vals["TEMPLATES_AVAILABLE"]

    def gate(raw):
        """与 make_recommendations() 中的门控表达式保持一致"""
        return vocab.get(raw, raw) in avail

    print("TEMPLATE_VOCAB      = %s" % (vocab,))
    print("TEMPLATES_AVAILABLE = %s" % (avail,))
    print("")
    print("=== 门控真值表：recommendations 是否提示跑 apply_templates ===")

    allok = True
    for raw, expected in CASES:
        got = gate(raw)
        ok = got == expected
        allok = allok and ok
        print("   %-14s -> %-10s %s" % (
            raw, "提示 apply" if got else "不提 apply", "OK" if ok else "FAIL"))

    print("")
    no_degraded = all(not gate(r) for r, e in CASES if not e)
    all_avail = all(gate(r) for r, e in CASES if e)
    print("不变量 1 降级/无模板场景一律不提 apply: %s" % no_degraded)
    print("不变量 2 有模板场景都提示 apply        : %s" % all_avail)
    print("真值表全部符合预期                    : %s" % allok)

    ok = allok and no_degraded and all_avail
    print("")
    print("结果: %s" % ("通过" if ok else "未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())