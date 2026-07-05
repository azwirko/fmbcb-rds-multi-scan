#!/usr/bin/env python3

import argparse
import csv
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Dict, List, Optional, Set, Tuple
import bz2
import requests


PI_CODES_URL = "https://picodes.nrscstandards.org/fs_pi_codes_allocated.html"

RABBITEARS_SPOT_URL = "http://rabbitears.info/tvdx/fm_spot"

RABBITEARS_HEADERS = {
    "Content-Type": "application/octet-stream",
    "Content-Charset": "binary",
}

# RabbitEars can return HTTP 500 when too many stations are submitted in one POST.
# Keep this as a code-level constant instead of a command-line option.
RABBITEARS_MAX_STATIONS_PER_POST = 20

# Reduce load on RabbitEars by suppressing repeat uploads for the same
# decoded station record until this cache interval expires. Local JSONL
# local JSONL logging is cycle-summarized; this only throttles upload.
# A station record is keyed by frequency Hz + PI code.
RABBITEARS_STATION_UPLOAD_CACHE_MINUTES = 30
RABBITEARS_STATION_UPLOAD_CACHE: Dict[str, float] = {}
RABBITEARS_STATION_UPLOAD_CACHE_LOCK = threading.Lock()


def format_rabbitears_time(record_time_unix=None) -> str:
    """
    RabbitEars timestamp format:
      2026-06-11T14:22:10-0400

    Note: this intentionally uses -0400, not -04:00.
    """
    if record_time_unix is not None:
        dt = datetime.fromtimestamp(float(record_time_unix)).astimezone()
    else:
        dt = datetime.now().astimezone()

    dt = datetime.now(timezone.utc)

    return dt.strftime("%Y-%m-%dT%H:%M") + "Z"


def format_log_date_time(record_time_unix=None) -> Tuple[str, str]:
    """
    Return separate local date and time strings for JSONL log output.

    The time field includes the local UTC offset, for example:
      date: 2026-06-11
      time: 14:14:52-0400
    """
    if record_time_unix is not None:
        dt = datetime.fromtimestamp(float(record_time_unix)).astimezone()
    else:
        dt = datetime.now().astimezone()

    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S%z")


def dms_to_decimal_degrees(degrees: float, minutes: float = 0.0, seconds: float = 0.0, hemisphere: str = "") -> float:
    """
    Convert degrees/minutes/seconds plus hemisphere to signed decimal degrees.

    North and East are positive. South and West are negative.
    """
    sign = -1 if float(degrees) < 0 else 1
    decimal = abs(float(degrees)) + (float(minutes) / 60.0) + (float(seconds) / 3600.0)

    hemi = (hemisphere or "").strip().upper()
    if hemi in ("S", "W"):
        sign = -1
    elif hemi in ("N", "E"):
        sign = 1

    return sign * decimal


def convert_location_dms_to_decimal(location: str) -> str:
    """
    Convert DMS-style latitude/longitude text to decimal degrees.

    Examples accepted:
      38 53 51 N 77 02 11 W
      38°53'51"N 77°02'11"W
      LAT. 38 53 51 N LON. 77 02 11 W

    Returns "lat,lon" using six decimal places when both coordinates are found.
    If no usable coordinate pair is found, returns the original location text.
    """
    if location is None:
        return ""

    original = str(location).strip()
    if not original:
        return ""

    text = original.upper()

    # Normalize common degree/minute/second punctuation and labels to spaces.
    text = re.sub(r"[°º]", " ", text)
    text = re.sub(r"[′’']", " ", text)
    text = re.sub(r"[″”\"]", " ", text)
    text = re.sub(r"\b(?:LAT|LATITUDE|LON|LONG|LONGITUDE)\.?\b", " ", text)
    text = re.sub(r"[(),;:/]", " ", text)
    text = " ".join(text.split())

    # Match D M S H where M/S are optional, but hemisphere is required.
    coord_re = re.compile(
        r"([+-]?\d+(?:\.\d+)?)\s+"
        r"(?:(\d+(?:\.\d+)?)\s+)?"
        r"(?:(\d+(?:\.\d+)?)\s+)?"
        r"([NSEW])\b"
    )

    lat = None
    lon = None

    for match in coord_re.finditer(text):
        deg = float(match.group(1))
        minute = float(match.group(2)) if match.group(2) is not None else 0.0
        second = float(match.group(3)) if match.group(3) is not None else 0.0
        hemi = match.group(4).upper()

        decimal = dms_to_decimal_degrees(deg, minute, second, hemi)

        if hemi in ("N", "S") and lat is None:
            lat = decimal
        elif hemi in ("E", "W") and lon is None:
            lon = decimal

    if lat is None or lon is None:
        return original

    return f"{lat:.6f},{lon:.6f}"



def split_decimal_location(location: str) -> Tuple[str, str]:
    """
    Split a decimal coordinate string of the form "lat,lon" into separate
    latitude and longitude strings. Returns ("", "") if location is not a
    parseable decimal coordinate pair.
    """
    if location is None:
        return "", ""

    text = str(location).strip()
    if not text:
        return "", ""

    m = re.match(
        r"^\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*$",
        text,
    )

    if not m:
        return "", ""

    try:
        lat = float(m.group(1))
        lon = float(m.group(2))
    except ValueError:
        return "", ""

    return f"{lat:.6f}", f"{lon:.6f}"


def build_single_rabbitears_payload(tuner_key: int, record: Dict) -> Optional[Dict]:
    """
    Convert one validated scanner record into one RabbitEars upload payload.

    Output format:
    {
      "tuner_key": 84,
      "signal": {
        "107700000": {
          "pi_code": 37135,
          "time": "2026-06-11T14:14:52-0400"
        }
      }
    }
    """
    try:
        pi_hex = normalize_pi(record.get("pi"))

        if not pi_hex or pi_hex == "0x0000":
            return None

        pi_dec = int(pi_hex, 16)

        frequency_hz = record.get("frequency_hz")

        if frequency_hz is None:
            frequency_mhz = record.get("frequency_mhz")

            if frequency_mhz is None:
                print(
                    f"RabbitEars upload: skipping record without frequency: {record!r}",
                    file=sys.stderr,
                )
                return None

            frequency_hz = int(round(float(frequency_mhz) * 1_000_000))
        else:
            frequency_hz = int(round(float(frequency_hz)))

        frequency_key = str(frequency_hz)
        date_time = format_rabbitears_time(record.get("time_unix"))

        return {
            "tuner_key" : tuner_key,
            "signal" : {
                frequency_key : {
                    "time" : date_time,
                    "pi_code" : pi_hex,
                }
            },
        }

    except Exception as e:
        print(
            f"RabbitEars upload: could not build payload from record {record!r}: {e}",
            file=sys.stderr,
        )
        return None


def post_single_rabbitears_payload(
    payload: Dict,
    timeout: float,
    retries: int,
    retry_delay: float,
    debug: bool = False,
) -> bool:
    """
    Compress and POST one RabbitEars payload.
    """
    try:
        json_text = json.dumps(payload, indent=6)
        bz2_upload = bz2.compress(json_text.encode("utf-8"))
    except Exception as e:
        print(
            f"RabbitEars upload: failed preparing compressed payload: {e}",
            file=sys.stderr,
        )
        return False

    if debug:
        print("RabbitEars single-record JSON payload:", file=sys.stderr)
        print(json_text, file=sys.stderr)

    for attempt in range(1, retries + 1):
        try:
            signal = payload.get("signal", {})
            frequency_key = next(iter(signal.keys()), "unknown")
            pi_code = signal.get(frequency_key, {}).get("pi_code", "unknown")

            if debug:
                print(f"RabbitEars POST {frequency_key} pi_code={pi_code} attempt {attempt}/{retries}",
                    file=sys.stderr,
                )

            response = requests.post(
                RABBITEARS_SPOT_URL,
                headers=RABBITEARS_HEADERS,
                data=bz2_upload,
                timeout=timeout,
            )

            if debug:
                print(f"RabbitEars response for {frequency_key}: HTTP {response.status_code}",
                    file=sys.stderr,
                )

                if response.text:
                    print(
                        f"RabbitEars response body for {frequency_key}: {response.text[:500]!r}",
                        file=sys.stderr,
                    )

            if response.status_code in (200, 201, 202, 204):
                return True

            print(
                f"RabbitEars upload failed for {frequency_key}: HTTP {response.status_code}",
                file=sys.stderr,
            )

        except requests.exceptions.Timeout:
            print(
                f"RabbitEars upload timed out after {timeout:.1f}s.",
                file=sys.stderr,
            )

        except requests.exceptions.ConnectionError as e:
            print(
                f"RabbitEars upload connection error: {e}",
                file=sys.stderr,
            )

        except requests.exceptions.RequestException as e:
            print(
                f"RabbitEars upload request error: {e}",
                file=sys.stderr,
            )

        except Exception as e:
            print(
                f"RabbitEars upload unexpected error: {e}",
                file=sys.stderr,
            )

        if attempt < retries:
            time.sleep(retry_delay)

    return False


def upload_bandscan_to_rabbitears_old(
    tuner_key: int,
    records: List[Dict],
    timeout: float = 20.0,
    retries: int = 3,
    retry_delay: float = 5.0,
    debug: bool = False,
    per_record_delay: float = 0.5,
) -> bool:
    """
    Upload validated PI/frequency results from one complete FM band-scan cycle
    to RabbitEars, one JSON record per POST.

    This intentionally does NOT batch multiple frequencies into one payload.
    """
    if tuner_key is None:
        print("RabbitEars upload skipped: no tuner key supplied.", file=sys.stderr)
        return False

    if not isinstance(tuner_key, int) or tuner_key <= 0:
        print(
            f"RabbitEars upload skipped: invalid tuner key {tuner_key!r}.",
            file=sys.stderr,
        )
        return False

    if not records:
        print(
            "RabbitEars upload skipped: no validated stations in this cycle.",
            file=sys.stderr,
        )
        return False

    # Deduplicate by frequency. Keep the latest record for each frequency.
    latest_by_frequency: Dict[str, Dict] = {}

    for record in records:
        try:
            frequency_hz = record.get("frequency_hz")

            if frequency_hz is None:
                frequency_mhz = record.get("frequency_mhz")
                if frequency_mhz is None:
                    continue
                frequency_hz = int(round(float(frequency_mhz) * 1_000_000))
            else:
                frequency_hz = int(round(float(frequency_hz)))

            frequency_key = str(frequency_hz)

            existing = latest_by_frequency.get(frequency_key)
            if existing is None:
                latest_by_frequency[frequency_key] = record
                continue

            existing_time = float(existing.get("time_unix", 0))
            record_time = float(record.get("time_unix", 0))

            if record_time >= existing_time:
                latest_by_frequency[frequency_key] = record

        except Exception as e:
            print(
                f"RabbitEars upload: skipping malformed record during dedupe {record!r}: {e}",
                file=sys.stderr,
            )

    if not latest_by_frequency:
        print(
            "RabbitEars upload skipped: no valid records after frequency dedupe.",
            file=sys.stderr,
        )
        return False

    print(
        f"RabbitEars upload: posting {len(latest_by_frequency)} individual record(s).",
        file=sys.stderr,
    )

    success_count = 0
    fail_count = 0

    for frequency_key in sorted(latest_by_frequency.keys(), key=lambda x: int(x)):
        record = latest_by_frequency[frequency_key]

        payload = build_single_rabbitears_payload(
            tuner_key=tuner_key,
            record=record,
        )

        if payload is None:
            fail_count += 1
            continue

        ok = post_single_rabbitears_payload(
            payload=payload,
            timeout=timeout,
            retries=retries,
            retry_delay=retry_delay,
            debug=debug,
        )

        if ok:
            success_count += 1
        else:
            fail_count += 1

        if per_record_delay > 0:
            time.sleep(per_record_delay)

    print(
        f"RabbitEars upload complete: success={success_count}, failed={fail_count}",
        file=sys.stderr,
    )

    return fail_count == 0


