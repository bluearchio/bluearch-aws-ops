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

Installing a fully qualified formula automatically adds the tap and trusts only
that formula. Install Core explicitly first so Homebrew records trust for the
separate dependency before resolving Ops. A separate `brew tap` or `brew trust`
command is not needed for a first-time install. See
[Homebrew's tap-trust documentation](https://docs.brew.sh/Tap-Trust).

```bash
brew install bluearchio/tap/bluearch-aws-core
brew install bluearchio/tap/bluearch-aws-ops
bluearch-aws-core start --daemon
bluearch-aws-ops scan
bluearch-aws-ops recommendations
```

`brew tap bluearchio/tap` only downloads and registers the repository; it does
not grant trust. Whole-tap trust is unnecessary.

### Recovery for an existing tap

If an existing or partially completed installation refuses to load either
formula, trust only Core and Ops, then retry the product installation:

```bash
brew trust --formula bluearchio/tap/bluearch-aws-core
brew trust --formula bluearchio/tap/bluearch-aws-ops
brew install bluearchio/tap/bluearch-aws-ops
```

Linux:

```bash
curl -fsSL https://github.com/bluearchio/bluearch-aws-ops/releases/latest/download/install-linux.sh | bash
export PATH="$HOME/.local/bin:$PATH"
bluearch-aws-core start --daemon
bluearch-aws-ops scan
bluearch-aws-ops recommendations
```

The Linux installer installs `bluearch-aws-core` automatically if it is missing.
It downloads both verified archives and their `SHA256SUMS` directly from GitHub
Releases by default. Set `BLUEARCH_VERSION=vX.Y.Z` and
`BLUEARCH_CORE_VERSION=vX.Y.Z` for immutable releases.
`BLUEARCH_DIST_BASE_URL` is supported only when explicitly set to an approved
mirror base URL.

From source:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
bluearch-aws-core start --daemon
bluearch-aws-ops scan
bluearch-aws-ops recommendations
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
npm ci
npm run dev
```

Shortcut:

```bash
make setup
make backend-dev
make frontend-dev
```

## Tests

```bash
PYTHONPATH=src/api python -m pytest src/api/tests
PYTHONPATH=src/api python -m compileall src/api
cd frontend && npm run build
```

Shortcut:

```bash
make test
```

## Verifying Release Assets

Tagged releases are published from GitHub Actions after Linux and signed/notarized macOS artifacts are built. Release assets include platform archives, CycloneDX SBOMs, `SHA256SUMS`, and GitHub artifact attestations.

```bash
sha256sum -c SHA256SUMS
# macOS: shasum -a 256 -c SHA256SUMS
gh attestation verify bluearch-aws-ops-linux-x86_64.tar.gz --repo bluearchio/bluearch-aws-ops
```

For macOS, verify `bluearch-aws-ops-macos-arm64.zip` with `gh attestation verify`.

The publish job can safely resume an existing draft. If a runner stops after
making the release public but before the job completes, an existing public
release is accepted only when its tag target and every remote asset name and
GitHub-provided SHA-256 digest exactly match the rebuilt local set. The workflow
then continues without mutating it; any mismatch fails closed.

After publication, a separate Homebrew job checks out
`bluearchio/homebrew-tap` at `main`, uses its `scripts/update_formula.py` to
generate the immutable GitHub Release URL and exact macOS archive SHA-256, and
opens or updates `release/bluearch-aws-ops-vX.Y.Z`. It requests an automatic
squash merge and waits up to two hours for the pull request to report `MERGED`;
the product release workflow does not succeed merely because auto-merge was
requested. A failed Homebrew job can be rerun without republishing the immutable
release: use GitHub Actions' **Re-run failed jobs** action. **Re-run all jobs**
is reserved for exact crash recovery and succeeds after publication only under
the tag-target and asset/digest equality checks above. Before creating a release
tag, the tap must have auto-merge enabled and
`main` protected by its required CI checks. Configure `HOMEBREW_TAP_TOKEN_2` as
a fine-grained token for that tap with Contents and Pull requests read/write
access.

## Security And Privacy Defaults

- The dashboard binds to loopback by default.
- Calls to `bluearch-aws-core` use the local service token.
- AWS credentials stay in the user's local AWS config/credential chain.
- No BlueArch-hosted telemetry, hosted sign-in, license gates, or private release services are included.
- Generated reports, logs, screenshots, and resource inventories may contain sensitive account data.
- Report suspected vulnerabilities privately; see `SECURITY.md`.

## Contributing

Keep AWS access user-owned through profiles, AWS SSO, and assume-role. Do not add BlueArch-hosted analytics, product sign-in, license gates, private buckets, internal AWS account IDs, Slack ops notifications, or private signing/release flows. New shared runtime needs should be implemented in `bluearch-aws-core` first.

See `CONTRIBUTING.md` for the full contribution workflow.
