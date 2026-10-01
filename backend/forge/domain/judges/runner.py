"""Running one judge on one run (docs/ARCHITECTURE.md §7.3), over the :class:`LLMClient` port.

Render → call → parse → (once) corrective retry when the answer is unusable → verdicts. HTTP retries
(429/5xx/timeouts) live in the infrastructure client; rate limiting and caching are applied by the
service around :func:`run_judge`. The heuristic provider needs no client.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from forge.domain.enums import JudgeProvider
from forge.domain.judge_defaults import JUDGE_OUTPUT_SCHEMA
from forge.domain.judges.heuristic import heuristic_response
from forge.domain.judges.parsing import ParsedJudgeOutput, parse_judge_output
from forge.domain.judges.prompting import RenderedPrompt, correction_message, render_prompt
from forge.domain.ports import LLMClient
from forge.domain.types import CriterionSpec, EvaluationContext, EvaluationResult, JudgeSpec

JudgeStatus = Literal["ok", "partial", "failed", "skipped"]
CostFn = Callable[[str, int, int], float | None]


@dataclass(slots=True)
class JudgeRun:
    judge: JudgeSpec
    criteria: list[CriterionSpec]
    prompt: RenderedPrompt
    status: JudgeStatus = "ok"
    parsed: ParsedJudgeOutput = field(default_factory=ParsedJudgeOutput)
    attempts: int = 0
    #: Raw answer text(s) of the judge (the last one first) or the heuristic JSON.
    response: dict[str, Any] | None = None
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost: float | None = None
    cached: bool = False
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def results(self) -> list[EvaluationResult]:
        return self.parsed.results

    def summary(self) -> dict[str, Any]:
        """Audit / API summary (no prompt, no answer content)."""
        return {
            "judge_id": self.judge.judge_id,
            "key": self.judge.key,
            "version": self.judge.version,
            "provider": str(self.judge.provider),
            "model": self.model or self.judge.model,
            "prompt_hash": self.prompt.prompt_hash,
            "status": self.status,
            "cached": self.cached,
            "attempts": self.attempts,
            "criteria": [c.key for c in self.criteria],
            "verdicts": len(self.results),
            "missing": list(self.parsed.missing),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost": self.cost,
            "latency_ms": round(self.latency_ms, 1),
            "error": self.error,
            "warnings": list(self.warnings),
        }


def _merge(first: ParsedJudgeOutput, second: ParsedJudgeOutput) -> ParsedJudgeOutput:
    """Keep verdicts of the first answer and complete them with the corrected answer."""
    have = {r.criterion_key for r in first.results}
    extra = [r for r in second.results if r.criterion_key not in have]
    merged = ParsedJudgeOutput(
        results=[*first.results, *extra],
        problems=[*first.problems, *second.problems],
        summary=second.summary or first.summary,
        data=second.data or first.data,
    )
    accepted = {r.criterion_key for r in merged.results}
    merged.rejected = {k: v for k, v in {**first.rejected, **second.rejected}.items() if k not in accepted}
    order = [*first.missing, *[k for k in second.missing if k not in first.missing]]
    merged.missing = [k for k in order if k not in accepted]
    return merged


def finalize_results(run: JudgeRun) -> None:
    """Copy call metrics onto the verdicts (tokens and cost split evenly, latency of the call)."""
    results = run.results
    if not results:
        return
    n = len(results)
    for index, result in enumerate(results):
        result.model = run.model or run.judge.model
        result.prompt_hash = run.prompt.prompt_hash
        result.latency_ms = round(run.latency_ms, 1)
        result.cached = run.cached
        result.input_tokens = run.input_tokens // n + (run.input_tokens % n if index == 0 else 0)
        result.output_tokens = run.output_tokens // n + (run.output_tokens % n if index == 0 else 0)
        result.cost = None if run.cost is None else round(run.cost / n, 8)
        if isinstance(result.raw_response, dict):
            result.raw_response["call"] = {
                "attempts": run.attempts,
                "cached": run.cached,
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
                "cost": run.cost,
                "split_over": n,
            }


def _status(parsed: ParsedJudgeOutput) -> JudgeStatus:
    if not parsed.results:
        return "failed"
    return "partial" if parsed.missing else "ok"


def parse_stored_response(
    run: JudgeRun,
    response: Mapping[str, Any],
    *,
    ctx: EvaluationContext,
    known_error_types: Sequence[str],
) -> None:
    """Re-parse a cached answer (``{"text": …}`` or ``{"json": …}``) into ``run``."""
    payload: Any = response.get("json") if response.get("json") is not None else response.get("text")
    run.parsed = parse_judge_output(
        payload,
        judge=run.judge,
        criteria=run.criteria,
        events=ctx.events,
        known_error_types=known_error_types,
        prompt_hash=run.prompt.prompt_hash,
        model=str(response.get("model") or run.judge.model),
    )
    run.model = str(response.get("model") or run.judge.model)
    run.response = dict(response)
    run.status = _status(run.parsed)
    run.cached = True
    run.cost = 0.0
    run.input_tokens = 0
    run.output_tokens = 0
    finalize_results(run)


async def run_judge(
    judge: JudgeSpec,
    ctx: EvaluationContext,
    criteria: Sequence[CriterionSpec],
    *,
    error_types: Mapping[str, str],
    client: LLMClient | None = None,
    timeout_seconds: float = 90.0,
    cost_fn: CostFn | None = None,
    before_call: Callable[[], Awaitable[None]] | None = None,
    max_corrections: int = 1,
    prompt: RenderedPrompt | None = None,
) -> JudgeRun:
    """Evaluate ``criteria`` with ``judge``. Never raises for judge failures: ``status="failed"``."""
    ordered = list(criteria)
    rendered = prompt or render_prompt(judge, ctx, ordered, error_types)
    run = JudgeRun(judge=judge, criteria=ordered, prompt=rendered, model=judge.model)
    if not ordered:
        run.status = "skipped"
        return run
    known = list(error_types)
    if JudgeProvider(judge.provider) == JudgeProvider.heuristic:
        started = time.perf_counter()
        heuristic = heuristic_response(ctx, ordered)
        run.attempts = 1
        run.latency_ms = (time.perf_counter() - started) * 1000
        run.response = {"json": heuristic, "model": judge.model}
        run.parsed = parse_judge_output(
            heuristic, judge=judge, criteria=ordered, events=ctx.events, known_error_types=known,
            prompt_hash=rendered.prompt_hash, model=judge.model,
        )  # fmt: skip
        run.cost = 0.0
        run.status = _status(run.parsed)
        finalize_results(run)
        return run
    if client is None:
        run.status = "failed"
        run.error = f"Aucun client LLM disponible pour le fournisseur « {judge.provider} »"
        return run
    messages: list[dict[str, Any]] = [{"role": "user", "content": rendered.user}]
    parsed: ParsedJudgeOutput | None = None
    texts: list[str] = []
    try:
        for attempt in range(1 + max(0, max_corrections)):
            if before_call is not None:
                await before_call()
            response = await client.complete(
                system=rendered.system,
                messages=messages,
                model=judge.model,
                temperature=judge.temperature,
                max_tokens=judge.max_tokens,
                json_schema=JUDGE_OUTPUT_SCHEMA,
                timeout_seconds=timeout_seconds,
            )
            run.attempts = attempt + 1
            run.model = response.model or judge.model
            run.input_tokens += int(response.input_tokens or 0)
            run.output_tokens += int(response.output_tokens or 0)
            run.latency_ms += float(response.latency_ms or 0.0)
            texts.append(response.text)
            current = parse_judge_output(
                response.text, judge=judge, criteria=ordered, events=ctx.events, known_error_types=known,
                prompt_hash=rendered.prompt_hash, model=run.model,
            )  # fmt: skip
            parsed = current if parsed is None else _merge(parsed, current)
            problems = parsed.blocking_problems()
            if not problems:
                break
            if attempt < max_corrections:
                run.warnings.append(
                    f"Réponse du juge {judge.ref} incomplète, nouvel essai : {'; '.join(problems)}"
                )
                messages = [
                    *messages,
                    {"role": "assistant", "content": response.text or "(réponse vide)"},
                    {"role": "user", "content": correction_message(problems, ordered)},
                ]
    except Exception as exc:  # the LLM client raises its own errors; a judge failure never aborts the run
        run.error = f"{type(exc).__name__}: {exc}"[:1000]
    if parsed is not None:
        run.parsed = parsed
    else:
        run.parsed = ParsedJudgeOutput(missing=[c.key for c in ordered])
    run.response = {"text": texts[-1] if texts else None, "model": run.model, "attempts_text": texts[:-1]}
    if cost_fn is not None and (run.input_tokens or run.output_tokens):
        run.cost = cost_fn(run.model, run.input_tokens, run.output_tokens)
    run.status = _status(run.parsed)
    if run.status == "failed" and run.error is None:
        run.error = "Réponse du juge inexploitable : " + "; ".join(run.parsed.blocking_problems())[:900]
    if run.parsed.problems:
        run.warnings.extend(run.parsed.problems[:10])
    finalize_results(run)
    return run


def cache_payload(run: JudgeRun) -> dict[str, Any]:
    """What is stored in ``judge_cache.response``: the accepted items (merged across attempts)."""
    return {
        "json": {
            "criteria": [r.raw_response.get("item") for r in run.results if isinstance(r.raw_response, dict)],
            "summary": run.parsed.summary,
        },
        "model": run.model,
        "prompt_hash": run.prompt.prompt_hash,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "cost": run.cost,
    }