def get_rabbitears_station_cache_key(record: Dict) -> Optional[str]:
    """
    Build a stable RabbitEars upload/cache key from one decoded station record.

    Key format:
      frequency_hz:pi_decimal

    Example:
      107700000:37135

    This key intentionally combines RF frequency and PI code. If a frequency
    changes PI, or a PI appears on a different frequency, it is treated as a
    different station record for upload-cache purposes.
    """
    try:
        pi_hex = normalize_pi(record.get("pi") or record.get("pi_code"))

        if not pi_hex or pi_hex == "0x0000":
            return None

        pi_dec = int(pi_hex, 16)

        frequency_hz = record.get("frequency_hz")

        if frequency_hz is None:
            frequency_mhz = record.get("frequency_mhz")
            if frequency_mhz is None:
                return None
            frequency_hz = int(round(float(frequency_mhz) * 1_000_000))
        else:
            frequency_hz = int(round(float(frequency_hz)))

        return f"{frequency_hz}:{pi_dec}"

    except Exception:
        return None


def dedupe_rabbitears_upload_records(records: List[Dict]) -> Dict[str, Dict]:
    """
    Collapse raw decode observations down to one record per unique station.

    This must happen before applying the RabbitEars upload cache; otherwise a
    station decoded hundreds of times in one cycle can inflate the "suppressed"
    count even though it represents only one station.

    If a station appears multiple times, keep the record with the highest
    accumulated decode count. If tied, keep the latest time_unix.
    """
    best_by_station: Dict[str, Dict] = {}

    for record in records:
        key = get_rabbitears_station_cache_key(record)
        if key is None:
            continue

        existing = best_by_station.get(key)
        if existing is None:
            best_by_station[key] = record
            continue

        try:
            existing_count = int(existing.get("count", 0) or 0)
        except Exception:
            existing_count = 0

        try:
            record_count = int(record.get("count", 0) or 0)
        except Exception:
            record_count = 0

        try:
            existing_time = float(existing.get("time_unix", 0) or 0)
        except Exception:
            existing_time = 0.0

        try:
            record_time = float(record.get("time_unix", 0) or 0)
        except Exception:
            record_time = 0.0

        if record_count > existing_count:
            best_by_station[key] = record
        elif record_count == existing_count and record_time >= existing_time:
            best_by_station[key] = record

    return best_by_station


def build_rabbitears_signal_entry(record: Dict) -> Optional[Tuple[str, Dict, str]]:
    """
    Convert one deduplicated station record into a RabbitEars signal entry.

    Returns:
      (frequency_key, signal_value, station_cache_key)

    Example:
      (
        "107700000",
        {"pi_code": 37135, "time": "2026-06-11T18:14Z"},
        "107700000:37135",
      )
    """
    try:
        pi_hex = normalize_pi(record.get("pi") or record.get("pi_code"))

        if not pi_hex or pi_hex == "0x0000":
            return None

        pi_dec = int(pi_hex, 16)

        frequency_hz = record.get("frequency_hz")

        if frequency_hz is None:
            frequency_mhz = record.get("frequency_mhz")
            if frequency_mhz is None:
                return None
            frequency_hz = int(round(float(frequency_mhz) * 1_000_000))
        else:
            frequency_hz = int(round(float(frequency_hz)))

        frequency_key = str(frequency_hz)
        station_cache_key = f"{frequency_key}:{pi_dec}"

        signal_value = {
            "pi_code": int(pi_dec),
            "time": format_rabbitears_time(record.get("time_unix")),
        }

        return frequency_key, signal_value, station_cache_key

    except Exception as e:
        print(
            f"RabbitEars upload: skipping malformed upload record {record!r}: {e}",
            file=sys.stderr,
        )
        return None


def upload_bandscan_to_rabbitears(
    tuner_key: int,
    records: List[Dict],
    timeout: float = 20.0,
    retries: int = 3,
    retry_delay: float = 5.0,
) -> bool:
    """
    Upload validated PI/frequency results to RabbitEars FM Live Band Scan.

    Important behavior:
    - Raw decode observations are first deduplicated to unique station records.
    - The upload cache is applied to unique station records, not raw decodes.
    - Repeated uploads are suppressed for RABBITEARS_STATION_UPLOAD_CACHE_MINUTES.
    - RabbitEars POSTs are split into batches of at most
      RABBITEARS_MAX_STATIONS_PER_POST stations.
    """
    if tuner_key is None:
        print("RabbitEars upload skipped: no tuner key supplied.", file=sys.stderr)
        return False

    if not isinstance(tuner_key, int) or tuner_key <= 0:
        print(
            f"RabbitEars upload skipped: invalid tuner key {tuner_key!r}.",
            file=sys.stderr,
        )
        return False

    if not records:
        print(
            "RabbitEars upload skipped: no validated stations in this cycle.",
            file=sys.stderr,
        )
        return False

    if RABBITEARS_MAX_STATIONS_PER_POST <= 0:
        print(
            "RabbitEars upload skipped: RABBITEARS_MAX_STATIONS_PER_POST must be greater than zero.",
            file=sys.stderr,
        )
        return False

    if RABBITEARS_STATION_UPLOAD_CACHE_MINUTES < 0:
        print(
            "RabbitEars upload skipped: RABBITEARS_STATION_UPLOAD_CACHE_MINUTES must be zero or greater.",
            file=sys.stderr,
        )
        return False

    best_by_station = dedupe_rabbitears_upload_records(records)

    if not best_by_station:
        print(
            "RabbitEars upload skipped: no valid unique station records after dedupe.",
            file=sys.stderr,
        )
        return False

    cache_ttl_seconds = RABBITEARS_STATION_UPLOAD_CACHE_MINUTES * 60.0
    now_unix = time.time()

    pending_uploads: Dict[str, Dict] = {}
    skipped_unique_by_cache = 0

    for station_cache_key, record in best_by_station.items():
        with RABBITEARS_STATION_UPLOAD_CACHE_LOCK:
            last_upload_unix = RABBITEARS_STATION_UPLOAD_CACHE.get(station_cache_key)

        if last_upload_unix is not None and cache_ttl_seconds > 0:
            if now_unix - last_upload_unix < cache_ttl_seconds:
                skipped_unique_by_cache += 1
                continue

        entry = build_rabbitears_signal_entry(record)
        if entry is None:
            continue

        frequency_key, signal_value, normalized_cache_key = entry
        pending_uploads[normalized_cache_key] = {
            "frequency_key": frequency_key,
            "station_cache_key": normalized_cache_key,
            "signal_value": signal_value,
        }

    if not pending_uploads:
        print(
            f"RabbitEars upload skipped: 0 station(s) due for upload; "
            f"{skipped_unique_by_cache} unique station(s) suppressed by "
            f"{RABBITEARS_STATION_UPLOAD_CACHE_MINUTES}-minute cache. "
            f"unique_station_records={len(best_by_station)} raw_records={len(records)}",
            file=sys.stderr,
        )
        return True

    sorted_entries = sorted(
        pending_uploads.values(),
        key=lambda entry: (int(entry["frequency_key"]), entry["signal_value"].get("pi_code", 0)),
    )

    batches = [
        sorted_entries[i:i + RABBITEARS_MAX_STATIONS_PER_POST]
        for i in range(0, len(sorted_entries), RABBITEARS_MAX_STATIONS_PER_POST)
    ]

    print(
        f"RabbitEars upload prepared {len(sorted_entries)} station(s) in {len(batches)} POST batch(es), "
        f"max {RABBITEARS_MAX_STATIONS_PER_POST} station(s) per POST; "
        f"{skipped_unique_by_cache} unique station(s) suppressed by "
        f"{RABBITEARS_STATION_UPLOAD_CACHE_MINUTES}-minute cache. "
        f"unique_station_records={len(best_by_station)} raw_records={len(records)}",
        file=sys.stderr,
    )

    success_batches = 0
    failed_batches = 0

    for batch_index, batch_entries in enumerate(batches, start=1):
        batch_signal = {
            entry["frequency_key"]: entry["signal_value"]
            for entry in batch_entries
        }
        batch_cache_keys = [entry["station_cache_key"] for entry in batch_entries]
        json_upload = {
            "signal": batch_signal,
            "tuner_key": str(tuner_key),
        }

        try:
            json_text = json.dumps(json_upload)
            bz2_upload = bz2.compress(json_text.encode("utf-8"))
        except Exception as e:
            print(
                f"RabbitEars upload failed while preparing batch {batch_index}/{len(batches)} payload: {e}",
                file=sys.stderr,
            )
            failed_batches += 1
            continue

        batch_freqs = ",".join(batch_signal.keys())

        for attempt in range(1, retries + 1):
            try:
                print(
                    f"Uploading RabbitEars batch {batch_index}/{len(batches)} "
                    f"with {len(batch_signal)} station(s), attempt {attempt}/{retries}...",
                    file=sys.stderr,
                )

                response = requests.post(
                    RABBITEARS_SPOT_URL,
                    headers=RABBITEARS_HEADERS,
                    data=bz2_upload,
                    timeout=timeout,
                )

                if response.text:
                    print(
                        f"RabbitEars response body for batch {batch_index}/{len(batches)}: "
                        f"{response.text[:500]!r}",
                        file=sys.stderr,
                    )

                # RabbitEars appears to use 202 Accepted for successful intake.
                if response.status_code in (200, 201, 202, 204):
                    success_batches += 1
                    cache_update_unix = time.time()
                    with RABBITEARS_STATION_UPLOAD_CACHE_LOCK:
                        for station_cache_key in batch_cache_keys:
                            # Reset only after the server accepts this batch.
                            RABBITEARS_STATION_UPLOAD_CACHE[station_cache_key] = cache_update_unix
                    break

                print(
                    f"RabbitEars upload failed for batch {batch_index}/{len(batches)}: "
                    f"HTTP {response.status_code}; frequencies={batch_freqs}",
                    file=sys.stderr,
                )

            except requests.exceptions.Timeout:
                print(
                    f"RabbitEars upload timed out for batch {batch_index}/{len(batches)} "
                    f"after {timeout:.1f}s.",
                    file=sys.stderr,
                )

            except requests.exceptions.ConnectionError as e:
                print(
                    f"RabbitEars upload connection error for batch {batch_index}/{len(batches)}: {e}",
                    file=sys.stderr,
                )

            except requests.exceptions.RequestException as e:
                print(
                    f"RabbitEars upload request error for batch {batch_index}/{len(batches)}: {e}",
                    file=sys.stderr,
                )

            except Exception as e:
                print(
                    f"RabbitEars upload unexpected error for batch {batch_index}/{len(batches)}: {e}",
                    file=sys.stderr,
                )

            if attempt < retries:
                time.sleep(retry_delay)
        else:
            failed_batches += 1

    print(
        f"RabbitEars upload complete: successful_batches={success_batches}, "
        f"failed_batches={failed_batches}, total_batches={len(batches)}, "
        f"unique_station_records={len(best_by_station)}, "
        f"cache_entries={len(RABBITEARS_STATION_UPLOAD_CACHE)}.",
        file=sys.stderr,
    )

    return failed_batches == 0


