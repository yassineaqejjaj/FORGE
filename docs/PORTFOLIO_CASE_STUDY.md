# FORGE | Engineering case study

> **Project status:** public beta / technical demonstration. This document describes the architecture and a **reproducible evaluation plan**, not externally verified business impact. Metrics below are proposed measurements, **not achieved results**.

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

## Evidence protocol

Report the exact dataset/version and run manifest, per-scenario pass rates, critical regressions, cost, latency, inter-rater agreement where available, repeated-run variance and CI gate decision. Keep synthetic demonstrations separate from real-world performance validation.

To make a claim credible, record the repository commit, environment, dataset version, exact prompts/inputs, configuration, baseline, number of runs, test results, raw observations, and reviewer decision. Store a redacted reproducible report in the repository (for example `docs/evidence/`) and link it here. If the measurements have not been performed, write **Not measured**.

| Measure | Baseline | Candidate | Method | Verified result |
|---|---|---|---|---|
| Quality / task success | To define | To define | Fixed evaluation set and human-reviewed criteria | Not measured |
| Safety / critical failures | To define | To define | Severity-weighted fixed scenarios | Not measured |
| Resource use | To define | To define | Token and runtime logs, same workload | Not measured |
| End-to-end latency | To define | To define | Repeated runs, median and p95 | Not measured |

## Limitations and honest disclosure

The Nordalis agent benchmark is simulated and seeded. A synthetic PASS is not evidence that a real agent is ready for production; real-world criteria need domain experts and independent datasets.

## Five-minute recorded walkthrough

1. **0:00–0:30 — Context.** Explain the user problem and intended scope.
2. **0:30–1:15 — Architecture.** Walk through the principal services and what each owns.
3. **1:15–3:15 — Workflow.** Run the concrete synthetic demo above, showing actual UI and results.
4. **3:15–4:15 — Evidence.** Show relevant trace, test, or comparison; distinguish mock and real providers.
5. **4:15–5:00 — Limits.** Name known constraints and the next experiment.

**Recording checklist:** no live secrets, tokens, proprietary client data, personal health data or real student data; visually label synthetic content; keep a link to the exact code commit and test run used.

---

[Back to repository](../README.md)
