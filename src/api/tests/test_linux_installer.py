from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
ASSET_NAME = "bluearch-aws-ops-linux-x86_64.tar.gz"
BINARY_NAME = "bluearch-aws-ops"
CORE_ASSET_NAME = "bluearch-aws-core-linux-x86_64.tar.gz"
CORE_BINARY_NAME = "bluearch-aws-core"
REAL_SUBPROCESS_RUN = subprocess.run


@pytest.fixture
def real_subprocess(mock_subprocess, monkeypatch):
    monkeypatch.setattr(subprocess, "run", REAL_SUBPROCESS_RUN)


def _write_archive(path: Path, members: list[str], version: str = "0.13.4") -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name in members:
            payload = f"#!/bin/sh\necho {version}\n".encode()
            info = tarfile.TarInfo(name)
            info.mode = 0o755
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def _write_fake_tools(bin_dir: Path) -> None:
    bin_dir.mkdir()
    uname = bin_dir / "uname"
    uname.write_text(
        "#!/usr/bin/env bash\n"
        "case \"${1:-}\" in -s) echo Linux ;; -m) echo x86_64 ;; *) echo Linux ;; esac\n",
        encoding="utf-8",
    )
    curl = bin_dir / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "url=''\n"
        "output=''\n"
        "while (($#)); do\n"
        "  case \"$1\" in\n"
        "    -o) output=\"$2\"; shift 2 ;;\n"
        "    -*) shift ;;\n"
        "    *) url=\"$1\"; shift ;;\n"
        "  esac\n"
        "done\n"
        "case \"$url\" in\n"
        "  */bluearch-aws-core/*) product=core ;;\n"
        "  */bluearch-aws-ops/*) product=ops ;;\n"
        "  *) exit 22 ;;\n"
        "esac\n"
        "printf '%s\\n' \"$url\" >> \"$BLUEARCH_TEST_CURL_LOG\"\n"
        "source_file=\"$BLUEARCH_TEST_DIST_ROOT/$product/${url##*/}\"\n"
        "[[ -f \"$source_file\" ]] || exit 22\n"
        "cp \"$source_file\" \"$output\"\n",
        encoding="utf-8",
    )
    sha256sum = bin_dir / "sha256sum"
    sha256sum.write_text(
        f"#!{sys.executable}\n"
        "import hashlib, pathlib, sys\n"
        "if len(sys.argv) == 3 and sys.argv[1] == '-c':\n"
        "    manifest = pathlib.Path(sys.argv[2]).read_text().strip().split()\n"
        "    expected, filename = manifest\n"
        "    actual = hashlib.sha256(pathlib.Path(filename).read_bytes()).hexdigest()\n"
        "    print(f'{filename}: OK' if actual == expected else f'{filename}: FAILED')\n"
        "    raise SystemExit(0 if actual == expected else 1)\n"
        "raise SystemExit(2)\n",
        encoding="utf-8",
    )
    for path in (uname, curl, sha256sum):
        path.chmod(0o755)


def _write_release(
    directory: Path,
    asset_name: str,
    binary_name: str,
    version: str,
    *,
    members: list[str] | None = None,
    manifest: str | None = None,
) -> None:
    directory.mkdir(parents=True)
    asset = directory / asset_name
    _write_archive(asset, members or [binary_name], version)
    if manifest is None:
        manifest = f"{hashlib.sha256(asset.read_bytes()).hexdigest()}  {asset_name}\n"
    (directory / "SHA256SUMS").write_text(manifest, encoding="utf-8")