def start_rx_sdr_with_retries(
    rx_cmd: List[str],
    center_hz: float,
    retries: int,
    retry_delay: float,
) -> subprocess.Popen:
    last_proc = None

    for attempt in range(1, retries + 1):
        print(
            f"Starting rx_sdr at center {format_mhz(center_hz)} MHz "
            f"attempt {attempt}/{retries}",
            file=sys.stderr,
        )
        print("rx_sdr command: " + " ".join(rx_cmd), file=sys.stderr)

        proc = subprocess.Popen(
            rx_cmd,
            stdout=subprocess.PIPE,
            # stderr=sys.stderr,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            start_new_session=True,
        )

        # Give rx_sdr a moment to fail if the device is busy.
        time.sleep(0.75)

        if proc.poll() is None:
            return proc

        last_proc = proc
        terminate_process_tree(proc, name="failed rx_sdr", timeout=1.0)

        if attempt < retries:
            print(
                f"rx_sdr exited immediately, waiting {retry_delay:.1f}s before retry...",
                file=sys.stderr,
            )
            time.sleep(retry_delay)

    raise RuntimeError(
        f"rx_sdr failed to start at center {format_mhz(center_hz)} MHz after {retries} attempts."
    )


def terminate_process_tree(proc: Optional[subprocess.Popen], name: str = "process", timeout: float = 2.0):
    """
    Terminate a subprocess and its process group.

    This is important for rx_sdr because the SDR device may not be released
    immediately if the process is only partially terminated.
    """
    if proc is None:
        return

    # Close pipes first so children see EOF where appropriate.
    try:
        if proc.stdout:
            proc.stdout.close()
    except Exception:
        pass

    try:
        if proc.stdin:
            proc.stdin.close()
    except Exception:
        pass

    if proc.poll() is not None:
        return

    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass

    try:
        proc.wait(timeout=timeout)
        return
    except subprocess.TimeoutExpired:
        pass

    print(f"Warning: {name} did not exit after SIGTERM; killing it.", file=sys.stderr)

    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

    try:
        proc.wait(timeout=timeout)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# rx_sdr hardware profiles and gain handling
# ---------------------------------------------------------------------------

RX_SDR_PROFILES = {
    "sdrplay": {
        "device_args": ["-d", "driver=sdrplay"],
        # rx_sdr wants SDRplay gain as: -g RFGR=<n>
        "gain_args": ["-g", "RFGR="],
        "gain_min": 0,
        "gain_max": 6,
        "gain_incr": 1,
    },
    "rtlsdr": {
        "device_args": ["-d", "driver=rtlsdr"],
        # rx_sdr wants RTL-SDR gain as: -g <n>
        "gain_args": ["-g", ""],
        "gain_min": 0,
        "gain_max": 50,
        "gain_incr": 1,
    },
}


def build_gain_args_from_profile(profile: Dict, gain_value: int, rx_sdr_name: str) -> List[str]:
    """
    Build vendor-specific rx_sdr gain arguments from profile["gain_args"].

    Examples:
      sdrplay: gain_args=["-g", "RFGR="] and gain=4 -> ["-g", "RFGR=4"]
      rtlsdr:  gain_args=["-g", ""]      and gain=4 -> ["-g", "4"]

    The gain value is appended to the final element in the list. This keeps
    the profile flexible for vendors whose gain option has a name prefix and
    vendors whose gain option is just a bare numeric argument.
    """
    gain_args = profile.get("gain_args")

    if not gain_args:
        raise ValueError(f"Gain is not supported for --rx-sdr {rx_sdr_name}.")

    if not isinstance(gain_args, list) or not all(isinstance(item, str) for item in gain_args):
        raise ValueError(
            f"Invalid gain_args profile for --rx-sdr {rx_sdr_name}; "
            "expected a list of strings."
        )

    built_args = list(gain_args)
    built_args[-1] = f"{built_args[-1]}{gain_value}"
    return built_args


def build_rx_sdr_hardware_args_for_gain(args, gain_value: Optional[int]) -> List[str]:
    """
    Build rx_sdr hardware-specific command arguments.

    Examples:
      --rx-sdr sdrplay --rx-gain 4 -> -d driver=sdrplay -g RFGR=4
      --rx-sdr rtlsdr  --rx-gain 4 -> -d driver=rtlsdr  -g 4

    args.rx_arg remains available for advanced extra rx_sdr arguments.
    """
    rx_args: List[str] = []
    rx_sdr_name = args.rx_sdr.strip().lower() if getattr(args, "rx_sdr", None) else ""

    if rx_sdr_name:
        profile = RX_SDR_PROFILES.get(rx_sdr_name)

        if profile is None:
            supported = ", ".join(sorted(RX_SDR_PROFILES.keys()))
            raise ValueError(
                f"Unsupported --rx-sdr '{args.rx_sdr}'. Supported values: {supported}"
            )

        rx_args.extend(profile.get("device_args", []))

        if gain_value is not None:
            gain_min = profile.get("gain_min")
            gain_max = profile.get("gain_max")

            if gain_min is not None and gain_value < gain_min:
                raise ValueError(
                    f"Gain {gain_value} is below valid range for {rx_sdr_name}: "
                    f"{gain_min}–{gain_max}"
                )

            if gain_max is not None and gain_value > gain_max:
                raise ValueError(
                    f"Gain {gain_value} is above valid range for {rx_sdr_name}: "
                    f"{gain_min}–{gain_max}"
                )

            rx_args.extend(build_gain_args_from_profile(profile, gain_value, rx_sdr_name))

    elif gain_value is not None:
        raise ValueError("--rx-gain requires --rx-sdr so the gain mapping is known.")

    if args.rx_arg:
        rx_args.extend(args.rx_arg)

    return rx_args


def get_gain_values_for_profile(args) -> List[int]:
    """Return all gain values to try for the selected --rx-sdr profile."""
    rx_sdr_name = args.rx_sdr.strip().lower() if getattr(args, "rx_sdr", None) else ""

    if not rx_sdr_name:
        raise ValueError("Automatic gain calibration requires --rx-sdr.")

    profile = RX_SDR_PROFILES.get(rx_sdr_name)

    if profile is None:
        raise ValueError(f"Unsupported --rx-sdr '{args.rx_sdr}'.")

    gain_min = profile.get("gain_min")
    gain_max = profile.get("gain_max")
    gain_incr = profile.get("gain_incr", 1)

    if gain_min is None or gain_max is None:
        raise ValueError(f"--rx-sdr {rx_sdr_name} does not define a gain range.")

    if int(gain_incr) <= 0:
        raise ValueError(f"--rx-sdr {rx_sdr_name} has invalid gain_incr={gain_incr}.")

    return list(range(int(gain_min), int(gain_max) + 1, int(gain_incr)))


def count_total_raw_station_decodes(records: List[Dict]) -> int:
    """
    Score a calibration scan by total raw PI decode count across stations.

    The scan buffer may contain multiple records for the same frequency/PI pair
    as its running count increases.  For each station, keep the maximum running
    count reached during the chunk, then sum those maxima.  This scores a gain
    by total decoded PI observations rather than by unique station count.
    """
    max_count_by_station: Dict[Tuple[int, str], int] = {}

    for record in records:
        pi = normalize_pi(record.get("pi"))
        frequency_hz = record.get("frequency_hz")

        if not pi or pi == "0x0000" or frequency_hz is None:
            continue

        try:
            frequency_key = int(round(float(frequency_hz)))
            record_count = int(record.get("count", 0) or 0)
        except Exception:
            continue

        if record_count <= 0:
            continue

        key = (frequency_key, pi)
        if record_count > max_count_by_station.get(key, 0):
            max_count_by_station[key] = record_count

    return sum(max_count_by_station.values())


def count_unique_station_pi_codes(records: List[Dict]) -> int:
    """
    Score a calibration scan by unique validated station PI/frequency pairs.

    This is the primary gain-calibration score. A station is counted once per
    frequency/PI pair after it has reached the calibration min-count threshold
    and passed database validation.
    """
    stations: Set[Tuple[int, str]] = set()

    for record in records:
        pi = normalize_pi(record.get("pi"))
        frequency_hz = record.get("frequency_hz")

        if not pi or pi == "0x0000" or frequency_hz is None:
            continue

        try:
            frequency_key = int(round(float(frequency_hz)))
        except Exception:
            continue

        stations.add((frequency_key, pi))

    return len(stations)


# ---------------------------------------------------------------------------
# Frequency helpers
# ---------------------------------------------------------------------------

def parse_db_frequency_to_hz(value: str) -> Optional[int]:
    """
    Parse a database frequency field into Hz.

    The NRSC table usually stores FM frequencies like:
      100.3
      100.3 MHz
      100300 kHz

    If the number is less than 1000, assume MHz.
    """
    if value is None:
        return None

    s = str(value).strip().lower()

    if not s:
        return None

    s = s.replace(",", "")
    s = s.replace("mhz", "m")
    s = s.replace("khz", "k")
    s = s.replace("hz", "")

    m = re.search(r"(\d+(?:\.\d+)?)\s*([mk]?)", s)

    if not m:
        return None

    number = float(m.group(1))
    suffix = m.group(2)

    if suffix == "m":
        hz = number * 1_000_000
    elif suffix == "k":
        hz = number * 1_000
    else:
        # NRSC FM table values such as 100.3 are MHz.
        if number < 1000:
            hz = number * 1_000_000
        else:
            hz = number

    return int(round(hz))


def summarize_chunk_station_records(records: List[Dict]) -> List[Dict]:
    """
    Return one summary row per validated station in a chunk.

    The summary keeps the record with the highest running PI decode count for
    each frequency/PI pair.  This is used for console output after a chunk
    completes, rather than printing every individual decode while counts rise.
    """
    best_by_station: Dict[Tuple[int, str], Dict] = {}

    for record in records:
        pi = normalize_pi(record.get("pi"))
        frequency_hz = record.get("frequency_hz")

        if not pi or pi == "0x0000" or frequency_hz is None:
            continue

        try:
            frequency_key = int(round(float(frequency_hz)))
            record_count = int(record.get("count", 0))
        except Exception:
            continue

        key = (frequency_key, pi)
        existing = best_by_station.get(key)

        if existing is None or record_count > int(existing.get("count", 0)):
            best_by_station[key] = record

    return [
        best_by_station[key]
        for key in sorted(best_by_station.keys(), key=lambda item: (item[0], item[1]))
    ]


