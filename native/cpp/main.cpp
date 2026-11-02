// Provides the Pebble command-line client. It handles command-line options,
// database selection, SQL input, and displaying query results.

#include "pebble/engine.hpp"

#include <algorithm>
#include <chrono>
#include <cctype>
#include <csignal>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <optional>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#if defined(__APPLE__) || defined(__linux__) || defined(__unix__)
#include <signal.h>
#include <unistd.h>
#endif

namespace {

volatile std::sig_atomic_t interrupted = 0;

// Records a Ctrl-C signal so the input loop can handle it safely.
void handle_sigint(int) { interrupted = 1; }

// Removes whitespace around input text.
std::string trim(std::string text) {
  const auto first = text.find_first_not_of(" \t\r\n");
  if (first == std::string::npos) return {};
  const auto last = text.find_last_not_of(" \t\r\n");
  return text.substr(first, last - first + 1);
}

// Replaces line breaks outside quoted text with spaces for SQL parsing.
std::string normalize_statement_whitespace(const std::string &statement) {
  std::string normalized;
  normalized.reserve(statement.size());
  char quote = '\0';
  for (std::size_t i = 0; i < statement.size(); ++i) {
    const char ch = statement[i];
    if (quote != '\0') {
      normalized.push_back(ch);
      if (ch == quote) {
        if (i + 1 < statement.size() && statement[i + 1] == quote) {
          normalized.push_back(statement[++i]);
        } else {
          quote = '\0';
        }
      } else if (ch == '\\' && i + 1 < statement.size()) {
        normalized.push_back(statement[++i]);
      }
    } else if (ch == '\'' || ch == '"') {
      quote = ch;
      normalized.push_back(ch);
    } else if (ch == '\n' || ch == '\r' || ch == '\t') {
      normalized.push_back(' ');
    } else {
      normalized.push_back(ch);
    }
  }
  return trim(std::move(normalized));
}

// Converts text to lowercase for command matching.
std::string lower(std::string text) {
  std::transform(text.begin(), text.end(), text.begin(), [](unsigned char ch) {
    return static_cast<char>(std::tolower(ch));
  });
  return text;
}

// Checks whether input is connected to a terminal.
bool stdin_is_terminal() {
#if defined(__APPLE__) || defined(__linux__) || defined(__unix__)
  return ::isatty(STDIN_FILENO) != 0;
#else
  return false;
#endif
}

// Checks whether output is connected to a terminal.
bool stdout_is_terminal() {
#if defined(__APPLE__) || defined(__linux__) || defined(__unix__)
  return ::isatty(STDOUT_FILENO) != 0;
#else
  return false;
#endif
}

// Chooses the data folder from the environment or the current directory.
std::filesystem::path default_data_directory() {
  if (const auto *configured = std::getenv("PEBBLE_DATA_DIR");
      configured != nullptr && configured[0] != '\0')
    return configured;
  return std::filesystem::current_path() / "data";
}

// Checks that a database name uses the supported identifier format.
bool valid_database_name(const std::string &name) {
  static const std::regex identifier(R"(^[A-Za-z_][A-Za-z0-9_]*$)");
  return std::regex_match(name, identifier);
}

// Creates a result for client commands that return a status message.
pebble::ExecutionResult command_result(std::string message) {
  pebble::ExecutionResult result;
  result.message = std::move(message);
  return result;
}

class ClientSession {
 public:
  // Sets up a client session using the selected database folder.
  explicit ClientSession(std::filesystem::path data_directory)
      : data_directory_(std::move(data_directory)) {}

  // Opens the database file provided directly by the user.
  void open_file(const std::filesystem::path &path) {
    auto candidate = std::make_unique<pebble::Engine>(path);
    close_current();
    engine_ = std::move(candidate);
    database_name_ = path.stem().string();
    database_path_ = path;
  }

  // Runs a client command or passes SQL through to the active database.
  pebble::ExecutionResult execute(const std::string &sql) {
    auto statement = normalize_statement_whitespace(sql);
    static const std::regex create_database_re(
        R"(^CREATE\s+DATABASE\s+([A-Za-z_][A-Za-z0-9_]*)\s*$)",
        std::regex::icase);
    static const std::regex use_re(
        R"(^USE\s+([A-Za-z_][A-Za-z0-9_]*)\s*$)", std::regex::icase);
    static const std::regex show_databases_re(
        R"(^SHOW\s+DATABASES\s*$)", std::regex::icase);
    std::smatch match;

    if (std::regex_match(statement, match, create_database_re))
      return create_database(match[1].str());
    if (std::regex_match(statement, match, use_re))
      return use_database(match[1].str());
    if (std::regex_match(statement, show_databases_re))
      return show_databases();
    if (engine_ == nullptr)
      throw std::runtime_error("no database selected; use CREATE DATABASE and USE");
    return engine_->execute_statement(statement);
  }

