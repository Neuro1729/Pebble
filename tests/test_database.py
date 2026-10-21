"""Step 10: Database front end + dumb SQL planner end-to-end."""

from __future__ import annotations

from pathlib import Path

from pebble.database import Database


def test_create_insert_select_where(tmp_path: Path) -> None:
    db_path = tmp_path / "v1.db"
    with Database(db_path) as db:
        db.execute("CREATE TABLE people (id INTEGER, name VARCHAR, age INTEGER)")
        db.execute(
            "INSERT INTO people VALUES (1, 'ann', 17), (2, 'bob', 30), (3, 'cara', 25)"
        )
        rows = db.execute("SELECT name FROM people WHERE age >= 18")
        assert rows == [["bob"], ["cara"]]


def test_join_via_sql(tmp_path: Path) -> None:
    db_path = tmp_path / "join.db"
    with Database(db_path) as db:
        db.execute("CREATE TABLE users (id INTEGER, name VARCHAR)")
        db.execute("CREATE TABLE orders (oid INTEGER, uid INTEGER)")
        db.execute("INSERT INTO users VALUES (1, 'ann'), (2, 'bob')")
        db.execute("INSERT INTO orders VALUES (10, 1), (11, 1), (20, 2)")
        rows = db.execute(
            "SELECT users.name, orders.oid FROM users JOIN orders ON users.id = orders.uid"
        )
        assert rows == [["ann", 10], ["ann", 11], ["bob", 20]]


def test_create_index_and_equality_select_uses_index(tmp_path: Path) -> None:
    """V2 step 9: CREATE INDEX + WHERE indexed_col = literal end-to-end."""
    db_path = tmp_path / "idx_sql.db"
    with Database(db_path) as db:
        db.execute("CREATE TABLE users (id INTEGER, name VARCHAR)")
        db.execute("INSERT INTO users VALUES (1, 'ann'), (2, 'bob'), (3, 'cara')")
        db.execute("CREATE INDEX users_id ON users (id)")

        rows = db.execute("SELECT name FROM users WHERE id = 2")
        assert rows == [["bob"]]

        # Non-equality still works via SeqScan + Filter
        rows2 = db.execute("SELECT name FROM users WHERE id > 1")
        assert rows2 == [["bob"], ["cara"]]

        assert db.catalog.list_indexes("users") == ["users_id"]
        assert db.catalog.get_index("users_id").tree.search(2) is not None