def print_chunk_station_summary(records: List[Dict]) -> None:
    """Print one console summary line per station after a chunk completes."""
    summary_records = summarize_chunk_station_records(records)

    if not summary_records:
        print("Chunk station summary: no validated stations decoded.", flush=True)
        return

    print("Chunk station summary:", flush=True)

    for record in summary_records:
        frequency_hz = record.get("frequency_hz")
        try:
            frequency_mhz = float(record.get("frequency_mhz", float(frequency_hz) / 1_000_000.0))
        except Exception:
            frequency_mhz = 0.0

        call_sign = record.get("call_sign") or "UNKNOWN"
        pi = normalize_pi(record.get("pi")) or "UNKNOWN"
        city = record.get("city") or ""
        state = record.get("state") or ""
        decimal_location = record.get("location") or ""
        decimal_lat, decimal_lon = split_decimal_location(decimal_location)
        count = record.get("count", 0)

        print(
            f"{frequency_mhz:.3f} MHz "
            f"{call_sign} "
            f"{pi} "
            f"{city} "
            f"{state} "
            f"{decimal_lat} "
            f"{decimal_lon} "
            f"count={count}",
            flush=True,
        )


def build_log_record_from_station_record(record: Dict) -> Dict:
    """
    Build the reduced JSONL log record from an internal station record.

    This is used only for cycle-complete summary logging, so count is the
    maximum decoded PI count for that station during the completed cycle.
    """
    time_unix_value = record.get("time_unix")
    log_date, log_time = format_log_date_time(time_unix_value)

    return {
        "date": log_date,
        "time": log_time,
        "call_sign": record.get("call_sign", ""),
        "frequency_mhz": record.get("frequency_mhz", ""),
        "pi_code": normalize_pi(record.get("pi")) or record.get("pi", ""),
        "city": record.get("city", ""),
        "state": record.get("state", ""),
        "location": record.get("location", ""),
        "count": record.get("count", 0),
        "cycle": record.get("cycle", ""),
        "time_unix": time_unix_value,
    }


def write_station_summary_log(
    output_path: str,
    records: List[Dict],
    cycle: int,
    chunk_index: Optional[int] = None,
) -> int:
    """
    Append one JSONL row per station after a chunk or single-center scan completes.

    For each frequency/PI station, only the record with the maximum accumulated
    decoded PI count from the provided records is written. This preserves the
    compact log layout while avoiding one log write per incremented decode.

    The JSONL file is created/touched even when no stations were decoded, so an
    otherwise successful run still leaves the requested log file behind.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    summary_records = summarize_chunk_station_records(records)

    # Touch/create the file even if there is nothing to append.
    with open(output_path, "a", buffering=1) as output_file:
        for record in summary_records:
            output_file.write(json.dumps(build_log_record_from_station_record(record)) + "\n")

    label = f"Cycle {cycle}"
    if chunk_index is not None:
        label += f", chunk {chunk_index}"

    if not summary_records:
        print(f"{label}: no validated stations to write to JSONL log.", file=sys.stderr)
        return 0

    print(
        f"{label}: wrote {len(summary_records)} station summary row(s) to {output_path}.",
        file=sys.stderr,
    )

    return len(summary_records)


# Backward-compatible name for any older call sites.
def write_cycle_station_summary_log(output_path: str, records: List[Dict], cycle: int) -> int:
    return write_station_summary_log(output_path=output_path, records=records, cycle=cycle)


def parse_freq(value: str) -> float:
    """
    Parse frequency strings like:
      100.3M, 100.3MHz, 100300k, 100300000
    Returns Hz as float.
    """
    s = value.strip().lower().replace("hz", "")

    multipliers = {
        "g": 1_000_000_000,
        "m": 1_000_000,
        "k": 1_000,
    }

    if s[-1:] in multipliers:
        return float(s[:-1]) * multipliers[s[-1]]

    return float(s)


def freq_for_rx_sdr(hz: float) -> str:
    return str(int(round(hz)))


def format_mhz(hz: float) -> str:
    return f"{hz / 1_000_000:.3f}"


def normalize_pi(pi) -> Optional[str]:
    """
    Normalize PI code to uppercase hex string like 0xD3C2.
    Return None for invalid/missing values.
    """
    if pi is None:
        return None

    pi_str = str(pi).strip()

    if not pi_str:
        return None

    if pi_str.lower().startswith("0x"):
        try:
            value = int(pi_str, 16)
            return f"0x{value:04X}"
        except ValueError:
            return None

    try:
        value = int(pi_str, 16)
        return f"0x{value:04X}"
    except ValueError:
        return pi_str.upper()


# ---------------------------------------------------------------------------
# NRSC PI-code database download / parse / CSV cache
# ---------------------------------------------------------------------------

class SimpleTableParser(HTMLParser):
    """
    Small stdlib HTML table parser.
    Captures all <tr>/<td>/<th> cell text into a list of tables.
    """

    def __init__(self):
        super().__init__()
        self.tables = []
        self.current_table = None
        self.current_row = None
        self.current_cell = None
        self.in_table = False
        self.in_row = False
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()

        if tag == "table":
            self.in_table = True
            self.current_table = []

        elif tag == "tr" and self.in_table:
            self.in_row = True
            self.current_row = []

        elif tag in ("td", "th") and self.in_table and self.in_row:
            self.in_cell = True
            self.current_cell = []

    def handle_data(self, data):
        if self.in_cell and self.current_cell is not None:
            self.current_cell.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()

        if tag in ("td", "th") and self.in_cell:
            text = " ".join("".join(self.current_cell).split())
            self.current_row.append(text)
            self.current_cell = None
            self.in_cell = False

        elif tag == "tr" and self.in_row:
            if self.current_row:
                self.current_table.append(self.current_row)
            self.current_row = None
            self.in_row = False

        elif tag == "table" and self.in_table:
            if self.current_table:
                self.tables.append(self.current_table)
            self.current_table = None
            self.in_table = False


def fetch_url_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "rds-multi-scan/1.0 Python urllib",
        },
    )

    with urllib.request.urlopen(req, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def parse_nrsc_last_updated(html: str) -> str:
    """
    Looks for text like:
      Last updated: Fri Apr 03 2026

    Returns YYYY-MM-DD if found, otherwise an empty string.
    """
    plain = re.sub(r"<[^>]+>", " ", html)
    plain = " ".join(plain.split())

    m = re.search(
        r"Last\s+updated:\s*([A-Za-z]{3}\s+[A-Za-z]{3}\s+\d{1,2}\s+\d{4})",
        plain,
        flags=re.IGNORECASE,
    )

    if not m:
        return ""

    raw = m.group(1)

    try:
        dt = datetime.strptime(raw, "%a %b %d %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return raw


def find_column(headers, patterns):
    for i, header in enumerate(headers):
        h = header.lower()
        for pattern in patterns:
            if re.search(pattern, h):
                return i
    return None


def extract_pi_rows_from_html(html: str):
    """
    Returns rows containing:
      pi, call_sign, frequency, city, state, location

    The NRSC table headers may change slightly, so this uses tolerant
    header matching.
    """
    parser = SimpleTableParser()
    parser.feed(html)

    best_rows = []

    for table in parser.tables:
        if len(table) < 2:
            continue

        headers = table[0]

        pi_idx = find_column(headers, [r"\bpi\b", r"pi\s*code"])
        call_idx = find_column(headers, [r"call", r"call\s*sign", r"callsign"])
        freq_idx = find_column(headers, [r"freq", r"frequency"])
        city_idx = find_column(headers, [r"city", r"community"])
        state_idx = find_column(headers, [r"state", r"\bst\b"])
        location_idx = find_column(headers, [r"location", r"city.*state", r"community.*state"])

        if pi_idx is None or call_idx is None:
            continue

        for row in table[1:]:
            if pi_idx >= len(row) or call_idx >= len(row):
                continue

            pi = normalize_pi(row[pi_idx])
            call = row[call_idx].strip().upper()

            if not pi or not call:
                continue

            if pi == "0x0000":
                continue

            frequency = row[freq_idx].strip() if freq_idx is not None and freq_idx < len(row) else ""
            city = row[city_idx].strip().upper() if city_idx is not None and city_idx < len(row) else ""
            state = row[state_idx].strip().upper() if state_idx is not None and state_idx < len(row) else ""
            location = row[location_idx].strip().upper() if location_idx is not None and location_idx < len(row) else ""

            if not location:
                if city and state:
                    location = f"{city}, {state}"
                elif city:
                    location = city
                elif state:
                    location = state

            best_rows.append(
                {
                    "pi": pi,
                    "call_sign": call,
                    "frequency": frequency,
                    "city": city,
                    "state": state,
                    "location": location,
                    "raw": row,
                }
            )

    if not best_rows:
        raise RuntimeError("Could not find a usable PI/call-sign table in downloaded HTML.")

    return best_rows


def read_local_pi_db_stamp(meta_path: str) -> str:
    if not os.path.exists(meta_path):
        return ""

    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return str(meta.get("source_last_updated", ""))
    except Exception:
        return ""


def write_pi_csv(csv_path: str, rows):
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "pi",
                "call_sign",
                "frequency",
                "city",
                "state",
                "location",
            ],
        )

        writer.writeheader()

        for row in rows:
            writer.writerow(
                {
                    "pi": row.get("pi", ""),
                    "call_sign": row.get("call_sign", ""),
                    "frequency": row.get("frequency", ""),
                    "city": row.get("city", ""),
                    "state": row.get("state", ""),
                    "location": row.get("location", ""),
                }
            )


def update_pi_database_if_needed(
    url: str,
    csv_path: str,
    html_path: str,
    meta_path: str,
    force: bool = False,
) -> str:
    """
    Downloads the NRSC page, checks its Last updated date against local metadata,
    and regenerates the CSV only when the web copy is newer.

    Returns the source_last_updated string.
    """
    print(f"Checking PI-code database: {url}", file=sys.stderr)

    html = fetch_url_text(url)
    remote_stamp = parse_nrsc_last_updated(html)

    if not remote_stamp:
        print(
            "Warning: could not parse remote Last updated timestamp; "
            "will update local PI CSV anyway.",
            file=sys.stderr,
        )

    local_stamp = read_local_pi_db_stamp(meta_path)

    should_update = force or not os.path.exists(csv_path)

    if remote_stamp and local_stamp:
        should_update = should_update or remote_stamp > local_stamp
    elif remote_stamp and not local_stamp:
        should_update = True
    elif not remote_stamp:
        should_update = True

    if not should_update:
        print(
            f"Local PI-code CSV is current. Last updated: {local_stamp}",
            file=sys.stderr,
        )
        return local_stamp

    print(
        f"Updating PI-code CSV. Remote Last updated: {remote_stamp or 'unknown'}",
        file=sys.stderr,
    )

    rows = extract_pi_rows_from_html(html)

    os.makedirs(os.path.dirname(os.path.abspath(html_path)), exist_ok=True)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    write_pi_csv(csv_path, rows)

    meta = {
        "source_url": url,
        "source_last_updated": remote_stamp,
        "downloaded_utc": datetime.now(timezone.utc).isoformat(),
        "row_count": len(rows),
    }

    os.makedirs(os.path.dirname(os.path.abspath(meta_path)), exist_ok=True)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True)

    print(
        f"Wrote {len(rows)} PI-code rows to {csv_path}",
        file=sys.stderr,
    )

    return remote_stamp


def load_pi_call_lookup(csv_path: str) -> Dict[str, List[Dict[str, str]]]:
    """
    Loads PI -> list of station metadata rows.

    This keeps individual rows so decoded PI + decoded frequency can be
    validated together against the database.
    """
    lookup: Dict[str, List[Dict[str, str]]] = defaultdict(list)

    if not os.path.exists(csv_path):
        print(
            f"Warning: PI-code CSV does not exist: {csv_path}",
            file=sys.stderr,
        )
        return {}

    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            pi = normalize_pi(row.get("pi"))

            if not pi:
                continue

            call_sign = str(row.get("call_sign", "")).strip().upper()
            frequency = str(row.get("frequency", "")).strip()
            city = str(row.get("city", "")).strip().upper()
            state = str(row.get("state", "")).strip().upper()
            location = str(row.get("location", "")).strip().upper()

            frequency_hz = parse_db_frequency_to_hz(frequency)

            if frequency_hz is None:
                continue

            lookup[pi].append(
                {
                    "pi": pi,
                    "call_sign": call_sign,
                    "frequency": frequency,
                    "frequency_hz": str(frequency_hz),
                    "city": city,
                    "state": state,
                    "location": location,
                }
            )

    print(
        f"Loaded {sum(len(v) for v in lookup.values())} PI-code station rows "
        f"for {len(lookup)} PI codes from {csv_path}",
        file=sys.stderr,
    )

    return dict(lookup)


# ---------------------------------------------------------------------------
# FM target / chunk generation
# ---------------------------------------------------------------------------

def generate_fm_targets(
    center_hz: float,
    bandwidth_hz: float,
    spacing_hz: float,
    grid_base_hz: float,
    manual_targets: Optional[str],
) -> List[float]:
    """
    Generate FM channel targets inside the capture bandwidth.

    Default uses a US FM-style 200 kHz grid:
      88.1, 88.3, ... 107.9 MHz
    """
    low = center_hz - bandwidth_hz / 2
    high = center_hz + bandwidth_hz / 2

    if manual_targets:
        targets = []

        for item in manual_targets.split(","):
            f = parse_freq(item)

            if low <= f <= high:
                targets.append(f)
            else:
                print(
                    f"Warning: target {format_mhz(f)} MHz is outside capture range; skipping.",
                    file=sys.stderr,
                )

        return sorted(set(targets))

    first_n = math.ceil((low - grid_base_hz) / spacing_hz)
    last_n = math.floor((high - grid_base_hz) / spacing_hz)

    targets = []

    for n in range(first_n, last_n + 1):
        f = grid_base_hz + n * spacing_hz

        if low <= f <= high:
            targets.append(f)

    return sorted(targets)


def generate_fm_band_channels(
    band_start_hz: float,
    band_end_hz: float,
    spacing_hz: float,
) -> List[float]:
    """
    Generate FM broadcast channels from band_start_hz to band_end_hz inclusive.
    Default is 88.1, ..., 107.9 MHz for US FM.
    """
    channels = []
    n = 0

    while True:
        f = band_start_hz + n * spacing_hz

        if f > band_end_hz + 1:
            break

        channels.append(f)
        n += 1

    return channels


def build_band_scan_chunks(
    band_start_hz: float,
    band_end_hz: float,
    bandwidth_hz: float,
    spacing_hz: float,
) -> List[dict]:
    """
    Split the full FM band into efficient chunks.

    Each chunk contains as many 200 kHz-spaced FM channels as fit inside the
    supplied SDR bandwidth. The center frequency is set to the midpoint of the
    first and last channel in that chunk.
    """
    channels = generate_fm_band_channels(
        band_start_hz=band_start_hz,
        band_end_hz=band_end_hz,
        spacing_hz=spacing_hz,
    )

    if not channels:
        raise ValueError("No FM channels generated for band scan.")

    max_channels_per_chunk = int(math.floor(bandwidth_hz / spacing_hz)) + 1

    if max_channels_per_chunk < 1:
        raise ValueError("Bandwidth is too small for the supplied FM channel spacing.")

    chunks = []

    for i in range(0, len(channels), max_channels_per_chunk):
        chunk_targets = channels[i:i + max_channels_per_chunk]

        low = chunk_targets[0]
        high = chunk_targets[-1]
        center = (low + high) / 2

        if (high - low) > bandwidth_hz:
            raise ValueError(
                f"Internal error: chunk span {(high - low) / 1e6:.3f} MHz "
                f"exceeds bandwidth {bandwidth_hz / 1e6:.3f} MHz."
            )

        chunks.append(
            {
                "center_hz": center,
                "targets": chunk_targets,
                "low_hz": low,
                "high_hz": high,
            }
        )

    return chunks


# ---------------------------------------------------------------------------
# DSP pipeline
# ---------------------------------------------------------------------------

def build_branch_pipeline(
    center_hz: float,
    target_hz: float,
    bandwidth_hz: float,
    channel_rate_hz: float,
    redsea_rate_hz: float,
) -> List[List[str]]:
    offset_hz = target_hz - center_hz

    if abs(offset_hz) > bandwidth_hz / 2:
        raise ValueError(
            f"Target {format_mhz(target_hz)} MHz is outside capture bandwidth."
        )

    # csdr shift_addition_cc expects normalized shift:
    # shift = -(target - center) / sample_rate
    shift = -offset_hz / bandwidth_hz

    # decim = max(1, int(round(bandwidth_hz / channel_rate_hz)))
    decim = max(1, int(round(bandwidth_hz / redsea_rate_hz)))
    post_decim_rate = bandwidth_hz / decim
    fractional_decim = post_decim_rate / redsea_rate_hz

    return [
        ["csdr", "shift_addition_cc", f"{shift:.12f}"],
        ["csdr", "fir_decimate_cc", str(decim), "0.02", "HAMMING"],
        ["csdr", "fmdemod_quadri_cf"],
        # ["csdr", "fractional_decimator_ff", f"{fractional_decim:.12f}"],
        ["csdr", "convert_f_i16"],
        ["redsea", "-r", f"{int(round(redsea_rate_hz))}"],
    ]


class CycleUploadBuffer:
    """
    Thread-safe buffer of validated PI/frequency records collected during one
    complete band-scan cycle.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.records: List[Dict] = []

    def add(self, record: Dict):
        with self.lock:
            self.records.append(dict(record))

    def snapshot(self) -> List[Dict]:
        with self.lock:
            return [dict(record) for record in self.records]

    def clear(self):
        with self.lock:
            self.records.clear()


