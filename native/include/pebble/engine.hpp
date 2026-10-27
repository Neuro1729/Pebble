#ifndef PEBBLE_ENGINE_HPP
#define PEBBLE_ENGINE_HPP

#include <cstdint>
#include <cstddef>
#include <filesystem>
#include <string>
#include <variant>
#include <vector>

namespace pebble {

// Persisted table values remain INTEGER/VARCHAR. Query operators can also
// produce wider counts/sums, averages, and SQL-style NULL aggregate results.
using Value = std::variant<std::int32_t, std::int64_t, double, std::string,
                           std::monostate>;
using Row = std::vector<Value>;

struct ExecutionResult {
  std::vector<std::string> columns;
  std::vector<Row> rows;
  std::size_t affected_rows{};
  bool is_query{};
  std::string message;
};

class Engine {
 public:
  explicit Engine(std::filesystem::path database_path);
  ~Engine();

  Engine(const Engine &) = delete;
  Engine &operator=(const Engine &) = delete;
  Engine(Engine &&) = delete;
  Engine &operator=(Engine &&) = delete;

  // Supported: CREATE TABLE/INDEX, INSERT, literal UPDATE/DELETE, and SELECT
  // with one equality JOIN, WHERE, GROUP BY aggregates, ORDER BY, LIMIT, and
  // OFFSET. SHOW TABLES and DESCRIBE are supported. Unsupported SQL raises.
  std::vector<Row> execute(const std::string &sql);
  ExecutionResult execute_statement(const std::string &sql);
  void close();

 private:
  struct Impl;
  Impl *impl_;
};

std::string value_to_string(const Value &value);

}  // namespace pebble

#endif
