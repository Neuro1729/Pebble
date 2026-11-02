#include "pebble/engine.hpp"
#include "pebble/arc_replacer.hpp"
#include "pebble/buffer_pool.hpp"
#include "pebble/index.hpp"
#include "pebble/storage.h"

#include <algorithm>
#include <cassert>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <cstring>
#include <string>
#include <vector>

int main() {
  const auto nonce = std::chrono::steady_clock::now().time_since_epoch().count();
  const auto base = std::filesystem::temp_directory_path() /
                    ("pebble-native-test-" + std::to_string(nonce) + ".db");
  std::error_code ignored;
  std::filesystem::remove(base, ignored);
  auto catalog = base;
  catalog += ".catalog";
  std::filesystem::remove(catalog, ignored);

  auto raw_path = base;
  raw_path += ".pages";
  std::filesystem::remove(raw_path, ignored);
  pb_status status{};
  char error[256]{};
  auto *disk = pb_disk_open(raw_path.string().c_str(), &status, error, sizeof(error));
  assert(status == PB_STATUS_OK && disk != nullptr);
  std::int32_t page_id = -1;
  assert(pb_disk_allocate_page(disk, &page_id, error, sizeof(error)) == PB_STATUS_OK);
  assert(page_id == 0);
  pb_page page{};
  assert(pb_disk_read_page(disk, page_id, &page, error, sizeof(error)) == PB_STATUS_OK);
  std::memcpy(page.data + 137, "Pebble", 6);
  assert(pb_disk_write_page(disk, &page, error, sizeof(error)) == PB_STATUS_OK);
  assert(pb_disk_read_page(disk, page_id, &page, error, sizeof(error)) == PB_STATUS_OK);
  assert(std::memcmp(page.data + 137, "Pebble", 6) == 0);
  assert(pb_disk_read_page(disk, -1, &page, error, sizeof(error)) == PB_STATUS_INVALID_ARGUMENT);
  assert(pb_disk_close(disk, error, sizeof(error)) == PB_STATUS_OK);
  disk = pb_disk_open(raw_path.string().c_str(), &status, error, sizeof(error));
  assert(status == PB_STATUS_OK && disk != nullptr);
  std::uint32_t page_count = 0;
  assert(pb_disk_page_count(disk, &page_count, error, sizeof(error)) == PB_STATUS_OK);
  assert(page_count >= 1);
  assert(pb_disk_read_page(disk, page_id, &page, error, sizeof(error)) == PB_STATUS_OK);
  assert(std::memcmp(page.data + 137, "Pebble", 6) == 0);
  assert(pb_disk_close(disk, error, sizeof(error)) == PB_STATUS_OK);
  std::filesystem::remove(raw_path, ignored);

  pebble::ArcReplacer arc(2);
  arc.record_access(0, 10);
  arc.unpin(0);
  arc.record_access(1, 11);
  arc.unpin(1);
  const auto arc_victim = arc.victim();
  assert(arc_victim.has_value());
  const auto ghost_page = *arc_victim == 0 ? 10 : 11;
  arc.record_access(*arc_victim, ghost_page);
  assert(arc.size() == 1);
  arc.unpin(*arc_victim);
  assert(arc.size() == 2);

  auto cache_path = base;
  cache_path += ".cachepages";
  std::filesystem::remove(cache_path, ignored);
  auto *cache_disk = pb_disk_open(cache_path.string().c_str(), &status, error, sizeof(error));
  assert(status == PB_STATUS_OK && cache_disk != nullptr);
  std::int32_t cache_ids[3]{};
  for (auto &id : cache_ids)
    assert(pb_disk_allocate_page(cache_disk, &id, error, sizeof(error)) == PB_STATUS_OK);
  {
    pebble::BufferPoolManager pool(cache_disk, 2);
    bool rejected_missing_page = false;
    try {
      (void)pool.fetch_page(1000);
    } catch (const std::runtime_error &) {
      rejected_missing_page = true;
    }
    assert(rejected_missing_page);
    auto valid_after_error = pool.fetch_page(cache_ids[0]);
    valid_after_error.mark_clean();
  }
  {
    pebble::BufferPoolManager pool(cache_disk, 2);
    auto first = pool.fetch_page(cache_ids[0]);
    auto second = pool.fetch_page(cache_ids[1]);
    first.page().data[0] = 0xa5;
    first.mark_dirty();
    second.page().data[0] = 0xb6;
    second.mark_dirty();
    bool rejected_all_pinned = false;
    try {
      (void)pool.fetch_page(cache_ids[2]);
    } catch (const std::runtime_error &) {
      rejected_all_pinned = true;
    }
    assert(rejected_all_pinned);
    first.drop();
    second.drop();
    auto third = pool.fetch_page(cache_ids[2]);
    third.page().data[0] = 0xc7;
    third.mark_dirty();
    third.drop();
    pool.flush_all_pages();
  }
  assert(pb_disk_close(cache_disk, error, sizeof(error)) == PB_STATUS_OK);
  cache_disk = pb_disk_open(cache_path.string().c_str(), &status, error, sizeof(error));
  assert(status == PB_STATUS_OK && cache_disk != nullptr);
  for (std::size_t i = 0; i < 3; ++i) {
    pb_page cached_page{};
    assert(pb_disk_read_page(cache_disk, cache_ids[i], &cached_page, error,
                             sizeof(error)) == PB_STATUS_OK);
    const std::uint8_t expected[] = {0xa5, 0xb6, 0xc7};
    assert(cached_page.data[0] == expected[i]);
  }
  assert(pb_disk_close(cache_disk, error, sizeof(error)) == PB_STATUS_OK);
  std::filesystem::remove(cache_path, ignored);

  {
    pebble::Engine db(base);
    assert(db.execute("CREATE TABLE people (id INTEGER, name VARCHAR, age INTEGER)").empty());
    assert(db.execute("INSERT INTO people VALUES (1, 'ann', 17), (2, 'bob', 30), (3, 'cara', 25)").empty());
    const auto table_list = db.execute_statement("SHOW TABLES");
    assert(table_list.is_query && table_list.columns == std::vector<std::string>{"Tables"});
    assert(table_list.rows.size() == 1 &&
           pebble::value_to_string(table_list.rows[0][0]) == "people");
    const auto description = db.execute_statement("DESCRIBE people");
    assert(description.columns == (std::vector<std::string>{"Field", "Type"}));
    assert(description.rows.size() == 3);
    const auto insert_result = db.execute_statement(
        "INSERT INTO people VALUES (4, 'dina', 28)");
    assert(!insert_result.is_query && insert_result.affected_rows == 1);
    db.execute("DELETE FROM people WHERE id = 4");
    db.execute("CREATE INDEX people_age ON people (age)");
    const auto indexed_range = db.execute("SELECT name FROM people WHERE age >= 18");
    assert(indexed_range.size() == 2);
    assert(pebble::value_to_string(indexed_range[0][0]) == "bob");
    assert(pebble::value_to_string(indexed_range[1][0]) == "cara");
    const auto rows = db.execute("SELECT name FROM people WHERE age >= 18");
    assert(rows.size() == 2);
    assert(pebble::value_to_string(rows[0][0]) == "bob");
    assert(pebble::value_to_string(rows[1][0]) == "cara");
    const auto ordered = db.execute(
        "SELECT name FROM people ORDER BY age DESC LIMIT 2 OFFSET 1");
    assert(ordered.size() == 2);
    assert(pebble::value_to_string(ordered[0][0]) == "cara");
    assert(pebble::value_to_string(ordered[1][0]) == "ann");
    const auto aggregates = db.execute(
        "SELECT COUNT(*), SUM(age), AVG(age), MIN(name), MAX(name) FROM people");
    assert(aggregates.size() == 1 && aggregates[0].size() == 5);
    assert(pebble::value_to_string(aggregates[0][0]) == "3");
    assert(pebble::value_to_string(aggregates[0][1]) == "72");
    assert(pebble::value_to_string(aggregates[0][2]) == "24");
    assert(pebble::value_to_string(aggregates[0][3]) == "ann");
    assert(pebble::value_to_string(aggregates[0][4]) == "cara");
    const auto grouped = db.execute(
        "SELECT age, COUNT(*) FROM people GROUP BY age "
        "ORDER BY COUNT(*) DESC, age ASC LIMIT 2");
    assert(grouped.size() == 2 && grouped[0].size() == 2);
    assert(pebble::value_to_string(grouped[0][0]) == "17");
    assert(pebble::value_to_string(grouped[1][0]) == "25");
    const auto empty_aggregate = db.execute(
        "SELECT COUNT(*), SUM(age), AVG(age), MIN(name) FROM people WHERE age > 100");
    assert(empty_aggregate.size() == 1 && empty_aggregate[0].size() == 4);
    assert(pebble::value_to_string(empty_aggregate[0][0]) == "0");
    assert(pebble::value_to_string(empty_aggregate[0][1]) == "0");
    assert(pebble::value_to_string(empty_aggregate[0][2]) == "NULL");
    assert(pebble::value_to_string(empty_aggregate[0][3]) == "NULL");
    db.execute("CREATE TABLE sort_runs (id INTEGER)");
    for (int batch = 0; batch < 9; ++batch) {
      std::string sql = "INSERT INTO sort_runs VALUES ";
      const auto start = batch * 250;
      const auto end = std::min(start + 250, 2050);
      for (int value = start; value < end; ++value) {
        if (value != start) sql += ", ";
        sql += "(" + std::to_string(2049 - value) + ")";
      }
      db.execute(sql);
    }
    const auto sorted_runs = db.execute("SELECT id FROM sort_runs ORDER BY id");
    assert(sorted_runs.size() == 2050);
    for (std::size_t i = 0; i < sorted_runs.size(); ++i)
      assert(std::get<std::int32_t>(sorted_runs[i][0]) == static_cast<std::int32_t>(i));
    assert(db.execute("CREATE TABLE orders (oid INTEGER, uid INTEGER)").empty());
    db.execute("INSERT INTO orders VALUES (10, 1), (11, 1), (20, 2)");
    const auto joined = db.execute("SELECT people.name, orders.oid FROM people JOIN orders ON people.id = orders.uid");
    assert(joined.size() == 3);
    assert(pebble::value_to_string(joined[0][0]) == "ann");
    assert(pebble::value_to_string(joined[2][1]) == "20");

    db.execute("CREATE TABLE wide_rows (id INTEGER, payload VARCHAR)");
    std::string bulk_insert = "INSERT INTO wide_rows VALUES ";
    for (int i = 0; i < 12; ++i) {
      if (i != 0) bulk_insert += ", ";
      bulk_insert += "(" + std::to_string(i - 10) + ", '" + std::string(500, 'x') + "')";
    }
    db.execute(bulk_insert);
    const auto across_pages = db.execute("SELECT id, payload FROM wide_rows WHERE id >= -10");
    assert(across_pages.size() == 12);
    assert(pebble::value_to_string(across_pages.front()[0]) == "-10");
    assert(pebble::value_to_string(across_pages.back()[1]).size() == 500);
    bool rejected_large_row = false;
    try {
      db.execute("INSERT INTO wide_rows VALUES (99, '" + std::string(5000, 'z') + "')");
    } catch (const std::runtime_error &) {
      rejected_large_row = true;
    }
    assert(rejected_large_row);
    assert(db.execute("SELECT id FROM wide_rows WHERE id = 1").size() == 1);
    db.execute("CREATE INDEX wide_rows_id ON wide_rows (id)");
    assert(pebble::value_to_string(db.execute("SELECT id FROM wide_rows WHERE id = -10")[0][0]) == "-10");

    db.execute("CREATE TABLE indexed_rows (id INTEGER, label VARCHAR)");
    std::string indexed_insert = "INSERT INTO indexed_rows VALUES ";
    for (int i = 0; i < 350; ++i) {
      if (i != 0) indexed_insert += ", ";
      indexed_insert += "(" + std::to_string(i) + ", 'v" + std::to_string(i) + "')";
    }
    db.execute(indexed_insert);
    db.execute("CREATE INDEX indexed_rows_id ON indexed_rows (id)");
    auto indexed = db.execute("SELECT label FROM indexed_rows WHERE id = 349");
    assert(indexed.size() == 1 && pebble::value_to_string(indexed[0][0]) == "v349");
    assert(db.execute("SELECT label FROM indexed_rows WHERE id = 900").empty());
    db.execute("INSERT INTO indexed_rows VALUES (350, 'v350')");
    assert(pebble::value_to_string(db.execute("SELECT label FROM indexed_rows WHERE id = 350")[0][0]) == "v350");
    bool rejected_duplicate = false;
    try {
      db.execute("INSERT INTO indexed_rows VALUES (349, 'duplicate')");
    } catch (const std::runtime_error &) {
      rejected_duplicate = true;
    }
    assert(rejected_duplicate);
    assert(db.execute("SELECT label FROM indexed_rows WHERE id = 349").size() == 1);

    db.execute("CREATE TABLE dml_rows (id INTEGER, label VARCHAR)");
    db.execute("INSERT INTO dml_rows VALUES (1, 'a'), (2, 'b'), (3, 'c')");
    db.execute("CREATE INDEX dml_rows_id ON dml_rows (id)");
    const auto update_result = db.execute_statement(
        "UPDATE dml_rows SET id = 4, label = 'alpha is longer' WHERE id = 1");
    assert(update_result.affected_rows == 1);
    const auto moved_update = db.execute("SELECT label FROM dml_rows WHERE id = 4");
    assert(moved_update.size() == 1 &&
           pebble::value_to_string(moved_update[0][0]) == "alpha is longer");
    bool rejected_conflicting_update = false;
    try {
      db.execute("UPDATE dml_rows SET id = 3 WHERE id = 4");
    } catch (const std::runtime_error &) {
      rejected_conflicting_update = true;
    }
    assert(rejected_conflicting_update);
    assert(db.execute("SELECT id FROM dml_rows WHERE id = 4").size() == 1);
    const auto delete_result = db.execute_statement("DELETE FROM dml_rows WHERE id >= 3");
    assert(delete_result.affected_rows == 2);
    assert(db.execute("SELECT id FROM dml_rows WHERE id = 3").empty());
    assert(db.execute("SELECT id FROM dml_rows WHERE id = 4").empty());
    assert(db.execute("SELECT id FROM dml_rows").size() == 1);
    db.close();
  }

  {
    pebble::Engine db(base);
    const auto rows = db.execute("SELECT id, name FROM people WHERE id = 2");
    assert(rows.size() == 1);
    assert(pebble::value_to_string(rows[0][1]) == "bob");
    const auto large_rows = db.execute("SELECT id FROM wide_rows WHERE id = -10");
    assert(large_rows.size() == 1);
    const auto indexed_row = db.execute("SELECT label FROM indexed_rows WHERE id = 350");
    assert(indexed_row.size() == 1 && pebble::value_to_string(indexed_row[0][0]) == "v350");
    assert(db.execute("SELECT id FROM dml_rows WHERE id = 4").empty());
    assert(db.execute("SELECT id FROM dml_rows").size() == 1);
    db.close();
  }

  auto legacy_base = base;
  legacy_base += ".legacy";
  auto legacy_catalog = legacy_base;
  legacy_catalog += ".catalog";
  auto legacy_lsm = legacy_base;
  legacy_lsm += ".lsm";
  {
    pebble::Engine db(legacy_base);
    db.execute("CREATE TABLE legacy (id INTEGER, value VARCHAR)");
    db.execute("INSERT INTO legacy VALUES (1, 'one'), (2, 'two')");
    db.execute("CREATE INDEX legacy_id ON legacy (id)");
    db.close();
  }
  {
    std::ifstream in(legacy_catalog);
    std::vector<std::string> lines;
    for (std::string line; std::getline(in, line);)
      lines.push_back(std::move(line));
    assert(lines.size() == 6);
    lines[0] = "PEBBLE_CATALOG 2";
    lines.back() += " 1";
    std::ofstream out(legacy_catalog, std::ios::trunc);
    for (const auto &line : lines) out << line << '\n';
    assert(out.good());
  }
  std::filesystem::remove_all(legacy_lsm, ignored);
  {
    pebble::Engine migrated(legacy_base);
    const auto rows = migrated.execute("SELECT value FROM legacy WHERE id >= 2");
    assert(rows.size() == 1);
    assert(pebble::value_to_string(rows[0][0]) == "two");
    migrated.close();
  }
  {
    std::ifstream in(legacy_catalog);
    std::string header;
    assert(std::getline(in, header));
    assert(header == "PEBBLE_CATALOG 3");
  }

  std::filesystem::remove(base, ignored);
  std::filesystem::remove(catalog, ignored);
  auto base_lsm = base;
  base_lsm += ".lsm";
  std::filesystem::remove_all(base_lsm, ignored);
  std::filesystem::remove(legacy_base, ignored);
  std::filesystem::remove(legacy_catalog, ignored);
  std::filesystem::remove_all(legacy_lsm, ignored);
  return 0;
}
