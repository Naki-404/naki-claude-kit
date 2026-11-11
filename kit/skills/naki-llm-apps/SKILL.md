---
name: naki-llm-apps
description: Building product features on LLMs: structured JSON output with schema validation and repair, versioned prompts, eval sets, cost and latency budgets, cascades from rules or cheap models to stronger ones, caching, timeouts and error analysis. Use when adding or changing an LLM call, prompt, model choice or LLM evaluation.
---

# LLM Application Engineering

Treat an LLM call as an unreliable, slow, paid external service that returns text. Everything around it (schemas, validation, fallbacks, evals, budgets) is ordinary engineering.

## When to use

- Adding an LLM call to a product or pipeline.
- Changing a prompt, model or provider.
- Output parsing fails, costs rise, or latency is too high.
- Deciding between rules, a small model and a large model.

For security of LLM features (prompt injection, data leakage, tool misuse), use `naki-sec-llm-security` as well. Follow the project rules skill if the project has one (for example `naki-myapp`), which may require approval before spending API money.

## Core rules

1. Define the output schema first, then the prompt.
2. Validate every response. Never pass unvalidated model output into code paths that act on it.
3. Prompts are code: versioned, reviewed, tested against an eval set.
4. Every call has a timeout, a retry policy and a fallback.
5. Set a cost and latency budget per request and measure against it.
6. Use the cheapest path that meets quality: rules, then a small model, then a large one.
7. Before reading a metric like refusal rate or accuracy, break down failures by kind.

## Structured output

Define the schema in code and use it for validation:

```python
from enum import StrEnum
from pydantic import BaseModel, Field

class Severity(StrEnum):
    low = "low"; medium = "medium"; high = "high"; critical = "critical"

class Triage(BaseModel):
    severity: Severity
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(max_length=400)
```

Pipeline:

1. Use the provider's structured output or tool calling mode when available.
2. Parse: extract the JSON object (strip code fences, leading text).
3. Validate with the schema.
4. On failure, one repair attempt: send the validation error and the bad output back, ask for corrected JSON only.
5. Still failing: return a typed failure (`parse_error`), never a guessed default that looks like a real answer.

Keep schemas small and flat. Enums beat free text for anything code branches on.

## Prompt versioning

- Store prompts in files (`prompts/triage_v3.md`), not inline strings scattered in code.
- Give each prompt an id and version; log the version with every call and result.
- A prompt change is a pull request with eval results attached.
- Keep the system prompt stable and put variable data last; this also helps provider-side prompt caching.

## Eval sets

- Start with 50 to 200 labeled cases that reflect real traffic, plus known hard cases.
- Keep a frozen test split that is never used while tuning prompts.
- Score automatically where possible (exact match on enums, schema validity, numeric tolerance).
- For free text, use rubric grading by a model and spot-check it against human labels.
- Run the eval on every prompt or model change and record: quality metric, parse failure rate, cost per item, p50 and p95 latency.

## Cost and latency

| Lever | Effect |
|---|---|
| Shorter prompts and fewer examples | lower cost and latency |
| Smaller model for easy cases | large cost cut |
| Caching identical requests | near zero cost on repeats |
| Provider prompt caching for long stable prefixes | cheaper input tokens |
| Batch APIs for offline jobs | lower price, higher latency |
| Max output tokens cap | bounds cost and runaway output |
| Streaming | better perceived latency in UIs |

Log tokens in, tokens out, model, cost and latency per call. Set an alert or hard stop when a job exceeds its budget.

## Cascades and routing

```python
def triage(alert) -> Result:
    if (r := rules.match(alert)) and r.confident:
        return r                      # free, instant, explainable
    small = call_model(SMALL, alert)
    if small.ok and small.value.confidence >= 0.8:
        return small
    return call_model(LARGE, alert)   # expensive path, only when unsure
```

- Tune the escalation threshold on the dev set; measure the share of traffic at each tier.
- Model self-reported confidence is often poorly calibrated. Check it against accuracy before relying on it, or use agreement between two cheap signals instead.
- Rules handle known, high-volume patterns. The model handles the long tail.

## Caching

- Key on: model id, prompt version, normalized input, and generation parameters.
- Cache only validated successes, never errors.
- Set a TTL when inputs depend on changing context.
- Temperature 0 makes caching meaningful; higher temperature means the cache returns one sample.

## Timeouts, retries, failures

- Timeout on every call (for example 20 to 60 seconds depending on output length).
- Retry only transient errors (429, 5xx, network) with exponential backoff and jitter, 2 to 3 attempts. See `naki-error-handling`.
- Do not retry validation failures blindly; use the repair step.
- Fallback: rules result, cached result, or an honest "needs human review" status.

## Error analysis before metrics

A "refusal rate" or "accuracy" number mixes different failures. First classify each failure:

| Kind | Typical cause |
|---|---|
| `timeout` / `api_error` | network, rate limits, provider outage |
| `parse_error` | broken JSON, extra prose, truncated by max tokens |
| `schema_error` | valid JSON, wrong fields or enum values |
| `refusal` | model declined the task |
| `empty` | no content returned |
| `wrong_answer` | valid output, incorrect label |

Only `refusal` is a refusal. A spike in "refusals" is often truncation or rate limiting. Fix infrastructure kinds before tuning prompts.

## Checklist

- [ ] Schema in code; validation and one repair step
- [ ] Typed failure results, no silent defaults
- [ ] Prompt in a versioned file; version logged
- [ ] Eval set with frozen test split; results recorded per change
- [ ] Timeout, transient-only retries, fallback
- [ ] Cost and latency logged and budgeted
- [ ] Cascade thresholds tuned on dev data
- [ ] Failures broken down by kind

## Common mistakes

- Parsing output with a regex and defaulting to "low" severity on failure.
- Tuning a prompt by eye on five examples.
- Changing model and prompt in the same step, then not knowing which helped.
- Caching errors, so one outage poisons later requests.
- Sending secrets or personal data in prompts without need.
