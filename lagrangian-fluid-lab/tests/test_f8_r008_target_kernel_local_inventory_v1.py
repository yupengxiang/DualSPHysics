from __future__ import annotations

import copy
from pathlib import Path
import shutil
import types

import pytest

from scripts import f8_r008_target_kernel_local_inventory_v1 as inventory


def _write_fixture(tmp_path: Path, *, release: str = "6.8.0-test-generic") -> tuple[Path, Path, types.SimpleNamespace]:
    usr_src = tmp_path / "usr-src"
    header_root = usr_src / f"linux-headers-{release}"
    (header_root / "include/config").mkdir(parents=True)
    (header_root / "include/generated/uapi/linux").mkdir(parents=True)
    (header_root / "include/uapi/linux").mkdir(parents=True)
    (header_root / "arch/x86/include/uapi/asm").mkdir(parents=True)
    (header_root / "include/config/kernel.release").write_text(release + "\n", encoding="ascii")
    (header_root / "include/generated/utsrelease.h").write_text(
        f'#define UTS_RELEASE "{release}"\n', encoding="ascii"
    )
    (header_root / "include/generated/uapi/linux/version.h").write_text(
        "#define LINUX_VERSION_CODE 393228\n", encoding="ascii"
    )
    config = (
        "CONFIG_FANOTIFY=y\n"
        "CONFIG_FANOTIFY_ACCESS_PERMISSIONS=y\n"
        "CONFIG_SECCOMP=y\n"
        "CONFIG_SECCOMP_FILTER=y\n"
        "# CONFIG_X86_X32_ABI is not set\n"
    )
    (header_root / ".config").write_text(config, encoding="ascii")
    (header_root / "Makefile").write_text("VERSION = 6\nPATCHLEVEL = 8\n", encoding="ascii")
    for relative, content in {
        "include/uapi/linux/fanotify.h": b"fanotify uapi\n",
        "include/uapi/linux/seccomp.h": b"seccomp uapi\n",
        "include/uapi/linux/unistd.h": b"unistd uapi\n",
        "arch/x86/include/uapi/asm/unistd.h": b"unistd x86 uapi\n",
        "arch/x86/include/uapi/asm/ptrace.h": b"ptrace x86 uapi\n",
    }.items():
        (header_root / relative).write_bytes(content)

    boot = tmp_path / "boot" / f"config-{release}"
    boot.parent.mkdir()
    shutil.copyfile(header_root / ".config", boot)
    modules = tmp_path / "lib" / "modules" / release
    modules.mkdir(parents=True)
    build_link = modules / "build"
    build_link.symlink_to(header_root, target_is_directory=True)
    uname_value = types.SimpleNamespace(
        sysname="Linux",
        release=release,
        version="#fixture",
        machine="x86_64",
    )
    return boot, build_link, uname_value


def test_default_report_is_diagnostic_only_and_fail_closed() -> None:
    report = inventory.build_report()

    assert report["status"] == inventory.STATUS
    assert report["authorization"] == inventory.AUTHORIZATION
    assert report["side_effects"] == inventory.SIDE_EFFECTS
    assert report["validation"]["fail_closed"] is True
    assert report["validation"]["required_pins_complete"] is False
    assert report["authorization"]["readiness_pass"] is False
    assert report["authorization"]["T1_numerical"] is False
    assert report["authorization"]["formal_admission"] is False
    assert report["authorization"]["qualification_credit"] == 0
    assert report["evidence"]["build_id"]["proven"] is False
    assert report["evidence"]["source_commit"]["proven"] is False
    assert report["evidence"]["source_tree"]["proven"] is False


def test_bounded_fixture_distinguishes_partial_local_evidence_from_full_pin(tmp_path: Path) -> None:
    boot, build_link, uname_value = _write_fixture(tmp_path)

    report = inventory.build_report(
        uname_value=uname_value,
        boot_config_path=boot,
        build_link_path=build_link,
        allowed_usr_src_root=tmp_path / "usr-src",
    )

    assert report["evidence"]["kernel_release"]["status"] == "present"
    assert report["evidence"]["kernel_release"]["proven"] is True
    assert report["evidence"]["config"]["status"] == "present"
    assert report["evidence"]["config"]["sha256_equal"] is True
    assert report["evidence"]["uapi"]["status"] == "present"
    assert report["evidence"]["headers"]["status"] == "present"
    assert report["pins"]["kernel_release_pinned"] is True
    assert report["pins"]["config_pinned"] is True
    assert report["pins"]["uapi_pinned"] is False
    assert report["pins"]["header_pinned"] is False
    assert report["pins"]["build_id_pinned"] is False
    assert report["pins"]["source_commit_pinned"] is False
    assert report["pins"]["source_tree_pinned"] is False
    assert report["authorization"]["qualification_credit"] == 0


