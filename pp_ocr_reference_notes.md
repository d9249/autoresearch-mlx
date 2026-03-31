# pp-ocr Reference Notes

These notes are for improving `Proposed (E2E Hybrid)` in `/Users/mean/Documents/Github/pp-ocr`
against `hf_finance_legal_mrc`.

Use them as hypothesis generators, not as a reason to copy large architectures wholesale.
Prefer small, local logic changes that adapt the same ideas to the current `pp-ocr` pipeline.

## Reference Repos

- [Marker](https://github.com/datalab-to/marker)
- [OpenDataLoader PDF](https://github.com/opendataloader-project/opendataloader-pdf)
- [MinerU](https://github.com/opendatalab/MinerU)
- [Docling](https://github.com/docling-project/docling)
- [table-transformer](https://github.com/Sudhanshu1304/table-transformer)
- [Camelot](https://github.com/camelot-dev/camelot)

## Marker

Observed themes:

- Marker focuses on conversion to markdown, JSON, chunks, and HTML, not just raw OCR.
- It explicitly formats tables/forms and removes page artifacts.
- Its optional LLM / hybrid mode is used to merge tables across pages, format tables better, and extract form values.

Adaptation ideas for `pp-ocr`:

- Add a stricter “high quality table repair” lane only for ambiguous or low-confidence tables.
- Treat table text repair and cross-region table normalization as separate post-structure stages.
- Prefer page artifact filtering and region cleanup before table fusion when text noise is high.

## OpenDataLoader PDF

Observed themes:

- It separates deterministic local parsing from AI hybrid escalation.
- Complex or nested tables, scanned PDFs, formulas, and charts are explicitly routed to hybrid mode.
- It emphasizes JSON with bounding boxes, markdown, HTML, and annotated debug output.
- The README claims strong table accuracy and highlights XY-Cut++ style reading-order handling.

Adaptation ideas for `pp-ocr`:

- Expand the current quality-gating logic so simple pages stay cheap while hard tables trigger stronger repair.
- Route only complex pages or regions into expensive recovery logic instead of globally increasing cost.
- Keep richer debugging metadata per table so failed hypotheses can be analyzed after each run.

## MinerU

Observed themes:

- Converts documents to markdown/JSON and exports tables as HTML.
- Detects scanned PDFs and turns on OCR automatically.
- Exposes visualization outputs for layout/span verification.
- The README openly notes that complex tables can still suffer row/column errors.

Adaptation ideas for `pp-ocr`:

- Keep a visible failure taxonomy: row split, row merge, cell text corruption, header inflation.
- Build hard-case slices and verify visual/layout outputs alongside aggregate metrics.
- Add stronger row/column correction rules before text repair when structure is the dominant failure.

## Docling

Observed themes:

- Strong emphasis on advanced PDF understanding: page layout, reading order, table structure, formulas, code.
- Uses a unified document representation.
- Also exposes an alternate VLM pipeline.

Adaptation ideas for `pp-ocr`:

- Normalize intermediate table candidates into one canonical internal representation before fusion/scoring.
- Keep structure selection separate from rendering/export formatting.
- Consider table-specific quality signals that combine reading order, structure confidence, and text quality.

## table-transformer

Observed themes:

- Combines OCR and table detection / computer vision rather than trusting either alone.
- Exports HTML/CSV/DataFrame style outputs.
- Treats text extraction and table structure detection as complementary modules.

Adaptation ideas for `pp-ocr`:

- Preserve the current structure-first candidate path, then fuse text more aggressively afterward.
- Try stronger separation between “choose grid” and “repair cell text”.
- Prefer experiments that upgrade candidate selection or cell fusion, not whole-model swaps.

## Camelot

Observed themes:

- Explicit PDF-native table extraction.
- Exposes a parsing report with accuracy / whitespace / order.
- Exports multiple structured formats and gives useful diagnostics.

Adaptation ideas for `pp-ocr`:

- Reuse PDF-native confidence/quality diagnostics as scoring features, not just binary fallback switches.
- Prefer Camelot-inspired candidate scoring on vector PDFs where lines/order signals are reliable.
- Use parsing diagnostics to decide whether to keep, fuse, or discard a candidate.

## Additional Libraries Worth Studying

The following are not in the original user list, but are strong references for document/table extraction logic.

### Surya

Repo:

- [Surya](https://github.com/datalab-to/surya)

Observed themes from the official repo:

- OCR toolkit with layout analysis, reading order, and table recognition in one stack.
- Strong emphasis on reading-order and document-structure primitives, not only OCR text.

Adaptation ideas for `pp-ocr`:

- Strengthen reading-order-aware table repair on pages with many similar rows.
- Keep layout, order, and table recognition signals separate so they can be recombined in scoring.

### img2table

Repo:

- [img2table](https://github.com/xavctn/img2table)

Observed themes from the official repo:

- Lightweight CPU-oriented table extraction using OpenCV image processing.
- Explicit options for borderless tables and implicit rows/columns.
- README notes that results depend strongly on OCR quality.

Adaptation ideas for `pp-ocr`:

- Add a borderless-table / implicit-structure rescue path for cases where ruled-line candidates fail.
- Use OCR-quality-aware gating before trying lighter structure heuristics.

### RapidTable

Repo:

- [RapidTable](https://github.com/RapidAI/RapidTable)

Observed themes from the official repo:

- Integrates multiple table-recognition model types, including PP-Structure and SLANet Plus.
- Exposes batch inference, model-type switching, and structured HTML outputs.

Adaptation ideas for `pp-ocr`:

- Keep the current multi-candidate design and make model-family choice more explicit in diagnostics.
- Compare candidate families using unified output normalization before selection.

### Unstructured

Repo:

- [Unstructured](https://github.com/Unstructured-IO/unstructured)

Observed themes from the official repo:

- Focuses on converting documents into clean structured data and downstream-ready representations.
- Emphasizes production ETL and structured outputs over raw OCR alone.

Adaptation ideas for `pp-ocr`:

- Treat table extraction as one stage in a larger structured-data pipeline.
- Prefer stable canonical outputs and metadata consistency so downstream systems can trust them.

### pdfplumber

Repo:

- [pdfplumber](https://github.com/jsvine/pdfplumber)

Observed themes from the official repo:

- Fine-grained access to PDF primitives like chars, lines, rectangles, and crop boxes.
- Strong visual debugging around table finding.
- Higher-level customizable methods for both text and tables.

Adaptation ideas for `pp-ocr`:

- Add more PDF-native debugging and line/rect diagnostics to explain candidate choices.
- Use PDF primitive signals to improve vector-PDF table scoring and fallback selection.

## Try Order

When forming new hypotheses, try in this order:

1. Better hard-table routing / escalation thresholds
2. Stronger cell re-OCR and cell text acceptance rules
3. Row split / merge correction for finance/legal layouts
4. Candidate scoring changes using diagnostics from lattice/Camelot-style signals
5. Canonical structure normalization before final export

## What Not To Do

- Do not import external competitors into `proposed` as hidden fallback if you want a fair benchmark.
- Do not turn every page into a heavy hybrid path.
- Do not add large new dependencies without strong evidence.