  // Returns the active database name for the command prompt.
  std::string database_label() const {
    return database_name_.empty() ? "(none)" : database_name_;
  }

  // Returns the current database details and available features.
  std::string status() const {
    std::ostringstream out;
    out << "Database: " << database_label() << '\n'
        << "Path: " << (database_path_.empty() ? data_directory_.string()
                                               : database_path_.string()) << '\n'
        << "Native transactions, WAL, and recovery: unavailable";
    return out.str();
  }

  // Closes the active database.
  void close() { close_current(); }

 private:
  std::filesystem::path data_directory_;
  std::filesystem::path database_path_;
  std::string database_name_;
  std::unique_ptr<pebble::Engine> engine_;

  // Builds the file path for a named database.
  std::filesystem::path database_file(const std::string &name) const {
    return data_directory_ / (name + ".db");
  }

  // Creates an empty named database in the data folder.
  pebble::ExecutionResult create_database(const std::string &name) {
    if (!valid_database_name(name)) throw std::runtime_error("invalid database name");
    std::error_code ec;
    std::filesystem::create_directories(data_directory_, ec);
    if (ec) throw std::runtime_error("cannot create database directory: " + ec.message());
    const auto path = database_file(name);
    auto catalog_path = path;
    catalog_path += ".catalog";
    if (std::filesystem::exists(path) || std::filesystem::exists(catalog_path))
      throw std::runtime_error("database already exists: " + name);
    try {
      pebble::Engine created(path);
      created.close();
    } catch (...) {
      std::filesystem::remove(path, ec);
      std::filesystem::remove(catalog_path, ec);
      auto temp_path = catalog_path;
      temp_path += ".tmp";
      std::filesystem::remove(temp_path, ec);
      throw;
    }
    return command_result("Database '" + name + "' created");
  }

  // Opens an existing named database as the active database.
  pebble::ExecutionResult use_database(const std::string &name) {
    if (!valid_database_name(name)) throw std::runtime_error("invalid database name");
    const auto path = database_file(name);
    auto catalog_path = path;
    catalog_path += ".catalog";
    if (!std::filesystem::is_regular_file(path) ||
        !std::filesystem::is_regular_file(catalog_path))
      throw std::runtime_error("database does not exist: " + name);
    auto candidate = std::make_unique<pebble::Engine>(path);
    close_current();
    engine_ = std::move(candidate);
    database_name_ = name;
    database_path_ = path;
    return command_result("Database changed to '" + name + "'");
  }

  // Lists named databases found in the data folder.
  pebble::ExecutionResult show_databases() const {
    pebble::ExecutionResult result;
    result.columns = {"Database"};
    result.is_query = true;
    std::error_code ec;
    if (!std::filesystem::is_directory(data_directory_, ec)) return result;
    for (std::filesystem::directory_iterator it(data_directory_, ec), end;
         !ec && it != end; it.increment(ec)) {
      const auto filename = it->path().filename().string();
      constexpr std::string_view suffix = ".db.catalog";
      if (filename.size() <= suffix.size() ||
          filename.compare(filename.size() - suffix.size(), suffix.size(), suffix) != 0)
        continue;
      const auto name = filename.substr(0, filename.size() - suffix.size());
      if (!valid_database_name(name)) continue;
      const auto db_path = database_file(name);
      if (std::filesystem::is_regular_file(db_path, ec) && !ec)
        result.rows.push_back({name});
      ec.clear();
    }
    std::sort(result.rows.begin(), result.rows.end(), [](const pebble::Row &a,
                                                         const pebble::Row &b) {
      return std::get<std::string>(a[0]) < std::get<std::string>(b[0]);
    });
    return result;
  }

