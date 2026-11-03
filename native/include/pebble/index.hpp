#ifndef PEBBLE_INDEX_HPP
#define PEBBLE_INDEX_HPP

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <optional>
#include <utility>
#include <vector>

namespace pebble {

struct RecordId {
  std::int32_t page_id;
  std::uint16_t slot_num;
};

class LSMTree {
 public:
  explicit LSMTree(std::filesystem::path directory,
                   std::size_t memtable_limit = 4096,
                   bool create_if_missing = true);
  ~LSMTree();

  LSMTree(const LSMTree &) = delete;
  LSMTree &operator=(const LSMTree &) = delete;
  LSMTree(LSMTree &&) noexcept;
  LSMTree &operator=(LSMTree &&) noexcept;

  std::optional<RecordId> search(std::int32_t key) const;
  void insert(std::int32_t key, RecordId value);
  // Inserts a key already checked by the owning table, avoiding a second lookup.
  void insert_known_unique(std::int32_t key, RecordId value);
  bool erase(std::int32_t key);
  std::vector<std::pair<std::int32_t, RecordId>> scan(
      std::optional<std::int32_t> low = std::nullopt,
      std::optional<std::int32_t> high = std::nullopt) const;
  void flush();

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace pebble

#endif
