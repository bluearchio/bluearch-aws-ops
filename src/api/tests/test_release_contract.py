from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
REAL_SUBPROCESS_RUN = subprocess.run


@pytest.fixture
def real_subprocess(mock_subprocess, monkeypatch):
    monkeypatch.setattr(subprocess, "run", REAL_SUBPROCESS_RUN)


def _workflow() -> dict:
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _run_text(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job.get("steps", []))


def test_release_graph_verifies_tag_and_main_before_builds() -> None:
    jobs = _workflow()["jobs"]

    assert jobs["linux"]["needs"] == "verify"
    assert jobs["macos"]["needs"] == "verify"
    assert set(jobs["publish"]["needs"]) == {"verify", "linux", "macos"}
    verify_commands = _run_text(jobs["verify"])
    assert "origin/main" in verify_commands
    assert "dev:refs/remotes/origin/dev" in verify_commands
    assert "pyproject.toml" in verify_commands
    assert "version_controller.py" in verify_commands
    assert "pytest" in verify_commands
    assert "npm --prefix frontend run build" in verify_commands


def test_release_source_gate_rejects_v_named_branches_and_ambiguous_refs() -> None:
    verify_commands = _run_text(_workflow()["jobs"]["verify"])

    assert 'test "${GITHUB_REF_TYPE:-}" = "tag"' in verify_commands
    assert '[[ "$RELEASE_TAG" =~ ^v[0-9]+\\.[0-9]+\\.[0-9]+$ ]]' in verify_commands
    assert 'git rev-parse --verify "refs/tags/${RELEASE_TAG}^{commit}"' in verify_commands
    assert 'head_sha="$(git rev-parse HEAD)"' in verify_commands
    assert 'test "$tag_sha" = "$head_sha"' in verify_commands
    assert 'test "$head_sha" = "$main_sha"' in verify_commands
    assert 'dev_sha="$(git rev-parse origin/dev)"' in verify_commands
    assert 'git merge-base --is-ancestor "$dev_sha" "$tag_sha"' in verify_commands
    assert 'git rev-list -n 1 "$RELEASE_TAG"' not in verify_commands


