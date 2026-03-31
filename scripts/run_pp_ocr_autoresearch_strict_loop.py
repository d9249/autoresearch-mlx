#!/usr/bin/env python3
"""
Strict autonomous loop for improving pp-ocr from autoresearch-mlx.

Rules enforced:
- keep/revert log is always written
- stop after N consecutive no-improvement iterations
- stop automatically when fixed targets are met
- never declare success without full-dataset revalidation
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
PROGRAM_PATH = REPO_ROOT / "program_pp_ocr_hf_finance_legal.md"
REFERENCE_NOTES = REPO_ROOT / "pp_ocr_reference_notes.md"
EVAL_SCRIPT = REPO_ROOT / "scripts" / "pp_ocr_finance_legal_eval.py"
DEFAULT_PP_OCR_ROOT = Path("/Users/mean/Documents/Github/pp-ocr")
DEFAULT_TARGET_FILE = REPO_ROOT / "pp_ocr_finance_legal_targets.json"
RUNS_DIR = REPO_ROOT / "pp_ocr_loop_runs"
KEEP_REVERT_TSV = REPO_ROOT / "pp_ocr_keep_revert.tsv"
LOOP_JSONL = REPO_ROOT / "pp_ocr_loop_log.jsonl"

PRIMARY_METRIC_ORDER: Tuple[Tuple[str, bool, float], ...] = (
    ("teds", False, 0.0005),
    ("teds_struct", False, 0.0005),
    ("cell_f1", False, 0.0005),
    ("mean_cell_cer", True, 0.0005),
    ("row_accuracy", False, 0.0),
    ("column_accuracy", False, 0.0),
    ("core_ms", True, 5.0),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a strict pp-ocr autoresearch loop.")
    parser.add_argument("--pp-ocr-root", type=Path, default=DEFAULT_PP_OCR_ROOT)
    parser.add_argument("--target-file", type=Path, default=DEFAULT_TARGET_FILE)
    parser.add_argument("--allow-target-fallback", action="store_true")
    parser.add_argument("--quick-samples", type=int, default=10)
    parser.add_argument("--sample-start", type=int, default=0)
    parser.add_argument("--max-iterations", type=int, default=12)
    parser.add_argument("--max-no-improve", type=int, default=3)
    parser.add_argument("--model", default="")
    parser.add_argument("--run-live-competitors", action="store_true")
    parser.add_argument("--note-prefix", default="strict-loop")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def now_kst() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def run(cmd: List[str], *, cwd: Path, input_text: Optional[str] = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        input=input_text,
        text=True if input_text is not None else True,
        capture_output=True,
    )


def git_output(pp_ocr_root: Path, *args: str) -> str:
    proc = run(["git", *args], cwd=pp_ocr_root)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout.strip()


def ensure_clean_worktree(pp_ocr_root: Path) -> None:
    status = git_output(pp_ocr_root, "status", "--porcelain")
    if status:
        raise RuntimeError(
            "pp-ocr worktree must be clean before starting strict loop.\n"
            f"Current status:\n{status}"
        )


def revert_workspace(pp_ocr_root: Path) -> None:
    proc1 = run(["git", "reset", "--hard", "HEAD"], cwd=pp_ocr_root)
    if proc1.returncode != 0:
        raise RuntimeError(f"git reset failed:\n{proc1.stdout}\n{proc1.stderr}")
    proc2 = run(["git", "clean", "-fd"], cwd=pp_ocr_root)
    if proc2.returncode != 0:
        raise RuntimeError(f"git clean failed:\n{proc2.stdout}\n{proc2.stderr}")


def current_head(pp_ocr_root: Path) -> str:
    return git_output(pp_ocr_root, "rev-parse", "--short", "HEAD")


def changed_files(pp_ocr_root: Path) -> List[str]:
    output = git_output(pp_ocr_root, "status", "--porcelain")
    files: List[str] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        files.append(line[3:])
    return files


def ensure_logs_exist() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    if not KEEP_REVERT_TSV.exists():
        KEEP_REVERT_TSV.write_text(
            "timestamp\titeration\tstatus\tpp_ocr_commit\tquick_teds\tfull_teds\tquick_cer\tfull_cer\tno_improve_count\tnote\tchanged_files\n",
            encoding="utf-8",
        )
    if not LOOP_JSONL.exists():
        LOOP_JSONL.write_text("", encoding="utf-8")


def append_keep_revert_row(
    *,
    iteration: int,
    status: str,
    commit: str,
    quick_summary: Optional[Dict[str, Any]],
    full_summary: Optional[Dict[str, Any]],
    no_improve_count: int,
    note: str,
    files: Iterable[str],
) -> None:
    quick_live = ((quick_summary or {}).get("live") or {}).get("proposed") or {}
    full_live = ((full_summary or {}).get("live") or {}).get("proposed") or {}
    row = [
        now_kst(),
        str(iteration),
        status,
        commit,
        str(quick_live.get("teds", "")),
        str(full_live.get("teds", "")),
        str(quick_live.get("mean_cell_cer", "")),
        str(full_live.get("mean_cell_cer", "")),
        str(no_improve_count),
        note,
        ",".join(files),
    ]
    with KEEP_REVERT_TSV.open("a", encoding="utf-8") as handle:
        handle.write("\t".join(row) + "\n")


def append_loop_jsonl(payload: Dict[str, Any]) -> None:
    with LOOP_JSONL.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def eval_summary(
    *,
    pp_ocr_root: Path,
    target_file: Path,
    max_samples: int,
    sample_start: int,
    note: str,
    run_live_competitors: bool,
    output_path: Path,
    allow_target_fallback: bool,
) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        str(EVAL_SCRIPT),
        "--pp-ocr-root",
        str(pp_ocr_root),
        "--target-file",
        str(target_file),
        "--max-samples",
        str(max_samples),
        "--sample-start",
        str(sample_start),
        "--note",
        note,
        "--output",
        str(output_path),
    ]
    if run_live_competitors:
        cmd.append("--run-live-competitors")

    proc = run(cmd, cwd=REPO_ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"eval failed:\n{proc.stdout}\n{proc.stderr}")
    return json.loads(proc.stdout)


def metric_value(summary: Dict[str, Any], name: str) -> Optional[float]:
    live = (summary.get("live") or {}).get("proposed") or {}
    value = live.get(name)
    if value is None:
        return None
    return float(value)


def is_meaningfully_better(candidate: Dict[str, Any], reference: Dict[str, Any]) -> bool:
    for metric_name, lower_is_better, tolerance in PRIMARY_METRIC_ORDER:
        cand = metric_value(candidate, metric_name)
        ref = metric_value(reference, metric_name)
        if cand is None or ref is None:
            continue
        if lower_is_better:
            delta = ref - cand
        else:
            delta = cand - ref
        if delta > tolerance:
            return True
        if delta < -tolerance:
            return False
    return False


def targets_met(summary: Dict[str, Any]) -> bool:
    head_to_head = summary.get("head_to_head") or {}
    if not head_to_head:
        return False
    for competitor in head_to_head.values():
        if not isinstance(competitor, dict):
            return False
        for row in competitor.values():
            if not isinstance(row, dict) or not bool(row.get("meets_target")):
                return False
    return True


def build_iteration_prompt(summary: Dict[str, Any], *, iteration: int, no_improve_count: int) -> str:
    program = PROGRAM_PATH.read_text(encoding="utf-8").strip()
    reference_notes = REFERENCE_NOTES.read_text(encoding="utf-8").strip()
    return textwrap.dedent(
        f"""
        You are running iteration {iteration} of a strict autoresearch loop.

        Follow this program:

        {program}

        Reference notes:

        {reference_notes}

        Strict loop rules:
        - You may make only one primary hypothesis this iteration.
        - Explicitly state which reference family inspired it.
        - Do not commit, stage, or create branches. Leave changes only in the working tree.
        - If you cannot find a promising change, leave the worktree unchanged and say so.
        - Prefer small, reversible edits.
        - The loop currently has {no_improve_count} consecutive non-improving iterations.

        Current benchmark snapshot:
        {json.dumps(summary, ensure_ascii=False, indent=2)}

        Work only in `/Users/mean/Documents/Github/pp-ocr`.
        """
    ).strip()


def run_codex_iteration(
    *,
    pp_ocr_root: Path,
    prompt: str,
    artifact_dir: Path,
    model: str,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        "codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "-C",
        str(REPO_ROOT),
        "--add-dir",
        str(pp_ocr_root),
        "--output-last-message",
        str(artifact_dir / "last_message.txt"),
        "-",
    ]
    if model:
        cmd[2:2] = ["--model", model]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), input=prompt, text=True, capture_output=True)
    (artifact_dir / "codex_stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
    (artifact_dir / "codex_stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
    return proc


def keep_commit(pp_ocr_root: Path, *, iteration: int, note: str, full_summary: Dict[str, Any]) -> str:
    live = ((full_summary.get("live") or {}).get("proposed") or {})
    teds = live.get("teds")
    cer = live.get("mean_cell_cer")
    message = textwrap.dedent(
        f"""
        Improve finance/legal proposed benchmark in strict loop iteration {iteration}

        Keep from autoresearch strict loop.
        Note: {note}
        TEDS: {teds}
        CER: {cer}
        """
    ).strip()
    proc_add = run(["git", "add", "-A"], cwd=pp_ocr_root)
    if proc_add.returncode != 0:
        raise RuntimeError(f"git add failed:\n{proc_add.stdout}\n{proc_add.stderr}")
    proc_commit = run(["git", "commit", "-m", message], cwd=pp_ocr_root)
    if proc_commit.returncode != 0:
        raise RuntimeError(f"git commit failed:\n{proc_commit.stdout}\n{proc_commit.stderr}")
    return current_head(pp_ocr_root)


def main() -> int:
    args = parse_args()
    pp_ocr_root = args.pp_ocr_root.resolve()
    target_file = args.target_file.resolve()
    if not target_file.exists() and not args.allow_target_fallback:
        raise SystemExit(
            f"target file required for strict loop: {target_file}\n"
            "Capture your full-dataset baselines first or rerun with --allow-target-fallback."
        )
    ensure_clean_worktree(pp_ocr_root)
    ensure_logs_exist()

    baseline_dir = RUNS_DIR / f"baseline-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    best_quick = eval_summary(
        pp_ocr_root=pp_ocr_root,
        target_file=target_file,
        max_samples=args.quick_samples,
        sample_start=args.sample_start,
        note=f"{args.note_prefix}-baseline-quick",
        run_live_competitors=args.run_live_competitors,
        output_path=baseline_dir / "quick.json",
        allow_target_fallback=args.allow_target_fallback,
    )
    best_full = eval_summary(
        pp_ocr_root=pp_ocr_root,
        target_file=target_file,
        max_samples=0,
        sample_start=args.sample_start,
        note=f"{args.note_prefix}-baseline-full",
        run_live_competitors=args.run_live_competitors,
        output_path=baseline_dir / "full.json",
        allow_target_fallback=args.allow_target_fallback,
    )

    if targets_met(best_full):
        append_keep_revert_row(
            iteration=0,
            status="success-already-met",
            commit=current_head(pp_ocr_root),
            quick_summary=best_quick,
            full_summary=best_full,
            no_improve_count=0,
            note="targets already met on baseline",
            files=[],
        )
        return 0

    no_improve_count = 0
    if args.dry_run:
        print("strict loop dry-run ready")
        return 0

    for iteration in range(1, args.max_iterations + 1):
        artifact_dir = RUNS_DIR / f"iter-{iteration:03d}"
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        prompt = build_iteration_prompt(best_full, iteration=iteration, no_improve_count=no_improve_count)
        (artifact_dir / "prompt.md").write_text(prompt, encoding="utf-8")

        pre_commit = current_head(pp_ocr_root)
        proc = run_codex_iteration(
            pp_ocr_root=pp_ocr_root,
            prompt=prompt,
            artifact_dir=artifact_dir,
            model=args.model,
        )

        files = changed_files(pp_ocr_root)
        if proc.returncode != 0:
            revert_workspace(pp_ocr_root)
            no_improve_count += 1
            append_keep_revert_row(
                iteration=iteration,
                status="agent-error-revert",
                commit=pre_commit,
                quick_summary=None,
                full_summary=None,
                no_improve_count=no_improve_count,
                note="codex exec failed",
                files=files,
            )
            append_loop_jsonl({
                "timestamp": now_kst(),
                "iteration": iteration,
                "status": "agent-error-revert",
                "stderr": proc.stderr,
                "stdout": proc.stdout,
            })
            if no_improve_count >= args.max_no_improve:
                return 0
            continue

        if not files:
            no_improve_count += 1
            append_keep_revert_row(
                iteration=iteration,
                status="no-change",
                commit=pre_commit,
                quick_summary=None,
                full_summary=None,
                no_improve_count=no_improve_count,
                note="agent left worktree unchanged",
                files=[],
            )
            append_loop_jsonl({
                "timestamp": now_kst(),
                "iteration": iteration,
                "status": "no-change",
            })
            if no_improve_count >= args.max_no_improve:
                return 0
            continue

        quick_summary = eval_summary(
            pp_ocr_root=pp_ocr_root,
            target_file=target_file,
            max_samples=args.quick_samples,
            sample_start=args.sample_start,
            note=f"{args.note_prefix}-iter-{iteration}-quick",
            run_live_competitors=args.run_live_competitors,
            output_path=artifact_dir / "quick.json",
            allow_target_fallback=args.allow_target_fallback,
        )
        if not is_meaningfully_better(quick_summary, best_quick):
            revert_workspace(pp_ocr_root)
            no_improve_count += 1
            append_keep_revert_row(
                iteration=iteration,
                status="quick-revert",
                commit=pre_commit,
                quick_summary=quick_summary,
                full_summary=None,
                no_improve_count=no_improve_count,
                note="quick eval not better than current best quick baseline",
                files=files,
            )
            append_loop_jsonl({
                "timestamp": now_kst(),
                "iteration": iteration,
                "status": "quick-revert",
                "quick_summary": quick_summary,
                "files": files,
            })
            if no_improve_count >= args.max_no_improve:
                return 0
            continue

        full_summary = eval_summary(
            pp_ocr_root=pp_ocr_root,
            target_file=target_file,
            max_samples=0,
            sample_start=args.sample_start,
            note=f"{args.note_prefix}-iter-{iteration}-full",
            run_live_competitors=args.run_live_competitors,
            output_path=artifact_dir / "full.json",
            allow_target_fallback=args.allow_target_fallback,
        )
        if not is_meaningfully_better(full_summary, best_full):
            revert_workspace(pp_ocr_root)
            no_improve_count += 1
            append_keep_revert_row(
                iteration=iteration,
                status="full-revert",
                commit=pre_commit,
                quick_summary=quick_summary,
                full_summary=full_summary,
                no_improve_count=no_improve_count,
                note="full eval failed improvement gate",
                files=files,
            )
            append_loop_jsonl({
                "timestamp": now_kst(),
                "iteration": iteration,
                "status": "full-revert",
                "quick_summary": quick_summary,
                "full_summary": full_summary,
                "files": files,
            })
            if no_improve_count >= args.max_no_improve:
                return 0
            continue

        keep_note = f"iteration {iteration} keep"
        keep_head = keep_commit(
            pp_ocr_root,
            iteration=iteration,
            note=keep_note,
            full_summary=full_summary,
        )
        best_quick = quick_summary
        best_full = full_summary
        no_improve_count = 0
        status = "keep-success" if targets_met(full_summary) else "keep"
        append_keep_revert_row(
            iteration=iteration,
            status=status,
            commit=keep_head,
            quick_summary=quick_summary,
            full_summary=full_summary,
            no_improve_count=no_improve_count,
            note=keep_note,
            files=files,
        )
        append_loop_jsonl({
            "timestamp": now_kst(),
            "iteration": iteration,
            "status": status,
            "quick_summary": quick_summary,
            "full_summary": full_summary,
            "files": files,
            "commit": keep_head,
        })
        if status == "keep-success":
            return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
