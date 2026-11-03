#!/usr/bin/env python3
"""Local browser workbench for Pebble and cross-platform machine telemetry."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]


def configured_path(variable: str, default: Path) -> Path:
    configured = os.environ.get(variable)
    path = Path(configured).expanduser() if configured else default
    return path if path.is_absolute() else ROOT / path


DBMS = configured_path("PEBBLE_DBMS", ROOT / "build/debug/bin/dbms")
DATABASE = configured_path("PEBBLE_STUDIO_DB", ROOT / "data/presenter.db")
PAGE = ROOT / "web/studio.html"
DEMO_TABLE = "demo_entries"
INDEXED_BENCHMARK_TABLE = "lsm_bench_indexed"
UNINDEXED_BENCHMARK_TABLE = "lsm_bench_unindexed"
WORKLOAD_SIZE = 10_000
COMPARE_OPERATION_LIMIT = 200
SQL_LOCK = threading.RLock()
COMPARE_INDEXED_FIRST = True


def run_sql(sql: str, timeout: int = 300) -> dict[str, object]:
    """Run SQL through the project's existing native client."""
    with SQL_LOCK:
        started = time.perf_counter()
        result = subprocess.run(
            [str(DBMS), "--database", str(DATABASE), "--table"],
            cwd=ROOT,
            input=sql,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "ok": result.returncode == 0,
        "output": result.stdout.strip(),
        "error": result.stderr.strip(),
        "elapsed_ms": round(elapsed_ms, 3),
    }


def ensure_demo_table() -> None:
    table = run_sql(
        f"CREATE TABLE {DEMO_TABLE} (id INTEGER, label VARCHAR, score INTEGER)"
    )
    if not table["ok"] and "table already exists" not in str(table["error"]):
        raise RuntimeError(str(table["error"] or table["output"]))

    index = run_sql(f"CREATE INDEX {DEMO_TABLE}_id ON {DEMO_TABLE} (id)")
    if not index["ok"] and "index already exists" not in str(index["error"]):
        raise RuntimeError(str(index["error"] or index["output"]))

    for table_name in (INDEXED_BENCHMARK_TABLE, UNINDEXED_BENCHMARK_TABLE):
        table = run_sql(
            f"CREATE TABLE {table_name} (id INTEGER, label VARCHAR, score INTEGER)"
        )
        if not table["ok"] and "table already exists" not in str(table["error"]):
            raise RuntimeError(str(table["error"] or table["output"]))

    index = run_sql(
        f"CREATE INDEX {INDEXED_BENCHMARK_TABLE}_id ON {INDEXED_BENCHMARK_TABLE} (id)"
    )
    if not index["ok"] and "index already exists" not in str(index["error"]):
        raise RuntimeError(str(index["error"] or index["output"]))


def get_row_count(table_name: str = DEMO_TABLE) -> int:
    result = run_sql(f"SELECT COUNT(*) FROM {table_name}")
    if not result["ok"]:
        raise RuntimeError(str(result["error"] or "Could not read workload table"))
    match = re.search(r"\b(\d+)\b", str(result["output"]))
    if not match:
        raise RuntimeError("Pebble returned an unreadable row count")
    return int(match.group(1))


def get_max_id(table_name: str = DEMO_TABLE) -> int | None:
    result = run_sql(f"SELECT MAX(id) FROM {table_name}")
    if not result["ok"]:
        raise RuntimeError(str(result["error"] or "Could not read the next demo row ID"))
    match = re.search(r"^\|\s*(NULL|-?\d+)\s*\|$", str(result["output"]), re.MULTILINE)
    if not match:
        raise RuntimeError("Pebble returned an unreadable next row ID")
    if match.group(1) == "NULL":
        return None
    return int(match.group(1))


def command_output(command: list[str], timeout: float = 1.5) -> str:
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
        return completed.stdout if completed.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


