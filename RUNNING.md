# Running Pebble

## A. Prerequisites

The native build targets macOS and Linux and needs C17 and C++20 compilers,
GNU Make, and a POSIX shell. There are no third-party native dependencies.
On macOS, install Apple's Command Line Tools with xcode-select --install.
Homebrew is optional; brew install llvm provides a newer Clang if needed.
On Debian/Ubuntu run sudo apt update followed by sudo apt install
build-essential. On Fedora run
sudo dnf install gcc gcc-c++ make.

The legacy Python suite requires Python 3.11+, uv, and pytest:

```
uv sync --extra dev
```

## B. Repository structure

- native/c/storage.c and native/include/pebble/storage.h: C17 page-file API.
- native/cpp/buffer_pool.cpp and arc_replacer.cpp: bounded C++ page cache,
  ARC replacement, and RAII guards.
- native/cpp/disk_scheduler.cpp: queued page I/O worker used by the cache.
- native/cpp/engine.cpp and native/include/pebble/engine.hpp: C++20 tuple,
  heap, catalog, and SQL runtime.
- native/cpp/main.cpp and scripts/dbms: interactive and batch client.
- native/cpp/index.cpp and native/include/pebble/index.hpp: persistent
  unique INTEGER B+Tree indexes using Pebble's existing index page layout.
- native/cpp/main.cpp: dbms command-line entry point.
- src/pebble/: original Python storage, index, executor, transaction, WAL,
  and recovery modules; many are not yet migrated into the native runtime.
- tests/native_engine_test.cpp and tests/native_integration.sh: native checks.
- tests/test_*.py: original Python pytest suite.
- .github/workflows/ci.yml: native CI on macOS and Linux.

Native rows are stored in 4096-byte pages. Catalog metadata lives in a
versioned DATABASE_FILE.catalog sidecar because the Python catalog was only
in memory.

## C. Build instructions

```
make -j
make clean && make -j
make debug
make release
make test
make check
```

Debug and release objects are separate under build/debug and build/release.
Run Python tests with uv run pytest after uv sync --extra dev. For sanitizers:

```
make clean
make SANITIZE=address test
```

There are no benchmarks yet; make bench reports that. Override tools and paths
without editing the Makefile, for example:

```
make CC=clang CXX=clang++ BUILD_DIR=build/custom PREFIX=/opt/pebble
```

Cross-compiling requires a matching C/C++ toolchain and target sysroot. Supply
target compilers and flags through CC, CXX, AR, CPPFLAGS, CFLAGS, CXXFLAGS,
and LDFLAGS. Cross-compilation was not verified here.

## D. Running the DBMS

After `make debug`, start the interactive shell with:

```
./scripts/dbms
```

The shell creates no database automatically. Its default directory is `./data`
(override with `PEBBLE_DATA_DIR` or `--database-dir`). Create and select one,
then run SQL:

```
CREATE DATABASE college;
USE college;
CREATE TABLE students (id INTEGER, name VARCHAR);
INSERT INTO students VALUES (1, 'Ada'), (2, 'Grace');
SELECT id, name FROM students;
SHOW TABLES;
DESCRIBE students;
```

The prompt accepts multiline statements and only splits on semicolons outside
single or double quotes. Client commands are `help`, `status`, `clear`, `exit`,
`quit`, and `\q`. Results use an aligned table in the interactive shell.
Timing is on by default in the interactive shell. Press Ctrl-C to discard the
pending statement; `exit`, `quit`, or `\q` closes the selected database.

For existing scripts and automation, the direct-file and batch interfaces are
still available:

```
./scripts/dbms --database ./people.db
./scripts/dbms --execute "SELECT * FROM people" ./people.db
./scripts/dbms --file ./setup.sql ./people.db
cat ./setup.sql | ./scripts/dbms ./people.db
make run DB_PATH=./people.db
```

## E. Browser studio

Build the native client and launch the local presenter UI:

```
make debug
./scripts/studio
```

Open the `http://127.0.0.1:8765` URL printed by the server. The SQL console
sends commands to the same native client and accepts the SQL supported by
Pebble. The workload controls use a dedicated `demo_entries` table. Choose
between 1 and 100,000 rows to append per run; repeated adds use new IDs. Update
changes every score, and delete clears the table. The right panel reports CPU,
whole-machine memory, and system-volume capacity and plots CPU and memory use
over time. Use the header toggle to switch between light and dark themes; the
choice is saved in the browser. Telemetry is read from macOS or Linux host
interfaces; storage model and SSD type are shown when the operating system
exposes them.

The studio binds to localhost. Choose another database file with
`PEBBLE_STUDIO_DB=/path/to/demo.db ./scripts/studio`. The default database is
`data/presenter.db`.

