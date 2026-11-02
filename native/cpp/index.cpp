// Implements the B+ tree index used to find records by integer key. It
// handles index pages, key updates, page splits, and range scans.

#include "pebble/index.hpp"

#include <algorithm>
#include <array>
#include <fstream>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <system_error>

namespace pebble {
namespace {

constexpr std::array<char, 8> kManifestMagic{'P', 'B', 'L', 'S', 'M', '0', '1', '\0'};
constexpr std::array<char, 8> kTableMagic{'P', 'B', 'S', 'S', 'T', '0', '1', '\0'};
constexpr std::uint32_t kFormatVersion = 1;
constexpr std::uint64_t kTableHeaderSize = 20;
constexpr std::uint64_t kRecordSize = 19;
constexpr std::size_t kCompactionRunCount = 4;

struct Entry {
  std::int32_t key{};
  std::uint64_t sequence{};
  std::optional<RecordId> value;
};

struct Run {
  std::uint64_t id{};
  std::uint64_t count{};
  std::filesystem::path path;
};

void put_u32(char *out, std::uint32_t value) {
  for (unsigned i = 0; i < 4; ++i)
    out[i] = static_cast<char>(value >> (8 * i));
}

void put_u64(char *out, std::uint64_t value) {
  for (unsigned i = 0; i < 8; ++i)
    out[i] = static_cast<char>(value >> (8 * i));
}

std::uint32_t get_u32(const char *in) {
  std::uint32_t value = 0;
  for (unsigned i = 0; i < 4; ++i)
    value |= static_cast<std::uint32_t>(static_cast<unsigned char>(in[i]))
             << (8 * i);
  return value;
}

std::uint64_t get_u64(const char *in) {
  std::uint64_t value = 0;
  for (unsigned i = 0; i < 8; ++i)
    value |= static_cast<std::uint64_t>(static_cast<unsigned char>(in[i]))
             << (8 * i);
  return value;
}

std::int32_t get_i32(const char *in) {
  const auto bits = get_u32(in);
  const auto value = bits <= 0x7fffffffu
                         ? static_cast<std::int64_t>(bits)
                         : static_cast<std::int64_t>(bits) - 0x100000000ll;
  return static_cast<std::int32_t>(value);
}

void put_i32(char *out, std::int32_t value) {
  put_u32(out, static_cast<std::uint32_t>(value));
}

std::runtime_error io_error(const std::string &operation,
                            const std::filesystem::path &path) {
  return std::runtime_error(operation + ": " + path.string());
}

void replace_file(const std::filesystem::path &temporary,
                  const std::filesystem::path &destination) {
  std::error_code error;
  std::filesystem::rename(temporary, destination, error);
  if (error)
    throw std::runtime_error("replacing " + destination.string() + " failed: " +
                             error.message());
}

std::array<char, kRecordSize> encode_entry(const Entry &entry) {
  std::array<char, kRecordSize> bytes{};
  put_i32(bytes.data(), entry.key);
  put_u64(bytes.data() + 4, entry.sequence);
  bytes[12] = entry.value ? 0 : 1;
  if (entry.value) {
    put_i32(bytes.data() + 13, entry.value->page_id);
    bytes[17] = static_cast<char>(entry.value->slot_num);
    bytes[18] = static_cast<char>(entry.value->slot_num >> 8);
  }
  return bytes;
}

Entry decode_entry(const std::array<char, kRecordSize> &bytes,
                   const std::filesystem::path &path) {
  Entry entry;
  entry.key = get_i32(bytes.data());
  entry.sequence = get_u64(bytes.data() + 4);
  const auto tombstone = static_cast<unsigned char>(bytes[12]);
  if (entry.sequence == 0 || tombstone > 1)
    throw io_error("corrupt LSM table record", path);
  if (tombstone == 0) {
    const auto page_id = get_i32(bytes.data() + 13);
    const auto slot = static_cast<std::uint16_t>(
        static_cast<unsigned char>(bytes[17]) |
        (static_cast<std::uint16_t>(static_cast<unsigned char>(bytes[18]))
         << 8));
    if (page_id < 0) throw io_error("invalid LSM record identifier", path);
    entry.value = RecordId{page_id, slot};
  }
  return entry;
}

}  // namespace

struct LSMTree::Impl {
  explicit Impl(std::filesystem::path path, std::size_t limit,
                bool create_if_missing)
      : directory(std::move(path)), memtable_limit(limit) {
    if (memtable_limit == 0)
      throw std::invalid_argument("LSM memtable limit must be positive");
    std::filesystem::create_directories(directory);
    if (!std::filesystem::exists(manifest_path())) {
      if (!create_if_missing)
        throw io_error("missing LSM manifest", manifest_path());
      write_manifest(next_sequence, next_file_id, {});
    } else {
      load_manifest();
    }
  }

