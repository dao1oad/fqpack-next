"""深析 agent 执行适配器（仓库内可版本控制，只读引用技能说明）。

默认生产协议：读取 a-share-fundamental-analysis 技能说明与单股深析规格，
通过 codex CLI 启动一次隔离 agent 会话，由 agent 把标准单股深析结果写入
`--output` 指定的 JSON 文件。本适配器不做分析、不生成任何伪造内容；输出
是否合格由 `deep_executor` 做 schema 校验。

技能目录可通过 `--skill-root` 或环境变量 `FQ_FUNDAMENTAL_SKILL_ROOT` 覆盖；
codex 可执行文件可通过 `--codex-bin` 或环境变量 `FQ_FUNDAMENTAL_CODEX_BIN`
覆盖。适配器只读取技能文件，不修改全局技能目录。
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

DEFAULT_SKILL_ROOT = pathlib.Path(
    r"C:/Users/Administrator/.codex/skills/a-share-fundamental-analysis"
)
TEMPLATE_DIR = pathlib.Path(__file__).parent / "prompt_templates"
DEFAULT_TEMPLATE = TEMPLATE_DIR / "standard_deep_v6.txt"


def build_prompt(
    symbol: str, spec: pathlib.Path, skill_root: pathlib.Path, output: pathlib.Path
) -> str:
    spec_text = spec.read_text(encoding="utf-8") if spec.is_file() else ""
    template = DEFAULT_TEMPLATE
    compact_path = output.parent.parent / "data" / f"compact_{symbol}.json"
    if template.is_file() and compact_path.is_file():
        run_dir = output.parent.parent
        analysis_path = run_dir / "data" / f"analysis_{symbol}.json"
        as_of = ""
        match = re.search(r"as-of[:：]\s*([0-9TZ+:.+-]+)", spec_text)
        if match:
            as_of = match.group(1).strip()
        if not as_of:
            as_of = "2026-08-12T15:00:00+08:00"
        return template.read_text(encoding="utf-8").format(
            symbol=symbol,
            run_dir=run_dir,
            compact_path=compact_path,
            analysis_path=analysis_path,
            output_path=output,
            as_of=as_of,
        )
    return (
        f"你是 A 股标准单股深析执行器（CLX 基本面评价自动主链）。\n"
        f"请先读取技能说明 {skill_root}/SKILL.md 及其 references 子文档，"
        f"对 {symbol} 执行标准单股分析（a-share-fundamental-analysis 默认工作流，不简化）。\n"
        f"as-of 之前可见证据为准；最新报告期不超过规格中的报告期；无未来数据泄漏。\n"
        f"硬性约束：本链路只保留基本面分析引擎，禁止调用/读取 a-share-market-replay "
        f"技能或任何市场复盘、市场主线/主题匹配工具；不得做市场叙事与短线方向判断。\n"
        f"输入规格：\n{spec_text}\n"
        f"输出：按仓库 schema freshquant/clx_daily_selection/fundamental/schemas/"
        f"fundamental-analysis.schema.json 写入 {output}（UTF-8 JSON，字段："
        f"schemaVersion=fundamental-analysis.v1 / symbol / name / tier=deep / asOf / "
        f"quoteDate / financialReportDate / oneLinePositioning / sixDimensionScores"
        f"(六维 grade+rationale) / compositeGrade / keyMetrics / risks / advantages / "
        f"problems / sections(八分节) / evidenceGrade / evidenceIds / generatedBy="
        f"a-share-fundamental-analysis / generatedAt）。\n"
        f"证据不足的维度只能给 evidence_gap，不伪造总分；写文件后输出一行 "
        f"DEEP_ANALYSIS_COMPLETE 作为最终消息。"
    )


def resolve_codex_bin(value: str | None) -> str:
    return value or os.environ.get("FQ_FUNDAMENTAL_CODEX_BIN") or "codex"


def run(args: argparse.Namespace) -> int:
    symbol = args.symbol
    spec = args.spec.resolve()
    output = args.output.resolve()
    skill_root = (
        args.skill_root
        or pathlib.Path(
            os.environ.get("FQ_FUNDAMENTAL_SKILL_ROOT") or DEFAULT_SKILL_ROOT
        )
    ).resolve()
    codex_bin = resolve_codex_bin(args.codex_bin)
    prompt = build_prompt(symbol, spec, skill_root, output)
    if args.dry_run:
        print(
            json_dumps(
                {
                    "dry_run": True,
                    "symbol": symbol,
                    "codex_bin": codex_bin,
                    "skill_root": str(skill_root),
                    "output": str(output),
                    "prompt_chars": len(prompt),
                }
            )
        )
        return 0
    if not skill_root.is_dir():
        print(f"AGENT_RUN_ERROR skill_root missing: {skill_root}", file=sys.stderr)
        return 3
    if not spec.is_file():
        print(f"AGENT_RUN_ERROR spec missing: {spec}", file=sys.stderr)
        return 4
    output.parent.mkdir(parents=True, exist_ok=True)
    run_dir = output.parent.parent
    analysis_path = run_dir / "data" / f"analysis_{args.symbol}.json"
    command = [
        codex_bin,
        "exec",
        "-s",
        "danger-full-access",
        "-c",
        'approval_policy="never"',
        "--skip-git-repo-check",
        "-C",
        str(spec.parent.parent),
        prompt,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=str(spec.parent.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        print(
            f"AGENT_RUN_ERROR timeout after {args.timeout}s: {symbol}", file=sys.stderr
        )
        return 5
    if result.returncode != 0:
        print(
            f"AGENT_RUN_ERROR exit={result.returncode} symbol={symbol}\n"
            f"{result.stdout[-4000:]}\n{result.stderr[-4000:]}",
            file=sys.stderr,
        )
        return result.returncode
    if analysis_path.is_file():
        # v6 组装：模型只写 analysis json，输出由固定脚本确定性生成并校验。
        # 无条件（幂等覆盖）执行：即使上次 attempt 已写出产物，也以本次
        # analysis 为准重建，避免非法/过期产物阻断重试自愈。
        write_cmd = [
            sys.executable,
            str(pathlib.Path(__file__).parent / "write_output.py"),
            "--run-dir", str(run_dir),
            "--symbol", symbol,
            "--analysis", str(analysis_path.relative_to(run_dir)),
            "--out", str(output.relative_to(run_dir)),
        ]
        try:
            wresult = subprocess.run(
                write_cmd, cwd=str(run_dir), capture_output=True, text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            print(f"AGENT_RUN_ERROR write_output timeout: {symbol}", file=sys.stderr)
            return 7
        if wresult.returncode != 0:
            print(
                f"AGENT_RUN_ERROR write_output exit={wresult.returncode} symbol={symbol}\n"
                f"{wresult.stdout[-2000:]}\n{wresult.stderr[-2000:]}",
                file=sys.stderr,
            )
            return wresult.returncode
    if not output.is_file():
        print(f"AGENT_RUN_ERROR output missing after agent: {output}", file=sys.stderr)
        return 6
    print(f"AGENT_RUN_OK symbol={symbol} output={output}")
    return 0


def json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--spec", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--skill-root", type=pathlib.Path, default=None)
    parser.add_argument("--codex-bin", default=None)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