  // Closes and clears the active database, if one is open.
  void close_current() {
    if (engine_ == nullptr) return;
    engine_->close();
    engine_.reset();
  }
};

// Escapes control characters so values can be printed on one line.
std::string display_value(const pebble::Value &value) {
  const auto raw = pebble::value_to_string(value);
  std::string escaped;
  escaped.reserve(raw.size());
  static constexpr char hex[] = "0123456789ABCDEF";
  for (const unsigned char ch : raw) {
    if (ch == '\n') escaped += "\\n";
    else if (ch == '\r') escaped += "\\r";
    else if (ch == '\t') escaped += "\\t";
    else if (ch == '\\') escaped += "\\\\";
    else if (ch < 0x20 || ch == 0x7f) {
      escaped += "\\x";
      escaped.push_back(hex[ch >> 4]);
      escaped.push_back(hex[ch & 0x0f]);
    } else {
      escaped.push_back(static_cast<char>(ch));
    }
  }
  return escaped;
}

// Formats table cells while distinguishing NULL values from the text "NULL".
std::string display_table_value(const pebble::Value &value) {
  if (std::holds_alternative<std::monostate>(value)) return "NULL";
  if (const auto *text = std::get_if<std::string>(&value);
      text != nullptr && *text == "NULL")
    return "\"NULL\"";
  return display_value(value);
}

// Prints query results in a table with columns sized to their contents.
void print_table(const pebble::ExecutionResult &result) {
  const auto column_count = result.columns.size();
  if (column_count == 0) {
    std::cout << "Query returned no columns\n";
    return;
  }
  std::vector<std::size_t> widths(column_count);
  for (std::size_t i = 0; i < column_count; ++i)
    widths[i] = result.columns[i].size();
  std::vector<std::vector<std::string>> cells;
  cells.reserve(result.rows.size());
  for (const auto &row : result.rows) {
    std::vector<std::string> display_row;
    display_row.reserve(column_count);
    for (std::size_t i = 0; i < column_count; ++i) {
      const auto cell = i < row.size() ? display_table_value(row[i]) : std::string{};
      widths[i] = std::max(widths[i], cell.size());
      display_row.push_back(cell);
    }
    cells.push_back(std::move(display_row));
  }
  auto border = [&] {
    std::cout << '+';
    for (const auto width : widths) std::cout << std::string(width + 2, '-') << '+';
    std::cout << '\n';
  };
  auto print_row = [&](const std::vector<std::string> &row) {
    std::cout << '|';
    for (std::size_t i = 0; i < column_count; ++i) {
      const auto &cell = row[i];
      std::cout << ' ' << cell << std::string(widths[i] - cell.size() + 1, ' ') << '|';
    }
    std::cout << '\n';
  };
  border();
  print_row(result.columns);
  border();
  for (const auto &row : cells) print_row(row);
  border();
  std::cout << result.rows.size() << (result.rows.size() == 1 ? " row in set\n"
                                                              : " rows in set\n");
}

// Prints query rows or a status message in the selected output style.
void print_result(const pebble::ExecutionResult &result, bool table_output,
                  bool interactive) {
  if (result.is_query) {
    if (table_output) {
      print_table(result);
    } else if (result.rows.empty()) {
      std::cout << "OK\n";
    } else {
      for (const auto &row : result.rows) {
        for (std::size_t i = 0; i < row.size(); ++i) {
          if (i != 0) std::cout << " | ";
          std::cout << display_value(row[i]);
        }
        std::cout << '\n';
      }
    }
    return;
  }
  if (interactive || table_output) {
    if (!result.message.empty()) std::cout << "Query OK. " << result.message << ".\n";
    else if (result.affected_rows != 0)
      std::cout << "Query OK, " << result.affected_rows << " row"
                << (result.affected_rows == 1 ? "" : "s") << " affected\n";
    else std::cout << "Query OK\n";
  } else {
    std::cout << "OK\n";
  }
}

// Prints the time spent executing a statement.
void print_timing(std::chrono::steady_clock::duration elapsed) {
  const std::chrono::duration<double, std::milli> milliseconds(elapsed);
  std::cerr << "Execution time: " << std::fixed << std::setprecision(2)
            << milliseconds.count() << " ms (engine; excludes result formatting)\n";
}

// Runs one statement and reports its result or error.
bool execute_statement(ClientSession &client, const std::string &statement,
                       bool timing, bool table_output, bool interactive) {
  const auto start = std::chrono::steady_clock::now();
  try {
    const auto result = client.execute(statement);
    const auto elapsed = std::chrono::steady_clock::now() - start;
    print_result(result, table_output, interactive);
    if (timing) print_timing(elapsed);
    std::cout.flush();
    return true;
  } catch (const std::exception &error) {
    const auto elapsed = std::chrono::steady_clock::now() - start;
    std::cerr << "ERROR: " << error.what() << '\n';
    if (timing) print_timing(elapsed);
    return false;
  }
}

// Handles shell commands that are not SQL statements.
bool meta_command(const std::string &line, ClientSession &client, bool &quit) {
  const auto command = lower(trim(line));
  if (command == "help") {
    std::cout << "Client commands: help, status, clear, exit, quit\n"
              << "SQL commands: CREATE DATABASE, USE, SHOW DATABASES, "
                 "SHOW TABLES, DESCRIBE, and supported Pebble SQL.\n"
              << "Finish SQL statements with a semicolon.\n";
  } else if (command == "status") {
    std::cout << client.status() << '\n';
  } else if (command == "clear") {
    if (stdout_is_terminal()) std::cout << "\033[2J\033[H";
  } else if (command == "exit" || command == "quit" || command == "\\q") {
    quit = true;
  } else {
    return false;
  }
  return true;
}

// Moves complete SQL statements out of the input while respecting quoted text.
void split_complete_statements(std::string &pending,
                               std::vector<std::string> &statements) {
  char quote = '\0';
  std::size_t start = 0;
  for (std::size_t i = 0; i < pending.size(); ++i) {
    const char ch = pending[i];
    if (quote != '\0') {
      if (ch == quote) {
        if (i + 1 < pending.size() && pending[i + 1] == quote) {
          ++i;
        } else {
          quote = '\0';
        }
      } else if (ch == '\\' && i + 1 < pending.size()) {
        ++i;
      }
    } else if (ch == '\'' || ch == '"') {
      quote = ch;
    } else if (ch == ';') {
      auto statement = trim(pending.substr(start, i - start));
      if (!statement.empty()) statements.push_back(std::move(statement));
      start = i + 1;
    }
  }
  if (start == 0) return;
  pending = trim(pending.substr(start));
}

// Checks whether input ends inside a quoted value.
bool has_open_quote(const std::string &text) {
  char quote = '\0';
  for (std::size_t i = 0; i < text.size(); ++i) {
    const char ch = text[i];
    if (quote != '\0') {
      if (ch == quote) {
        if (i + 1 < text.size() && text[i + 1] == quote) ++i;
        else quote = '\0';
      } else if (ch == '\\' && i + 1 < text.size()) {
        ++i;
      }
    } else if (ch == '\'' || ch == '"') {
      quote = ch;
    }
  }
  return quote != '\0';
}

struct Options {
  enum class Mode { Automatic, Execute, File } mode{Mode::Automatic};
  std::string sql;
  std::filesystem::path file;
  std::optional<std::filesystem::path> database_file;
  std::filesystem::path data_directory{default_data_directory()};
  bool timing{};
  bool timing_explicit{};
  bool table_output{};
};

// Prints command-line usage information.
void print_usage(const char *program) {
  std::cout << "Usage: " << program << " [DATABASE_FILE]\n"
            << "       " << program << " --execute SQL [DATABASE_FILE] [--timing]\n"
            << "       " << program << " --file SCRIPT.sql [DATABASE_FILE] [--timing]\n"
            << "       " << program << " --database-dir DIRECTORY\n"
            << "With no command, use an interactive shell on a terminal or batch "
               "SQL from stdin.\n"
            << "Named databases are stored as .db files with .catalog sidecars.\n";
}

// Reads command-line arguments and returns the selected run options.
Options parse_options(int argc, char **argv) {
  Options options;
  for (int i = 1; i < argc; ++i) {
    const std::string arg(argv[i]);
    if (arg == "--help" || arg == "-h") {
      print_usage(argv[0]);
      std::exit(0);
    }
    if (arg == "--execute" || arg == "-e") {
      if (options.mode != Options::Mode::Automatic)
        throw std::runtime_error("choose either --execute or --file");
      if (++i >= argc) throw std::runtime_error("--execute needs SQL text");
      options.mode = Options::Mode::Execute;
      options.sql = argv[i];
    } else if (arg == "--file" || arg == "-f") {
      if (options.mode != Options::Mode::Automatic)
        throw std::runtime_error("choose either --execute or --file");
      if (++i >= argc) throw std::runtime_error("--file needs a script path");
      options.mode = Options::Mode::File;
      options.file = argv[i];
    } else if (arg == "--database" || arg == "--database-dir") {
      if (++i >= argc) throw std::runtime_error(arg + " needs a path");
      if (arg == "--database") options.database_file = argv[i];
      else options.data_directory = argv[i];
    } else if (arg == "--timing") {
      options.timing = true;
      options.timing_explicit = true;
    } else if (arg == "--no-timing") {
      options.timing = false;
      options.timing_explicit = true;
    } else if (arg == "--table") {
      options.table_output = true;
    } else if (!arg.empty() && arg[0] == '-') {
      throw std::runtime_error("unknown option: " + arg);
    } else if (!options.database_file.has_value()) {
      options.database_file = arg;
    } else {
      throw std::runtime_error("unexpected argument: " + arg);
    }
  }
  return options;
}

// Runs all complete statements in a script or batch input.
bool process_batch(std::string text, ClientSession &client, bool timing,
                   bool table_output) {
  std::vector<std::string> statements;
  split_complete_statements(text, statements);
  bool succeeded = true;
  for (const auto &statement : statements)
    succeeded = execute_statement(client, statement, timing, table_output, false) && succeeded;
  if (!text.empty()) {
    if (has_open_quote(text)) {
      std::cerr << "ERROR: incomplete quoted statement at end of input\n";
      succeeded = false;
    } else {
      succeeded = execute_statement(client, text, timing, table_output, false) && succeeded;
    }
  }
  return succeeded;
}

// Reads and runs statements until the user exits the interactive shell.
int run_interactive(ClientSession &client, bool timing) {
  std::string pending;
  bool quit = false;
  bool succeeded = true;
  while (!quit) {
    std::cout << (pending.empty() ? "Pebble [" + client.database_label() + "]> "
                                  : "   -> ") << std::flush;
    std::string line;
    if (!std::getline(std::cin, line)) {
      if (interrupted != 0) {
        interrupted = 0;
        std::cin.clear();
        pending.clear();
        std::cout << "^C\n";
        continue;
      }
      if (!trim(pending).empty()) {
        std::cerr << "ERROR: incomplete statement discarded at end of input\n";
        succeeded = false;
      }
      break;
    }
    if (interrupted != 0) {
      interrupted = 0;
      pending.clear();
      std::cout << "^C\n";
      continue;
    }
    if (pending.empty() && trim(line).empty()) continue;
    if (pending.empty() && meta_command(line, client, quit)) continue;
    pending += line;
    pending.push_back('\n');
    std::vector<std::string> statements;
    split_complete_statements(pending, statements);
    for (const auto &statement : statements) {
      if (interrupted != 0) break;
      const bool statement_succeeded = execute_statement(
          client, statement, timing, true, true);
      succeeded = statement_succeeded && succeeded;
    }
    if (interrupted != 0) {
      interrupted = 0;
      pending.clear();
      std::cout << "^C\n";
    }
  }
  return succeeded ? 0 : 1;
}

}  // namespace

