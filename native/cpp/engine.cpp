#include "pebble/engine.hpp"
#include "pebble/buffer_pool.hpp"
#include "pebble/index.hpp"

#include "pebble/storage.h"

#include <algorithm>
#include <charconv>
#include <cctype>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <queue>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <system_error>
#include <unordered_set>
#include <utility>

namespace pebble {
namespace {

enum class Type { Integer, Varchar };
struct Column {
  std::string name;
  Type type;
};
struct IndexInfo {
  std::string name;
  std::size_t column_index;
  std::unique_ptr<LSMTree> tree;
};
struct Table {
  std::string name;
  std::vector<Column> columns;
  std::int32_t first_page;
  std::int32_t last_page;
  std::vector<IndexInfo> indexes;
};

void require_status(pb_status status, const char *error) {
  if (status != PB_STATUS_OK) {
    throw std::runtime_error(std::string(pb_status_name(status)) + ": " + error);
  }
}

std::string trim(std::string value) {
  const auto first = value.find_first_not_of(" \t\r\n");
  if (first == std::string::npos) return {};
  const auto last = value.find_last_not_of(" \t\r\n");
  return value.substr(first, last - first + 1);
}

std::string upper(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
    return static_cast<char>(std::toupper(c));
  });
  return value;
}

std::vector<std::string> split_commas(const std::string &text) {
  std::vector<std::string> result;
  std::string current;
  bool in_string = false;
  for (std::size_t i = 0; i < text.size(); ++i) {
    const char ch = text[i];
    if (ch == '\'') {
      current.push_back(ch);
      if (in_string && i + 1 < text.size() && text[i + 1] == '\'') {
        current.push_back(text[++i]);
      } else {
        in_string = !in_string;
      }
    } else if (ch == ',' && !in_string) {
      auto part = trim(current);
      if (!part.empty()) result.push_back(std::move(part));
      current.clear();
    } else {
      current.push_back(ch);
    }
  }
  auto tail = trim(current);
  if (!tail.empty()) result.push_back(std::move(tail));
  if (in_string) throw std::runtime_error("unterminated string literal");
  return result;
}

Value parse_value(const std::string &raw) {
  const auto text = trim(raw);
  if (text.size() >= 2 && text.front() == '\'' && text.back() == '\'') {
    std::string result;
    for (std::size_t i = 1; i + 1 < text.size(); ++i) {
      if (text[i] == '\'' && i + 1 < text.size() - 1 && text[i + 1] == '\'') {
        result.push_back('\'');
        ++i;
      } else {
        result.push_back(text[i]);
      }
    }
    return result;
  }
  std::int32_t value{};
  const char *begin = text.data();
  const char *end = begin + text.size();
  const auto parsed = std::from_chars(begin, end, value);
  if (text.empty() || parsed.ec != std::errc{} || parsed.ptr != end) {
    throw std::runtime_error("bad literal: " + text);
  }
  return value;
}

void put_u16(std::uint8_t *out, std::uint16_t value) {
  out[0] = static_cast<std::uint8_t>(value);
  out[1] = static_cast<std::uint8_t>(value >> 8);
}
void put_u32(std::uint8_t *out, std::uint32_t value) {
  for (unsigned i = 0; i < 4; ++i) out[i] = static_cast<std::uint8_t>(value >> (8 * i));
}
std::uint16_t get_u16(const std::uint8_t *in) {
  return static_cast<std::uint16_t>(in[0]) |
         static_cast<std::uint16_t>(static_cast<std::uint16_t>(in[1]) << 8);
}
std::uint32_t get_u32(const std::uint8_t *in) {
  std::uint32_t value = 0;
  for (unsigned i = 0; i < 4; ++i) value |= static_cast<std::uint32_t>(in[i]) << (8 * i);
  return value;
}

std::vector<std::uint8_t> encode_row(const Table &table, const Row &row) {
  if (row.size() != table.columns.size()) throw std::runtime_error("wrong number of values");
  std::vector<std::uint8_t> bytes;
  for (std::size_t i = 0; i < row.size(); ++i) {
    if (table.columns[i].type == Type::Integer) {
      if (!std::holds_alternative<std::int32_t>(row[i]))
        throw std::runtime_error("column " + table.columns[i].name + " expects INTEGER");
      const auto value = static_cast<std::uint32_t>(std::get<std::int32_t>(row[i]));
      const auto offset = bytes.size();
      bytes.resize(offset + 4);
      put_u32(bytes.data() + offset, value);
    } else {
      if (!std::holds_alternative<std::string>(row[i]))
        throw std::runtime_error("column " + table.columns[i].name + " expects VARCHAR");
      const auto &value = std::get<std::string>(row[i]);
      if (value.size() > std::numeric_limits<std::uint32_t>::max())
        throw std::runtime_error("VARCHAR value is too large");
      const auto offset = bytes.size();
      bytes.resize(offset + 4 + value.size());
      put_u32(bytes.data() + offset, static_cast<std::uint32_t>(value.size()));
      std::memcpy(bytes.data() + offset + 4, value.data(), value.size());
    }
  }
  return bytes;
}

Row decode_row(const Table &table, const std::uint8_t *data, std::size_t length) {
  Row row;
  std::size_t offset = 0;
  for (const auto &column : table.columns) {
    if (column.type == Type::Integer) {
      if (length - offset < 4) throw std::runtime_error("truncated INTEGER in page");
      const auto bits = get_u32(data + offset);
      const auto signed_value = bits <= 0x7fffffffu
                                    ? static_cast<std::int64_t>(bits)
                                    : static_cast<std::int64_t>(bits) - 0x100000000ll;
      row.emplace_back(static_cast<std::int32_t>(signed_value));
      offset += 4;
    } else {
      if (length - offset < 4) throw std::runtime_error("truncated VARCHAR length in page");
      const auto size = static_cast<std::size_t>(get_u32(data + offset));
      offset += 4;
      if (size > length - offset) throw std::runtime_error("truncated VARCHAR payload in page");
      row.emplace_back(std::string(reinterpret_cast<const char *>(data + offset), size));
      offset += size;
    }
  }
  if (offset != length) throw std::runtime_error("trailing bytes in stored tuple");
  return row;
}

void init_slotted_page(pb_page &page, std::int32_t next = PB_INVALID_PAGE_ID) {
  pb_page_init(&page, page.page_id);
  put_u32(page.data, static_cast<std::uint32_t>(next));
  put_u16(page.data + 4, 0);
  put_u16(page.data + 6, static_cast<std::uint16_t>(PB_PAGE_SIZE));
}