class MetricsCollector:
    def __init__(self) -> None:
        self.system = platform.system()
        self.platform_name = self._platform_name()
        self.logical_cpus = os.cpu_count() or 1
        self.cpu_model = self._cpu_model()
        self.memory_total = self._memory_total()
        self.storage = self._storage_details()
        self.previous_cpu: tuple[int, int] | None = None
        self.previous_cpu_time: tuple[float, float] | None = None
        self.previous_mach_cpu: tuple[int, int] | None = None
        self.mach_cpu_api = self._mach_cpu_api() if self.system == "Darwin" else None
        self.lock = threading.Lock()

    def _platform_name(self) -> str:
        if self.system == "Darwin":
            version = platform.mac_ver()[0]
            return f"macOS {version}" if version else "macOS"
        if self.system == "Linux":
            try:
                release = platform.freedesktop_os_release()
                return release.get("PRETTY_NAME", "Linux")
            except (AttributeError, OSError):
                return f"Linux {platform.release()}"
        return f"{self.system} {platform.release()}"

    def _mach_cpu_api(self) -> tuple[object, object, object] | None:
        try:
            library = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            host_self = library.mach_host_self
            host_self.restype = ctypes.c_uint
            statistics = library.host_statistics
            statistics.argtypes = [
                ctypes.c_uint,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_int32),
                ctypes.POINTER(ctypes.c_uint),
            ]
            statistics.restype = ctypes.c_int
            return library, host_self, statistics
        except (AttributeError, OSError):
            return None

    def _cpu_model(self) -> str:
        if self.system == "Darwin":
            model = command_output(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
            if model:
                return model
        if self.system == "Linux":
            try:
                for line in Path("/proc/cpuinfo").read_text().splitlines():
                    if line.lower().startswith(("model name", "hardware")):
                        return line.split(":", 1)[1].strip()
            except OSError:
                pass
        return platform.processor() or platform.machine() or "CPU model unavailable"

    def _memory_total(self) -> int:
        if self.system == "Linux":
            try:
                for line in Path("/proc/meminfo").read_text().splitlines():
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) * 1024
            except (OSError, ValueError, IndexError):
                pass
        if self.system == "Darwin":
            value = command_output(["sysctl", "-n", "hw.memsize"]).strip()
            if value.isdigit():
                return int(value)
        try:
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        except (AttributeError, OSError, ValueError):
            return 0

    def _storage_details(self) -> dict[str, str]:
        details = {"device": "System volume", "kind": "Volume storage"}
        if self.system == "Darwin":
            output = command_output(["diskutil", "info", str(DATABASE.parent)], timeout=2.0)
            for line in output.splitlines():
                if ":" not in line:
                    continue
                key, value = (part.strip() for part in line.split(":", 1))
                if key in {"Device / Media Name", "Device Identifier"} and value:
                    details["device"] = value
                elif key == "Solid State" and value.lower() in {"yes", "no"}:
                    details["kind"] = "Solid state" if value.lower() == "yes" else "Rotating disk"
        elif self.system == "Linux":
            source = command_output(
                ["findmnt", "-n", "-o", "SOURCE", "-T", str(DATABASE.parent)]
            ).strip().splitlines()
            if source:
                device = source[0].split("[", 1)[0]
                if device.startswith("/dev/"):
                    try:
                        real_device = Path(os.path.realpath(device))
                        info = Path("/sys/dev/block") / f"{os.major(os.stat(device).st_rdev)}:{os.minor(os.stat(device).st_rdev)}"
                        for candidate in (info.resolve(), *info.resolve().parents):
                            rotational = candidate / "queue/rotational"
                            if rotational.exists():
                                value = rotational.read_text().strip()
                                details["kind"] = "Solid state" if value == "0" else "Rotating disk"
                                model = candidate / "device/model"
                                if model.exists() and model.read_text().strip():
                                    details["device"] = model.read_text().strip()
                                else:
                                    details["device"] = real_device.name
                                break
                    except (OSError, ValueError):
                        pass
        return details

    def _cpu_percent(self) -> float:
        if self.system == "Linux":
            try:
                fields = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
                values = [int(value) for value in fields[:8]]
                idle = values[3] + (values[4] if len(values) > 4 else 0)
                total = sum(values)
                previous = self.previous_cpu
                self.previous_cpu = (total, idle)
                if previous is None:
                    return 0.0
                total_delta = total - previous[0]
                idle_delta = idle - previous[1]
                return max(0.0, min(100.0, (1 - idle_delta / total_delta) * 100)) if total_delta else 0.0
            except (OSError, ValueError, IndexError, ZeroDivisionError):
                return 0.0

        if self.system == "Darwin":
            if self.mach_cpu_api is not None:
                _library, host_self, statistics = self.mach_cpu_api
                ticks = (ctypes.c_uint32 * 4)()
                count = ctypes.c_uint(4)
                status = statistics(
                    host_self(),
                    3,
                    ctypes.cast(ticks, ctypes.POINTER(ctypes.c_int32)),
                    ctypes.byref(count),
                )
                if status == 0 and count.value >= 4:
                    total = sum(ticks)
                    idle = ticks[2]
                    previous = self.previous_mach_cpu
                    self.previous_mach_cpu = (total, idle)
                    if previous is None:
                        return 0.0
                    total_delta = total - previous[0]
                    idle_delta = idle - previous[1]
                    return max(0.0, min(100.0, (1 - idle_delta / total_delta) * 100)) if total_delta else 0.0

            output = command_output(["ps", "-A", "-o", "%cpu="], timeout=2.0)
            try:
                total = sum(float(line.strip()) for line in output.splitlines() if line.strip())
                return max(0.0, min(100.0, total / self.logical_cpus))
            except ValueError:
                return 0.0

        now = os.times()
        previous = self.previous_cpu_time
        current = (now.user + now.children_user, now.system + now.children_system)
        self.previous_cpu_time = current
        if previous is None:
            return 0.0
        elapsed = (current[0] - previous[0]) + (current[1] - previous[1])
        return max(0.0, min(100.0, elapsed * 100 / self.logical_cpus))

    def _memory_used(self) -> int:
        if self.system == "Linux":
            try:
                values: dict[str, int] = {}
                for line in Path("/proc/meminfo").read_text().splitlines():
                    key, raw = line.split(":", 1)
                    values[key] = int(raw.strip().split()[0]) * 1024
                return max(0, values["MemTotal"] - values.get("MemAvailable", values["MemFree"]))
            except (OSError, ValueError, KeyError, IndexError):
                pass
        if self.system == "Darwin":
            output = command_output(["vm_stat"])
            page_match = re.search(r"page size of (\d+) bytes", output)
            page_size = int(page_match.group(1)) if page_match else 4096
            available_pages = 0
            for key in ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable"):
                match = re.search(rf"^{re.escape(key)}:\s+(\d+)", output, re.MULTILINE)
                if match:
                    available_pages += int(match.group(1))
            if available_pages:
                return max(0, self.memory_total - min(self.memory_total, available_pages * page_size))
        try:
            free = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES")
            return max(0, self.memory_total - free)
        except (AttributeError, OSError, ValueError):
            return 0

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            memory_used = self._memory_used()
            try:
                disk = shutil.disk_usage(DATABASE.parent)
            except OSError:
                disk = shutil.disk_usage(ROOT)
            cpu_percent = self._cpu_percent()
            return {
                "platform": self.platform_name,
                "architecture": platform.machine(),
                "cpu_model": self.cpu_model,
                "logical_cpus": self.logical_cpus,
                "cpu_percent": round(cpu_percent, 1),
                "memory_total": self.memory_total,
                "memory_used": memory_used,
                "memory_percent": round(memory_used * 100 / self.memory_total, 1) if self.memory_total else 0,
                "disk_device": self.storage["device"],
                "disk_kind": self.storage["kind"],
                "disk_path": str(DATABASE.parent),
                "disk_total": disk.total,
                "disk_used": disk.used,
                "disk_free": disk.free,
                "disk_percent": round(disk.used * 100 / disk.total, 1) if disk.total else 0,
            }