  std::filesystem::path directory;
  std::size_t memtable_limit;
  std::uint64_t next_sequence{1};
  std::uint64_t next_file_id{1};
  std::map<std::int32_t, Entry> memtable;
  std::vector<Run> runs;

  std::filesystem::path manifest_path() const { return directory / "MANIFEST"; }

  std::filesystem::path run_path(std::uint64_t id) const {
    return directory / ("table-" + std::to_string(id) + ".sst");
  }

  void load_manifest() {
    const auto path = manifest_path();
    std::ifstream in(path);
    std::string magic;
    std::uint32_t version{};
    std::size_t count{};
    if (!(in >> magic >> version >> next_sequence >> next_file_id >> count) ||
        magic != "PEBBLE_LSM" || version != kFormatVersion ||
        next_sequence == 0 || next_file_id == 0)
      throw io_error("unsupported or corrupt LSM manifest", path);

    std::vector<std::uint64_t> ids;
    ids.reserve(count);
    std::uint64_t greatest_id = 0;
    std::uint64_t greatest_sequence = 0;
    for (std::size_t i = 0; i < count; ++i) {
      std::uint64_t id{};
      if (!(in >> id) || id == 0 ||
          std::find(ids.begin(), ids.end(), id) != ids.end())
        throw io_error("corrupt LSM manifest run list", path);
      ids.push_back(id);
      greatest_id = std::max(greatest_id, id);
    }
    if (greatest_id >= next_file_id)
      throw io_error("invalid LSM table identifier", path);
    std::string trailing;
    if (in >> trailing) throw io_error("trailing LSM manifest data", path);

    for (const auto id : ids) {
      auto run = load_run(id);
      for (const auto &entry : read_all(run))
        greatest_sequence = std::max(greatest_sequence, entry.sequence);
      runs.push_back(std::move(run));
    }
    if (greatest_sequence >= next_sequence)
      throw io_error("invalid LSM sequence number", path);
  }

  Run load_run(std::uint64_t id) const {
    const auto path = run_path(id);
    std::ifstream in(path, std::ios::binary);
    if (!in) throw io_error("cannot read LSM table", path);
    std::array<char, kTableHeaderSize> header{};
    in.read(header.data(), static_cast<std::streamsize>(header.size()));
    if (!in || !std::equal(kTableMagic.begin(), kTableMagic.end(),
                           header.begin()) ||
        get_u32(header.data() + 8) != kFormatVersion)
      throw io_error("corrupt LSM table header", path);
    const auto count = get_u64(header.data() + 12);
    std::error_code error;
    const auto size = std::filesystem::file_size(path, error);
    if (error || count > (std::numeric_limits<std::uint64_t>::max() -
                          kTableHeaderSize) /
                             kRecordSize ||
        size != kTableHeaderSize + count * kRecordSize)
      throw io_error("invalid LSM table size", path);
    return {id, count, path};
  }

  std::vector<Entry> read_all(const Run &run) const {
    std::ifstream in(run.path, std::ios::binary);
    if (!in) throw io_error("cannot read LSM table", run.path);
    in.seekg(static_cast<std::streamoff>(kTableHeaderSize));
    std::vector<Entry> entries;
    if (run.count > entries.max_size())
      throw io_error("LSM table is too large", run.path);
    entries.reserve(static_cast<std::size_t>(run.count));
    std::optional<std::int32_t> previous;
    for (std::uint64_t i = 0; i < run.count; ++i) {
      std::array<char, kRecordSize> bytes{};
      in.read(bytes.data(), static_cast<std::streamsize>(bytes.size()));
      if (!in) throw io_error("truncated LSM table", run.path);
      auto entry = decode_entry(bytes, run.path);
      if (previous && entry.key <= *previous)
        throw io_error("unsorted LSM table", run.path);
      previous = entry.key;
      entries.push_back(std::move(entry));
    }
    return entries;
  }