std::int32_t next_page(const pb_page &page) {
  return static_cast<std::int32_t>(get_u32(page.data));
}

int compare_values(const Value &left, const Value &right) {
  if (left.index() != right.index())
    throw std::runtime_error("cannot compare values of different types");
  if (std::holds_alternative<std::monostate>(left)) return 0;
  if (const auto *value = std::get_if<std::int32_t>(&left)) {
    const auto other = std::get<std::int32_t>(right);
    return *value < other ? -1 : *value > other ? 1 : 0;
  }
  if (const auto *value = std::get_if<std::int64_t>(&left)) {
    const auto other = std::get<std::int64_t>(right);
    return *value < other ? -1 : *value > other ? 1 : 0;
  }
  if (const auto *value = std::get_if<double>(&left)) {
    const auto other = std::get<double>(right);
    return *value < other ? -1 : *value > other ? 1 : 0;
  }
  const auto &value = std::get<std::string>(left);
  const auto &other = std::get<std::string>(right);
  return value < other ? -1 : value > other ? 1 : 0;
}

struct ValueVectorLess {
  bool operator()(const std::vector<Value> &left,
                  const std::vector<Value> &right) const {
    const auto common = std::min(left.size(), right.size());
    for (std::size_t i = 0; i < common; ++i) {
      const auto cmp = compare_values(left[i], right[i]);
      if (cmp != 0) return cmp < 0;
    }
    return left.size() < right.size();
  }
};

struct AggregateSpec {
  std::string operation;
  std::optional<std::size_t> column;
};

struct AggregateState {
  std::int64_t count{};
  std::int64_t total{};
  std::optional<Value> minimum;
  std::optional<Value> maximum;

  void add(const AggregateSpec &spec, const Row &row) {
    if (spec.operation == "COUNT" && !spec.column) {
      ++count;
      return;
    }
    const auto &value = row.at(*spec.column);
    if (spec.operation == "COUNT") {
      ++count;
      return;
    }
    if (spec.operation == "SUM" || spec.operation == "AVG") {
      if (!std::holds_alternative<std::int32_t>(value))
        throw std::runtime_error(spec.operation + " requires an INTEGER column");
      const auto number = static_cast<std::int64_t>(std::get<std::int32_t>(value));
      if ((number > 0 && total > std::numeric_limits<std::int64_t>::max() - number) ||
          (number < 0 && total < std::numeric_limits<std::int64_t>::min() - number))
        throw std::runtime_error(spec.operation + " aggregate overflow");
      total += number;
      ++count;
      return;
    }
    if (!minimum || compare_values(value, *minimum) < 0) minimum = value;
    if (!maximum || compare_values(value, *maximum) > 0) maximum = value;
    ++count;
  }

  Value finish(const std::string &operation) const {
    if (operation == "COUNT") return count;
    if (operation == "SUM") return total;
    if (operation == "AVG") {
      if (count == 0) return std::monostate{};
      return static_cast<double>(total) / static_cast<double>(count);
    }
    if (operation == "MIN") return minimum.value_or(Value{std::monostate{}});
    if (operation == "MAX") return maximum.value_or(Value{std::monostate{}});
    throw std::runtime_error("unsupported aggregate: " + operation);
  }
};

int compare_rows(const Row &left, const Row &right,
                 const std::vector<std::size_t> &columns,
                 const std::vector<bool> &descending) {
  for (std::size_t i = 0; i < columns.size(); ++i) {
    const auto cmp = compare_values(left.at(columns[i]), right.at(columns[i]));
    if (cmp != 0) return descending[i] ? -cmp : cmp;
  }
  return 0;
}

std::vector<Row> merge_sort_rows(std::vector<Row> rows,
                                 const std::vector<std::size_t> &columns,
                                 const std::vector<bool> &descending) {
  if (columns.empty()) return rows;
  if (columns.size() != descending.size())
    throw std::runtime_error("sort directions must match sort columns");
  constexpr std::size_t kRunSize = 1024;
  std::vector<std::vector<Row>> runs;
  for (std::size_t start = 0; start < rows.size(); start += kRunSize) {
    const auto end = std::min(rows.size(), start + kRunSize);
    std::vector<Row> run;
    run.reserve(end - start);
    for (std::size_t i = start; i < end; ++i) run.push_back(std::move(rows[i]));
    std::stable_sort(run.begin(), run.end(), [&](const Row &left, const Row &right) {
      return compare_rows(left, right, columns, descending) < 0;
    });
    runs.push_back(std::move(run));
  }
  if (runs.size() <= 1) return runs.empty() ? std::vector<Row>{} : std::move(runs.front());

  struct Cursor { std::size_t run; std::size_t position; };
  struct LaterRow {
    const std::vector<std::vector<Row>> *runs;
    const std::vector<std::size_t> *columns;
    const std::vector<bool> *descending;
    bool operator()(const Cursor &left, const Cursor &right) const {
      const auto cmp = compare_rows((*runs)[left.run][left.position],
                                    (*runs)[right.run][right.position],
                                    *columns, *descending);
      if (cmp != 0) return cmp > 0;
      return left.run > right.run;
    }
  };
  std::priority_queue<Cursor, std::vector<Cursor>, LaterRow> queue(
      LaterRow{&runs, &columns, &descending});
  for (std::size_t i = 0; i < runs.size(); ++i)
    if (!runs[i].empty()) queue.push({i, 0});
  std::vector<Row> sorted;
  sorted.reserve(rows.size());
  while (!queue.empty()) {
    const auto cursor = queue.top();
    queue.pop();
    sorted.push_back(std::move(runs[cursor.run][cursor.position]));
    const auto next = cursor.position + 1;
    if (next < runs[cursor.run].size()) queue.push({cursor.run, next});
  }
  return sorted;
}
std::uint16_t slot_count(const pb_page &page) { return get_u16(page.data + 4); }
std::uint16_t free_top(const pb_page &page) { return get_u16(page.data + 6); }
std::pair<std::uint16_t, std::uint16_t> slot_at(const pb_page &page, std::uint16_t slot) {
  const auto count = slot_count(page);
  if (slot >= count) throw std::runtime_error("slot number out of range");
  const auto offset = 8u + static_cast<std::size_t>(slot) * 4u;
  return {get_u16(page.data + offset), get_u16(page.data + offset + 2)};
}

}  // namespace

