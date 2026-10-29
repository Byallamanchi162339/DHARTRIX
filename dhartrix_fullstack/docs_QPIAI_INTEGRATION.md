# DHARTRIX AI — QpiAI integration notes

## Included in this build

- `GET /api/qpiai/opt/status`: checks whether an Opt token and a docs-verified create payload are configured; never returns secrets.
- `POST /api/qpiai/opt/qubo`: generates a small QUBO formulation for choosing exactly one eligible diagnostic service under budget. It is a local formulation, not a remote solve.
- `POST /api/qpiai/opt/submit`: uses the Opt Bearer-token header and submits the server-configured JSON body to `/problems/create` only after the exact body is provided in `.env`. It deliberately does not guess required schema fields or claim a solver job completed.
- `GET /api/qpiai/cloud/status`: checks optional SDK and key configuration.
- `POST /api/qpiai/cloud/smoke-test?shots=256`: on explicit user request, runs the documented QpiAI Quantum SDK 3-qubit GHZ example. This verifies SDK/cloud access only, not crop diagnosis or quantum advantage.

## Setup

1. Copy `.env.example` to `.env` in the project root.
2. Add `QPIAI_OPT_TOKEN` from your QpiAI Opt account. Never add credentials to JavaScript or commit `.env`.
3. Read the current official Opt API docs and configure `QPIAI_OPT_CREATE_PAYLOAD_JSON` with the exact required create-problem JSON schema for your account/API version. Leave it blank until verified; no request is sent while blank.
4. Install optional QCloud SDK: `pip install -r requirements-qpiai.txt`.
5. Add `QPIAI_QCLOUD_API_KEY` in `.env`.
6. Restart `uvicorn backend.main:app --reload` and use the QpiAI Lab page.

## QUBO formulation

The generated model selects exactly one service from those that are marked available and cost no more than the budget. Its binary variables represent service choices. The objective trades off normalized cost and turnaround time with a one-hot penalty. It is a small demonstration formulation, not a complete multi-test/capacity scheduling model. Validate the coefficient convention against the exact QpiAI Opt input schema before submitting it.

## Official documentation

- Opt API overview and routes: https://opt-api-docs.qpiai.tech/docs/introduction/overview
- Opt authentication: https://opt-api-docs.qpiai.tech/docs/introduction/authentication
- QpiAI Quantum SDK: https://docs.qcloud.qpiai.tech/

## Evidence and claims

Save actual returned job/problem IDs, execution status, timestamps, solver/backend names, output and credit usage. A successful problem-creation response is not proof that a solver job finished. The GHZ smoke test is not a domain-connected quantum optimization algorithm and is not evidence of quantum advantage. Compare a real Opt result against the classical baseline before making any performance claims.
