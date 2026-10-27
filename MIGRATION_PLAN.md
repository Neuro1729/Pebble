# Pebble C/C++ Migration Plan

## Current architecture

Pebble is currently a Python 3.11+ teaching DBMS with no third-party runtime dependencies. Its 36 implementation modules are under `src/pebble`; 28 test modules cover the storage engine, executors, indexes, and transaction helpers.

The storage path is `DiskManager` → `DiskScheduler` → `BufferPoolManager` → `Page`/`PageGuard` → `SlottedPage`/`TableHeap`. The catalog creates in-memory table and index descriptors. Integer-key B+Tree pages are stored in the same page file. The query path uses pull-based executors for scans, insert, filter, projection, nested-loop and hash joins, aggregation, sorting, and limit. `Database` contains a small regular-expression SQL front end. Transaction objects, an undo log, a transaction manager, and WAL record serialization exist, but restart recovery is incomplete.

The working tree was clean at inspection. The committed `src/pebble/database.py` has an unexpected indent at line 94, so importing the public `Database` API fails before SQL can run. The catalog is not persisted, so closing and reopening preserves page bytes but does not reconstruct table definitions. Recovery redo/undo and parts of the SQL-facing update/delete path are unfinished. `README.md` is not yet usable run documentation.

## Existing feature inventory

| Area | Existing implementation | State / notes |
| --- | --- | --- |
| Values and rows | INTEGER and VARCHAR schemas; little-endian tuple encoding | Implemented; no NULL values |
| Page storage | 4 KiB pages; linked slotted pages; synchronous file manager | Implemented; page file can be reopened |
| Buffer management | Pin counts, dirty pages, guards, ARC replacement, queued disk worker | Implemented; Python components are not generally synchronized for concurrent callers |
| Tables and catalog | Heap scans/inserts; in-memory catalog | Implemented; catalog metadata is lost on restart |
| Indexes | Unique signed integer B+Tree, split, point lookup, leaf scan, naive leaf delete | Implemented with limited keys and delete balancing |
| Query execution | Scan, insert, filter, projection, joins, aggregation, sort, limit | Mostly implemented as executor APIs; SQL integration is narrower |
| SQL | CREATE TABLE/INDEX, INSERT, SELECT, equality JOIN, simple predicates, transaction commands | Imports after repairing syntax defects; SQL UPDATE/DELETE/GROUP BY/ORDER BY are not wired into `Database.execute` |
| Transactions | Begin/commit/abort manager, undo helpers, WAL serialization and analysis | Partial; abort/undo and restart recovery do not provide complete durability guarantees |
| Tests | 28 pytest modules, 83 test functions | pytest is absent; after repairing syntax defects, a dependency-free runner passed 76 functions and skipped 7 functions marked by the existing transaction/WAL modules |

## Proposed C/C++ boundaries

- **C17 (`native/c`)**: fixed-size page representation and portable database-file page operations. Keep this ABI small, validate page IDs and short I/O, and expose opaque disk-manager ownership through `extern "C"` declarations.
- **C++20 (`native/cpp`)**: engine objects and runtime. Use RAII for page/file ownership, typed schema/value structures, the buffer pool, table/catalog integration, indexes, executor composition, and CLI. Do not pass exceptions through the C ABI.
- **Compatibility**: preserve the current 4096-byte page size and documented little-endian tuple/slotted-page layouts when replacing those components. The existing catalog has no durable format, so any durable native catalog needs a versioned sidecar or an explicitly documented new format and must not reinterpret legacy page zero as metadata.

## Dependency and integration map

```text
CLI / SQL front end (C++)
  └─ binder/planner and executors (C++)
       ├─ catalog/schema/tuple (C++)
       ├─ B+Tree and table heap (C++)
       │    └─ buffer pool and page guards (C++)
       │         └─ page + disk file operations (C17 ABI)
       └─ transaction/WAL/recovery (C++, only where guarantees are implemented)
```

Keep dependencies pointed downward; storage must not depend on SQL or executors. Add C-facing headers only for the low-level storage boundary.

## Migration order

1. Repair and record baseline defects; inventory every Python module, public API, and existing test behavior.
2. Establish a native build with separate C and C++ objects and generated header dependencies.
3. Port page and disk primitives to C; verify byte layouts and error handling.
4. Port schema, tuple serialization, slotted pages, heap, buffer pool, and guards to C++ with compatibility fixtures.
5. Port the B+Tree/catalog and query operators; preserve current limits rather than claiming unsupported SQL.
6. Integrate a native executable and client, and route supported SQL through the actual storage/executor implementation.
7. Port transaction/WAL behavior only to the extent that existing guarantees can be preserved; do not label analysis-only recovery as crash recovery.
8. Replace Python tests with native unit and executable-level integration coverage, then remove Python only after feature parity is demonstrated.

## Portability strategy

Use standard C17/C++20, `FILE`-based portable I/O or standard C++ facilities behind the C API, and `std::filesystem` for C++ paths. Keep target triple, sysroot, compiler, and flags caller-configurable. Do not assume native macOS builds verify Linux; use separate CI jobs for macOS and Linux. Cross-compilation is only validated when an appropriate target toolchain and runtime are available.

## Validation plan