struct Engine::Impl {
  explicit Impl(std::filesystem::path path) : database_path(std::move(path)) {
    const auto parent = database_path.parent_path();
    if (!parent.empty()) std::filesystem::create_directories(parent);
    char error[256]{};
    pb_status status{};
    disk = pb_disk_open(database_path.string().c_str(), &status, error, sizeof(error));
    require_status(status, error);
    try {
      buffer_pool = std::make_unique<BufferPoolManager>(disk, 64);
      load_catalog();
    } catch (...) {
      buffer_pool.reset();
      char close_error[256]{};
      (void)pb_disk_close(disk, close_error, sizeof(close_error));
      disk = nullptr;
      throw;
    }
  }

  ~Impl() {
    if (disk != nullptr) {
      try {
        close();
      } catch (...) {
      }
    }
    if (buffer_pool != nullptr) buffer_pool.reset();
    if (disk != nullptr) {
      char error[256]{};
      (void)pb_disk_close(disk, error, sizeof(error));
      disk = nullptr;
    }
  }

  std::filesystem::path database_path;
  pb_disk_manager *disk{};
  std::unique_ptr<BufferPoolManager> buffer_pool;
  std::vector<Table> tables;
  bool closed{};

  void close() {
    if (closed) return;
    for (auto &table : tables)
      for (auto &index : table.indexes) index.tree->flush();
    save_catalog();
    buffer_pool->flush_all_pages();
    buffer_pool.reset();
    char error[256]{};
    const auto status = pb_disk_close(disk, error, sizeof(error));
    disk = nullptr;
    require_status(status, error);
    closed = true;
  }

  void check_open() const {
    if (closed || disk == nullptr) throw std::runtime_error("database is closed");
  }

  std::filesystem::path index_directory(const std::string &name) const {
    auto path = database_path;
    path += ".lsm";
    return path / name;
  }

  Table &get_table(const std::string &name) {
    const auto it = std::find_if(tables.begin(), tables.end(), [&](const Table &table) {
      return table.name == name;
    });
    if (it == tables.end()) throw std::runtime_error("table not found: " + name);
    return *it;
  }

  void load_catalog() {
    auto catalog_path = database_path;
    catalog_path += ".catalog";
    if (!std::filesystem::exists(catalog_path)) return;
    std::ifstream in(catalog_path);
    if (!in.good()) throw std::runtime_error("cannot read catalog: " + catalog_path.string());
    std::string magic;
    unsigned version{};
    if (!(in >> magic >> version) || magic != "PEBBLE_CATALOG" ||
        version < 1 || version > 3)
      throw std::runtime_error("unsupported or corrupt catalog file: " + catalog_path.string());
    std::size_t table_count{};
    if (!(in >> table_count)) throw std::runtime_error("corrupt catalog table count");
    for (std::size_t t = 0; t < table_count; ++t) {
      Table table;
      std::size_t column_count{};
      std::size_t index_count{};
      if (!(in >> std::quoted(table.name) >> table.first_page >> table.last_page >> column_count) ||
          (version >= 2 && !(in >> index_count)))
        throw std::runtime_error("corrupt catalog table record");
      if (table.first_page < 0 || table.last_page < 0 || column_count == 0)
        throw std::runtime_error("invalid catalog table metadata");
      for (std::size_t c = 0; c < column_count; ++c) {
        std::string name, type;
        if (!(in >> std::quoted(name) >> type) || (type != "I" && type != "V"))
          throw std::runtime_error("corrupt catalog column record");
        table.columns.push_back({name, type == "I" ? Type::Integer : Type::Varchar});
      }
      for (std::size_t i = 0; i < index_count; ++i) {
        IndexInfo index{.name = {}, .column_index = 0, .tree = nullptr};
        std::int32_t legacy_root{};
        if (!(in >> std::quoted(index.name) >> index.column_index) ||
            (version == 2 && !(in >> legacy_root)) ||
            index.column_index >= table.columns.size() ||
            table.columns[index.column_index].type != Type::Integer ||
            (version == 2 && legacy_root < 0))
          throw std::runtime_error("corrupt catalog index record");
        if (version == 3)
          index.tree =
              std::make_unique<LSMTree>(index_directory(index.name), 128, false);
        table.indexes.push_back(std::move(index));
      }
      tables.push_back(std::move(table));
    }
    if (version == 2) {
      for (auto &table : tables) {
        for (auto &index : table.indexes) {
          const auto directory = index_directory(index.name);
          std::error_code error;
          std::filesystem::remove_all(directory, error);
          if (error)
            throw std::runtime_error("cannot prepare LSM index migration at " +
                                     directory.string() + ": " + error.message());
          index.tree = std::make_unique<LSMTree>(directory);
          for (const auto &[rid, row] : scan_records(table))
            index.tree->insert(
                std::get<std::int32_t>(row[index.column_index]), rid);
          index.tree->flush();
        }
      }
      save_catalog();
    }
  }

  void save_catalog() {
    auto catalog_path = database_path;
    catalog_path += ".catalog";
    auto temp_path = catalog_path;
    temp_path += ".tmp";
    {
      std::ofstream out(temp_path, std::ios::trunc);
      if (!out) throw std::runtime_error("cannot write catalog: " + temp_path.string());
      out << "PEBBLE_CATALOG 3\n" << tables.size() << '\n';
      for (const auto &table : tables) {
        out << std::quoted(table.name) << ' ' << table.first_page << ' '
            << table.last_page << ' ' << table.columns.size() << ' '
            << table.indexes.size() << '\n';
        for (const auto &column : table.columns)
          out << std::quoted(column.name) << ' '
              << (column.type == Type::Integer ? "I" : "V") << '\n';
        for (const auto &index : table.indexes)
          out << std::quoted(index.name) << ' ' << index.column_index << '\n';
      }
      out.flush();
      if (!out) throw std::runtime_error("writing catalog failed");
    }
    std::error_code ec;
    std::filesystem::rename(temp_path, catalog_path, ec);
    if (ec) {
      std::filesystem::remove(temp_path);
      throw std::runtime_error("replacing catalog failed: " + ec.message());
    }
  }

  std::int32_t allocate_page() {
    char error[256]{};
    std::int32_t id{};
    require_status(pb_disk_allocate_page(disk, &id, error, sizeof(error)), error);
    return id;
  }

  pb_page read_page(std::int32_t id) const {
    return buffer_pool->read_page(id);
  }

  void write_page(const pb_page &page) const {
    buffer_pool->write_page(page);
  }

