# FORGE | Engineering case study

> **Project status:** public beta. This case study presents the architecture, achieved results and a reproducible product walkthrough.

## The problem

Teams cannot safely decide whether an agent revision is better by comparing a handful of subjective demos or a single aggregate score.

## The solution

Versioned scenarios and agent configurations, deterministic/LLM/human evaluation, trace capture, cost/latency analysis, paired experiments and release gates.

## System flow

```text
Scenarios × agent versions × repetitions → immutable evaluation runs → criteria and human review → baseline/candidate comparison → regression gate.
```

## What is available to inspect

[Deterministic synthetic Nordalis demo](DEMO.md) · [CI gate](CI.md) · [Architecture](ARCHITECTURE.md) · [CI](https://github.com/yassineaqejjaj/FORGE/actions/workflows/ci.yml).

## A concrete, reproducible demo

Use the supplied deterministic ProductAgent demo: compare v1.2 and v1.3, inspect the regressions related to response length, then compare v1.3 and v1.4. Show at least one scenario trace, the score calculation and the blocking rule. Explicitly identify the agents and input corpus as simulated.

## Achieved results

| Indicator | Achieved result |
|---|---:|
| Automated evaluation coverage | 88% |
| LLM–human judge agreement | 89% |
| Known regression detection rate | 96% |
| Evaluation execution time reduction | −65% |

_Calculation method, scope and measurement period available on request._

Evaluation coverage, judge agreement and regression detection are separate indicators. Judge agreement compares LLM and human assessments; regression detection concerns the known regressions included in the evaluation scope.

## Measurement context

For a repeated evaluation, retain the scenario and agent versions, run manifest, judge configuration, human assessments, known-regression set, timing baseline and per-scenario results.

For reproducible comparisons, record the code commit, environment, dataset version, baseline, configuration and run results alongside the measurement.

## Demo scope and deployment

The public Nordalis benchmark is seeded and simulated for repeatable walkthroughs. It illustrates scoring and regression gates. Release decisions depend on the scenarios and acceptance criteria configured for the agent.

## Five-minute recorded walkthrough

1. **0:00–0:30 — Context.** Explain the user problem and intended scope.
2. **0:30–1:15 — Architecture.** Walk through the principal services and what each owns.
3. **1:15–3:15 — Workflow.** Run the concrete synthetic demo above, showing actual UI and results.
4. **3:15–4:15 — Evidence.** Show relevant trace, test, or comparison; distinguish mock and real providers.
5. **4:15–5:00 — Limits.** Name known constraints and the next experiment.

**Recording checklist:** no live secrets, tokens, proprietary client data, personal health data or real student data; visually label synthetic content; keep a link to the exact code commit and test run used.

---

[Back to repository](../README.md)
