"""``forge`` CLI: commands, waiting, French output, exit codes (HTTP mocked with respx)."""

from __future__ import annotations

import io
import json

import httpx
import pytest
import respx

from forge.cli import main as cli
from forge.cli.client import ForgeClient

BASE = "http://forge.test/api/v1"
EXP_ID = "11111111-1111-1111-1111-111111111111"
BASE_V = "22222222-2222-2222-2222-222222222222"
CAND_V = "33333333-3333-3333-3333-333333333333"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "sleep", lambda _s: None)


def run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    client = ForgeClient(base_url="http://forge.test", api_key="fgk_test_key")
    code = cli.main(list(argv), client=client, out=out, err=err)
    client.close()
    return code, out.getvalue(), err.getvalue()


def _experiment(status: str, **extra) -> dict:
    return {
        "id": EXP_ID,
        "name": "v1.2 → v1.3",
        "status": status,
        "total_runs": 8,
        "completed_runs": 8 if status == "completed" else 2,
        "failed_runs": 0,
        "warnings": [],
        **extra,
    }


COMPARISON = {
    "baseline": {"agent_label": "ProductAgent v1.2", "n_scored": 4},
    "candidate": {"agent_label": "ProductAgent v1.3", "n_scored": 4},
    "n_pairs": 4,
    "n_unpaired": 0,
    "composite": {
        "key": "composite",
        "label": "Score composite",
        "baseline_mean": 70.0,
        "candidate_mean": 64.0,
        "delta": -6.0,
        "ci_low": -9.0,
        "ci_high": -3.0,
        "p_value": 0.01,
        "verdict": "worse",
    },
    "dimensions": [
        {
            "key": "quality",
            "label": "Qualité",
            "baseline_mean": 72.0,
            "candidate_mean": 60.0,
            "delta": -12.0,
            "ci_low": -15.0,
            "ci_high": -9.0,
            "p_value": 0.0004,
            "verdict": "worse",
        }
    ],
    "resources": [
        {
            "key": "cost",
            "label": "Coût moyen par run",
            "baseline_mean": 0.02,
            "candidate_mean": 0.03,
            "relative_change": 0.5,
        }
    ],
    "regressions": [
        {
            "name": "Rédiger un PRD",
            "severity": "critical",
            "delta": -18.0,
            "reasons": ["Nouveau garde-fou en échec"],
        }
    ],
    "improvements": [],
    "errors": {"appeared": ["DATA_LEAK"], "disappeared": []},
    "warnings": [],
    "statistics": {"confidence": 0.95},
    "recommendation": {
        "recommendation": "do_not_ship",
        "label": "Ne pas déployer",
        "confidence": "medium",
        "confidence_label": "moyenne",
        "summary": "Déploiement déconseillé : régression critique.",
    },
}
GATE_FAIL = {
    "passed": False,
    "recommendation": "do_not_ship",
    "reasons": ["Garde-fou CI bloquant : recommandation « Ne pas déployer »."],
    "composite_delta": -6.0,
    "regressions": 1,
}
GATE_OK = {
    "passed": True,
    "recommendation": "ship",
    "reasons": ["Garde-fou CI franchi : recommandation « Déployer »."],
    "composite_delta": 5.0,
    "regressions": 0,
}


@respx.mock
def test_whoami_sends_api_key() -> None:
    route = respx.get(f"{BASE}/auth/me").mock(
        return_value=httpx.Response(
            200, json={"kind": "api_key", "label": "Clé « ci »", "role": "editor", "clearance": 1}
        )
    )
    code, out, _ = run("whoami")
    assert code == 0
    assert route.calls[0].request.headers["Authorization"] == "Bearer fgk_test_key"
    assert "Clé « ci »" in out and "Rôle : editor" in out and "Habilitation : C1" in out


@respx.mock
def test_errors_exit_2_with_french_message() -> None:
    respx.get(f"{BASE}/auth/me").mock(
        return_value=httpx.Response(401, json={"detail": "Clé d'API invalide", "code": "unauthorized"})
    )
    code, _, err = run("whoami")
    assert code == 2 and "Authentification refusée : Clé d'API invalide" in err and "FORGE_API_KEY" in err
    respx.get(f"{BASE}/agents").mock(side_effect=httpx.ConnectError("refused"))
    code, _, err = run("agents", "list")
    assert code == 2 and "injoignable" in err


