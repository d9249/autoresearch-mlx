# pp-ocr Finance/Legal Competition Mode

Use this program when `autoresearch-mlx` is acting as an autonomous experiment harness for improving:

- target repo: `/Users/mean/Documents/Github/pp-ocr`
- target dataset: `/Users/mean/Documents/Github/pp-ocr/data/benchmarks/hf_finance_legal_mrc`
- target method: `proposed`
- competitor baselines: `external_paddleocr_vl`, `external_glm_ocr`

## Goal

Improve `pp-ocr` so that `proposed` moves toward or exceeds the competitor baselines on:

- `row_accuracy`
- `column_accuracy`
- `cell_f1`
- `mean_cell_cer` (lower is better)
- `teds`
- `teds_struct`
- `composite_score`
- `core_ms` / `e2e_ms` (lower is better)

Primary priority order:

1. `teds`
2. `teds_struct`
3. `cell_f1`
4. `mean_cell_cer`
5. `row_accuracy` / `column_accuracy`
6. `core_ms` / `e2e_ms`

## Scope

You run from the `autoresearch-mlx` repo, but you edit code in:

- `/Users/mean/Documents/Github/pp-ocr`

Preferred edit areas inside `pp-ocr`:

- `app/invision/table/`
- `app/invision/workflows/`
- `app/invision/layout/`
- `app/invision/parser/`
- `app/invision/workflows/research_table.py`

Do not use `external_paddleocr_vl` or `external_glm_ocr` as fallback inside `proposed` if the purpose is a fair head-to-head comparison.

## Single Source Of Truth

Primary target source:

- If `/Users/mean/Documents/Github/autoresearch-mlx/pp_ocr_finance_legal_targets.json` exists, use it as the fixed benchmark target captured by the user.
- Otherwise, fall back to the latest saved unified result in `pp-ocr`.

After every experiment, run:

```bash
python scripts/pp_ocr_finance_legal_eval.py --note "<short description>"
```

Quick iteration default:

- `--max-samples 10`
- competitor targets loaded from latest saved unified benchmark JSON if live competitors are unavailable

Occasional validation run:

```bash
python scripts/pp_ocr_finance_legal_eval.py --run-live-competitors --max-samples 10 --note "<short description>"
```

Full-dataset check when a change looks promising:

```bash
python scripts/pp_ocr_finance_legal_eval.py --max-samples 0 --note "<short description>"
```

The script writes:

- JSON summary: `pp_ocr_finance_legal_latest.json`
- TSV log: `pp_ocr_results.tsv`

Strict loop artifacts:

- `pp_ocr_keep_revert.tsv`
- `pp_ocr_loop_log.jsonl`
- `pp_ocr_loop_runs/`

## Reference Analysis

Before making non-trivial logic changes, read:

- `/Users/mean/Documents/Github/autoresearch-mlx/pp_ocr_reference_notes.md`

Use the listed repos as design references:

- [Marker](https://github.com/datalab-to/marker)
- [OpenDataLoader PDF](https://github.com/opendataloader-project/opendataloader-pdf)
- [MinerU](https://github.com/opendatalab/MinerU)
- [Docling](https://github.com/docling-project/docling)
- [table-transformer](https://github.com/Sudhanshu1304/table-transformer)
- [Camelot](https://github.com/camelot-dev/camelot)

When you try a new idea, explicitly tag the hypothesis with one reference family, for example:

- `marker-style high quality repair lane`
- `opendataloader-style hard-page routing`
- `mineru-style row/col correction`
- `docling-style canonical structure normalization`
- `table-transformer structure-first text-fusion`
- `camelot-inspired diagnostic scoring`

## Experiment Loop

1. Read the latest JSON summary.
2. Identify the largest gaps versus PaddleOCR-VL and GLM-OCR.
3. Form one concrete hypothesis.
4. Edit only the relevant `pp-ocr` files.
5. Run the evaluation script.
6. Keep the change only if the target metrics improve meaningfully.
7. Revert or revise if the metrics regress.

## Strict Termination

When using the strict loop runner:

- Always leave a keep/revert record.
- Stop after the configured number of consecutive non-improving iterations.
- Stop immediately when the fixed target file is fully satisfied on a full-dataset run.
- Do not declare success from quick-sample results alone.

## Good Hypotheses

Focus on:

- table cell re-OCR policy
- fusion acceptance rules
- row split / merge handling
- finance/legal header and numeric text robustness
- threshold tuning for `det_box_thresh`, `rec_score_thresh`, `layout_score_thresh`
- candidate selection logic
- reference-inspired logic families from `pp_ocr_reference_notes.md`

Avoid spending time on ideas already shown to be neutral on this dataset unless you have new evidence.

## Logging

Use short, specific notes in the TSV log, for example:

- `increase reocr budget for long-form tables`
- `relax fusion acceptance for low-cer replacements`
- `tune finance/legal layout thresholds`

## Safety

- Never use blind `git add -A` in `pp-ocr`.
- Do not revert unrelated user changes.
- Prefer small, reviewable diffs.