def test_config_drift_and_missing_source_markers_fail_closed(tmp_path: Path) -> None:
    boot, build_link, uname_value = _write_fixture(tmp_path)
    boot.write_text(boot.read_text(encoding="ascii") + "CONFIG_DRIFT=y\n", encoding="ascii")

    report = inventory.build_report(
        uname_value=uname_value,
        boot_config_path=boot,
        build_link_path=build_link,
        allowed_usr_src_root=tmp_path / "usr-src",
    )

    assert report["evidence"]["config"]["sha256_equal"] is False
    assert report["pins"]["config_pinned"] is False
    assert report["evidence"]["source_commit"]["status"] == "not_observed_in_bounded_header_scope"
    assert report["evidence"]["source_tree"]["status"] == "not_proven"
    assert report["validation"]["required_pins_complete"] is False
    assert report["authorization"]["readiness_pass"] is False


def test_build_target_outside_usr_src_is_rejected_without_following_it(tmp_path: Path) -> None:
    boot, _, uname_value = _write_fixture(tmp_path)
    modules = tmp_path / "lib" / "modules" / uname_value.release
    bad_target = tmp_path / "outside"
    bad_target.mkdir()
    bad_link = modules / "build"
    bad_link.unlink()
    bad_link.symlink_to(bad_target, target_is_directory=True)

    report = inventory.build_report(
        uname_value=uname_value,
        boot_config_path=boot,
        build_link_path=bad_link,
        allowed_usr_src_root=tmp_path / "usr-src",
    )

    assert report["paths"]["modules_build"]["target_within_usr_src"] is False
    assert report["paths"]["modules_build"]["target_directory"] is False
    assert report["evidence"]["headers"]["observed"] is False
    assert report["authorization"]["qualification_credit"] == 0


def test_symlink_final_file_and_oversize_are_not_read(tmp_path: Path) -> None:
    boot, build_link, uname_value = _write_fixture(tmp_path)
    header_root = tmp_path / "usr-src" / f"linux-headers-{uname_value.release}"
    real = header_root / "include/uapi/linux/fanotify.real"
    real.write_bytes(b"not the selected file")
    selected = header_root / "include/uapi/linux/fanotify.h"
    selected.unlink()
    selected.symlink_to(real)

    report = inventory.build_report(
        uname_value=uname_value,
        boot_config_path=boot,
        build_link_path=build_link,
        allowed_usr_src_root=tmp_path / "usr-src",
    )

    assert report["evidence"]["uapi"]["files"]["include/uapi/linux/fanotify.h"]["readable"] is False
    assert report["evidence"]["uapi"]["status"] == "not_proven"
    assert report["authorization"]["readiness_pass"] is False

    selected.unlink()
    selected.write_bytes(b"x" * (inventory.MAX_HEADER_BYTES + 1))
    report = inventory.build_report(
        uname_value=uname_value,
        boot_config_path=boot,
        build_link_path=build_link,
        allowed_usr_src_root=tmp_path / "usr-src",
    )
    assert report["evidence"]["uapi"]["files"]["include/uapi/linux/fanotify.h"]["readable"] is False
    assert "bounded byte limit" in report["evidence"]["uapi"]["files"]["include/uapi/linux/fanotify.h"]["error"]


def test_duplicate_json_is_rejected_and_checked_in_report_binds() -> None:
    duplicate = inventory.LAB_ROOT / "reports" / "f8-local-inventory-duplicate-test.json"
    duplicate.write_bytes(b'{"schema":"one","schema":"two"}')
    try:
        with pytest.raises(inventory.LocalInventoryError, match="duplicate JSON object key"):
            inventory._read_json(duplicate)
    finally:
        duplicate.unlink()

    checked = inventory.verify_report()
    assert checked == inventory.build_report()
    inventory.validate_report(checked)


def test_report_validator_rejects_promoted_source_or_readiness_claim() -> None:
    report = inventory.build_report()
    promoted = copy.deepcopy(report)
    promoted["pins"]["source_tree_pinned"] = True
    with pytest.raises(inventory.LocalInventoryError, match="unproven build/source identity"):
        inventory.validate_report(promoted)

    promoted = copy.deepcopy(report)
    promoted["authorization"]["readiness_pass"] = True
    with pytest.raises(inventory.LocalInventoryError, match="authorization boundary"):
        inventory.validate_report(promoted)