`--database FILE` selects a database file, and the legacy positional file
argument remains supported. `--execute` and `--file` accept multiple
semicolon-terminated statements. `--table` enables aligned result tables in
batch mode. Batch timing is opt-in with `--timing`; it writes one duration per
statement to stderr, including failed engine statements, and leaves result
stdout unchanged. The measured interval covers client dispatch and engine
execution, but excludes result formatting and time waiting for shell input.

Native SQL supports CREATE TABLE, CREATE INDEX on one INTEGER column,
multi-row INSERT, SELECT projection, one equality JOIN, one simple WHERE
comparison, literal UPDATE and DELETE, GROUP BY, COUNT/SUM/AVG/MIN/MAX,
ORDER BY, LIMIT, and OFFSET. The client also supports CREATE DATABASE, USE,
SHOW DATABASES, SHOW TABLES, and DESCRIBE. DML supports one simple WHERE
comparison and literal assignments. VARCHAR length declarations such as
`VARCHAR(100)` are not supported; use `VARCHAR`. Aggregate calls do not
support aliases.
ORDER BY on grouped/aggregate queries must refer to a selected expression.
Sorting uses in-memory runs and a k-way merge; it does not spill runs to disk.
Keywords are case-insensitive and identifiers are case-sensitive. Empty
results have column headings in the interactive/table output; legacy raw batch
output prints `OK` when no rows are returned. Table output renders SQL `NULL`
as `NULL` and a string whose contents are `NULL` as `"NULL"`.
The current engine materializes each query result before formatting it. The
table formatter sizes columns from all returned rows, so large results can use
substantial memory; it does not silently truncate values.

## F. Example workflow

```
make -j
./scripts/dbms --execute "CREATE TABLE people (id INTEGER, name VARCHAR, age INTEGER)" ./people.db
./scripts/dbms --execute "INSERT INTO people VALUES (1, 'ann', 17), (2, 'bob', 30), (3, 'cara', 25)" ./people.db
./scripts/dbms --execute "CREATE INDEX people_id ON people (id)" ./people.db
./scripts/dbms --execute "SELECT name FROM people WHERE age >= 18" ./people.db
```

Representative output:

```
OK
OK
OK
bob
cara
```

The next process reopens the same rows and catalog. Keep the `.catalog` sidecar
beside the page file. To choose a named database directory, use
`./scripts/dbms --database-dir ./data` and issue `CREATE DATABASE`/`USE`.

## G. Testing and troubleshooting

make test exercises C page-file allocation/read/write/reopen, ARC replacement,
buffer-pool pinning/eviction/dirty flushing, B+Tree leaf and internal splits,
index lookup and persistence, C++ SQL filtering, aggregation, ordering, limits,
indexed UPDATE/DELETE, and the actual executable for joins and invalid-column
errors.
Use make clean to remove build outputs. If uv sync cannot download pytest,
check Python 3.11+ and package-index connectivity.

The committed Python SQL module had malformed indentation; that syntax defect
has been repaired. Its pytest suite has not run here because pytest is absent
and PyPI is unreachable. A dependency-free runner executed the existing plain
test functions with temporary-path and raises shims: 76 passed and 7 tests
remained skipped by their existing module-level markers. This is useful
coverage, but it does not replace a run under pytest itself.

## H. Platform-specific notes

The Makefile uses portable C17/C++20 flags and no CPU-specific options. The
native build and tests ran on macOS with Apple Clang 21 and GNU Make 3.81.
Linux support is configured in CI but was not run locally. Cross-compilation
also remains unverified; run target binaries on their target OS.

## I. Current limitations

The native disk scheduler serializes page reads and writes through a worker,
while each cache operation waits for its request to finish. Disk-backed sort
spilling is not yet implemented. The native runtime has no transactions, undo,
WAL, or recovery. `BEGIN`, `COMMIT`, and `ROLLBACK` are unsupported; there is no
autocommit policy, rollback, isolation, or crash-recovery guarantee. DML writes
directly to storage, so an I/O error during a multi-row statement can leave
partial work. Concurrent writers are not coordinated. The client does not
offer transaction commands.

Sort and grouping are in-memory operations; there is no configurable sort
budget, spill-run format, or temporary-run lifecycle. The query path returns
materialized vectors and still integrates operators inside `Engine`; it does
not expose the modular Volcano `Init`/`Next`/`Close` API or stream rows to the
client.

Legacy Python databases have no persisted catalog to discover. Native SQL
requires its own versioned `.catalog` sidecar, and there is no legacy import or
migration command. The Python and native runtimes should not concurrently write
the same files. No performance gain is claimed because there is no benchmark.
Linux, cross-compilation, and the Python pytest suite remain unverified.