class SharedPiState:
    def __init__(
            self,
            output_file,
            min_count: int,
            echo: bool,
            pi_call_lookup: Dict[str, List[Dict[str, str]]],
            cycle: int,
            chunk_index: int,
            center_hz: float,
            freq_match_tolerance_hz: float,
            upload_buffer: Optional[CycleUploadBuffer] = None,
    ):
        self.output_file = output_file
        self.min_count = min_count
        self.echo = echo
        self.pi_call_lookup = pi_call_lookup
        self.cycle = cycle
        self.chunk_index = chunk_index
        self.center_hz = center_hz
        self.freq_match_tolerance_hz = freq_match_tolerance_hz
        self.upload_buffer = upload_buffer
        self.lock = threading.Lock()

        # Keyed by: (target_hz_int, pi)
        self.pi_counts: Dict[Tuple[int, str], int] = defaultdict(int)

        # Do not suppress repeated decodes.  Once a station reaches min_count,
        # every later validated PI decode for that station in the chunk is logged
        # with the current running count.
        self.emitted: Set[Tuple[int, str]] = set()

    def find_matching_station(self, target_hz_int: int, pi: str) -> Optional[Dict[str, str]]:
        """
        Return the database station row only if both PI and frequency match.

        If no row has the same PI and same licensed frequency, return None.
        """
        station_rows = self.pi_call_lookup.get(pi, [])

        for station in station_rows:
            try:
                db_frequency_hz = int(station.get("frequency_hz", "0"))
            except ValueError:
                continue

            if abs(target_hz_int - db_frequency_hz) <= self.freq_match_tolerance_hz:
                return station

        return None

    def observe_pi(self, target_hz: float, pi: str):
        target_hz_int = int(round(target_hz))
        key = (target_hz_int, pi)

        with self.lock:
            if pi == "0x0000":
                return

            self.pi_counts[key] += 1
            count = self.pi_counts[key]

            if count < self.min_count:
                return

            station = self.find_matching_station(target_hz_int, pi)

            # Critical validation:
            # If decoded PI and decoded frequency do not both match the database,
            # do not write to screen and do not write to file.
            if station is None:
                return

            call_sign = station.get("call_sign", "")
            licensed_frequency = station.get("frequency", "")
            licensed_frequency_hz = station.get("frequency_hz", "")
            city = station.get("city", "")
            state = station.get("state", "")
            location = station.get("location", "")
            decimal_location = convert_location_dms_to_decimal(location)
            decimal_lat, decimal_lon = split_decimal_location(decimal_location)
            time_unix_value = time.time()
            log_date, log_time = format_log_date_time(time_unix_value)

            # Full internal record is retained for RabbitEars upload and any
            # non-log processing that still needs frequency_hz or validation metadata.
            record = {
                "time_unix": time_unix_value,
                "cycle": self.cycle,
                "chunk_index": self.chunk_index,
                "center_frequency_hz": int(round(self.center_hz)),
                "center_frequency_mhz": round(self.center_hz / 1_000_000, 6),
                "frequency_hz": target_hz_int,
                "frequency_mhz": round(target_hz / 1_000_000, 6),
                "pi": pi,
                "count": count,
                "validated_against_database": True,
                "freq_match_tolerance_hz": self.freq_match_tolerance_hz,
                "call_sign": call_sign,
                "licensed_frequency": licensed_frequency,
                "licensed_frequency_hz": licensed_frequency_hz,
                "city": city,
                "state": state,
                "location": decimal_location,
            }

            # Do not write JSONL here. Local logging is now summarized once
            # after a completed scan cycle, using the maximum count seen for
            # each station. Keep every validated decode in the capture buffer
            # so the cycle summary can choose the max-count record.

            if self.upload_buffer is not None:
                self.upload_buffer.add(record)

            # Console output is intentionally deferred until the chunk has
            # completed, so the operator sees one summary line per station
            # with the maximum PI decode count for that chunk.