- Capture the existing test baseline when pytest is available and after the syntax defect is isolated.
- Add byte-for-byte C storage tests, including empty allocation, page round-trip, invalid IDs, short reads, and reopen behavior.
- Test C++ tuple/page/heap/catalog/index operations and SQL through the actual executable.
- Run clean debug and release builds, sanitizer builds on supported compilers, and `make -j`.
- Add native macOS/Linux CI and only report platforms that CI actually exercises.

## Risks and unresolved items

- The current SQL module does not import, so its runtime behavior must be reconstructed from tests and implementation intent rather than treated as a passing baseline.
- Existing B+Tree indexes are unique INTEGER-only and deletes do not rebalance; widening them would change behavior and format.
- The catalog is volatile, so preserving data across database reopen requires a new metadata persistence design.
- WAL commit/abort and recovery helpers are incomplete; integration must not imply crash safety that the code does not provide.
- The available environment is macOS with Apple Clang and GNU Make 3.81. Linux native validation requires CI or another host.
- pytest is not installed in the project environment, and the environment's Python 3.9 is below the project's declared minimum.


## Implementation checkpoint (2026-10-27)

The native checkpoint is implemented. native/c/storage.c and its public header
provide page-file allocation, read/write, page count, and close through a C17
ABI. native/cpp/engine.cpp implements typed row serialization using the
existing little-endian tuple format, slotted heap pages, a versioned catalog
sidecar, a bounded ARC buffer pool with RAII page guards, and a deliberately
small SQL runtime. native/cpp/index.cpp ports the unique INTEGER B+Tree page
format and split/search/scan/delete behavior. native/cpp/main.cpp is the dbms
CLI. A queued worker serializes page I/O; each buffer-pool call waits for its
request to complete.

The native runtime supports CREATE TABLE, unique INTEGER CREATE INDEX, multi-row
INSERT, SELECT projection, one simple WHERE comparison, one equality JOIN,
literal UPDATE/DELETE, GROUP BY with COUNT/SUM/AVG/MIN/MAX, ORDER BY, LIMIT, and
OFFSET. Equality and integer range predicates use B+Tree lookups when a matching
index exists; equality joins use a hash build/probe path. Grouping, sorting, and
limiting currently happen in memory. Index roots and table metadata are saved
in a versioned catalog sidecar, written to a temporary file and renamed into
place. This is new persistence behavior because the Python catalog was
volatile. The B+Tree page layout matches the Python implementation; transaction
and recovery code remain unported. Multi-row DML is not atomic if storage I/O
fails midway. No performance improvement is claimed without benchmarks.

The root Makefile now builds separate C/C++ object trees and a C static library,
generates compiler dependency files, uses distinct debug/release directories,
and provides all/lib/test/check/bench/clean/run/debug/release/help/install
targets. Native tests cover C page round-trip and reopen, ARC ghost hits,
buffer-pool pinning/eviction/dirty flushing, B+Tree leaf/internal splits and
range traversal, indexed duplicate checks and point lookup, multi-page heaps,
SQL filtering/joins, aggregate edge cases and grouping, ordering/offset/limits,
indexed UPDATE/DELETE, restart persistence, and error handling.

Validation completed on macOS with Apple Clang 21 and GNU Make 3.81:

- Clean debug, optimized release, AddressSanitizer/UndefinedBehaviorSanitizer,
  and explicit clang/clang++ native test runs passed.
- A native-created row was read back through the Python Page/SlottedPage/Tuple
  implementation, confirming the current row/page binary layout is compatible.
- All Python source and test modules compile. The Python SQL smoke check passed
  after fixing malformed SQL indentation and three misplaced future imports.
- A temporary dependency-free runner executed all unmarked Python test
  functions: 76 passed and 7 were skipped by existing transaction/WAL module
  markers. This is not a pytest invocation. Pytest was absent, and uv sync
  failed because this environment cannot resolve PyPI.
- Linux CI is configured with ubuntu-latest and macos-latest, but the workflow
  has not run from this checkout. Linux and cross-compilation are unverified.
- No benchmarks were added, so no performance improvement is claimed.

Remaining migration work: add disk-backed sort spilling, port
transaction/undo/WAL/recovery, and remaining SQL forms.
Native query logic still integrates operators in Engine rather than exposing the
modular Volcano executor API from the Python implementation. Decide and
document an import strategy for legacy page files and a durable native catalog
migration. Run the original suite under pytest when available, add parity and
failure-consistency tests, and verify Linux CI before declaring the migration
complete.

### Client checkpoint (2026-10-27)

The executable now starts an interactive shell when attached to a terminal.
It accepts multiline statements, splits semicolons outside single/double
quotes, supports `CREATE DATABASE`, `USE`, `SHOW DATABASES`, `SHOW TABLES`, and
`DESCRIBE`, and prints query results in aligned tables. Client commands include
`help`, `status`, `clear`, `exit`, `quit`, and `\q`. Existing `--execute` and
positional database-file usage remain; `--file`, piped SQL, `--database`,
`--database-dir`, and `--table` are also available. `--timing` measures each
statement with `steady_clock`, writes durations to stderr, and does not include
result formatting. Timing defaults on only in interactive mode. `make run` and
the `scripts/dbms` launcher provide short entry points.

This is a client milestone, not a completion of the native engine migration.
The engine still has no transaction/undo/WAL/recovery support, disk-backed
external sorting, modular Volcano executor API, or legacy Python catalog
discovery. Multi-row DML is not atomic when storage I/O fails. These items
remain required before claiming feature parity or transactional durability.
