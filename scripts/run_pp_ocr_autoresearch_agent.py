#!/usr/bin/env python3
"""
Launch Codex against pp-ocr using autoresearch-mlx as the control surface.

This script turns the current repo into a practical orchestration harness:
1. optionally refreshes the latest benchmark snapshot,
2. builds a prompt from the finance/legal competition program and current gaps,
3. launches Codex with write access to the target pp-ocr repo.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
PROGRAM_PATH = REPO_ROOT / "program_pp_ocr_hf_finance_legal.md"
EVAL_SCRIPT = REPO_ROOT / "scripts" / "pp_ocr_finance_legal_eval.py"
LATEST_SUMMARY = REPO_ROOT / "pp_ocr_finance_legal_latest.json"
REFERENCE_NOTES = REPO_ROOT / "pp_ocr_reference_notes.md"
DEFAULT_PP_OCR_ROOT = Path("/Users/mean/Documents/Github/pp-ocr")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch a Codex agent that improves pp-ocr using autoresearch-mlx orchestration."
    )
    parser.add_argument("--pp-ocr-root", type=Path, default=DEFAULT_PP_OCR_ROOT)
    parser.add_argument("--mode", choices=("interactive", "exec"), default="interactive")
    parser.add_argument("--model", default="")
    parser.add_argument("--max-samples", type=int, default=10)
    parser.add_argument("--sample-start", type=int, default=0)
    parser.add_argument("--run-live-competitors", action="store_true")
    parser.add_argument("--skip-pre-eval", action="store_true")
    parser.add_argument("--note", default="prelaunch")
    parser.add_argument("--print-prompt", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def run_pre_eval(args: argparse.Namespace) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        str(EVAL_SCRIPT),
        "--pp-ocr-root",
        str(args.pp_ocr_root.resolve()),
        "--max-samples",
        str(args.max_samples),
        "--sample-start",
        str(args.sample_start),
        "--note",
        args.note,
    ]
    if args.run_live_competitors:
        cmd.append("--run-live-competitors")

    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "Pre-launch pp-ocr eval failed.\n"
            f"Command: {' '.join(cmd)}\n"
            f"Stdout:\n{proc.stdout}\n"
            f"Stderr:\n{proc.stderr}"
        )
    return json.loads(proc.stdout)


def load_latest_summary() -> Dict[str, Any]:
    if not LATEST_SUMMARY.exists():
        raise FileNotFoundError(f"Latest summary not found: {LATEST_SUMMARY}")
    return json.loads(LATEST_SUMMARY.read_text(encoding="utf-8"))


def metric_line(label: str, payload: Dict[str, Any]) -> str:
    return (
        f"{label}: "
        f"row={payload.get('row_accuracy')} "
        f"col={payload.get('column_accuracy')} "
        f"cell_f1={payload.get('cell_f1')} "
        f"cer={payload.get('mean_cell_cer')} "
        f"teds={payload.get('teds')} "
        f"teds_s={payload.get('teds_struct')} "
        f"composite={payload.get('composite_score')} "
        f"core_ms={payload.get('core_ms')} "
        f"e2e_ms={payload.get('e2e_ms')}"
    )


def build_gap_summary(summary: Dict[str, Any]) -> str:
    parts: List[str] = []
    live = (summary.get("live") or {}).get("proposed") or {}
    parts.append(metric_line("live.proposed", live))
    for method, payload in sorted(((summary.get("targets") or {}).get("competitors") or {}).items()):
        parts.append(metric_line(f"target.{method}", payload))
        head_to_head = ((summary.get("head_to_head") or {}).get(method) or {})
        misses = [
            name
            for name, row in head_to_head.items()
            if not bool(row.get("meets_target"))
        ]
        if misses:
            parts.append(f"target.{method}.unmet={', '.join(misses)}")
    return "\n".join(parts)


def build_prompt(summary: Dict[str, Any]) -> str:
    program = PROGRAM_PATH.read_text(encoding="utf-8").strip()
    reference_notes = REFERENCE_NOTES.read_text(encoding="utf-8").strip()
    gap_summary = build_gap_summary(summary)
    return textwrap.dedent(
        f"""
        You are running in orchestration mode from `/Users/mean/Documents/Github/autoresearch-mlx`.
        Your actual implementation target is `/Users/mean/Documents/Github/pp-ocr`.

        Follow this program exactly:

        {program}

        Also use these reference notes when forming hypotheses:

        {reference_notes}

        Current benchmark snapshot:
        - summary file: `{LATEST_SUMMARY}`
        - pp-ocr commit: `{summary.get("pp_ocr_commit")}`
        - dataset: `{summary.get("dataset_name")}`
        - max_samples: `{summary.get("max_samples")}`
        - sample_start: `{summary.get("sample_start")}`

        Current gap summary:
        {gap_summary}

        Execution instructions:
        1. Work in `/Users/mean/Documents/Github/pp-ocr`.
        2. Make the most promising small, reversible change.
        3. Re-run `python scripts/pp_ocr_finance_legal_eval.py --note "<what changed>"`.
        4. Inspect the latest JSON/TSV.
        5. Keep iterating until you have a verified improvement or a clearly logged dead end.

        Start immediately by identifying the single highest-leverage change for `hf_finance_legal_mrc`,
        and explicitly state which reference family inspired that first hypothesis.
        """
    ).strip()


def build_codex_command(args: argparse.Namespace) -> List[str]:
    cmd = [
        "codex",
        "--dangerously-bypass-approvals-and-sandbox",
        "-C",
        str(REPO_ROOT),
        "--add-dir",
        str(args.pp_ocr_root.resolve()),
    ]
    if args.model:
        cmd.extend(["--model", args.model])
    if args.mode == "exec":
        cmd.append("exec")
        cmd.append("-")
    return cmd


def launch_codex(args: argparse.Namespace, prompt: str) -> int:
    cmd = build_codex_command(args)
    if args.mode == "interactive":
        cmd.append(prompt)
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT))
        return int(proc.returncode)
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), input=prompt, text=True)
    return int(proc.returncode)


def main() -> int:
    args = parse_args()
    summary = load_latest_summary() if args.skip_pre_eval else run_pre_eval(args)
    prompt = build_prompt(summary)

    if args.print_prompt:
        print(prompt)

    if args.dry_run:
        print("\n--- COMMAND ---")
        print(" ".join(build_codex_command(args)))
        return 0

    return launch_codex(args, prompt)


if __name__ == "__main__":
    raise SystemExit(main())