class RedseaBranch:
    def __init__(
        self,
        target_hz: float,
        pipeline: List[List[str]],
        shared_state: SharedPiState,
        show_command: bool,
    ):
        self.target_hz = target_hz
        self.pipeline = pipeline
        self.shared_state = shared_state
        self.show_command = show_command

        self.processes: List[subprocess.Popen] = []
        self.reader_thread: Optional[threading.Thread] = None
        self.first_stdin = None
        self.redsea_stdout = None
        self.dead = False

    def start(self):
        if self.show_command:
            print(f"\nBranch for {format_mhz(self.target_hz)} MHz:", file=sys.stderr)
            for cmd in self.pipeline:
                print("  " + " ".join(cmd), file=sys.stderr)

        prev_stdout = None

        for i, cmd in enumerate(self.pipeline):
            stdin = prev_stdout if prev_stdout is not None else subprocess.PIPE
            stdout = subprocess.PIPE

            p = subprocess.Popen(
                cmd,
                stdin=stdin,
                stdout=stdout,
                # stderr=sys.stderr,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                start_new_session=True,
            )

            if prev_stdout is not None:
                prev_stdout.close()

            if i == 0:
                self.first_stdin = p.stdin

            prev_stdout = p.stdout
            self.processes.append(p)

        self.redsea_stdout = self.processes[-1].stdout

        self.reader_thread = threading.Thread(
            target=self._read_redsea_output,
            daemon=True,
        )
        self.reader_thread.start()

    def _read_redsea_output(self):
        assert self.redsea_stdout is not None

        for raw_line in self.redsea_stdout:
            line = raw_line.decode("utf-8", errors="replace").strip()

            if not line:
                continue

            try:
                redsea_msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            pi = normalize_pi(redsea_msg.get("pi"))

            if not pi:
                continue

            if pi == "0x0000":
                continue

            self.shared_state.observe_pi(self.target_hz, pi)

    def write(self, data: bytes):
        if self.dead or self.first_stdin is None:
            return

        try:
            self.first_stdin.write(data)
            self.first_stdin.flush()
        except BrokenPipeError:
            self.dead = True
        except OSError:
            self.dead = True

    def close_input(self):
        if self.first_stdin:
            try:
                self.first_stdin.close()
            except Exception:
                pass

    def stop(self):
        self.close_input()

        for p in self.processes:
            terminate_process_tree(p, name=f"branch {format_mhz(self.target_hz)} MHz", timeout=2.0)

        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=1)


# ---------------------------------------------------------------------------
# Scan execution
# ---------------------------------------------------------------------------

def run_scan_chunk(
    args,
    center_hz: float,
    bandwidth_hz: float,
    targets: List[float],
    channel_rate_hz: float,
    redsea_rate_hz: float,
    pi_call_lookup: Dict[str, List[Dict[str, str]]],
    cycle: int,
    chunk_index: int,
    upload_buffer: Optional[CycleUploadBuffer] = None,
    gain_override: Optional[int] = None,
    duration_override: Optional[float] = None,
    min_count_override: Optional[int] = None,
    suppress_echo: bool = False,
    write_output: bool = True,
) -> Tuple[int, List[Dict]]:
    """
    Run one rx_sdr capture centered at center_hz for args.duration seconds,
    scanning the provided target channels simultaneously.
    """
    effective_duration = duration_override if duration_override is not None else args.duration
    effective_min_count = min_count_override if min_count_override is not None else args.min_pi_count
    local_capture_buffer = CycleUploadBuffer()

    print(
        f"\nScanning chunk center={format_mhz(center_hz)} MHz "
        f"range={format_mhz(targets[0])}–{format_mhz(targets[-1])} MHz "
        f"channels={len(targets)}",
        file=sys.stderr,
    )

    # for f in targets:
    #     print(f"  {format_mhz(f)} MHz", file=sys.stderr)

    rx_hardware_args = build_rx_sdr_hardware_args_for_gain(args, gain_override)

    if gain_override is not None:
        print(f"Using rx_sdr gain {gain_override} for this chunk.", file=sys.stderr)

    rx_cmd = [
        "rx_sdr",
        "-f", freq_for_rx_sdr(center_hz),
        "-s", str(int(round(bandwidth_hz))),
        "-F", "CF32",
        *rx_hardware_args,
        "-",
    ]

    if args.show_command:
        print("\nrx_sdr command:", file=sys.stderr)
        print("  " + " ".join(rx_cmd), file=sys.stderr)

    branches: List[RedseaBranch] = []
    rx_proc = None
    return_code = 0

    try:
        output_path = args.output if write_output else os.devnull
        with open(output_path, "a", buffering=1) as output_file:
            shared_state = SharedPiState(
                output_file=output_file,
                min_count=effective_min_count,
                echo=(not args.no_echo) and (not suppress_echo),
                pi_call_lookup=pi_call_lookup,
                cycle=cycle,
                chunk_index=chunk_index,
                center_hz=center_hz,
                freq_match_tolerance_hz=args.freq_match_tolerance,
                upload_buffer=local_capture_buffer,
            )

            for target_hz in targets:
                branch_pipeline = build_branch_pipeline(
                    center_hz=center_hz,
                    target_hz=target_hz,
                    bandwidth_hz=bandwidth_hz,
                    channel_rate_hz=channel_rate_hz,
                    redsea_rate_hz=redsea_rate_hz,
                )

                branch = RedseaBranch(
                    target_hz=target_hz,
                    pipeline=branch_pipeline,
                    shared_state=shared_state,
                    show_command=args.show_command,
                )

                branch.start()
                branches.append(branch)

            # print(
            #     f"Starting rx_sdr at center {format_mhz(center_hz)} MHz",
            #     file=sys.stderr,
            # )
            #
            # print(
            #     "rx_sdr command: " + " ".join(rx_cmd),
            #     file=sys.stderr,
            # )

            rx_proc = start_rx_sdr_with_retries(
                rx_cmd=rx_cmd,
                center_hz=center_hz,
                retries=args.rx_start_retries,
                retry_delay=args.rx_retry_delay,
            )

            assert rx_proc.stdout is not None

            end_time = time.monotonic() + effective_duration

            while time.monotonic() < end_time:
                chunk = rx_proc.stdout.read(args.chunk_size)

                if not chunk:
                    break

                for branch in branches:
                    branch.write(chunk)

            print(
                f"Chunk complete: center={format_mhz(center_hz)} MHz. "
                "Shutting down pipelines...",
                file=sys.stderr,
            )

    except KeyboardInterrupt:
        print("\nInterrupted. Shutting down pipelines...", file=sys.stderr)
        return_code = 130

    finally:
        print(
            f"Stopping rx_sdr for center {format_mhz(center_hz)} MHz...",
            file=sys.stderr,
        )

        terminate_process_tree(
            rx_proc,
            name=f"rx_sdr center {format_mhz(center_hz)} MHz",
            timeout=3.0,
        )

        for branch in branches:
            branch.close_input()

        # Give redsea a brief chance to flush decoded output after stdin closes.

        time.sleep(0.5)

        for branch in branches:
            branch.stop()

        if args.device_release_delay > 0:
            print(
                f"Waiting {args.device_release_delay:.1f}s for SDR device release...",
                file=sys.stderr,
            )

            time.sleep(args.device_release_delay)

    chunk_records = local_capture_buffer.snapshot()

    if upload_buffer is not None:
        for record in chunk_records:
            upload_buffer.add(record)

    if return_code == 0 and (not args.no_echo) and (not suppress_echo):
        print_chunk_station_summary(chunk_records)

    return return_code, chunk_records


# ---------------------------------------------------------------------------
# Gain calibration
# ---------------------------------------------------------------------------


def calibrate_chunk_gain(
    args,
    chunk: dict,
    bandwidth_hz: float,
    channel_rate_hz: float,
    redsea_rate_hz: float,
    pi_call_lookup: Dict[str, List[Dict[str, str]]],
    chunk_index: int,
) -> int:
    """
    Try all gain values and pick the best calibration gain.

    Primary score: number of unique validated station PI/frequency pairs.
    Tie-breaker: total raw validated PI decode count across those stations.
    """
    gain_values = get_gain_values_for_profile(args)
    calibration_duration = (
        args.gain_calibration_duration
        if args.gain_calibration_duration is not None
        else args.duration
    )
    calibration_min_count = (
        args.gain_calibration_min_count
        if args.gain_calibration_min_count is not None
        else args.min_pi_count
    )

    print(
        f"\nCalibrating gain for chunk {chunk_index}: "
        f"{format_mhz(chunk['low_hz'])}–{format_mhz(chunk['high_hz'])} MHz, "
        f"center={format_mhz(chunk['center_hz'])} MHz",
        file=sys.stderr,
    )

    best_gain = gain_values[0]
    best_unique_count = -1
    best_raw_decode_count = -1

    for order, gain in enumerate(gain_values):
        print(
            f"  Testing gain {gain} for {calibration_duration:.1f}s...",
            file=sys.stderr,
        )

        rc, records = run_scan_chunk(
            args=args,
            center_hz=chunk["center_hz"],
            bandwidth_hz=bandwidth_hz,
            targets=chunk["targets"],
            channel_rate_hz=channel_rate_hz,
            redsea_rate_hz=redsea_rate_hz,
            pi_call_lookup=pi_call_lookup,
            cycle=0,
            chunk_index=chunk_index,
            upload_buffer=None,
            gain_override=gain,
            duration_override=calibration_duration,
            min_count_override=calibration_min_count,
            suppress_echo=True,
            write_output=False,
        )

        if rc == 130:
            raise KeyboardInterrupt

        unique_count = count_unique_station_pi_codes(records)
        raw_decode_count = count_total_raw_station_decodes(records)

        print(
            f"  Gain {gain}: {unique_count} unique validated PI/frequency pair(s), "
            f"{raw_decode_count} total raw validated PI decode(s)",
            file=sys.stderr,
        )

        if (
            unique_count > best_unique_count
            or (
                unique_count == best_unique_count
                and raw_decode_count > best_raw_decode_count
            )
        ):
            best_unique_count = unique_count
            best_raw_decode_count = raw_decode_count
            best_gain = gain

    print(
        f"Selected gain {best_gain} for chunk {chunk_index} "
        f"with {best_unique_count} unique validated PI/frequency pair(s) "
        f"and {best_raw_decode_count} total raw validated PI decode(s).",
        file=sys.stderr,
    )

    return best_gain


def calibrate_all_chunk_gains(
    args,
    chunks: List[dict],
    bandwidth_hz: float,
    channel_rate_hz: float,
    redsea_rate_hz: float,
    pi_call_lookup: Dict[str, List[Dict[str, str]]],
) -> Dict[int, int]:
    """Calibrate and return chunk_index -> best gain."""
    best_gains: Dict[int, int] = {}

    print("\nStarting automatic per-chunk gain calibration.", file=sys.stderr)

    for chunk_index, chunk in enumerate(chunks, start=1):
        best_gains[chunk_index] = calibrate_chunk_gain(
            args=args,
            chunk=chunk,
            bandwidth_hz=bandwidth_hz,
            channel_rate_hz=channel_rate_hz,
            redsea_rate_hz=redsea_rate_hz,
            pi_call_lookup=pi_call_lookup,
            chunk_index=chunk_index,
        )

    print("\nGain calibration complete:", file=sys.stderr)

    for chunk_index in sorted(best_gains):
        print(
            f"  Chunk {chunk_index}: gain {best_gains[chunk_index]}",
            file=sys.stderr,
        )

    return best_gains


# ---------------------------------------------------------------------------
# Gain calibration cache
# ---------------------------------------------------------------------------

GAIN_CALIBRATION_CACHE_VERSION = 3
GAIN_CALIBRATION_SCORE_METHOD = "unique_station_count_then_raw_decode_tiebreak_v1"