  void write_manifest(std::uint64_t sequence, std::uint64_t file_id,
                      const std::vector<Run> &manifest_runs) const {
    const auto path = manifest_path();
    auto temporary = path;
    temporary += ".tmp";
    {
      std::ofstream out(temporary, std::ios::trunc);
      if (!out) throw io_error("cannot write LSM manifest", temporary);
      out << "PEBBLE_LSM " << kFormatVersion << ' ' << sequence << ' '
          << file_id << ' ' << manifest_runs.size() << '\n';
      for (const auto &run : manifest_runs) out << run.id << '\n';
      out.flush();
      if (!out) throw io_error("writing LSM manifest failed", temporary);
    }
    replace_file(temporary, path);
  }

  Run write_run(std::uint64_t id, const std::vector<Entry> &entries) const {
    const auto path = run_path(id);
    auto temporary = path;
    temporary += ".tmp";
    {
      std::ofstream out(temporary, std::ios::binary | std::ios::trunc);
      if (!out) throw io_error("cannot write LSM table", temporary);
      std::array<char, kTableHeaderSize> header{};
      std::copy(kTableMagic.begin(), kTableMagic.end(), header.begin());
      put_u32(header.data() + 8, kFormatVersion);
      put_u64(header.data() + 12, entries.size());
      out.write(header.data(), static_cast<std::streamsize>(header.size()));
      for (const auto &entry : entries) {
        const auto bytes = encode_entry(entry);
        out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
      }
      out.flush();
      if (!out) throw io_error("writing LSM table failed", temporary);
    }
    replace_file(temporary, path);
    return {id, entries.size(), path};
  }

  void erase_runs(const std::vector<Run> &old_runs) const {
    for (const auto &run : old_runs) {
      std::error_code error;
      if (!std::filesystem::remove(run.path, error) && error)
        throw std::runtime_error("removing obsolete LSM table " +
                                 run.path.string() + " failed: " +
                                 error.message());
    }
  }

