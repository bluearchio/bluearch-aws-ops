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
REAL_SUBPROCESS_RUN = subprocess.run


@pytest.fixture
def real_subprocess(mock_subprocess, monkeypatch):
    monkeypatch.setattr(subprocess, "run", REAL_SUBPROCESS_RUN)


def _write_archive(path: Path, members: list[str]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name in members:
            payload = b"#!/bin/sh\necho 0.13.4\n"
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
        "source_file=\"$BLUEARCH_TEST_DIST_ROOT/${url##*/}\"\n"
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


def _run_installer(tmp_path: Path, members: list[str], manifest: str | None) -> subprocess.CompletedProcess[str]:
    dist = tmp_path / "dist"
    dist.mkdir()
    asset = dist / ASSET_NAME
    _write_archive(asset, members)
    if manifest is None:
        manifest = f"{hashlib.sha256(asset.read_bytes()).hexdigest()}  {ASSET_NAME}\n"
    (dist / "SHA256SUMS").write_text(manifest, encoding="utf-8")
    fake_bin = tmp_path / "fake-bin"
    _write_fake_tools(fake_bin)
    install_dir = tmp_path / "install"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(tmp_path / "home"),
        "INSTALL_DIR": str(install_dir),
        "BLUEARCH_INSTALL_CORE": "skip",
        "BLUEARCH_TEST_DIST_ROOT": str(dist),
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