// Selects the input mode, starts the client, and returns the program status.
int main(int argc, char **argv) {
  Options options;
  try {
    options = parse_options(argc, argv);
  } catch (const std::exception &error) {
    std::cerr << "dbms: " << error.what() << '\n';
    print_usage(argv[0]);
    return 2;
  }

  const bool interactive = options.mode == Options::Mode::Automatic && stdin_is_terminal();
  const bool batch_stdin = options.mode == Options::Mode::Automatic && !interactive;
  if (!options.timing_explicit) options.timing = interactive;
  const bool table_output = interactive || options.table_output || stdout_is_terminal();

#if defined(__APPLE__) || defined(__linux__) || defined(__unix__)
  struct sigaction interrupt_action {};
  interrupt_action.sa_handler = handle_sigint;
  sigemptyset(&interrupt_action.sa_mask);
  interrupt_action.sa_flags = 0;
  if (sigaction(SIGINT, &interrupt_action, nullptr) != 0) {
    std::cerr << "dbms: could not install Ctrl-C handler\n";
    return 1;
  }
#else
  std::signal(SIGINT, handle_sigint);
#endif
  try {
    ClientSession client(options.data_directory);
    if (options.database_file.has_value()) client.open_file(*options.database_file);

    int exit_code = 0;
    if (options.mode == Options::Mode::Execute) {
      exit_code = process_batch(options.sql, client, options.timing, table_output) ? 0 : 1;
    } else if (options.mode == Options::Mode::File) {
      std::ifstream input(options.file);
      if (!input) throw std::runtime_error("cannot open script: " + options.file.string());
      std::ostringstream contents;
      contents << input.rdbuf();
      exit_code = process_batch(contents.str(), client, options.timing, table_output) ? 0 : 1;
    } else if (batch_stdin) {
      std::ostringstream contents;
      contents << std::cin.rdbuf();
      exit_code = process_batch(contents.str(), client, options.timing, table_output) ? 0 : 1;
    } else {
      exit_code = run_interactive(client, options.timing);
    }
    client.close();
    return exit_code;
  } catch (const std::exception &error) {
    std::cerr << "dbms: " << error.what() << '\n';
    return 1;
  }
}
