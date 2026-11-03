# Pebble SQL Commands

This reference lists the SQL statements and DBMS client commands supported by
the native Pebble project. Pebble implements a small SQL subset; these forms
are not a promise of full SQL or PostgreSQL/MySQL compatibility.

## Quick start

Start the interactive client:

```sh
make debug
./scripts/dbms
```

Create and select a named database, then create a table and add rows:

```sql
CREATE DATABASE college;
USE college;
CREATE TABLE students (id INTEGER, name VARCHAR, age INTEGER);
INSERT INTO students VALUES (1, 'Ada', 17), (2, 'Grace', 30);
CREATE INDEX students_id ON students (id);
SELECT id, name FROM students WHERE age >= 18;
```

## Database commands

These commands are handled by the DBMS client. Named databases are stored in
the data directory (default `./data`, configurable with `PEBBLE_DATA_DIR` or
`--database-dir`).

| Command | Purpose |
| --- | --- |
| `CREATE DATABASE name;` | Create a named database. |
| `DROP DATABASE name;` | Remove a named database and its files. |
| `USE name;` | Select an existing named database. |
| `SHOW DATABASES;` | List named databases in the data directory. |

Database names must start with a letter or underscore and continue with
letters, digits, or underscores. `USE` is required before table commands when
the client was not opened with a database file.

## Table and index commands

```sql
CREATE TABLE table_name (
    column_name INTEGER,
    another_column VARCHAR
);

DROP TABLE table_name;
CREATE INDEX index_name ON table_name (integer_column);
SHOW TABLES;
DESCRIBE table_name;
```

- Column types are `INTEGER`, `INT` (an alias for `INTEGER`), and `VARCHAR`.
- `VARCHAR(n)` is not supported. There are no primary-key, foreign-key,
  `UNIQUE`, `NOT NULL`, or default-value declarations.
- An index covers one `INTEGER` column. Index keys are unique, so duplicate
  values in an indexed column are rejected. Creating an index on existing
  duplicate values fails.
- `DROP TABLE` removes its metadata and index files. Its old heap pages remain
  allocated in the database file.
- `DROP INDEX`, `ALTER TABLE`, and `CREATE TABLE IF NOT EXISTS` are not
  supported.

## Data commands

### Insert

```sql
INSERT INTO table_name VALUES (value, value, ...);
INSERT INTO table_name VALUES (value, value, ...), (value, value, ...);
```

Insert values must match the table's columns in order and count. There is no
column-list form or `INSERT ... SELECT` form.

### Update

```sql
UPDATE table_name
SET column_name = value [, another_column = value]
[WHERE column_name operator value];
```

### Delete

```sql
DELETE FROM table_name [WHERE column_name operator value];
```

For `UPDATE` and `DELETE`, the optional `WHERE` clause accepts one comparison.
Without it, every row is updated or deleted. DML `WHERE` column names are
unqualified (write `id`, not `table_name.id`).

## Queries

```sql
SELECT * | column_name [, column_name ...]
FROM table_name
[JOIN other_table ON table_name.column_name = other_table.column_name]
[WHERE column_name operator value]
[GROUP BY column_name [, column_name ...]]
[ORDER BY column_name [ASC | DESC] [, column_name [ASC | DESC] ...]]
[LIMIT row_count [OFFSET row_count]];
```

`SELECT` supports `*`, column projections, and one equality `JOIN`. A join
returns matching rows from both tables (inner-join behavior). Qualified column
names such as `students.id` may be used where a column is accepted. Table
aliases and column aliases are not supported.

The supported comparison operators are `=`, `!=`, `<`, `<=`, `>`, and `>=`.
Only one simple condition is allowed per `WHERE`; `AND`, `OR`, `LIKE`, `IN`,
`BETWEEN`, and `IS NULL` are not supported. The `WHERE` value must have the
same type as the compared column.

`ORDER BY` accepts one or more columns, with `ASC` as the default direction.
On grouped or aggregate queries, each ordering expression must also appear in
the selected expressions. `LIMIT` may be followed by `OFFSET`; `OFFSET` alone
is not supported.

### Aggregates and grouping

Supported aggregate expressions are:

```sql
COUNT(*), COUNT(column_name), SUM(integer_column), AVG(integer_column),
MIN(column_name), MAX(column_name)
```

`SUM` and `AVG` require an integer column. `MIN` and `MAX` accept integer or
varchar columns. `*` is supported only by `COUNT`. Grouped queries can select
grouping columns and aggregate expressions; every selected non-aggregate
column must be included in `GROUP BY`. Aggregate aliases are not supported.

Example:

```sql
SELECT age, COUNT(*), AVG(age)
FROM students
GROUP BY age
ORDER BY COUNT(*) DESC, age ASC
LIMIT 10;
```

## Literals and identifiers

- Integer literals are signed 32-bit integers.
- Text literals use single quotes, for example `'Ada'`. A single quote inside
  text is doubled: `'O''Reilly'`.
- SQL `NULL` is not accepted as an input literal. On empty input, `COUNT` and
  `SUM` return `0`; `AVG`, `MIN`, and `MAX` return `NULL`.
- SQL keywords are case-insensitive. Table and column identifiers are
  case-sensitive and use letters, digits, and underscores. Quote marks around
  identifiers are not supported.
- Statements end with semicolons. Interactive input can span lines, and the
  client splits semicolons outside quoted text.

## Interactive client commands

Enter these on a line by themselves, without a semicolon:

| Command | Purpose |
| --- | --- |
| `help` | Show a brief command summary. |
| `status` | Show the selected database and path. |
| `clear` | Clear the screen when connected to a terminal. |
| `exit`, `quit`, or `\q` | Close the session. |

Press Ctrl-C to discard the SQL statement currently being entered.

## DBMS command-line options

```text
./scripts/dbms [DATABASE_FILE]
./scripts/dbms --execute SQL [DATABASE_FILE] [--timing]
./scripts/dbms --file SCRIPT.sql [DATABASE_FILE] [--timing]
./scripts/dbms --database-dir DIRECTORY
```

| Option | Purpose |
| --- | --- |
| `-e`, `--execute SQL` | Execute one or more semicolon-separated statements. |
| `-f`, `--file SCRIPT.sql` | Execute statements from a SQL file. |
| `--database FILE` or positional `DATABASE_FILE` | Open a database file directly. |
| `--database-dir DIRECTORY` | Set the directory for named databases. |
| `--timing` | Print execution duration to stderr for each statement. |
| `--no-timing` | Disable statement timing. |
| `--table` | Print query results as aligned tables in batch mode. |
| `-h`, `--help` | Print command-line usage. |

With no mode option, the client opens an interactive shell when stdin is a
terminal; otherwise it reads SQL from stdin. Interactive timing is enabled by
default. `--timing` measures client dispatch and engine execution, excluding
result formatting.

## Not supported

The native SQL engine does not support transactions (`BEGIN`, `COMMIT`, or
`ROLLBACK`), `CREATE/DROP VIEW`, subqueries, set operations, expressions or
functions beyond the listed aggregates, multiple joins, outer joins, indexes
on varchar columns, or general SQL clauses not listed above.
