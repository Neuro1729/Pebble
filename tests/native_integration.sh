#!/bin/sh
set -eu

dbms=$1
tmp_root=${TMPDIR:-/tmp}
tmp_dir=$(mktemp -d "$tmp_root/pebble-integration.XXXXXX")
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM
db="$tmp_dir/integration.db"

"$dbms" --execute "CREATE TABLE people (id INTEGER, name VARCHAR, age INTEGER)" "$db" >/dev/null
"$dbms" --execute "INSERT INTO people VALUES (1, 'ann', 17), (2, 'bob', 30), (3, 'cara', 25)" "$db" >/dev/null
"$dbms" --execute "CREATE INDEX people_id ON people (id)" "$db" >/dev/null
"$dbms" --execute "CREATE INDEX people_age ON people (age)" "$db" >/dev/null
result=$("$dbms" --execute "SELECT name FROM people WHERE age >= 18" "$db")
test "$result" = "bob
cara"

# A second process must read rows and schema from the files written by the first.
result=$("$dbms" --execute "SELECT id, name FROM people WHERE id = 2" "$db")
test "$result" = "2 | bob"
result=$("$dbms" --execute "SELECT name FROM people ORDER BY age DESC LIMIT 2 OFFSET 1" "$db")
test "$result" = "cara
ann"
result=$("$dbms" --execute "SELECT age, COUNT(*) FROM people GROUP BY age ORDER BY COUNT(*) DESC, age ASC LIMIT 2" "$db")
test "$result" = "17 | 1
25 | 1"

"$dbms" --execute "CREATE TABLE orders (oid INTEGER, uid INTEGER)" "$db" >/dev/null
"$dbms" --execute "INSERT INTO orders VALUES (10, 1), (20, 2)" "$db" >/dev/null
result=$("$dbms" --execute "SELECT people.name, orders.oid FROM people JOIN orders ON people.id = orders.uid" "$db")
test "$result" = "ann | 10
bob | 20"

if "$dbms" --execute "INSERT INTO people VALUES (2, 'duplicate', 99)" "$db" >/dev/null 2>&1; then
  echo "duplicate indexed key unexpectedly succeeded" >&2
  exit 1
fi
result=$("$dbms" --execute "SELECT name FROM people WHERE id = 2" "$db")
test "$result" = "bob"
result=$("$dbms" --execute "SELECT name FROM people WHERE id = 999" "$db" --table)
test "$result" = "+------+
| name |
+------+
+------+
0 rows in set"

"$dbms" --execute "UPDATE people SET name = 'alice now' WHERE id = 1" "$db" >/dev/null
result=$("$dbms" --execute "SELECT name FROM people WHERE id = 1" "$db")
test "$result" = "alice now"
"$dbms" --execute "DELETE FROM people WHERE id = 3" "$db" >/dev/null
result=$("$dbms" --execute "SELECT id FROM people WHERE id = 3" "$db")
test "$result" = "OK"
result=$("$dbms" --execute "SELECT id FROM people WHERE id = 2" "$db")
test "$result" = "2"

if "$dbms" --execute "SELECT missing FROM people" "$db" >/dev/null 2>&1; then
  echo "invalid column unexpectedly succeeded" >&2
  exit 1
fi

# Script and stdin modes share the same quote-aware semicolon handling.
cat >"$tmp_dir/script.sql" <<'SQL'
CREATE TABLE semicolons (
  id INTEGER,
  value VARCHAR
);
INSERT INTO semicolons VALUES (1, 'left;right');
SELECT value FROM semicolons;
SQL
result=$("$dbms" --file "$tmp_dir/script.sql" "$db")
test "$result" = "OK
OK
left;right"
"$dbms" --execute "INSERT INTO semicolons VALUES (3, 'NULL')" "$db" >/dev/null
result=$("$dbms" --execute "SELECT value FROM semicolons WHERE id = 3" "$db" --table)
test "$result" = "+--------+
| value  |
+--------+
| \"NULL\" |
+--------+
1 row in set"
result=$("$dbms" --execute "SELECT AVG(id) FROM semicolons WHERE id > 999" "$db" --table)
test "$result" = "+---------+
| AVG(id) |
+---------+
| NULL    |
+---------+
1 row in set"
result=$(printf "INSERT INTO semicolons VALUES\n(2, 'line;two');\nSELECT id, value FROM semicolons ORDER BY id;\n" | "$dbms" "$db")
test "$result" = "OK
1 | left;right
2 | line;two
3 | NULL"

# Named databases can be created, selected, listed, and used in one batch.
result=$("$dbms" --database-dir "$tmp_dir/named" --execute \
  "CREATE DATABASE college; USE college; CREATE TABLE students (id INTEGER, name VARCHAR); INSERT INTO students VALUES (1, 'Ada'); SELECT name FROM students;")
test "$result" = "OK
OK
OK
OK
Ada"
result=$("$dbms" --database-dir "$tmp_dir/named" --execute "SHOW DATABASES")
test "$result" = "college"
result=$("$dbms" --database-dir "$tmp_dir/named" --execute "USE college; SHOW TABLES; DESCRIBE students")
test "$result" = "OK
students
id | INTEGER
name | VARCHAR"
"$dbms" --database-dir "$tmp_dir/named" --execute \
  "USE college; CREATE INDEX students_id ON students (id); DROP TABLE students" >/dev/null
test ! -e "$tmp_dir/named/college.db.lsm/students_id"
result=$("$dbms" --database-dir "$tmp_dir/named" --execute "USE college; SHOW TABLES")
test "$result" = "OK
OK"
"$dbms" --database-dir "$tmp_dir/named" --execute \
  "USE college; CREATE TABLE students (id INTEGER, name VARCHAR); CREATE INDEX students_id ON students (id); DROP DATABASE college" >/dev/null
test ! -e "$tmp_dir/named/college.db"
test ! -e "$tmp_dir/named/college.db.catalog"
test ! -e "$tmp_dir/named/college.db.lsm"
if "$dbms" --database-dir "$tmp_dir/named" --execute "USE college" >/dev/null 2>&1; then
  echo "dropped database unexpectedly remained available" >&2
  exit 1
fi

# Timing stays on stderr, is emitted per executed statement, and covers errors.
timing_stdout=$("$dbms" --execute "SELECT name FROM people WHERE id = 2" "$db" --timing 2>"$tmp_dir/timing.err")
test "$timing_stdout" = "bob"
grep -Eq '^Execution time: [0-9]+\.[0-9]{2} ms \(engine; excludes result formatting\)$' "$tmp_dir/timing.err"
"$dbms" --execute "SELECT id FROM people WHERE id = 1; SELECT id FROM people WHERE id = 2" "$db" --timing >/dev/null 2>"$tmp_dir/timing-multiple.err"
test "$(grep -c '^Execution time:' "$tmp_dir/timing-multiple.err")" -eq 2
if "$dbms" --execute "SELECT missing FROM people" "$db" --timing >/dev/null 2>"$tmp_dir/timing-failure.err"; then
  echo "timed invalid query unexpectedly succeeded" >&2
  exit 1
fi
grep -q '^ERROR:' "$tmp_dir/timing-failure.err"
grep -Eq '^Execution time: [0-9]+\.[0-9]{2} ms ' "$tmp_dir/timing-failure.err"
"$dbms" --execute "" "$db" --timing >/dev/null 2>"$tmp_dir/timing-empty.err"
test ! -s "$tmp_dir/timing-empty.err"

echo "native integration checks passed"