def gain_calibration_cache_key(
    args,
    bandwidth_hz: float,
    band_start_hz: float,
    band_end_hz: float,
    spacing_hz: float,
) -> str:
    """
    Build a stable cache key for saved per-chunk gain calibration.

    The primary requested dimensions are SDR vendor and bandwidth. The band
    limits and spacing are included as safety dimensions because they determine
    the actual chunk boundaries.
    """
    rx_sdr_name = args.rx_sdr.strip().lower() if getattr(args, "rx_sdr", None) else "default"

    return "|".join(
        [
            f"rx_sdr={rx_sdr_name}",
            f"bandwidth_hz={int(round(bandwidth_hz))}",
            f"band_start_hz={int(round(band_start_hz))}",
            f"band_end_hz={int(round(band_end_hz))}",
            f"spacing_hz={int(round(spacing_hz))}",
            f"score_method={GAIN_CALIBRATION_SCORE_METHOD}",
        ]
    )


def chunk_cache_signature(chunks: List[dict]) -> List[Dict]:
    """Return the chunk layout fields needed to validate cached gains."""
    signature = []

    for idx, chunk in enumerate(chunks, start=1):
        signature.append(
            {
                "chunk_index": idx,
                "center_hz": int(round(chunk["center_hz"])),
                "low_hz": int(round(chunk["low_hz"])),
                "high_hz": int(round(chunk["high_hz"])),
                "target_count": len(chunk.get("targets", [])),
            }
        )

    return signature


def load_gain_calibration_cache(cache_path: str) -> Dict:
    """Load the gain calibration cache file, returning an empty cache on absence."""
    if not cache_path:
        return {"version": GAIN_CALIBRATION_CACHE_VERSION, "entries": {}}

    if not os.path.exists(cache_path):
        return {"version": GAIN_CALIBRATION_CACHE_VERSION, "entries": {}}

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception as e:
        print(
            f"Warning: could not read gain calibration cache {cache_path}: {e}",
            file=sys.stderr,
        )
        return {"version": GAIN_CALIBRATION_CACHE_VERSION, "entries": {}}

    if not isinstance(cache, dict):
        return {"version": GAIN_CALIBRATION_CACHE_VERSION, "entries": {}}

    if "entries" not in cache or not isinstance(cache.get("entries"), dict):
        cache["entries"] = {}

    cache["version"] = cache.get("version", GAIN_CALIBRATION_CACHE_VERSION)

    return cache


