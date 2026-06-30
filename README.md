# bluearch-aws-ops

`bluearch-aws-ops` is the AWS operations CLI and local dashboard. It scans AWS accounts, generates recommendations, supports alerting/remediation workflows, analyzes logs, and exposes a FastAPI/Vue dashboard.

## What This Repo Is Not

This repo is not the shared runtime. It does not own account context, shared persistence, hosted sign-in, hosted analytics, commercial licensing, or private release infrastructure. Those private systems have been removed for the public build.

## How It Works With The Other Repos

- Requires `bluearch-aws-core` running locally first.
- Reads and writes shared state through core APIs.
- Complements `bluearch-aws-tags` for tagging/FinOps workflows.
- Complements `bluearch-aws-governance` for misconfiguration catalog and governance scans.

## Install

```bash
brew tap bluearchio/tap
brew install bluearchio/tap/bluearch-aws-core
brew install bluearchio/tap/bluearch-aws-ops
bluearch-core start --daemon
bluearch scan
bluearch recommendations
```

From source:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
bluearch-core start --daemon
bluearch scan
bluearch web start
```

## Local Development

Backend:

```bash
. .venv/bin/activate
PYTHONPATH=src/api python -m uvicorn web.app:create_app --factory --host 127.0.0.1 --port 8095
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Tests

```bash
PYTHONPATH=src/api python -m pytest src/api/tests
PYTHONPATH=src/api python -m compileall src/api
cd frontend && npm run build
```

## Contributing

Keep AWS access user-owned through profiles, AWS SSO, and assume-role. Do not add BlueArch-hosted analytics, product sign-in, license gates, private buckets, internal AWS account IDs, Slack ops notifications, or private signing/release flows. New shared runtime needs should be implemented in `bluearch-aws-core` first.
