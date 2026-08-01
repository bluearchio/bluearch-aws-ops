# Contributing

Thanks for helping improve `bluearch-aws-ops`.

## Local Setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e . pytest pytest-mock httpx2

cd frontend
npm ci
```

## Run Locally

Start core first:

```bash
bluearch-aws-core start --daemon
```

Run the backend:

```bash
PYTHONPATH=src/api python -m uvicorn web.app:create_app --factory --host 127.0.0.1 --port 8095
```

Run the frontend:

```bash
cd frontend
npm run dev
```

## Test

```bash
PYTHONPATH=src/api python -m pytest src/api/tests
PYTHONPATH=src/api python -m compileall src/api
cd frontend && npm run build
```

Or use:

```bash
make setup
make test
```

## Pull Requests

- Keep changes small and focused.
- Include tests or explain why a test is not practical.
- Update the README when commands, configuration, APIs, frontend behavior, or AWS permissions change.
- Do not commit secrets, AWS account IDs, local databases, generated reports, screenshots with account data, or local `.env` files.
- Do not add hosted telemetry, hosted sign-in, private release URLs, license gates, internal AWS account IDs, Slack ops hooks, or private deployment automation.

## Security-Sensitive Changes

Changes to AWS credential handling, remediation logic, service-token handling, local persistence, or generated reports need extra review. Describe the security impact in the PR.
