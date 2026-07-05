#!/usr/bin/env python3
"""Environment checker for fmbcb-rds-multi-scan."""

from __future__ import annotations

import argparse
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    required: bool = True


def run_cmd(cmd: list[str], timeout: float = 5.0) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout:g}s"


def command_check(name: str, required: bool = True, version_args: Optional[list[str]] = None) -> Check:
    path = shutil.which(name)
    if not path:
        return Check(name, False, "not found in PATH", required=required)
    detail = path
    if version_args:
        code, out, err = run_cmd([name, *version_args], timeout=5.0)
        text = (out or err).splitlines()[0] if (out or err) else ""
        if text:
            detail = f"{path} ({text})"
        elif code not in (0, 1):
            detail = f"{path} (version check exit {code})"
    return Check(name, True, detail, required=required)


def python_module_check(module: str, required: bool = True) -> Check:
    spec = importlib.util.find_spec(module)
    if spec is None:
        return Check(f"python module {module}", False, "not importable", required=required)
    origin = spec.origin or "built-in/namespace"
    return Check(f"python module {module}", True, origin, required=required)


def soapy_find_check(driver: str, required: bool = False) -> Check:
    if not shutil.which("SoapySDRUtil"):
        return Check(f"SoapySDR driver {driver}", False, "SoapySDRUtil not found", required=required)
    code, out, err = run_cmd(["SoapySDRUtil", f"--find={driver}"], timeout=8.0)
    text = "\n".join(x for x in (out, err) if x).strip()
    found = code == 0 and driver.lower() in text.lower() and "No devices found" not in text
    detail = text.splitlines()[0] if text else f"SoapySDRUtil exit {code}"
    return Check(f"SoapySDR driver {driver}", found, detail, required=required)


def lsmod_check(modules: Iterable[str]) -> Check:
    code, out, err = run_cmd(["lsmod"], timeout=5.0)
    if code != 0:
        return Check("conflicting RTL kernel modules", True, f"lsmod unavailable: {err}", required=False)
    loaded = []
    for line in out.splitlines()[1:]:
        name = line.split()[0] if line.split() else ""
        if name in modules:
            loaded.append(name)
    if loaded:
        return Check(
            "conflicting RTL kernel modules",
            False,
            "loaded: " + ", ".join(sorted(loaded)) + " (may claim RTL-SDR dongles)",
            required=False,
        )
    return Check("conflicting RTL kernel modules", True, "none detected", required=False)


def usb_check() -> Check:
    if not shutil.which("lsusb"):
        return Check("USB SDR visibility", False, "lsusb not installed", required=False)
    code, out, err = run_cmd(["lsusb"], timeout=5.0)
    if code != 0:
        return Check("USB SDR visibility", False, err or f"lsusb exit {code}", required=False)
    interesting = []
    for line in out.splitlines():
        low = line.lower()
        if any(token in low for token in ["realtek", "rtl", "sdrplay", "mirics", "miri"]):
            interesting.append(line)
    if interesting:
        return Check("USB SDR visibility", True, "; ".join(interesting[:3]), required=False)
    return Check("USB SDR visibility", False, "no obvious RTL-SDR/SDRplay USB device in lsusb", required=False)


def print_check(check: Check) -> None:
    status = "OK" if check.ok else ("FAIL" if check.required else "WARN")
    print(f"[{status:4}] {check.name}")
    if check.detail:
        print(f"       {check.detail}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check fmbcb-rds-multi-scan runtime environment.")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures.")
    parser.add_argument("--skip-soapy-probe", action="store_true", help="Do not run SoapySDRUtil driver probes.")
    args = parser.parse_args(argv)

    print("fmbcb-rds-multi-scan environment check")
    print(f"Python: {sys.version.split()[0]} at {sys.executable}")
    print(f"OS: {platform.platform()}")
    print(f"PATH: {os.environ.get('PATH', '')}")
    print()

    checks: list[Check] = [
        command_check("rx_sdr", required=True, version_args=["--help"]),
        command_check("csdr", required=True),
        command_check("redsea", required=True, version_args=["--version"]),
        command_check("SoapySDRUtil", required=False, version_args=["--info"]),
        command_check("lsusb", required=False),
        python_module_check("requests", required=True),
        usb_check(),
        lsmod_check(["dvb_usb_rtl28xxu", "rtl2832", "rtl2830"]),
    ]

    if not args.skip_soapy_probe:
        checks.extend([
            soapy_find_check("rtlsdr", required=False),
            soapy_find_check("sdrplay", required=False),
        ])

    failures = 0
    warnings = 0
    for check in checks:
        print_check(check)
        if not check.ok and check.required:
            failures += 1
        elif not check.ok:
            warnings += 1

    print()
    if failures:
        print(f"Environment check failed: {failures} required check(s) failed, {warnings} warning(s).")
        return 2
    if warnings and args.strict:
        print(f"Environment check failed in --strict mode: {warnings} warning(s).")
        return 3
    if warnings:
        print(f"Environment check passed with {warnings} warning(s).")
    else:
        print("Environment check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
