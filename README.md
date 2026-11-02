# Pebble

Pebble is a small educational DBMS. The repository contains the original Python
storage/query components and an initial native implementation using C17 for
portable page-file operations and C++20 for the DBMS runtime.

The native executable supports CREATE TABLE, CREATE INDEX on one INTEGER
column, multi-row INSERT, literal UPDATE/DELETE predicates, equality joins,
GROUP BY aggregates, ORDER BY, LIMIT, and OFFSET. It stores rows in 4 KiB heap
pages and unique-key indexes in a disk-backed LSM tree with a sorted memtable,
SSTables, tombstones, and compaction. Catalog metadata is persisted in a
versioned `.catalog` sidecar file. Disk-backed query-sort spilling,
transactions, and recovery are not implemented in the native runtime yet.

See [RUNNING.md](RUNNING.md) for prerequisites, build commands, supported SQL,
testing, shell and batch usage, and limitations. Build and start the client with
`make debug && ./scripts/dbms`, then use `CREATE DATABASE`, `USE`, and SQL at
the prompt. For automation, `./scripts/dbms --file setup.sql ./people.db` and
`--execute` remain available. Batch query timing is opt-in with `--timing` and
is written to stderr.

For a browser workbench with configurable insert/update/delete workloads and
live machine telemetry, run
`make debug && ./scripts/studio` and open the local URL it prints. The studio
uses a separate `data/presenter.db` database by default; set
`PEBBLE_STUDIO_DB` to use a different database file.

The native runtime still lacks transactions, undo, WAL, crash recovery,
disk-backed sorting, the modular Volcano executor API, and automatic discovery
of legacy Python databases. Multi-row DML can leave partial work after an I/O
failure. See [MIGRATION_PLAN.md](MIGRATION_PLAN.md) for the architecture
inventory and remaining migration work.
