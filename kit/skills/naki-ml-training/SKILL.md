---
name: naki-ml-training
description: PyTorch training and fine-tuning, including QLoRA on a 12 GB GPU: leakage-free splits, frozen test sets, dev-set checkpoint selection, seeds, logged configs, early stopping, and evaluation with per-class metrics and confidence intervals. Use when writing or reviewing training, fine-tuning or evaluation code, or planning a training run.
---

# ML Training and Fine-Tuning

A model result is only worth something if the test data was never seen during training or selection, and the run can be reproduced from its logged config.

## When to use

- Building a dataset split for training and evaluation.
- Writing or changing a training loop, fine-tuning script or eval script.
- Planning a LoRA or QLoRA run on limited GPU memory.
- Comparing models or checkpoints and deciding which one to keep.

Follow the project rules skill if the project has one (for example `naki-myapp`): it may define frozen files, GPU booking and where results go. If the `naki-kit` MCP server is available, `kit_verify_frozen`, `kit_dataset_summary`, `kit_gpu_status` and `kit_results` help with the checks below.

## Core rules

1. Split by group, not by row. Samples from the same scenario, family, template, source document, user or time window go to the same split.
2. The test set is frozen. It is never used to choose hyperparameters, prompts, thresholds, epochs or checkpoints. Verify its hash before every evaluation.
3. Select on a dev set. Keep a hard dev set (unseen groups, difficult cases) for checkpoint selection and early stopping.
4. Every run is reproducible: seed, code commit, data hashes, full config and environment logged next to the outputs.
5. Report per-class metrics and confidence intervals, not only overall accuracy.
6. Compare against a simple baseline (majority class, rules, logistic regression, the base model without tuning).
7. Change one thing at a time between runs you intend to compare.

## Data splits and leakage

```python
from sklearn.model_selection import GroupShuffleSplit

gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=13)
train_idx, holdout_idx = next(gss.split(X, y, groups=df["scenario_id"]))
```

Leakage sources to check:

| Source | Example | Fix |
|---|---|---|
| Near duplicates | same alert with a new timestamp | dedupe by normalized hash before splitting |
| Shared groups | two variants of one scenario in train and test | group split by scenario or family |
| Time | future events in train for a past test | split by time for forecasting-like tasks |
| Preprocessing | scaler or vocabulary fit on all data | fit on train only |
| Labels in features | a field set by the analyst after triage | drop post-outcome fields |
| Synthetic data | generator templates shared across splits | split by template |

Write a test that asserts no group id appears in two splits, and run it in CI.

## Reproducibility

```python
import random, numpy as np, torch

def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
```

Log at run start, into the run folder:

- resolved config (YAML or JSON), not just CLI args
- git commit and dirty flag
- SHA-256 of every data file used
- library versions (`torch`, `transformers`, `peft`, `bitsandbytes`), CUDA, GPU name
- seed

Name runs with a date and short description, and never overwrite a previous run folder. Run at least 3 seeds before claiming one setup beats another.

## Training loop essentials

- Evaluate on dev every N steps or each epoch; save the checkpoint only when the dev metric improves.
- Early stopping with patience (for example 3 evals without improvement) on the dev metric you actually care about, such as macro F1, not loss alone.
- Gradient clipping (`max_norm=1.0`) and a learning rate warmup for transformers.
- Class imbalance: weighted loss or sampling, and judge by macro metrics.
- Log loss, learning rate, dev metrics and GPU memory to a file, not only to the console.
- Handle interruption: save optimizer and scheduler state so a run can resume.

## QLoRA on a 12 GB GPU

Practical settings for 7B to 8B models:

| Setting | Typical value |
|---|---|
| Quantization | 4-bit NF4, double quantization, compute dtype bf16 (fp16 if bf16 unsupported) |
| LoRA rank / alpha | r 8 to 16, alpha 16 to 32, dropout 0.05 |
| Target modules | attention projections first; add MLP projections if quality is short |
| Batch | micro batch 1 to 4, gradient accumulation to reach effective 16 to 32 |
| Sequence length | as short as the data allows; memory grows with it |
| Memory savers | gradient checkpointing, paged 8-bit optimizer |
| Learning rate | about 1e-4 to 2e-4 for adapters |

Practicalities:

- Check free memory before starting; other processes (a browser, another notebook) hold VRAM.
- On Windows, `bitsandbytes` support depends on the version; test a 10-step dry run first.
- Out of memory: lower sequence length, then micro batch, then rank, in that order.
- Save adapters, not full weights, during training. They are small and fast to write.

## Merging adapters

- Merge into the base model loaded in full precision (fp16/bf16), not into the 4-bit quantized model. Merging into quantized weights loses quality.
- Evaluate the merged model on the dev set and confirm it matches the adapter model within noise before replacing anything.
- Keep the unmerged adapter and the exact base model revision. Record both in the run log.
- Do not stack adapters trained on different base revisions.

## Evaluation

- Run the frozen test set once per final candidate, after selection is finished.
- Report a confusion matrix, per-class precision, recall and F1, and macro F1.
- Add 95 percent bootstrap confidence intervals (resample test items, 1000 or more times).
- For two models on the same test items, use a paired test (McNemar for accuracy, paired bootstrap for F1).
- Check error kinds, not only counts: parse failures, empty outputs and refusals are different problems.
- Save raw predictions per item so any metric can be recomputed later.

## Checklist

- [ ] Group-based split; overlap test passes
- [ ] Test set hash verified, untouched during selection
- [ ] Hard dev set used for early stopping and checkpoint choice
- [ ] Seed, commit, data hashes, config, versions logged
- [ ] Baseline included
- [ ] Per-class metrics with confidence intervals
- [ ] Multiple seeds before claiming improvement
- [ ] Adapters merged into full-precision base and re-checked

## Common mistakes

- Random row split on data with many variants of the same scenario, giving inflated scores.
- Peeking at test results, adjusting, and re-running ("just once more").
- Choosing the best of 10 seeds and reporting it as the result.
- Reporting accuracy on imbalanced data.
- Tokenizer or chat template mismatch between training and inference.
- Losing the config of the run that produced the best model.

## Related

- `naki-research-writing` for reporting results with statistics.
- `naki-llm-apps` for using the trained model inside a product.