  RecordId insert_heap(Table &table, const std::vector<std::uint8_t> &bytes) {
    if (bytes.empty() || bytes.size() > PB_PAGE_SIZE - 8u - 4u)
      throw std::runtime_error("tuple is empty or too large");
    pb_page page = read_page(table.last_page);
    const auto count = slot_count(page);
    const auto top = free_top(page);
    const auto lower = 8u + static_cast<std::size_t>(count) * 4u;
    if (top < lower || static_cast<std::size_t>(top) - lower < 4u + bytes.size()) {
      const auto new_id = allocate_page();
      pb_page fresh{};
      fresh.page_id = new_id;
      init_slotted_page(fresh);
      put_u32(page.data, static_cast<std::uint32_t>(new_id));
      write_page(page);
      page = fresh;
      table.last_page = new_id;
    }
    const auto n = slot_count(page);
    const auto old_top = free_top(page);
    const auto new_top = static_cast<std::uint16_t>(old_top - bytes.size());
    std::memcpy(page.data + new_top, bytes.data(), bytes.size());
    const auto slot_offset = 8u + static_cast<std::size_t>(n) * 4u;
    put_u16(page.data + slot_offset, new_top);
    put_u16(page.data + slot_offset + 2, static_cast<std::uint16_t>(bytes.size()));
    put_u16(page.data + 4, static_cast<std::uint16_t>(n + 1));
    put_u16(page.data + 6, new_top);
    write_page(page);
    return RecordId{page.page_id, n};
  }

  RecordId insert(Table &table, const Row &row) {
    const auto bytes = encode_row(table, row);
    for (const auto &index : table.indexes) {
      const auto key = std::get<std::int32_t>(row[index.column_index]);
      if (index.tree->search(key).has_value())
        throw std::runtime_error("duplicate index key: " + std::to_string(key));
    }
    const auto rid = insert_heap(table, bytes);
    for (auto &index : table.indexes) {
      const auto key = std::get<std::int32_t>(row[index.column_index]);
      index.tree->insert(key, rid);
    }
    save_catalog();
    return rid;
  }

  void mark_deleted(RecordId rid) {
    auto page = read_page(rid.page_id);
    const auto [offset, length] = slot_at(page, rid.slot_num);
    if (length == 0 || offset + length > PB_PAGE_SIZE)
      throw std::runtime_error("record is already deleted or corrupt");
    put_u16(page.data + 8u + static_cast<std::size_t>(rid.slot_num) * 4u + 2u, 0);
    write_page(page);
  }

  bool row_matches(const Table &table, const Row &row,
                   const std::string &condition) const {
    static const std::regex where_re(
        R"(^\s*([\w.]+)\s*(=|!=|<=|>=|<|>)\s*(.+?)\s*$)");
    std::smatch where_match;
    if (!std::regex_match(condition, where_match, where_re))
      throw std::runtime_error("bad WHERE: " + condition);
    auto column_name = where_match[1].str();
    if (column_name.find('.') != std::string::npos)
      throw std::runtime_error("qualified columns are unsupported in DML WHERE");
    const auto index = column_index(table, column_name);
    const auto expected = parse_value(where_match[3].str());
    if (row.at(index).index() != expected.index())
      throw std::runtime_error("WHERE value type does not match column");
    const auto cmp = compare_values(row[index], expected);
    const auto op = where_match[2].str();
    if (op == "=") return cmp == 0;
    if (op == "!=") return cmp != 0;
    if (op == "<") return cmp < 0;
    if (op == "<=") return cmp <= 0;
    if (op == ">") return cmp > 0;
    return cmp >= 0;
  }

  Row get_record(const Table &table, RecordId rid) const {
    const auto page = read_page(rid.page_id);
    const auto [offset, length] = slot_at(page, rid.slot_num);
    if (length == 0 || offset < 8u + static_cast<std::size_t>(slot_count(page)) * 4u ||
        static_cast<std::size_t>(offset) + length > PB_PAGE_SIZE)
      throw std::runtime_error("invalid or deleted record id");
    return decode_row(table, page.data + offset, length);
  }

  std::vector<Row> scan(const Table &table) const {
    std::vector<Row> rows;
    for (auto &item : scan_records(table)) rows.push_back(std::move(item.second));
    return rows;
  }

  std::vector<std::pair<RecordId, Row>> scan_records(const Table &table) const {
    std::vector<std::pair<RecordId, Row>> rows;
    auto id = table.first_page;
    std::uint64_t pages_seen = 0;
    std::uint32_t page_count{};
    char error[256]{};
    require_status(pb_disk_page_count(disk, &page_count, error, sizeof(error)), error);
    while (id != PB_INVALID_PAGE_ID) {
      if (id < 0 || static_cast<std::uint32_t>(id) >= page_count || ++pages_seen > page_count)
        throw std::runtime_error("invalid or cyclic table page chain");
      const auto page = read_page(id);
      const auto count = slot_count(page);
      for (std::uint16_t slot = 0; slot < count; ++slot) {
        const auto [offset, length] = slot_at(page, slot);
        if (length == 0) continue;
        if (offset < 8u + static_cast<std::size_t>(count) * 4u ||
            static_cast<std::size_t>(offset) + length > PB_PAGE_SIZE)
          throw std::runtime_error("corrupt slot bounds");
        rows.emplace_back(RecordId{id, slot}, decode_row(table, page.data + offset, length));
      }
      id = next_page(page);
    }
    return rows;
  }