def test_bad_arguments_exit_2() -> None:
    assert run("experiment", "run", "--baseline", BASE_V)[0] == 2
    code, _, err = run("experiment", "run", "--baseline", BASE_V, "--candidate", CAND_V)
    assert code == 2 and "--benchmark" in err


@respx.mock
def test_lists() -> None:
    respx.get(f"{BASE}/agents").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "a1",
                        "slug": "product-agent",
                        "name": "ProductAgent",
                        "latest_version": {"version": "1.3"},
                        "versions_count": 3,
                    }
                ],
                "total": 1,
            },
        )
    )
    respx.get(f"{BASE}/benchmarks").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "slug": "pm-core",
                        "name": "PM",
                        "n_scenarios": 12,
                        "n_agents": 3,
                        "repetitions": 2,
                        "last_execution": {"number": 4, "status": "completed"},
                    }
                ],
                "total": 1,
            },
        )
    )
    code, out, _ = run("agents", "list")
    assert code == 0 and "product-agent" in out and "1.3" in out
    code, out, _ = run("benchmarks", "list")
    assert code == 0 and "pm-core" in out and "n° 4 (terminé)" in out
    code, out, _ = run("benchmarks", "list", "--json")
    assert json.loads(out)[0]["slug"] == "pm-core"


@respx.mock
def test_benchmark_run_wait() -> None:
    respx.post(f"{BASE}/benchmarks/pm-core/run").mock(
        return_value=httpx.Response(202, json={"id": "e1", "number": 5, "total_runs": 4, "status": "running"})
    )
    respx.get(f"{BASE}/benchmark-executions/e1").mock(
        side_effect=[
            httpx.Response(200, json={"id": "e1", "number": 5, "status": "running", "total_runs": 4, "completed_runs": 1, "failed_runs": 0}),
            httpx.Response(200, json={
                "id": "e1", "number": 5, "status": "completed", "total_runs": 4, "completed_runs": 4, "failed_runs": 0,
                "benchmark_name": "PM",
                "summary": {"ranking": [
                    {"rank": 1, "agent_label": "ProductAgent v1.3", "group_composite": 81.2, "composite_mean": 80.0, "ci_low": 77.0, "ci_high": 83.0, "pass_rate": 0.9},
                    {"rank": 2, "agent_label": "ProductAgent v1.2", "group_composite": 75.0, "composite_mean": 74.0, "ci_low": 70.0, "ci_high": 78.0, "pass_rate": 0.7, "delta_to_leader": -6.2},
                ]},
            }),
        ]
    )  # fmt: skip
    code, out, err = run("benchmark", "run", "pm-core", "--wait")
    assert code == 0
    assert "Exécution n° 5 lancée" in err and "1/4 runs terminés" in err
    assert "ProductAgent v1.3" in out and "81,2" in out and "-6,2" in out


@respx.mock
def test_benchmark_run_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = iter([0.0, 10.0, 20.0, 30.0])
    monkeypatch.setattr(cli, "monotonic", lambda: next(clock))
    respx.post(f"{BASE}/benchmarks/b/run").mock(
        return_value=httpx.Response(202, json={"id": "e1", "number": 1, "total_runs": 2})
    )
    respx.get(f"{BASE}/benchmark-executions/e1").mock(
        return_value=httpx.Response(
            200,
            json={"id": "e1", "status": "running", "total_runs": 2, "completed_runs": 0, "failed_runs": 0},
        )
    )
    code, _, err = run("benchmark", "run", "b", "--wait", "--timeout", "15")
    assert code == 2 and "Délai d'attente dépassé" in err