def _run_installer(
    tmp_path: Path,
    members: list[str],
    manifest: str | None,
    *,
    core_policy: str = "skip",
    core_candidate: tuple[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    dist = tmp_path / "dist"
    _write_release(
        dist / "ops",
        ASSET_NAME,
        BINARY_NAME,
        "0.13.4",
        members=members,
        manifest=manifest,
    )
    _write_release(
        dist / "core",
        CORE_ASSET_NAME,
        CORE_BINARY_NAME,
        "bluearch-aws-core 0.2.9",
    )
    fake_bin = tmp_path / "fake-bin"
    _write_fake_tools(fake_bin)
    if core_candidate is not None:
        target_name, version = core_candidate
        target = tmp_path / "existing-core" / target_name
        target.parent.mkdir()
        target.write_text(f"#!/bin/sh\necho {version}\n", encoding="utf-8")
        target.chmod(0o755)
        (fake_bin / CORE_BINARY_NAME).symlink_to(target)
    install_dir = tmp_path / "install"
    curl_log = tmp_path / "curl.log"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(tmp_path / "home"),
        "INSTALL_DIR": str(install_dir),
        "BLUEARCH_INSTALL_CORE": core_policy,
        "BLUEARCH_TEST_DIST_ROOT": str(dist),
        "BLUEARCH_TEST_CURL_LOG": str(curl_log),
        "BLUEARCH_DIST_BASE_URL": "https://example.invalid",
    }
    return subprocess.run(
        ["bash", str(ROOT / "scripts" / "install-linux.sh")],
        env=env,
        capture_output=True,
        text=True,
    )


def test_installer_accepts_only_verified_single_binary_archive(tmp_path: Path, real_subprocess) -> None:
    result = _run_installer(tmp_path, [BINARY_NAME], None)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "install" / BINARY_NAME).is_file()


def test_installer_rejects_missing_manifest_row(tmp_path: Path, real_subprocess) -> None:
    result = _run_installer(tmp_path, [BINARY_NAME], "0" * 64 + "  another-asset.tar.gz\n")

    assert result.returncode != 0
    assert not (tmp_path / "install" / BINARY_NAME).exists()


def test_installer_rejects_checksum_mismatch(tmp_path: Path, real_subprocess) -> None:
    result = _run_installer(tmp_path, [BINARY_NAME], "0" * 64 + f"  {ASSET_NAME}\n")

    assert result.returncode != 0
    assert not (tmp_path / "install" / BINARY_NAME).exists()


def test_installer_rejects_extra_archive_members(tmp_path: Path, real_subprocess) -> None:
    result = _run_installer(tmp_path, [BINARY_NAME, "unexpected"], None)

    assert result.returncode != 0
    assert not (tmp_path / "install" / BINARY_NAME).exists()


def test_installer_keeps_compatible_canonical_public_core(tmp_path: Path, real_subprocess) -> None:
    result = _run_installer(
        tmp_path,
        [BINARY_NAME],
        None,
        core_policy="missing",
        core_candidate=(CORE_BINARY_NAME, "bluearch-aws-core 0.2.9"),
    )

    assert result.returncode == 0, result.stderr
    assert "/bluearch-aws-core/" not in (tmp_path / "curl.log").read_text(encoding="utf-8")


def test_installer_replaces_public_name_symlink_to_legacy_core(tmp_path: Path, real_subprocess) -> None:
    result = _run_installer(
        tmp_path,
        [BINARY_NAME],
        None,
        core_policy="missing",
        core_candidate=("bluearch-core", "bluearch-core 9.9.9"),
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "install" / CORE_BINARY_NAME).is_file()
    assert "/bluearch-aws-core/" in (tmp_path / "curl.log").read_text(encoding="utf-8")


def test_installer_replaces_public_named_core_with_legacy_version_identity(
    tmp_path: Path, real_subprocess
) -> None:
    result = _run_installer(
        tmp_path,
        [BINARY_NAME],
        None,
        core_policy="missing",
        core_candidate=(CORE_BINARY_NAME, "bluearch-core 9.9.9"),
    )

    assert result.returncode == 0, result.stderr
    installed_core = tmp_path / "install" / CORE_BINARY_NAME
    assert installed_core.is_file()
    assert "bluearch-aws-core 0.2.9" in installed_core.read_text(encoding="utf-8")
    assert "/bluearch-aws-core/" in (tmp_path / "curl.log").read_text(encoding="utf-8")


def test_installer_replaces_outdated_public_core_target(tmp_path: Path, real_subprocess) -> None:
    result = _run_installer(
        tmp_path,
        [BINARY_NAME],
        None,
        core_policy="missing",
        core_candidate=(CORE_BINARY_NAME, "bluearch-aws-core 0.2.8"),
    )

    assert result.returncode == 0, result.stderr
    installed_core = tmp_path / "install" / CORE_BINARY_NAME
    assert installed_core.is_file()
    assert "0.2.9" in installed_core.read_text(encoding="utf-8")
    assert "/bluearch-aws-core/" in (tmp_path / "curl.log").read_text(encoding="utf-8")