def test_normal_ci_runs_on_dev_and_main() -> None:
    workflow = yaml.load(CI_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    assert set(workflow["on"]["push"]["branches"]) == {"dev", "main"}


def test_release_verifies_final_artifacts_without_inline_stamping() -> None:
    jobs = _workflow()["jobs"]
    workflow_text = WORKFLOW.read_text(encoding="utf-8")

    assert "scripts/verify_linux_artifact.sh" in _run_text(jobs["linux"])
    assert "scripts/verify_macos_artifact.sh" in _run_text(jobs["macos"])
    assert "scripts/prepare_release_templates.py" in _run_text(jobs["linux"])
    assert "scripts/prepare_release_templates.py" in _run_text(jobs["macos"])
    assert "SHA256SUMS" in _run_text(jobs["publish"])
    assert "Stamp release version" not in workflow_text
    macos_commands = _run_text(jobs["macos"])
    assert "--keepParent" not in macos_commands
    assert "--norsrc --noextattr --noqtn --noacl" in macos_commands
    assert "cd dist" in macos_commands
    linux_verifier = (ROOT / "scripts" / "verify_linux_artifact.sh").read_text(encoding="utf-8")
    macos_verifier = (ROOT / "scripts" / "verify_macos_artifact.sh").read_text(encoding="utf-8")
    assert '"$PUBLIC_BINARY_NAME $EXPECTED_VERSION"' in linux_verifier
    assert '"$PUBLIC_BINARY_NAME $EXPECTED_VERSION"' in macos_verifier


def test_publish_commands_are_explicitly_repository_scoped() -> None:
    publish_commands = _run_text(_workflow()["jobs"]["publish"])

    assert publish_commands.count('--repo "$GITHUB_REPOSITORY"') == 3
    assert 'gh release view "$RELEASE_TAG" --repo "$GITHUB_REPOSITORY"' in publish_commands
    assert 'gh release create "$RELEASE_TAG"' in publish_commands
    assert 'gh release edit "$RELEASE_TAG" --repo "$GITHUB_REPOSITORY"' in publish_commands


def test_release_validates_cross_repo_token_before_publication() -> None:
    workflow = _workflow()
    publish = workflow["jobs"]["publish"]
    names = [step.get("name") for step in publish["steps"]]
    token_step = next(step for step in publish["steps"] if step.get("name") == "Validate Homebrew tap token")
    gate = token_step["run"]

    assert workflow["env"]["HOMEBREW_TAP_REPO"] == "bluearchio/homebrew-tap"
    assert token_step["env"]["GH_TOKEN"] == "${{ secrets.HOMEBREW_TAP_TOKEN_2 }}"
    assert names.index("Validate Homebrew tap token") < names.index("Publish immutable release assets")
    assert '[[ -z "${GH_TOKEN:-}" ]]' in gate
    assert 'gh api "repos/${HOMEBREW_TAP_REPO}"' in gate
    assert ".permissions.push // false" in gate
    assert ".allow_auto_merge // false" in gate
    assert 'gh pr list --repo "${HOMEBREW_TAP_REPO}"' in gate
    assert "|| true" not in gate


def test_release_updates_formula_from_exact_verified_macos_asset() -> None:
    publish = _workflow()["jobs"]["publish"]
    checkout = next(step for step in publish["steps"] if step.get("name") == "Checkout Homebrew tap main")
    update = next(
        step for step in publish["steps"] if step.get("name") == "Update Homebrew formula from verified asset"
    )["run"]

    assert checkout["with"]["repository"] == "${{ env.HOMEBREW_TAP_REPO }}"
    assert checkout["with"]["ref"] == "main"
    assert checkout["with"]["token"] == "${{ secrets.HOMEBREW_TAP_TOKEN_2 }}"
    assert checkout["with"]["persist-credentials"] == "false"
    assert 'asset="${BINARY_NAME}-macos-arm64.zip"' in update
    assert "release-assets/SHA256SUMS" in update
    assert '"${#checksum_rows[@]}" -ne 1' in update
    assert "sha256sum -c -" in update
    assert "homebrew-tap/scripts/update_formula.py" in update
    for argument in ("--formula", "--repo", "--version", "--asset", "--sha256", "--binary"):
        assert argument in update


def test_release_pr_is_main_scoped_and_auto_merge_is_conditional() -> None:
    publish = _workflow()["jobs"]["publish"]
    prepare = next(step for step in publish["steps"] if step.get("name") == "Prepare Homebrew release branch")["run"]
    pr_step = next(
        step for step in publish["steps"] if step.get("name") == "Open or update Homebrew tap pull request"
    )
    commands = pr_step["run"]

    assert pr_step["env"]["GH_TOKEN"] == "${{ secrets.HOMEBREW_TAP_TOKEN_2 }}"
    assert 'branch="release/${HOMEBREW_FORMULA}-${RELEASE_TAG}"' in prepare
    assert 'git checkout -B "${branch}" origin/main' in prepare
    assert 'git push --force-with-lease="refs/heads/${branch}:${remote_sha}" origin "HEAD:refs/heads/${branch}"' in commands
    assert commands.count('--repo "${HOMEBREW_TAP_REPO}"') >= 4
    assert commands.count("--base main") >= 2
    assert commands.count('--head "${branch}"') >= 2
    assert 'if [[ -n "${pr_number}" ]]' in commands
    assert 'gh pr merge "${pr_number}"' in commands
    assert "--auto" in commands
    assert "--squash" in commands
    assert "--delete-branch" in commands
    assert "--admin" not in commands
    assert "git push origin main" not in commands


def test_runtime_identity_dependency_is_declared_and_bundled() -> None:
    requirements = (ROOT / "src" / "api" / "requirements.txt").read_text(encoding="utf-8")
    linux_build = (ROOT / "scripts" / "build_nuitka_linux.sh").read_text(encoding="utf-8")
    macos_build = (ROOT / "scripts" / "build_nuitka_macos.sh").read_text(encoding="utf-8")
    entrypoint = (ROOT / "cli_entry.py").read_text(encoding="utf-8")

    assert re.search(r"^psutil==\d+\.\d+\.\d+$", requirements, re.MULTILINE)
    assert "--include-package=psutil" in linux_build
    assert "--include-package=psutil" in macos_build
    assert "import psutil" in entrypoint


def test_legacy_binary_overwrite_updater_is_not_shipped() -> None:
    execution_source = (ROOT / "src" / "api" / "commons" / "execution.py").read_text(
        encoding="utf-8"
    )

    assert "def update_cli(" not in execution_source
    assert 'installed_binary = os.path.join(install_dir, "bluearch")' not in execution_source
    assert "requests.get(binary_url" not in execution_source
    assert "bluearch_{plat}_{arch}" not in execution_source


def test_committed_versions_are_bare_and_equal() -> None:
    project_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version_text = (ROOT / "src" / "api" / "aws" / "misc" / "version_controller.py").read_text(encoding="utf-8")
    project_version = re.search(r'^version = "([^"]+)"$', project_text, re.MULTILINE).group(1)
    runtime_version = re.search(
        r'^CURRENT_VERSION = os\.environ\.get\("BLUEARCH_AWS_OPS_VERSION", "([^"]+)"\)$',
        version_text,
        re.MULTILINE,
    ).group(1)

    assert project_version == runtime_version == "0.13.4"
    assert re.fullmatch(r"\d+\.\d+\.\d+", project_version)


def test_version_setter_accepts_v_prefixed_semver_and_writes_bare_metadata(
    tmp_path: Path, real_subprocess
) -> None:
    (tmp_path / "scripts").mkdir()
    version_dir = tmp_path / "src" / "api" / "aws" / "misc"
    version_dir.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "set_release_version.py", tmp_path / "scripts")
    shutil.copy2(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copy2(
        ROOT / "src" / "api" / "aws" / "misc" / "version_controller.py",
        version_dir / "version_controller.py",
    )

    valid = subprocess.run(
        [sys.executable, str(tmp_path / "scripts" / "set_release_version.py"), "v9.8.7"],
        capture_output=True,
        text=True,
    )
    invalid = subprocess.run(
        [sys.executable, str(tmp_path / "scripts" / "set_release_version.py"), "9.8.7"],
        capture_output=True,
        text=True,
    )

    assert valid.returncode == 0
    assert 'version = "9.8.7"' in (tmp_path / "pyproject.toml").read_text()
    assert 'os.environ.get("BLUEARCH_AWS_OPS_VERSION", "9.8.7")' in (
        version_dir / "version_controller.py"
    ).read_text()
    assert invalid.returncode != 0


def test_template_preparation_is_deterministic(tmp_path: Path, real_subprocess) -> None:
    (tmp_path / "scripts").mkdir()
    templates = tmp_path / "src" / "api" / "templates"
    templates.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "prepare_release_templates.py", tmp_path / "scripts")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.13.4"\n', encoding="utf-8")
    template = templates / "sample.yaml"
    template.write_text(
        "version: __TEMPLATE_VERSION__\ncli: __CLI_VERSION__\ndate: __DEPLOYMENT_DATE__\n",
        encoding="utf-8",
    )
    env = {**os.environ, "RELEASE_TAG": "v0.13.4", "SOURCE_DATE_EPOCH": "0"}

    result = subprocess.run(
        [sys.executable, str(tmp_path / "scripts" / "prepare_release_templates.py")],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert template.read_text() == "version: 0.13.4\ncli: 0.13.4\ndate: 1970-01-01T00:00:00Z\n"


def test_linux_installer_is_fail_closed_and_has_exact_layout_checks() -> None:
    source = (ROOT / "scripts" / "install-linux.sh").read_text(encoding="utf-8")

    assert "continuing without checksum" not in source
    assert "exactly one row" in source
    assert "exactly one top-level" in source
    assert "find " not in source


def test_linux_installer_defaults_to_github_releases_and_keeps_mirror_opt_in() -> None:
    source = (ROOT / "scripts" / "install-linux.sh").read_text(encoding="utf-8")

    assert 'https://github.com/%s/releases/latest/download' in source
    assert 'https://github.com/%s/releases/download/%s' in source
    assert 'local dist_base="${BLUEARCH_DIST_BASE_URL:-}"' in source
    assert 'BLUEARCH_DIST_BASE_URL:-https://dist.bluearch.io' not in source


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS signature tools are required")
def test_macos_verifier_rejects_unsigned_archive(tmp_path: Path, real_subprocess) -> None:
    binary = tmp_path / "bluearch-aws-ops"
    binary.write_text("#!/bin/sh\necho 0.13.4\n", encoding="utf-8")
    binary.chmod(0o755)
    archive = tmp_path / "unsigned.zip"
    subprocess.run(["ditto", "-c", "-k", "--keepParent", str(binary), str(archive)], check=True)

    result = subprocess.run(
        [
            "bash",
            str(ROOT / "scripts" / "verify_macos_artifact.sh"),
            str(archive),
            binary.name,
            "0.13.4",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