METRICS: MetricsCollector | None = None


class StudioHandler(BaseHTTPRequestHandler):
    server_version = "PebbleStudio/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[studio] {self.address_string()} - {fmt % args}", file=sys.stderr)

    def send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler API
        path = urlparse(self.path).path
        if path == "/":
            try:
                body = PAGE.read_bytes()
            except OSError as error:
                self.send_error(500, str(error))
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/metrics":
            assert METRICS is not None
            self.send_json(200, METRICS.snapshot())
        elif path == "/api/status":
            try:
                self.send_json(200, {
                    "database": str(DATABASE),
                    "table": DEMO_TABLE,
                    "rows": get_row_count(),
                    "indexed_benchmark_rows": get_row_count(INDEXED_BENCHMARK_TABLE),
                    "unindexed_benchmark_rows": get_row_count(UNINDEXED_BENCHMARK_TABLE),
                })
            except (OSError, subprocess.TimeoutExpired, RuntimeError) as error:
                self.send_json(500, {"error": str(error)})
        else:
            self.send_error(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler API
        global COMPARE_INDEXED_FIRST
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 1_000_000:
                self.send_json(413, {"error": "Request is too large"})
                return
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object")
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": f"Invalid request: {error}"})
            return

        if path == "/api/sql":
            sql = payload.get("sql")
            if not isinstance(sql, str) or not sql.strip():
                self.send_json(400, {"error": "Enter a SQL statement first"})
                return
            try:
                result = run_sql(sql)
                status = 200 if result["ok"] else 400
                if result["ok"]:
                    result["rows"] = get_row_count()
                self.send_json(status, result)
            except (OSError, subprocess.TimeoutExpired, RuntimeError) as error:
                self.send_json(500, {"error": str(error)})
            return

        if path == "/api/compare":
            operation = payload.get("operation")
            operations = payload.get("operations", 25)
            if operation not in ("read", "update", "delete"):
                self.send_json(400, {"error": "Choose read, update, or delete."})
                return
            if isinstance(operations, bool) or not isinstance(operations, int):
                self.send_json(400, {"error": "Operations must be a whole number."})
                return
            if operations < 1 or operations > COMPARE_OPERATION_LIMIT:
                self.send_json(400, {"error": f"Choose between 1 and {COMPARE_OPERATION_LIMIT} operations."})
                return

            try:
                with SQL_LOCK:
                    indexed_rows = get_row_count(INDEXED_BENCHMARK_TABLE)
                    unindexed_rows = get_row_count(UNINDEXED_BENCHMARK_TABLE)
                    if indexed_rows == 0 or unindexed_rows == 0:
                        self.send_json(409, {"error": "Add rows to both benchmark tables first."})
                        return
                    if indexed_rows != unindexed_rows:
                        self.send_json(409, {"error": "The benchmark tables have different row counts. Clear both tables, then add the same batch to each."})
                        return

                    indexed_max = get_max_id(INDEXED_BENCHMARK_TABLE)
                    unindexed_max = get_max_id(UNINDEXED_BENCHMARK_TABLE)
                    if indexed_max is None or indexed_max != unindexed_max or indexed_max != indexed_rows:
                        self.send_json(409, {"error": "The benchmark rows are not aligned. Clear both tables, then add the same batch to each."})
                        return

                    operation_count = min(operations, indexed_rows)
                    first_id = indexed_max - operation_count + 1
                    ids = range(first_id, indexed_max + 1)

                    def statements(table_name: str) -> str:
                        if operation == "read":
                            sql = [f"SELECT id FROM {table_name} WHERE id = {row_id}" for row_id in ids]
                        elif operation == "update":
                            sql = [f"UPDATE {table_name} SET score = 9001 WHERE id = {row_id}" for row_id in ids]
                        else:
                            sql = [f"DELETE FROM {table_name} WHERE id = {row_id}" for row_id in ids]
                        return ";\n".join(sql) + ";"

                    indexed_sql = statements(INDEXED_BENCHMARK_TABLE)
                    unindexed_sql = statements(UNINDEXED_BENCHMARK_TABLE)
                    order = (
                        ("indexed", INDEXED_BENCHMARK_TABLE, indexed_sql),
                        ("unindexed", UNINDEXED_BENCHMARK_TABLE, unindexed_sql),
                    )
                    if not COMPARE_INDEXED_FIRST:
                        order = tuple(reversed(order))
                    COMPARE_INDEXED_FIRST = not COMPARE_INDEXED_FIRST
                    timings: dict[str, float] = {}
                    for label, _table_name, sql in order:
                        result = run_sql(sql, timeout=600)
                        if not result["ok"]:
                            self.send_json(400, result)
                            return
                        timings[label] = float(result["elapsed_ms"])

                    noun = {"read": "point reads", "update": "point updates", "delete": "point deletes"}[operation]
                    self.send_json(200, {
                        "ok": True,
                        "operation": operation,
                        "operations": operation_count,
                        "message": f"Compared {operation_count:,} matching {noun} on both tables.",
                        "output": f"Indexed: {timings['indexed']:.2f} ms\nUnindexed: {timings['unindexed']:.2f} ms",
                        "indexed_elapsed_ms": timings["indexed"],
                        "unindexed_elapsed_ms": timings["unindexed"],
                        "elapsed_ms": timings["indexed"] + timings["unindexed"],
                        "indexed_benchmark_rows": get_row_count(INDEXED_BENCHMARK_TABLE),
                        "unindexed_benchmark_rows": get_row_count(UNINDEXED_BENCHMARK_TABLE),
                    })
            except (OSError, subprocess.TimeoutExpired, RuntimeError) as error:
                self.send_json(500, {"error": str(error)})
            return

        if path == "/api/workload":
            action = payload.get("action")
            try:
                with SQL_LOCK:
                    current_rows = get_row_count()
                    if action in ("add", "benchmark_indexed", "benchmark_unindexed"):
                        if action == "benchmark_indexed":
                            table_name = INDEXED_BENCHMARK_TABLE
                        elif action == "benchmark_unindexed":
                            table_name = UNINDEXED_BENCHMARK_TABLE
                        else:
                            table_name = DEMO_TABLE
                        requested_rows = payload.get("rows", WORKLOAD_SIZE)
                        if isinstance(requested_rows, bool) or not isinstance(requested_rows, int):
                            self.send_json(400, {"error": "Rows to add must be a whole number."})
                            return
                        if requested_rows < 1 or requested_rows > 100_000:
                            self.send_json(400, {"error": "Choose between 1 and 100,000 rows per add."})
                            return
                        maximum_id = get_max_id(table_name)
                        first_id = 1 if maximum_id is None else maximum_id + 1
                        last_id = first_id + requested_rows - 1
                        if last_id > 2_147_483_647:
                            self.send_json(409, {"error": "The next row IDs would exceed Pebble's INTEGER limit."})
                            return
                        rows = ",".join(
                            f"({row_id}, 'Pebble row {row_id:05d}', {row_id % 1000})"
                            for row_id in range(first_id, last_id + 1)
                        )
                        sql = f"INSERT INTO {table_name} VALUES {rows}"
                        if action == "benchmark_indexed":
                            mode = "with the LSM index"
                        elif action == "benchmark_unindexed":
                            mode = "without an index"
                        else:
                            mode = "to the demo table"
                        message = f"Added {requested_rows:,} entries {mode} in {table_name} (IDs {first_id:,}–{last_id:,})."
                    elif action in ("clear_benchmark_indexed", "clear_benchmark_unindexed", "clear_benchmarks"):
                        reset_indexed = action in ("clear_benchmark_indexed", "clear_benchmarks")
                        reset_unindexed = action in ("clear_benchmark_unindexed", "clear_benchmarks")
                        removed_indexed = get_row_count(INDEXED_BENCHMARK_TABLE) if reset_indexed else 0
                        removed_unindexed = get_row_count(UNINDEXED_BENCHMARK_TABLE) if reset_unindexed else 0
                        statements = []
                        if reset_indexed:
                            statements.extend([
                                f"DROP TABLE {INDEXED_BENCHMARK_TABLE}",
                                f"CREATE TABLE {INDEXED_BENCHMARK_TABLE} (id INTEGER, label VARCHAR, score INTEGER)",
                                f"CREATE INDEX {INDEXED_BENCHMARK_TABLE}_id ON {INDEXED_BENCHMARK_TABLE} (id)",
                            ])
                        if reset_unindexed:
                            statements.extend([
                                f"DROP TABLE {UNINDEXED_BENCHMARK_TABLE}",
                                f"CREATE TABLE {UNINDEXED_BENCHMARK_TABLE} (id INTEGER, label VARCHAR, score INTEGER)",
                            ])
                        sql = ";\n".join(statements) + ";"
                        removed_total = removed_indexed + removed_unindexed
                        if action == "clear_benchmarks":
                            message = f"Reset both benchmark tables and removed {removed_total:,} rows."
                        elif reset_indexed:
                            message = f"Reset the indexed benchmark table and removed {removed_indexed:,} rows."
                        else:
                            message = f"Reset the unindexed benchmark table and removed {removed_unindexed:,} rows."
                    elif action == "update":
                        if not current_rows:
                            self.send_json(409, {"error": "There are no demo rows to update. Add some rows first."})
                            return
                        sql = f"UPDATE {DEMO_TABLE} SET score = 9001"
                        message = f"Updated {current_rows:,} entries: set score to 9001."
                    elif action == "delete":
                        if not current_rows:
                            self.send_json(409, {"error": "The demo table is already empty."})
                            return
                        sql = f"DELETE FROM {DEMO_TABLE}"
                        message = f"Deleted {current_rows:,} entries from {DEMO_TABLE}."
                    else:
                        self.send_json(400, {"error": "Unknown workload action"})
                        return

                    result = run_sql(sql, timeout=600)
                    if not result["ok"]:
                        self.send_json(400, result)
                        return
                    self.send_json(200, {
                        "ok": True,
                        "output": result["output"],
                        "message": message,
                        "elapsed_ms": result["elapsed_ms"],
                        "rows_added": requested_rows if action in ("add", "benchmark_indexed", "benchmark_unindexed") else None,
                        "rows": get_row_count(),
                        "indexed_benchmark_rows": get_row_count(INDEXED_BENCHMARK_TABLE),
                        "unindexed_benchmark_rows": get_row_count(UNINDEXED_BENCHMARK_TABLE),
                    })
            except (OSError, subprocess.TimeoutExpired, RuntimeError) as error:
                self.send_json(500, {"error": str(error)})
            return

        self.send_error(404, "Not found")


def main() -> int:
    global METRICS

    parser = argparse.ArgumentParser(description="Open the Pebble browser workbench")
    parser.add_argument("--host", default="127.0.0.1", help="interface to bind (default: localhost)")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port (default: 8765)")
    args = parser.parse_args()

    if not DBMS.is_file() or not os.access(DBMS, os.X_OK):
        print(f"Pebble DBMS is not built yet. Run: make -C '{ROOT}' debug", file=sys.stderr)
        return 127
    if not PAGE.is_file():
        print(f"Studio page is missing: {PAGE}", file=sys.stderr)
        return 1

    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    METRICS = MetricsCollector()
    try:
        ensure_demo_table()
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as error:
        print(f"Could not prepare the demo table: {error}", file=sys.stderr)
        return 1

    server = ThreadingHTTPServer((args.host, args.port), StudioHandler)
    print(f"Pebble Studio is running at http://{args.host}:{args.port}")
    print(f"Database: {DATABASE}")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Pebble Studio.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