  std::optional<Entry> find_in_run(const Run &run, std::int32_t key) const {
    std::ifstream in(run.path, std::ios::binary);
    if (!in) throw io_error("cannot read LSM table", run.path);
    std::uint64_t low = 0;
    std::uint64_t high = run.count;
    while (low < high) {
      const auto mid = low + (high - low) / 2;
      const auto offset = kTableHeaderSize + mid * kRecordSize;
      in.seekg(static_cast<std::streamoff>(offset));
      std::array<char, kRecordSize> bytes{};
      in.read(bytes.data(), static_cast<std::streamsize>(bytes.size()));
      if (!in) throw io_error("truncated LSM table", run.path);
      const auto entry = decode_entry(bytes, run.path);
      if (entry.key < key)
        low = mid + 1;
      else
        high = mid;
    }
    if (low == run.count) return std::nullopt;
    in.clear();
    in.seekg(static_cast<std::streamoff>(kTableHeaderSize + low * kRecordSize));
    std::array<char, kRecordSize> bytes{};
    in.read(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    if (!in) throw io_error("truncated LSM table", run.path);
    auto entry = decode_entry(bytes, run.path);
    return entry.key == key ? std::optional<Entry>(std::move(entry))
                            : std::nullopt;
  }

  std::optional<Entry> latest_entry(std::int32_t key) const {
    std::optional<Entry> latest;
    const auto in_memory = memtable.find(key);
    if (in_memory != memtable.end()) latest = in_memory->second;
    for (const auto &run : runs) {
      const auto found = find_in_run(run, key);
      if (found && (!latest || found->sequence > latest->sequence))
        latest = found;
    }
    return latest;
  }

  void compact() {
    if (runs.size() < kCompactionRunCount) return;
    std::map<std::int32_t, Entry> latest;
    for (const auto &run : runs) {
      for (const auto &entry : read_all(run)) {
        const auto current = latest.find(entry.key);
        if (current == latest.end() ||
            current->second.sequence < entry.sequence)
          latest[entry.key] = entry;
      }
    }

    std::vector<Entry> compacted;
    compacted.reserve(latest.size());
    for (auto &[key, entry] : latest) {
      (void)key;
      if (entry.value) compacted.push_back(std::move(entry));
    }

    std::vector<Run> new_runs;
    auto new_next_file_id = next_file_id;
    if (!compacted.empty()) {
      if (new_next_file_id == std::numeric_limits<std::uint64_t>::max())
        throw std::overflow_error("LSM table identifier exhausted");
      new_runs.push_back(write_run(new_next_file_id++, compacted));
    }
    write_manifest(next_sequence, new_next_file_id, new_runs);
    const auto old_runs = runs;
    runs = std::move(new_runs);
    next_file_id = new_next_file_id;
    erase_runs(old_runs);
  }

  void flush() {
    if (memtable.empty()) return;
    if (next_file_id == std::numeric_limits<std::uint64_t>::max())
      throw std::overflow_error("LSM table identifier exhausted");
    std::vector<Entry> entries;
    entries.reserve(memtable.size());
    for (const auto &[key, entry] : memtable) {
      (void)key;
      entries.push_back(entry);
    }
    const auto new_run = write_run(next_file_id, entries);
    auto new_runs = runs;
    new_runs.push_back(new_run);
    const auto next_file = next_file_id + 1;
    write_manifest(next_sequence, next_file, new_runs);
    runs = std::move(new_runs);
    next_file_id = next_file;
    memtable.clear();
    compact();
  }

  std::uint64_t take_sequence() {
    if (next_sequence == std::numeric_limits<std::uint64_t>::max())
      throw std::overflow_error("LSM sequence number exhausted");
    return next_sequence++;
  }
};

LSMTree::LSMTree(std::filesystem::path directory, std::size_t memtable_limit,
                 bool create_if_missing)
    : impl_(std::make_unique<Impl>(std::move(directory), memtable_limit,
                                   create_if_missing)) {}

LSMTree::~LSMTree() = default;
LSMTree::LSMTree(LSMTree &&) noexcept = default;
LSMTree &LSMTree::operator=(LSMTree &&) noexcept = default;

std::optional<RecordId> LSMTree::search(std::int32_t key) const {
  const auto entry = impl_->latest_entry(key);
  if (!entry || !entry->value) return std::nullopt;
  return entry->value;
}

void LSMTree::insert(std::int32_t key, RecordId value) {
  if (value.page_id < 0) throw std::invalid_argument("invalid RID page id");
  if (search(key))
    throw std::runtime_error("duplicate index key: " + std::to_string(key));
  const auto sequence = impl_->take_sequence();
  impl_->memtable[key] = Entry{key, sequence, value};
  if (impl_->memtable.size() >= impl_->memtable_limit) impl_->flush();
}

bool LSMTree::erase(std::int32_t key) {
  if (!search(key)) return false;
  const auto sequence = impl_->take_sequence();
  impl_->memtable[key] = Entry{key, sequence, std::nullopt};
  if (impl_->memtable.size() >= impl_->memtable_limit) impl_->flush();
  return true;
}

std::vector<std::pair<std::int32_t, RecordId>> LSMTree::scan(
    std::optional<std::int32_t> low, std::optional<std::int32_t> high) const {
  std::map<std::int32_t, Entry> latest;
  const auto consider = [&](const Entry &entry) {
    const auto current = latest.find(entry.key);
    if (current == latest.end() ||
        current->second.sequence < entry.sequence)
      latest[entry.key] = entry;
  };
  for (const auto &run : impl_->runs)
    for (const auto &entry : impl_->read_all(run)) consider(entry);
  for (const auto &[key, entry] : impl_->memtable) {
    (void)key;
    consider(entry);
  }

  std::vector<std::pair<std::int32_t, RecordId>> result;
  for (auto it = low ? latest.lower_bound(*low) : latest.begin();
       it != latest.end() && (!high || it->first <= *high); ++it) {
    if (it->second.value) result.emplace_back(it->first, *it->second.value);
  }
  return result;
}

void LSMTree::flush() { impl_->flush(); }

}  // namespace pebble