  ExecutionResult execute(const std::string &sql) {
    check_open();
    auto statement = trim(sql);
    while (!statement.empty() && statement.back() == ';') statement.pop_back();
    statement = trim(statement);
    if (statement.empty()) throw std::runtime_error("empty SQL");

    static const std::regex create_table(
        R"(^CREATE\s+TABLE\s+(\w+)\s*\((.+)\)\s*$)",
        std::regex::icase);
    std::smatch match;
    static const std::regex drop_table(
        R"(^DROP\s+TABLE\s+(\w+)\s*$)", std::regex::icase);
    if (std::regex_match(statement, match, drop_table)) {
      const auto table_name = match[1].str();
      const auto it = std::find_if(tables.begin(), tables.end(),
                                   [&](const Table &table) {
                                     return table.name == table_name;
                                   });
      if (it == tables.end())
        throw std::runtime_error("table not found: " + table_name);

      std::vector<std::filesystem::path> index_directories;
      index_directories.reserve(it->indexes.size());
      for (const auto &index : it->indexes)
        index_directories.push_back(index_directory(index.name));
      const auto position = static_cast<std::size_t>(it - tables.begin());
      Table removed = std::move(*it);
      tables.erase(it);
      try {
        save_catalog();
      } catch (...) {
        tables.insert(tables.begin() + static_cast<std::ptrdiff_t>(position),
                      std::move(removed));
        throw;
      }

      removed.indexes.clear();
      for (const auto &directory : index_directories) {
        std::error_code error;
        std::filesystem::remove_all(directory, error);
        if (error)
          throw std::runtime_error("cannot remove LSM index directory " +
                                   directory.string() + ": " + error.message());
      }
      ExecutionResult result;
      result.message = "Table '" + table_name + "' dropped";
      return result;
    }

    if (std::regex_match(statement, match, create_table)) {
      const auto name = match[1].str();
      if (std::any_of(tables.begin(), tables.end(), [&](const Table &t) { return t.name == name; }))
        throw std::runtime_error("table already exists: " + name);
      Table table{name, {}, -1, -1, {}};
      static const std::regex column_re(R"(^\s*(\w+)\s+(INTEGER|INT|VARCHAR)\s*$)",
                                        std::regex::icase);
      for (const auto &part : split_commas(match[2].str())) {
        std::smatch column_match;
        if (!std::regex_match(part, column_match, column_re))
          throw std::runtime_error("bad column definition: " + part);
        const auto type = upper(column_match[2].str());
        table.columns.push_back({column_match[1].str(), type == "VARCHAR" ? Type::Varchar : Type::Integer});
      }
      if (table.columns.empty()) throw std::runtime_error("schema must have at least one column");
      for (std::size_t i = 0; i < table.columns.size(); ++i)
        for (std::size_t j = 0; j < i; ++j)
          if (table.columns[i].name == table.columns[j].name)
            throw std::runtime_error("duplicate column: " + table.columns[i].name);
      table.first_page = table.last_page = allocate_page();
      auto page = read_page(table.first_page);
      init_slotted_page(page);
      write_page(page);
      tables.push_back(std::move(table));
      save_catalog();
      return {};
    }

    static const std::regex show_tables_re(R"(^SHOW\s+TABLES\s*$)",
                                           std::regex::icase);
    if (std::regex_match(statement, show_tables_re)) {
      ExecutionResult result;
      result.columns = {"Tables"};
      result.is_query = true;
      for (const auto &table : tables) result.rows.push_back({table.name});
      return result;
    }

    static const std::regex describe_re(R"(^DESCRIBE\s+(\w+)\s*$)",
                                        std::regex::icase);
    if (std::regex_match(statement, match, describe_re)) {
      const auto &table = get_table(match[1].str());
      ExecutionResult result;
      result.columns = {"Field", "Type"};
      result.is_query = true;
      for (const auto &column : table.columns) {
        result.rows.push_back({column.name,
                               column.type == Type::Integer ? "INTEGER" : "VARCHAR"});
      }
      return result;
    }

    static const std::regex create_index(
        R"(^CREATE\s+INDEX\s+(\w+)\s+ON\s+(\w+)\s*\((\w+)\)\s*$)",
        std::regex::icase);
    if (std::regex_match(statement, match, create_index)) {
      const auto index_name = match[1].str();
      const auto table_name = match[2].str();
      const auto column_name = match[3].str();
      for (const auto &existing_table : tables)
        for (const auto &existing_index : existing_table.indexes)
          if (existing_index.name == index_name)
            throw std::runtime_error("index already exists: " + index_name);
      auto &table = get_table(table_name);
      const auto index_column = column_index(table, column_name);
      if (table.columns[index_column].type != Type::Integer)
        throw std::runtime_error("index key column must be INTEGER");
      const auto directory = index_directory(index_name);
      std::error_code remove_error;
      std::filesystem::remove_all(directory, remove_error);
      if (remove_error)
        throw std::runtime_error("cannot prepare LSM index directory " +
                                 directory.string() + ": " +
                                 remove_error.message());
      auto tree = std::make_unique<LSMTree>(directory);
      for (const auto &[rid, row] : scan_records(table)) {
        tree->insert(std::get<std::int32_t>(row[index_column]), rid);
      }
      tree->flush();
      table.indexes.push_back({index_name, index_column, std::move(tree)});
      save_catalog();
      return {};
    }

    static const std::regex delete_re(
        R"(^DELETE\s+FROM\s+(\w+)(?:\s+WHERE\s+(.+))?\s*$)",
        std::regex::icase);
    if (std::regex_match(statement, match, delete_re)) {
      auto &table = get_table(match[1].str());
      const auto rows = scan_records(table);
      std::vector<RecordId> victims;
      for (const auto &[rid, row] : rows)
        if (!match[2].matched || row_matches(table, row, match[2].str()))
          victims.push_back(rid);
      for (const auto rid : victims) {
        const auto row = get_record(table, rid);
        for (auto &index : table.indexes) {
          const auto key = std::get<std::int32_t>(row[index.column_index]);
          if (!index.tree->erase(key))
            throw std::runtime_error("missing index entry during DELETE");
        }
      }
      for (const auto rid : victims) mark_deleted(rid);
      return ExecutionResult{{}, {}, victims.size(), false, {}};
    }

    static const std::regex update_re(
        R"(^UPDATE\s+(\w+)\s+SET\s+(.+?)(?:\s+WHERE\s+(.+))?\s*$)",
        std::regex::icase);
    if (std::regex_match(statement, match, update_re)) {
      auto &table = get_table(match[1].str());
      std::vector<std::pair<std::size_t, Value>> assignments;
      std::unordered_set<std::size_t> assigned_columns;
      static const std::regex assignment_re(R"(^\s*(\w+)\s*=\s*(.+?)\s*$)");
      for (const auto &assignment : split_commas(match[2].str())) {
        std::smatch assignment_match;
        if (!std::regex_match(assignment, assignment_match, assignment_re))
          throw std::runtime_error("bad UPDATE assignment: " + assignment);
        const auto column = column_index(table, assignment_match[1].str());
        if (!assigned_columns.insert(column).second)
          throw std::runtime_error("column assigned more than once: " + assignment_match[1].str());
        auto value = parse_value(assignment_match[2].str());
        const bool is_integer = std::holds_alternative<std::int32_t>(value);
        if ((table.columns[column].type == Type::Integer && !is_integer) ||
            (table.columns[column].type == Type::Varchar && is_integer))
          throw std::runtime_error("UPDATE value type does not match column " +
                                   table.columns[column].name);
        assignments.emplace_back(column, std::move(value));
      }
      if (assignments.empty()) throw std::runtime_error("UPDATE requires an assignment");

      struct Change {
        RecordId old_rid;
        Row old_row;
        Row new_row;
        std::vector<std::uint8_t> bytes;
        std::uint16_t old_length;
        RecordId new_rid;
        bool moved{};
      };
      std::vector<Change> changes;
      for (const auto &[rid, row] : scan_records(table)) {
        if (match[3].matched && !row_matches(table, row, match[3].str())) continue;
        Row replacement = row;
        for (const auto &[column, value] : assignments) replacement[column] = value;
        auto bytes = encode_row(table, replacement);
        if (bytes.empty() || bytes.size() > PB_PAGE_SIZE - 8u - 4u)
          throw std::runtime_error("updated tuple is empty or too large");
        const auto page = read_page(rid.page_id);
        const auto slot = slot_at(page, rid.slot_num);
        changes.push_back({rid, row, std::move(replacement), std::move(bytes),
                           slot.second, rid, false});
      }

      // Validate every unique index against the final table state before
      // changing rows or index pages. This also permits swaps of unique keys.
      for (const auto &index : table.indexes) {
        std::unordered_set<std::int32_t> keys;
        for (const auto &[rid, row] : scan_records(table)) {
          const auto change = std::find_if(changes.begin(), changes.end(),
              [&](const Change &item) {
                return item.old_rid.page_id == rid.page_id &&
                       item.old_rid.slot_num == rid.slot_num;
              });
          const auto &final_row = change == changes.end() ? row : change->new_row;
          const auto key = std::get<std::int32_t>(final_row[index.column_index]);
          if (!keys.insert(key).second)
            throw std::runtime_error("duplicate index key after UPDATE: " +
                                     std::to_string(key));
        }
      }

      // Append rows that no longer fit their original slots before removing
      // old versions. Shorter/equal rows reuse the existing slot.
      for (auto &change : changes) {
        if (change.bytes.size() > change.old_length) {
          change.new_rid = insert_heap(table, change.bytes);
          change.moved = true;
        }
      }
      for (auto &change : changes) {
        if (change.moved) {
          mark_deleted(change.old_rid);
        } else {
          auto page = read_page(change.old_rid.page_id);
          const auto [offset, length] = slot_at(page, change.old_rid.slot_num);
          if (length != change.old_length) throw std::runtime_error("row changed during UPDATE");
          std::memcpy(page.data + offset, change.bytes.data(), change.bytes.size());
          put_u16(page.data + 8u + static_cast<std::size_t>(change.old_rid.slot_num) * 4u + 2u,
                  static_cast<std::uint16_t>(change.bytes.size()));
          write_page(page);
        }
      }

      // Erase all old index entries before inserting replacements so valid
      // unique-key swaps do not conflict with their old values.
      for (const auto &change : changes) {
        for (auto &index : table.indexes) {
          const auto key = std::get<std::int32_t>(change.old_row[index.column_index]);
          if (!index.tree->erase(key))
            throw std::runtime_error("missing index entry during UPDATE");
        }
      }
      for (const auto &change : changes) {
        for (auto &index : table.indexes) {
          const auto key = std::get<std::int32_t>(change.new_row[index.column_index]);
          index.tree->insert(key, change.new_rid);
        }
      }
      save_catalog();
      return ExecutionResult{{}, {}, changes.size(), false, {}};
    }

    static const std::regex insert_re(R"(^INSERT\s+INTO\s+(\w+)\s+VALUES\s*(.+)$)",
                                      std::regex::icase);
    if (std::regex_match(statement, match, insert_re)) {
      auto &table = get_table(match[1].str());
      const auto values = match[2].str();
      std::size_t position = 0;
      std::size_t inserted = 0;
      while (position < values.size()) {
        while (position < values.size() && (std::isspace(static_cast<unsigned char>(values[position])) || values[position] == ',')) ++position;
        if (position == values.size()) break;
        if (values[position++] != '(') throw std::runtime_error("expected '(' in VALUES");
        const auto start = position;
        int depth = 1;
        bool in_string = false;
        while (position < values.size() && depth != 0) {
          const char ch = values[position];
          if (ch == '\'') {
            if (in_string && position + 1 < values.size() && values[position + 1] == '\'') {
              position += 2;
              continue;
            }
            in_string = !in_string;
          } else if (!in_string && ch == '(') {
            ++depth;
          } else if (!in_string && ch == ')') {
            --depth;
          }
          ++position;
        }
        if (depth != 0) throw std::runtime_error("unclosed row in VALUES");
        const auto row_text = values.substr(start, position - start - 1);
        Row row;
        for (const auto &value : split_commas(row_text)) row.push_back(parse_value(value));
        (void)insert(table, row);
        ++inserted;
      }
      if (inserted == 0) throw std::runtime_error("INSERT VALUES needs at least one row");
      return ExecutionResult{{}, {}, inserted, false, {}};
    }

    static const std::regex select_re(
        R"(^SELECT\s+(.+?)\s+FROM\s+(\w+)(?:\s+JOIN\s+(\w+)\s+ON\s+(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+))?(?:\s+WHERE\s+(.+?))?(?:\s+GROUP\s+BY\s+(.+?))?(?:\s+ORDER\s+BY\s+(.+?))?(?:\s+LIMIT\s+(\d+)(?:\s+OFFSET\s+(\d+))?)?\s*$)",
        std::regex::icase);
    if (!std::regex_match(statement, match, select_re))
      throw std::runtime_error("unsupported SQL: " + statement);

    const auto columns_text = trim(match[1].str());
    const auto left_name = match[2].str();
    const bool has_join = match[3].matched;
    const auto &left = get_table(left_name);
    const Table *right = has_join ? &get_table(match[3].str()) : nullptr;
    std::vector<Row> input;
    std::vector<Row> left_rows;
    bool used_index = false;
    if (!has_join && match[8].matched) {
      static const std::regex index_predicate_re(
          R"(^\s*([\w.]+)\s*(=|!=|<=|>=|<|>)\s*(.+?)\s*$)");
      std::smatch predicate_match;
      const auto where_candidate = match[8].str();
      if (std::regex_match(where_candidate, predicate_match, index_predicate_re)) {
        std::optional<std::int32_t> key;
        try {
          const auto literal = parse_value(predicate_match[3].str());
          if (std::holds_alternative<std::int32_t>(literal))
            key = std::get<std::int32_t>(literal);
        } catch (const std::runtime_error &) {
          // The normal binder below reports malformed literals.
        }
        const auto op = predicate_match[2].str();
        if (key && op != "!=") {
          const auto column = resolve_column(predicate_match[1].str(), left,
                                             nullptr, left_name);
          if (left.columns[column].type == Type::Integer) {
            const auto indexed = std::find_if(left.indexes.begin(), left.indexes.end(),
                [&](const IndexInfo &index) { return index.column_index == column; });
            if (indexed != left.indexes.end()) {
              const auto &tree = *indexed->tree;
              std::vector<std::pair<std::int32_t, RecordId>> matches;
              if (op == "=") {
                const auto rid = tree.search(*key);
                if (rid.has_value()) matches.emplace_back(*key, *rid);
              } else if (op == ">" || op == ">=") {
                matches = tree.scan(*key, std::nullopt);
                if (op == ">")
                  matches.erase(std::remove_if(matches.begin(), matches.end(),
                      [&](const auto &entry) { return entry.first == *key; }), matches.end());
              } else {
                matches = tree.scan(std::nullopt, *key);
                if (op == "<")
                  matches.erase(std::remove_if(matches.begin(), matches.end(),
                      [&](const auto &entry) { return entry.first == *key; }), matches.end());
              }
              std::sort(matches.begin(), matches.end(), [](const auto &a, const auto &b) {
                if (a.second.page_id != b.second.page_id)
                  return a.second.page_id < b.second.page_id;
                return a.second.slot_num < b.second.slot_num;
              });
              used_index = true;
              for (const auto &entry : matches)
                left_rows.push_back(get_record(left, entry.second));
            }
          }
        }
      }
    }
    if (!used_index) left_rows = scan(left);
    if (!has_join) {
      input = left_rows;
    } else {
      const auto right_rows = scan(*right);
      const auto left_table_name = match[4].str();
      const auto left_column = match[5].str();
      const auto right_table_name = match[6].str();
      const auto right_column = match[7].str();
      std::size_t left_key, right_key;
      if (left_table_name == left_name && right_table_name == right->name) {
        left_key = column_index(left, left_column);
        right_key = column_index(*right, right_column);
      } else if (left_table_name == right->name && right_table_name == left_name) {
        left_key = column_index(left, right_column);
        right_key = column_index(*right, left_column);
      } else {
        throw std::runtime_error("JOIN ON tables must match FROM/JOIN names");
      }
      std::unordered_map<Value, std::vector<const Row *>> right_hash;
      right_hash.reserve(right_rows.size());
      for (const auto &rrow : right_rows)
        right_hash[rrow[right_key]].push_back(&rrow);
      for (const auto &lrow : left_rows) {
        const auto found = right_hash.find(lrow[left_key]);
        if (found == right_hash.end()) continue;
        for (const auto *rrow : found->second) {
          Row joined = lrow;
          joined.insert(joined.end(), rrow->begin(), rrow->end());
          input.push_back(std::move(joined));
        }
      }
    }

    if (match[8].matched) {
      static const std::regex where_re(R"(^\s*([\w.]+)\s*(=|!=|<=|>=|<|>)\s*(.+?)\s*$)");
      std::smatch where_match;
      const auto where_text = match[8].str();
      if (!std::regex_match(where_text, where_match, where_re))
        throw std::runtime_error("bad WHERE: " + where_text);
      const auto index = resolve_column(where_match[1].str(), left, right, left_name);
      const auto op = where_match[2].str();
      const auto literal = parse_value(where_match[3].str());
      input.erase(std::remove_if(input.begin(), input.end(), [&](const Row &row) {
        const auto &value = row[index];
        if (value.index() != literal.index())
          throw std::runtime_error("WHERE value type does not match column");
        const auto cmp = compare_values(value, literal);
        if (op == "=") return cmp != 0;
        if (op == "!=") return cmp == 0;
        if (op == "<") return cmp >= 0;
        if (op == "<=") return cmp > 0;
        if (op == ">") return cmp <= 0;
        return cmp < 0;
      }), input.end());
    }

    std::vector<std::size_t> group_indexes;
    if (match[9].matched) {
      for (const auto &item : split_commas(match[9].str()))
        group_indexes.push_back(resolve_column(trim(item), left, right, left_name));
    }

    const auto select_items = columns_text == "*"
                                  ? std::vector<std::string>{"*"}
                                  : split_commas(columns_text);
    std::vector<std::string> result_columns;
    if (columns_text == "*") {
      for (const auto &column : left.columns) result_columns.push_back(column.name);
      if (right != nullptr)
        for (const auto &column : right->columns) result_columns.push_back(column.name);
    } else {
      result_columns.reserve(select_items.size());
      for (const auto &item : select_items) result_columns.push_back(trim(item));
    }
    static const std::regex aggregate_re(
        R"(^\s*(COUNT|SUM|AVG|MIN|MAX)\s*\(\s*(\*|[\w.]+)\s*\)\s*$)",
        std::regex::icase);
    struct SelectedExpression {
      bool aggregate;
      std::size_t index;
    };
    std::vector<AggregateSpec> aggregate_specs;
    std::vector<SelectedExpression> selected_expressions;
    bool has_aggregate = false;
    if (columns_text != "*") {
      for (const auto &item : select_items) {
        std::smatch aggregate_match;
        if (std::regex_match(item, aggregate_match, aggregate_re)) {
          has_aggregate = true;
          const auto operation = upper(aggregate_match[1].str());
          const auto argument = aggregate_match[2].str();
          if (argument == "*" && operation != "COUNT")
            throw std::runtime_error(operation + "(*) is not supported");
          std::optional<std::size_t> column;
          if (argument != "*") {
            column = resolve_column(argument, left, right, left_name);
            if ((operation == "SUM" || operation == "AVG") &&
                ((*column < left.columns.size() &&
                  left.columns[*column].type != Type::Integer) ||
                 (*column >= left.columns.size() &&
                  (right == nullptr ||
                   right->columns[*column - left.columns.size()].type != Type::Integer))))
              throw std::runtime_error(operation + " requires an INTEGER column");
          }
          aggregate_specs.push_back({operation, column});
          selected_expressions.push_back({true, aggregate_specs.size() - 1});
        } else {
          if (item == "*")
            throw std::runtime_error("SELECT * cannot be combined with aggregates");
          selected_expressions.push_back(
              {false, resolve_column(trim(item), left, right, left_name)});
        }
      }
    }

    std::vector<Row> projected;
    if (has_aggregate || !group_indexes.empty()) {
      using Groups = std::map<std::vector<Value>, std::vector<AggregateState>,
                              ValueVectorLess>;
      Groups groups;
      if (has_aggregate && group_indexes.empty())
        groups.emplace(std::vector<Value>{},
                       std::vector<AggregateState>(aggregate_specs.size()));
      for (const auto &row : input) {
        std::vector<Value> key;
        key.reserve(group_indexes.size());
        for (const auto index : group_indexes) key.push_back(row.at(index));
        auto [it, inserted] = groups.try_emplace(
            std::move(key), std::vector<AggregateState>(aggregate_specs.size()));
        (void)inserted;
        for (std::size_t i = 0; i < aggregate_specs.size(); ++i)
          it->second[i].add(aggregate_specs[i], row);
      }

      if (!has_aggregate) {
        if (columns_text == "*")
          throw std::runtime_error("SELECT * with GROUP BY is unsupported");
        for (const auto &item : select_items) {
          const auto source = resolve_column(trim(item), left, right, left_name);
          if (std::find(group_indexes.begin(), group_indexes.end(), source) ==
              group_indexes.end())
            throw std::runtime_error("selected column must appear in GROUP BY: " + item);
        }
      } else {
        for (const auto &expression : selected_expressions) {
          if (!expression.aggregate &&
              std::find(group_indexes.begin(), group_indexes.end(), expression.index) ==
                  group_indexes.end())
            throw std::runtime_error("selected column must appear in GROUP BY");
        }
      }

      for (const auto &[key, states] : groups) {
        Row out;
        out.reserve(selected_expressions.size());
        for (const auto &expression : selected_expressions) {
          if (expression.aggregate) {
            const auto index = expression.index;
            out.push_back(states[index].finish(aggregate_specs[index].operation));
          } else {
            const auto it = std::find(group_indexes.begin(), group_indexes.end(),
                                      expression.index);
            out.push_back(key[static_cast<std::size_t>(it - group_indexes.begin())]);
          }
        }
        projected.push_back(std::move(out));
      }
    } else {
      if (match[10].matched) {
        std::vector<std::size_t> order_columns;
        std::vector<bool> order_descending;
        static const std::regex order_re(
            R"(^\s*([\w.]+)(?:\s+(ASC|DESC))?\s*$)", std::regex::icase);
        for (const auto &item : split_commas(match[10].str())) {
          std::smatch order_match;
          if (!std::regex_match(item, order_match, order_re))
            throw std::runtime_error("bad ORDER BY expression: " + item);
          order_columns.push_back(resolve_column(order_match[1].str(), left, right,
                                                 left_name));
          order_descending.push_back(order_match[2].matched &&
                                     upper(order_match[2].str()) == "DESC");
        }
        input = merge_sort_rows(std::move(input), order_columns, order_descending);
      }
      if (columns_text == "*") {
        projected = std::move(input);
      } else {
        projected.reserve(input.size());
        for (const auto &row : input) {
          Row out;
          out.reserve(selected_expressions.size());
          for (const auto &expression : selected_expressions)
            out.push_back(row.at(expression.index));
          projected.push_back(std::move(out));
        }
      }
    }

    if ((has_aggregate || !group_indexes.empty()) && match[10].matched) {
      std::vector<std::size_t> order_columns;
      std::vector<bool> order_descending;
      static const std::regex order_re(
          R"(^\s*(.+?)(?:\s+(ASC|DESC))?\s*$)", std::regex::icase);
      for (const auto &item : split_commas(match[10].str())) {
        std::smatch order_match;
        if (!std::regex_match(item, order_match, order_re))
          throw std::runtime_error("bad ORDER BY expression: " + item);
        const auto expression = upper(trim(order_match[1].str()));
        const auto selected = std::find_if(select_items.begin(), select_items.end(),
            [&](const std::string &selected_item) {
              return upper(trim(selected_item)) == expression;
            });
        if (selected == select_items.end())
          throw std::runtime_error("ORDER BY aggregate queries must use a selected expression");
        order_columns.push_back(static_cast<std::size_t>(selected - select_items.begin()));
        order_descending.push_back(order_match[2].matched &&
                                   upper(order_match[2].str()) == "DESC");
      }
      projected = merge_sort_rows(std::move(projected), order_columns,
                                  order_descending);
    }

    if (match[11].matched) {
      std::size_t limit{};
      const auto limit_text = match[11].str();
      const auto parsed = std::from_chars(limit_text.data(),
                                          limit_text.data() + limit_text.size(), limit);
      if (parsed.ec != std::errc{}) throw std::runtime_error("invalid LIMIT value");
      std::size_t offset{};
      if (match[12].matched) {
        const auto offset_text = match[12].str();
        const auto offset_parse = std::from_chars(offset_text.data(),
                                                  offset_text.data() + offset_text.size(),
                                                  offset);
        if (offset_parse.ec != std::errc{}) throw std::runtime_error("invalid OFFSET value");
      }
      const auto first = std::min(offset, projected.size());
      const auto count = std::min(limit, projected.size() - first);
      ExecutionResult result;
      result.columns = std::move(result_columns);
      result.rows.assign(projected.begin() + static_cast<std::ptrdiff_t>(first),
                         projected.begin() + static_cast<std::ptrdiff_t>(first + count));
      result.is_query = true;
      return result;
    }
    ExecutionResult result;
    result.columns = std::move(result_columns);
    result.rows = std::move(projected);
    result.is_query = true;
    return result;
  }

