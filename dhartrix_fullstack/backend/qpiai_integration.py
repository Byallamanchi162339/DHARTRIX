"""Server-side QpiAI integration helpers.

Opt API: authenticates with a Bearer token. The exact problem-creation payload must
be taken from the current official Opt API docs; this module never guesses it.
QCloud: uses the documented qpiai-quantum SDK for an explicitly requested GHZ smoke test.
"""
from __future__ import annotations
import json, os
from typing import Any
from urllib.parse import urljoin
import httpx

OPT_DOCS = "https://opt-api-docs.qpiai.tech/docs/introduction/overview"
QCLOUD_DOCS = "https://docs.qcloud.qpiai.tech/"


def opt_status() -> dict[str, Any]:
    token = os.getenv("QPIAI_OPT_TOKEN", "").strip()
    payload = os.getenv("QPIAI_OPT_CREATE_PAYLOAD_JSON", "").strip()
    return {
        "provider": "QpiAI Opt",
        "configured": bool(token),
        "token_present": bool(token),
        "create_payload_configured": bool(payload),
        "remote_execution_verified": False,
        "message": (
            "Credentials and a verified request payload are configured; submit a real problem to verify execution."
            if token and payload else
            "Opt is not ready for remote submission. Add QPIAI_OPT_TOKEN and confirm the exact create-problem JSON body in the official docs."
        ),
        "docs_url": OPT_DOCS,
    }


def build_service_selection_qubo(services: list[dict[str, Any]], budget_inr: float) -> dict[str, Any]:
    """Build a small QUBO model selecting exactly one eligible diagnostic service.

    Objective trades off normalized cost and turnaround, with a one-hot penalty.
    This is a formulation/export, not a claim that QpiAI Opt solved it.
    """
    eligible = []
    for idx, s in enumerate(services):
        try:
            cost = float(s.get("cost_inr", s.get("cost", 0)))
            hours = float(s.get("turnaround_hours", s.get("hours", 0)))
            available = s.get("available", True)
            if isinstance(available, str): available = available.strip().lower() in {"true", "1", "yes"}
            if available and cost <= float(budget_inr) and cost >= 0 and hours >= 0:
                eligible.append({"id": str(s.get("service_id", s.get("id", f"S{idx+1}"))),
                                 "name": str(s.get("service_name", s.get("name", f"Service {idx+1}"))),
                                 "cost_inr": cost, "turnaround_hours": hours})
        except (TypeError, ValueError):
            continue
    if not eligible:
        return {"ok": False, "message": "No eligible services fit the budget; no QUBO was built.", "variables": [], "qubo": {}}
    max_cost = max(max(x["cost_inr"] for x in eligible), 1.0)
    max_hours = max(max(x["turnaround_hours"] for x in eligible), 1.0)
    # x_i in {0,1}; minimize cost/max_cost + time/max_hours + A(sum(x)-1)^2.
    # Expansion adds A to each diagonal and 2A to each off-diagonal coefficient.
    penalty = 3.0
    q = {}
    for i, s in enumerate(eligible):
        # Expansion of penalty * (sum(x) - 1)^2 contributes -penalty to each diagonal.
        q[f"x{i}"] = {f"x{i}": round(s["cost_inr"] / max_cost + s["turnaround_hours"] / max_hours - penalty, 8)}
        for j in range(i + 1, len(eligible)):
            q[f"x{i}"][f"x{j}"] = round(2 * penalty, 8)
    return {
        "ok": True,
        "formulation": "QUBO",
        "objective": "normalized cost + normalized turnaround + one-hot penalty",
        "constraint": "select exactly one eligible diagnostic service",
        "budget_inr": float(budget_inr),
        "variables": [{"name": f"x{i}", **s} for i, s in enumerate(eligible)],
        "qubo": q,
        "note": "Formulation generated locally. This is not evidence of a QpiAI Opt remote solve.",
        "docs_url": OPT_DOCS,
    }