@respx.mock
def test_experiment_run_fail_on_regression() -> None:
    create = respx.post(f"{BASE}/experiments").mock(
        return_value=httpx.Response(201, json=_experiment("running"))
    )
    respx.get(f"{BASE}/experiments/{EXP_ID}").mock(
        side_effect=[
            httpx.Response(200, json=_experiment("running")),
            httpx.Response(200, json=_experiment("completed")),
        ]
    )
    respx.get(f"{BASE}/experiments/{EXP_ID}/comparison").mock(
        return_value=httpx.Response(200, json=COMPARISON)
    )
    gate = respx.get(f"{BASE}/experiments/{EXP_ID}/gate").mock(
        return_value=httpx.Response(200, json=GATE_FAIL)
    )
    code, out, _ = run(
        "experiment", "run", "--baseline", BASE_V, "--candidate", CAND_V, "--benchmark", "pm-core",
        "--repetitions", "3", "--fail-on-regression",
    )  # fmt: skip
    assert code == 1
    body = json.loads(create.calls[0].request.content)
    assert body == {
        "baseline_version_id": BASE_V,
        "candidate_version_id": CAND_V,
        "trigger": "ci",
        "benchmark_id": "pm-core",
        "repetitions": 3,
    }
    assert gate.calls[0].request.url.params["strict"] == "false"
    assert "Score composite" in out and "-6,0" in out and "moins bonne" in out
    assert "[critique] Rédiger un PRD : -18,0 points" in out
    assert "Ne pas déployer" in out and "Garde-fou CI : ÉCHEC" in out
    assert "+50 %" in out and "DATA_LEAK" in out


@respx.mock
def test_experiment_run_json_and_without_flag() -> None:
    respx.post(f"{BASE}/experiments").mock(return_value=httpx.Response(201, json=_experiment("running")))
    respx.get(f"{BASE}/experiments/{EXP_ID}").mock(
        return_value=httpx.Response(200, json=_experiment("completed"))
    )
    respx.get(f"{BASE}/experiments/{EXP_ID}/comparison").mock(
        return_value=httpx.Response(200, json=COMPARISON)
    )
    respx.get(f"{BASE}/experiments/{EXP_ID}/gate").mock(return_value=httpx.Response(200, json=GATE_FAIL))
    code, out, _ = run(
        "experiment",
        "run",
        "--baseline",
        BASE_V,
        "--candidate",
        CAND_V,
        "--scenario",
        "s1",
        "--scenario",
        "s2",
        "--wait",
        "--json",
    )
    assert code == 0  # no --fail-on-regression: report only
    payload = json.loads(out)
    assert payload["gate"]["passed"] is False and payload["comparison"]["n_pairs"] == 4
    code, out, _ = run("experiment", "run", "--baseline", BASE_V, "--candidate", CAND_V, "--scenario", "s1")
    assert code == 0 and out == ""  # launched, not waited


@respx.mock
def test_experiment_failed_is_error() -> None:
    respx.post(f"{BASE}/experiments").mock(return_value=httpx.Response(201, json=_experiment("running")))
    respx.get(f"{BASE}/experiments/{EXP_ID}").mock(
        return_value=httpx.Response(200, json=_experiment("failed", error="Aucun run n'a abouti"))
    )
    respx.get(f"{BASE}/experiments/{EXP_ID}/comparison").mock(
        return_value=httpx.Response(200, json=COMPARISON)
    )
    respx.get(f"{BASE}/experiments/{EXP_ID}/gate").mock(return_value=httpx.Response(200, json=GATE_FAIL))
    code, _, err = run(
        "experiment",
        "run",
        "--baseline",
        BASE_V,
        "--candidate",
        CAND_V,
        "--scenario",
        "s1",
        "--fail-on-regression",
    )
    assert code == 2 and "Aucun run n'a abouti" in err


@respx.mock
def test_experiment_gate() -> None:
    route = respx.get(f"{BASE}/experiments/{EXP_ID}/gate").mock(
        side_effect=[httpx.Response(200, json=GATE_OK), httpx.Response(200, json=GATE_FAIL)]
    )
    code, out, _ = run("experiment", "gate", EXP_ID, "--strict")
    assert code == 0 and "Garde-fou CI : OK" in out and "+5,0" in out
    assert route.calls[0].request.url.params["strict"] == "true"
    code, out, _ = run("experiment", "gate", EXP_ID)
    assert code == 1 and "ÉCHEC" in out


def test_client_uses_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_URL", "http://ci.forge:9000/")
    monkeypatch.setenv("FORGE_API_KEY", "fgk_env")
    client = ForgeClient()
    assert client.base_url == "http://ci.forge:9000"
    assert client._client.headers["Authorization"] == "Bearer fgk_env"
    client.close()