  static std::size_t column_index(const Table &table, const std::string &name) {
    for (std::size_t i = 0; i < table.columns.size(); ++i)
      if (table.columns[i].name == name) return i;
    throw std::runtime_error("unknown column: " + name);
  }

  static std::size_t resolve_column(const std::string &name, const Table &left,
                                    const Table *right, const std::string &left_name) {
    const auto dot = name.find('.');
    if (dot != std::string::npos) {
      const auto table_name = name.substr(0, dot);
      const auto column = name.substr(dot + 1);
      if (table_name == left_name) return column_index(left, column);
      if (right != nullptr && table_name == right->name)
        return left.columns.size() + column_index(*right, column);
      throw std::runtime_error("unknown table qualifier: " + table_name);
    }
    if (right == nullptr) return column_index(left, name);
    bool left_has = false, right_has = false;
    for (const auto &col : left.columns) left_has |= col.name == name;
    for (const auto &col : right->columns) right_has |= col.name == name;
    if (left_has == right_has) throw std::runtime_error("unknown or ambiguous column: " + name);
    return left_has ? column_index(left, name) : left.columns.size() + column_index(*right, name);
  }
};

Engine::Engine(std::filesystem::path database_path) : impl_(new Impl(std::move(database_path))) {}
Engine::~Engine() { delete impl_; }
std::vector<Row> Engine::execute(const std::string &sql) {
  return execute_statement(sql).rows;
}
ExecutionResult Engine::execute_statement(const std::string &sql) {
  return impl_->execute(sql);
}
void Engine::close() { impl_->close(); }

std::string value_to_string(const Value &value) {
  if (const auto *integer = std::get_if<std::int32_t>(&value))
    return std::to_string(*integer);
  if (const auto *integer = std::get_if<std::int64_t>(&value))
    return std::to_string(*integer);
  if (const auto *number = std::get_if<double>(&value)) {
    std::ostringstream out;
    out << std::setprecision(15) << *number;
    return out.str();
  }
  if (const auto *text = std::get_if<std::string>(&value)) return *text;
  return "NULL";
}

}  // namespace pebble