async def submit_opt_problem(payload: dict[str, Any]) -> dict[str, Any]:
    """Submit only an explicit user-supplied, docs-verified payload to Opt create endpoint."""
    token = os.getenv("QPIAI_OPT_TOKEN", "").strip()
    base = os.getenv("QPIAI_OPT_BASE_URL", "https://opt-server.qpiai.tech/api").strip().rstrip("/")
    path = os.getenv("QPIAI_OPT_CREATE_PATH", "/problems/create").strip()
    configured_payload = os.getenv("QPIAI_OPT_CREATE_PAYLOAD_JSON", "").strip()
    if not token:
        return {"ok": False, "status": "not_configured", "message": "Set QPIAI_OPT_TOKEN in the backend .env file.", "docs_url": OPT_DOCS}
    if not configured_payload:
        return {"ok": False, "status": "payload_not_verified", "message": "Remote submission is disabled until QPIAI_OPT_CREATE_PAYLOAD_JSON matches the current official API schema. No request was sent.", "docs_url": OPT_DOCS}
    try:
        body = json.loads(configured_payload)
    except json.JSONDecodeError:
        return {"ok": False, "status": "invalid_payload_config", "message": "QPIAI_OPT_CREATE_PAYLOAD_JSON is not valid JSON."}
    # Never forward a client-supplied arbitrary body; the body is configured server-side after schema verification.
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                base + path,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=body,
            )
        if response.status_code >= 400:
            return {"ok": False, "status": "provider_error", "http_status": response.status_code,
                    "message": "QpiAI Opt rejected the request. Check the current schema, credentials and provider response in server logs.",
                    "response": response.text[:1000], "docs_url": OPT_DOCS}
        try: data = response.json()
        except ValueError: data = {"text": response.text[:1000]}
        return {"ok": True, "status": "problem_created_response_received", "response": data,
                "message": "QpiAI Opt returned a successful create-problem response. This alone does not prove a solver job completed.", "docs_url": OPT_DOCS}
    except httpx.HTTPError:
        return {"ok": False, "status": "network_error", "message": "Could not reach QpiAI Opt. Check internet access and service status.", "docs_url": OPT_DOCS}


def qcloud_status() -> dict[str, Any]:
    key = os.getenv("QPIAI_QCLOUD_API_KEY", "").strip()
    try:
        import qpiai_quantum  # noqa: F401
        sdk_installed = True
    except Exception:
        sdk_installed = False
    return {
        "provider": "QpiAI Quantum Cloud",
        "api_key_configured": bool(key),
        "sdk_installed": sdk_installed,
        "remote_execution_verified": False,
        "message": "Ready to attempt an explicit SDK smoke test." if key and sdk_installed else "Install requirements-qpiai.txt and configure QPIAI_QCLOUD_API_KEY to enable the cloud test.",
        "docs_url": QCLOUD_DOCS,
    }


def run_qcloud_smoke_test(shots: int = 256) -> dict[str, Any]:
    """Run the documented 3-qubit GHZ SDK example only when the user explicitly requests it.

    This verifies SDK/cloud access, not an agriculture optimization or quantum advantage.
    Check resource costs and available backends in your QpiAI account before running.
    """
    key = os.getenv("QPIAI_QCLOUD_API_KEY", "").strip()
    if not key:
        return {"ok": False, "status": "not_configured", "message": "Set QPIAI_QCLOUD_API_KEY in backend .env first.", "docs_url": QCLOUD_DOCS}
    try:
        from qpiai_quantum import QpiAIQuantumAuth
        from qpiai_quantum.predefined_states import GHZStateGenerator
        QpiAIQuantumAuth.login(key)
        verified = QpiAIQuantumAuth.verify_api_key()
        if verified is False:
            return {"ok": False, "status": "authentication_failed", "message": "QpiAI SDK did not verify the API key.", "docs_url": QCLOUD_DOCS}
        resources = QpiAIQuantumAuth.list_compute_resources(display=False)
        ghz = GHZStateGenerator(num_qubits=3)
        circuit = ghz.build_circuit(measure=True)
        result = ghz.run(shots=max(64, min(int(shots), 2048)))
        counts = result.get_counts()
        return {
            "ok": True,
            "status": "execution_returned_results",
            "experiment": "3-qubit GHZ SDK smoke test",
            "shots": max(64, min(int(shots), 2048)),
            "counts": counts,
            "resources": resources,
            "message": "QCloud SDK returned a result. This is a connectivity/circuit smoke test, not a crop diagnosis or proof of quantum advantage.",
            "docs_url": QCLOUD_DOCS,
        }
    except Exception as exc:
        return {"ok": False, "status": "execution_failed", "message": f"QCloud test failed: {type(exc).__name__}: {exc}", "docs_url": QCLOUD_DOCS}
