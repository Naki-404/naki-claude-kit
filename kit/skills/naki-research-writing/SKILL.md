---
name: naki-research-writing
description: Literature review and writing papers, theses and reports where every number traces to a script output: pre-registered hypotheses, honest negative results, verified citations, paired statistics (McNemar, bootstrap CIs, Holm) and clear figures. Use when writing or reviewing a paper, report, thesis chapter or results section.
---

# Research Writing

A research text is a set of claims. Each claim needs evidence the reader can check: a script output, a cited source, or an explicit statement that it is an opinion.

## When to use

- Writing a paper, thesis chapter, technical report or results section.
- Reviewing literature for related work.
- Turning experiment outputs into tables and figures.
- Checking a draft before submission.

Follow the project rules skill if the project has one (for example `naki-myapp`), which may fix where results and hypotheses live. If the `naki-kit` MCP server is available, `kit_results` and `kit_status_log` help locate result files.

## Core rules

1. Every number in the text traces to a file produced by a script. No hand-typed numbers.
2. Hypotheses and the primary metric are written down before the experiment runs.
3. Negative and null results are reported, with the same care as positive ones.
4. Every citation is verified: the source exists and actually says what you claim.
5. Uncertainty is shown: confidence intervals, number of seeds, test set size.
6. Multiple comparisons are corrected.
7. Say what you did, not what you wish you did. Limitations are a section, not an afterthought.

## Numbers traced to scripts

- Results come from scripts that write machine-readable outputs (JSON or CSV) into a results folder with the run id.
- Tables are generated from those files by a script, not copied by hand.
- In the draft, keep a source note next to each table or number, for example a comment `<!-- results/2026-05-02_eval/metrics.json: macro_f1 -->`.
- Before submission, re-run the table script and diff against the text.
- Rounding: decide once (for example 3 decimals for metrics, 1 for percentages) and apply it in the script.

## Pre-registration

Before running the main experiment, write a short file with:

```markdown
# Hypotheses (frozen 2026-04-10)
H1: fine-tuned model has higher macro F1 than the base model on the frozen test set.
Primary metric: macro F1. Test: paired bootstrap, alpha 0.05.
H2: cascade reduces cost per alert by at least 50 percent with macro F1 drop under 0.02.
Secondary analyses (exploratory): per-class recall, latency.
Exclusions: none planned. Seeds: 3.
```

Commit it, so the date is in history. Anything added later is labeled exploratory.

## Honest negative results

- Report the hypothesis, the result and the interval: "H2 not supported: cost fell 31 percent (95% CI 27 to 35)".
- Do not switch the primary metric after seeing results.
- Do not drop seeds, classes or test items that look bad, unless the exclusion rule was set beforehand.
- Explain plausible reasons briefly, marked as speculation.

## Literature review

1. Define the question and inclusion criteria (years, venues, task, data type).
2. Search several databases (Google Scholar, Semantic Scholar, arXiv, IEEE Xplore, ACM DL) with recorded queries and dates.
3. Screen titles, then abstracts, then full text; log why items were excluded.
4. Extract per paper: task, data, method, metric, result, limitations.
5. Synthesize by theme or method, not paper by paper.
6. Weigh evidence: peer-reviewed beats preprint, large and public data beats small and private, replicated beats single study.

## Citation verification

- Open every cited source. Confirm title, authors, year, venue and DOI.
- Confirm the specific claim appears in the source (note page or section).
- Never cite a reference produced by a language model without finding it yourself; fabricated citations are common.
- Prefer the published version over the preprint when both exist.
- Use a reference manager and one citation style throughout.

## Statistics

| Situation | Method |
|---|---|
| Two classifiers, same test items, accuracy | McNemar test on the disagreement counts |
| Two classifiers, same items, F1 or other metric | paired bootstrap of the difference |
| Interval for one metric | bootstrap CI, 1000 to 10000 resamples of test items |
| Several comparisons | Holm-Bonferroni correction of p-values |
| Several seeds | report mean and standard deviation, and per-seed values |

```python
import numpy as np

def bootstrap_ci(y_true, y_pred, metric, n=2000, seed=0):
    rng = np.random.default_rng(seed)
    idx = np.arange(len(y_true))
    stats = [metric(y_true[s], y_pred[s])
             for s in (rng.choice(idx, len(idx)) for _ in range(n))]
    return np.percentile(stats, [2.5, 97.5])
```

Holm: sort p-values ascending, compare the i-th (from 0) with alpha / (m - i), stop at the first that fails.

Report effect sizes and intervals, not only p-values. A significant but tiny difference should be described as tiny.

## Figures and tables

- One message per figure; the caption states it.
- Label axes with units; start bar charts at zero.
- Show error bars or intervals and say what they are (95% CI, SD).
- Colorblind-safe palettes; do not rely on color alone.
- Vector formats (PDF, SVG) for print; generated by a script saved with the results.
- Tables: best result marked only if the difference is significant; same decimals per column.

## Writing

- Structure: introduction (problem, gap, contribution), related work, method, experiments, results, discussion, limitations, conclusion.
- Method detailed enough to reproduce: data, splits, model, hyperparameters, hardware, seeds.
- Plain sentences, active voice, defined terms used consistently.
- Claims match evidence strength: "suggests" for one dataset, "shows" for robust results.

## Checklist

- [ ] Every number linked to a result file; tables regenerated
- [ ] Hypotheses committed before the main run; exploratory work labeled
- [ ] Negative results reported
- [ ] All citations opened and checked
- [ ] Paired tests, CIs and Holm correction where needed
- [ ] Figures labeled, with intervals, generated by script
- [ ] Limitations section written

## Common mistakes

- Copying a number from a console log that came from an older run.
- Comparing to a baseline from another paper with a different test split.
- Treating overlapping intervals as proof of no difference, or non-overlap as the only evidence of one.
- Citing a survey for a claim it only repeats from another paper.
- Reporting the best seed as the result.

## Related

- `naki-ml-training` for producing results that are worth reporting.
- `naki-adr` for recording method decisions during the project.