def save_gain_calibration_cache(cache_path: str, cache: Dict) -> bool:
    """Atomically save the gain calibration cache file."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
        tmp_path = cache_path + ".tmp"

        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, sort_keys=True)
            f.write("\n")

        os.replace(tmp_path, cache_path)
        return True

    except Exception as e:
        print(
            f"Warning: could not save gain calibration cache {cache_path}: {e}",
            file=sys.stderr,
        )
        return False


def read_cached_chunk_gains(
    args,
    chunks: List[dict],
    bandwidth_hz: float,
    band_start_hz: float,
    band_end_hz: float,
    spacing_hz: float,
) -> Optional[Dict[int, int]]:
    """Return cached chunk gains if a valid cache entry exists; otherwise None."""
    cache_path = args.gain_calibration_file
    cache = load_gain_calibration_cache(cache_path)
    key = gain_calibration_cache_key(args, bandwidth_hz, band_start_hz, band_end_hz, spacing_hz)
    entry = cache.get("entries", {}).get(key)

    if not entry:
        print(f"No saved gain calibration found for {key}.", file=sys.stderr)
        return None

    expected_signature = chunk_cache_signature(chunks)
    if entry.get("chunk_signature") != expected_signature:
        print(
            "Saved gain calibration exists but chunk layout no longer matches; "
            "a new calibration is required.",
            file=sys.stderr,
        )
        return None

    raw_gains = entry.get("chunk_gains", {})
    gains: Dict[int, int] = {}

    try:
        for idx in range(1, len(chunks) + 1):
            gains[idx] = int(raw_gains[str(idx)])
    except Exception as e:
        print(
            f"Saved gain calibration is incomplete or invalid: {e}; recalibration is required.",
            file=sys.stderr,
        )
        return None

    print(
        f"Loaded saved gain calibration from {cache_path} for {key}.",
        file=sys.stderr,
    )
    for idx in sorted(gains):
        print(f"  Chunk {idx}: gain {gains[idx]}", file=sys.stderr)

    return gains


def write_cached_chunk_gains(
    args,
    chunks: List[dict],
    bandwidth_hz: float,
    band_start_hz: float,
    band_end_hz: float,
    spacing_hz: float,
    chunk_best_gains: Dict[int, int],
) -> None:
    """Store calibrated chunk gains under the SDR/bandwidth-specific cache key."""
    cache_path = args.gain_calibration_file
    cache = load_gain_calibration_cache(cache_path)
    key = gain_calibration_cache_key(args, bandwidth_hz, band_start_hz, band_end_hz, spacing_hz)

    cache.setdefault("entries", {})[key] = {
        "rx_sdr": args.rx_sdr.strip().lower() if args.rx_sdr else "default",
        "bandwidth_hz": int(round(bandwidth_hz)),
        "band_start_hz": int(round(band_start_hz)),
        "band_end_hz": int(round(band_end_hz)),
        "spacing_hz": int(round(spacing_hz)),
        "score_method": GAIN_CALIBRATION_SCORE_METHOD,
        "chunk_signature": chunk_cache_signature(chunks),
        "chunk_gains": {str(k): int(v) for k, v in sorted(chunk_best_gains.items())},
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }

    cache["version"] = GAIN_CALIBRATION_CACHE_VERSION

    if save_gain_calibration_cache(cache_path, cache):
        print(
            f"Saved gain calibration to {cache_path} for {key}.",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Scan FM broadcast channels using rx_sdr, csdr, and redsea. "
            "Can scan one center frequency or automatically scan the full FM band "
            "in bandwidth-sized chunks."
        )
    )

    parser.add_argument(
        "--center",
        help=(
            "Optional SDR center frequency, e.g. 100M. "
            "If omitted, the full FM band is scanned in bandwidth-sized chunks."
        ),
    )

    parser.add_argument(
        "--bandwidth",
        required=True,
        help="rx_sdr sample rate / capture bandwidth, e.g. 5M",
    )

    parser.add_argument(
        "--duration",
        type=float,
        required=True,
        help="Number of seconds to run rx_sdr per center-frequency chunk.",
    )

    parser.add_argument(
        "--output",
        required=True,
        help="Output JSONL file to append confirmed frequency/PI records to.",
    )

    parser.add_argument(
        "--min-pi-count",
        type=int,
        default=3,
        help="Minimum number of times a PI code must be seen on a frequency before output. Default: 3",
    )

    parser.add_argument(
        "--targets",
        help=(
            "Optional comma-separated FM target list. "
            "Example: --targets 99.5M,100.3M,101.1M. "
            "Only valid when --center is supplied."
        ),
    )

    parser.add_argument(
        "--spacing",
        default="200k",
        help="FM channel spacing. Default: 200k",
    )

    parser.add_argument(
        "--grid-base",
        default="88.1M",
        help="FM grid base frequency for single-center auto target generation. Default: 88.1M",
    )

    parser.add_argument(
        "--band-start",
        default="88.1M",
        help="Bottom FM broadcast channel for automatic band scan. Default: 88.1M",
    )

    parser.add_argument(
        "--band-end",
        default="107.9M",
        help="Top FM broadcast channel for automatic band scan. Default: 107.9M",
    )

    parser.add_argument(
        "--cycles",
        type=int,
        default=0,
        help=(
            "Number of complete band-scan cycles to run when --center is omitted. "
            "Default: 0, meaning loop forever."
        ),
    )

    parser.add_argument(
        "--channel-rate",
        default="500k",
        help="Intermediate single-channel complex rate after decimation. Default: 500k",
    )

    parser.add_argument(
        "--redsea-rate",
        default="166666",
        help="MPX sample rate sent to redsea. Default: 171k",
    )

    parser.add_argument(
        "--chunk-size",
        type=int,
        default=65536,
        help="Number of bytes read from rx_sdr per loop. Default: 262144",
    )

    parser.add_argument(
        "--no-echo",
        action="store_true",
        help="Do not print confirmed PI codes to terminal; only append JSONL output.",
    )

    parser.add_argument(
        "--show-command",
        action="store_true",
        help="Print generated rx_sdr and csdr/redsea pipelines.",
    )

    parser.add_argument(
        "--rx-sdr",
        choices=sorted(RX_SDR_PROFILES.keys()),
        help=(
            "SDR hardware profile to use for rx_sdr device selection. "
            "Example: --rx-sdr sdrplay expands to -d driver=sdrplay."
        ),
    )

    parser.add_argument(
        "--rx-gain",
        type=int,
        help=(
            "Fixed SDR gain value using the selected --rx-sdr profile. "
            "For --rx-sdr sdrplay this expands to -g RFGR=<value>, valid range 0–6. "
            "If omitted, full-band mode can calibrate the best gain per chunk."
        ),
    )

    parser.add_argument(
        "--skip-gain-calibration",
        action="store_true",
        help=(
            "Skip automatic per-chunk gain calibration when --rx-gain is omitted. "
            "If omitted and --rx-gain is not set, the app calibrates gain per chunk."
        ),
    )

    parser.add_argument(
        "--gain-calibration-duration",
        type=float,
        help=(
            "Seconds to scan each gain during automatic gain calibration. "
            "Default: same as --duration."
        ),
    )

    parser.add_argument(
        "--gain-calibration-min-count",
        type=int,
        help=(
            "Minimum PI count required before a PI/frequency pair is counted during gain calibration. "
            "The selected gain is scored first by unique validated PI/frequency count, then by total raw validated PI decodes as a tie-breaker. "
            "Default: same as --min-pi-count."
        ),
    )

    parser.add_argument(
        "--force-gain-calibration",
        action="store_true",
        help=(
            "Force automatic per-chunk gain calibration to rerun at startup and "
            "overwrite the saved calibration entry for this SDR/bandwidth/chunk layout."
        ),
    )

    parser.add_argument(
        "--gain-calibration-file",
        default="rds_gain_calibration.json",
        help=(
            "JSON file used to save and reload automatic per-chunk gain calibration data. "
            "Default: rds_gain_calibration.json"
        ),
    )

    parser.add_argument(
        "--rx-arg",
        action="append",
        default=[],
        help=(
            "Advanced extra argument to pass directly to rx_sdr. "
            "Use --rx-sdr for device selection and --rx-gain for gain. "
            "Use this only for additional rx_sdr options not modeled by the app."
        ),
    )

    parser.add_argument(
        "--pi-url",
        default=PI_CODES_URL,
        help=f"NRSC PI-code database URL. Default: {PI_CODES_URL}",
    )

    parser.add_argument(
        "--pi-csv",
        default="pi_codes_allocated.csv",
        help="Local PI-code CSV file used for PI-to-station lookup. Default: pi_codes_allocated.csv",
    )

    parser.add_argument(
        "--pi-html",
        default="pi_codes_allocated.html",
        help="Cached downloaded NRSC PI-code HTML file. Default: pi_codes_allocated.html",
    )

    parser.add_argument(
        "--pi-meta",
        default="pi_codes_allocated.meta.json",
        help="Local metadata file storing source Last updated timestamp. Default: pi_codes_allocated.meta.json",
    )

    parser.add_argument(
        "--skip-pi-update",
        action="store_true",
        help="Do not check/download the online PI-code database; use existing local CSV.",
    )

    parser.add_argument(
        "--force-pi-update",
        action="store_true",
        help="Force download and CSV regeneration of the PI-code database.",
    )

    parser.add_argument(
        "--device-release-delay",
        type=float,
        default=2.0,
        help=(
            "Seconds to wait after each chunk before starting the next rx_sdr process. "
            "Useful when the SDR device needs time to release. Default: 2.0"
        ),
    )

    parser.add_argument(
        "--rx-start-retries",
        type=int,
        default=3,
        help="Number of times to retry starting rx_sdr if it exits immediately. Default: 3",
    )

    parser.add_argument(
        "--rx-retry-delay",
        type=float,
        default=2.0,
        help="Seconds to wait between rx_sdr start retries. Default: 2.0",
    )

    parser.add_argument(
        "--freq-match-tolerance",
        type=float,
        default=1000.0,
        help=(
            "Allowed Hz difference between decoded FM channel and database frequency. "
            "Default: 1000 Hz."
        ),
    )

    parser.add_argument(
        "--tuner-key",
        type=int,
        help=(
            "RabbitEars FM Live Band Scan tuner key. "
            "If omitted, upload is disabled."
        ),
    )

    parser.add_argument(
        "--upload-timeout",
        type=float,
        default=20.0,
        help="RabbitEars upload timeout in seconds. Default: 20.",
    )

    parser.add_argument(
        "--upload-retries",
        type=int,
        default=3,
        help="RabbitEars upload retry count. Default: 3.",
    )

    parser.add_argument(
        "--upload-retry-delay",
        type=float,
        default=5.0,
        help="Seconds to wait between RabbitEars upload retries. Default: 5.",
    )

    parser.add_argument(
        "--upload-debug",
        action="store_true",
        help="Print each RabbitEars single-record JSON payload before compression.",
    )

    parser.add_argument(
        "--upload-per-record-delay",
        type=float,
        default=0.5,
        help="Delay in seconds between individual RabbitEars record uploads. Default: 0.5.",
    )

    args = parser.parse_args()

    if args.duration <= 0:
        print("Error: --duration must be greater than zero.", file=sys.stderr)
        return 2

    if args.min_pi_count <= 0:
        print("Error: --min-pi-count must be greater than zero.", file=sys.stderr)
        return 2

    if args.cycles < 0:
        print("Error: --cycles must be zero or greater.", file=sys.stderr)
        return 2

    if args.gain_calibration_duration is not None and args.gain_calibration_duration <= 0:
        print("Error: --gain-calibration-duration must be greater than zero.", file=sys.stderr)
        return 2

    if args.gain_calibration_min_count is not None and args.gain_calibration_min_count <= 0:
        print("Error: --gain-calibration-min-count must be greater than zero.", file=sys.stderr)
        return 2

    if args.force_gain_calibration and args.skip_gain_calibration:
        print("Error: --force-gain-calibration cannot be used with --skip-gain-calibration.", file=sys.stderr)
        return 2

    try:
        # Validate fixed gain/profile early. For automatic calibration this also
        # confirms the profile exists before long-running work begins.
        build_rx_sdr_hardware_args_for_gain(args, args.rx_gain)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    bandwidth_hz = parse_freq(args.bandwidth)
    spacing_hz = parse_freq(args.spacing)
    channel_rate_hz = parse_freq(args.channel_rate)
    redsea_rate_hz = parse_freq(args.redsea_rate)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    if not args.skip_pi_update:
        try:
            update_pi_database_if_needed(
                url=args.pi_url,
                csv_path=args.pi_csv,
                html_path=args.pi_html,
                meta_path=args.pi_meta,
                force=args.force_pi_update,
            )
        except Exception as e:
            print(
                f"Warning: PI-code database update failed: {e}",
                file=sys.stderr,
            )
            print(
                "Continuing with existing local PI CSV if available.",
                file=sys.stderr,
            )

    pi_call_lookup = load_pi_call_lookup(args.pi_csv)

    # -----------------------------------------------------------------------
    # Single-center mode
    # -----------------------------------------------------------------------
    if args.center:
        center_hz = parse_freq(args.center)

        targets = generate_fm_targets(
            center_hz=center_hz,
            bandwidth_hz=bandwidth_hz,
            spacing_hz=spacing_hz,
            grid_base_hz=parse_freq(args.grid_base),
            manual_targets=args.targets,
        )

        if not targets:
            print("Error: no FM targets found inside capture bandwidth.", file=sys.stderr)
            return 2

        print(
            f"Single-center mode: center={format_mhz(center_hz)} MHz, "
            f"duration={args.duration:.1f} seconds",
            file=sys.stderr,
        )

        upload_buffer = CycleUploadBuffer()

        rc, chunk_records = run_scan_chunk(
            args=args,
            center_hz=center_hz,
            bandwidth_hz=bandwidth_hz,
            targets=targets,
            channel_rate_hz=channel_rate_hz,
            redsea_rate_hz=redsea_rate_hz,
            pi_call_lookup=pi_call_lookup,
            cycle=1,
            chunk_index=1,
            upload_buffer=upload_buffer,
            gain_override=args.rx_gain,
        )

        if rc == 0:
            write_station_summary_log(
                output_path=args.output,
                records=chunk_records,
                cycle=1,
                chunk_index=1,
            )

        if rc == 0 and args.tuner_key and upload_buffer is not None:
            upload_bandscan_to_rabbitears(
                tuner_key=args.tuner_key,
                records=upload_buffer.snapshot(),
                timeout=args.upload_timeout,
                retries=args.upload_retries,
                retry_delay=args.upload_retry_delay,
            )

        return rc


    # -----------------------------------------------------------------------
    # Automatic full-band scan mode
    # -----------------------------------------------------------------------
    if args.targets:
        print(
            "Error: --targets can only be used with --center. "
            "When --center is omitted, the program scans the full broadcast band.",
            file=sys.stderr,
        )
        return 2

    band_start_hz = parse_freq(args.band_start)
    band_end_hz = parse_freq(args.band_end)

    if band_end_hz <= band_start_hz:
        print("Error: --band-end must be greater than --band-start.", file=sys.stderr)
        return 2

    try:
        chunks = build_band_scan_chunks(
            band_start_hz=band_start_hz,
            band_end_hz=band_end_hz,
            bandwidth_hz=bandwidth_hz,
            spacing_hz=spacing_hz,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    print("\nAutomatic full-band scan mode enabled.", file=sys.stderr)
    print(
        f"Band: {format_mhz(band_start_hz)}–{format_mhz(band_end_hz)} MHz",
        file=sys.stderr,
    )
    print(f"Bandwidth per chunk: {bandwidth_hz / 1e6:.3f} MHz", file=sys.stderr)
    print(f"Duration per chunk: {args.duration:.1f} seconds", file=sys.stderr)
    print(f"Chunks per full pass: {len(chunks)}", file=sys.stderr)

    for idx, chunk in enumerate(chunks, start=1):
        print(
            f"  Chunk {idx}: "
            f"{format_mhz(chunk['low_hz'])}–{format_mhz(chunk['high_hz'])} MHz, "
            f"center {format_mhz(chunk['center_hz'])} MHz, "
            f"{len(chunk['targets'])} channels",
            file=sys.stderr,
        )

    chunk_best_gains: Dict[int, Optional[int]] = {}

    if args.rx_gain is not None:
        for idx in range(1, len(chunks) + 1):
            chunk_best_gains[idx] = args.rx_gain

    elif args.rx_sdr and not args.skip_gain_calibration:
        cached_gains = None

        if not args.force_gain_calibration:
            cached_gains = read_cached_chunk_gains(
                args=args,
                chunks=chunks,
                bandwidth_hz=bandwidth_hz,
                band_start_hz=band_start_hz,
                band_end_hz=band_end_hz,
                spacing_hz=spacing_hz,
            )

        if cached_gains is not None:
            chunk_best_gains = cached_gains
        else:
            if args.force_gain_calibration:
                print("Forcing gain recalibration at startup.", file=sys.stderr)

            try:
                calibrated_gains = calibrate_all_chunk_gains(
                    args=args,
                    chunks=chunks,
                    bandwidth_hz=bandwidth_hz,
                    channel_rate_hz=channel_rate_hz,
                    redsea_rate_hz=redsea_rate_hz,
                    pi_call_lookup=pi_call_lookup,
                )
            except KeyboardInterrupt:
                print("\nInterrupted during gain calibration. Exiting.", file=sys.stderr)
                return 130
            except ValueError as e:
                print(f"Error during gain calibration: {e}", file=sys.stderr)
                return 2

            chunk_best_gains = calibrated_gains
            write_cached_chunk_gains(
                args=args,
                chunks=chunks,
                bandwidth_hz=bandwidth_hz,
                band_start_hz=band_start_hz,
                band_end_hz=band_end_hz,
                spacing_hz=spacing_hz,
                chunk_best_gains=calibrated_gains,
            )

    else:
        for idx in range(1, len(chunks) + 1):
            chunk_best_gains[idx] = None

    cycle = 0

    try:
        while True:
            cycle += 1

            cycle_upload_buffer = CycleUploadBuffer()

            print(f"\nStarting band-scan cycle {cycle}", file=sys.stderr)

            for chunk_index, chunk in enumerate(chunks, start=1):
                print(
                    f"\nCycle {cycle}, chunk {chunk_index}/{len(chunks)}",
                    file=sys.stderr,
                )

                rc, chunk_records = run_scan_chunk(
                    args=args,
                    center_hz=chunk["center_hz"],
                    bandwidth_hz=bandwidth_hz,
                    targets=chunk["targets"],
                    channel_rate_hz=channel_rate_hz,
                    redsea_rate_hz=redsea_rate_hz,
                    pi_call_lookup=pi_call_lookup,
                    cycle=cycle,
                    chunk_index=chunk_index,
                    upload_buffer=cycle_upload_buffer,
                    gain_override=chunk_best_gains.get(chunk_index),
                )

                if rc == 130:
                    return 130

                if rc == 0:
                    write_station_summary_log(
                        output_path=args.output,
                        records=chunk_records,
                        cycle=cycle,
                        chunk_index=chunk_index,
                    )

            print(
                f"\nCompleted band-scan cycle {cycle}; "
                f"top channel {format_mhz(band_end_hz)} MHz has been scanned. "
                f"Looping back to {format_mhz(band_start_hz)} MHz.",
                file=sys.stderr,
            )

            if args.tuner_key and cycle_upload_buffer is not None:
                upload_bandscan_to_rabbitears(
                    tuner_key=args.tuner_key,
                    records=cycle_upload_buffer.snapshot(),
                    timeout=args.upload_timeout,
                    retries=args.upload_retries,
                    retry_delay=args.upload_retry_delay,
                )

            if args.cycles > 0 and cycle >= args.cycles:
                print(f"Completed requested {args.cycles} cycle(s). Exiting.", file=sys.stderr)
                break

    except KeyboardInterrupt:
        print("\nInterrupted. Exiting.", file=sys.stderr)
        return 130

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
