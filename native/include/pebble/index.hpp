#ifndef PEBBLE_INDEX_HPP
#define PEBBLE_INDEX_HPP

#include "pebble/buffer_pool.hpp"
#include "pebble/storage.h"

#include <cstdint>
#include <optional>
#include <utility>
#include <vector>

namespace pebble {

struct RecordId {
  std::int32_t page_id;
  std::uint16_t slot_num;
};

class BPlusTree {
 public:
  BPlusTree(pb_disk_manager *disk, std::int32_t root_page_id,
            std::uint16_t internal_max_size = 511,
            BufferPoolManager *buffer_pool = nullptr);
  BPlusTree(pb_disk_manager *disk, std::int32_t root_page_id,
            BufferPoolManager *buffer_pool);
  static BPlusTree create(pb_disk_manager *disk,
                          std::uint16_t leaf_max_size = 340,
                          std::uint16_t internal_max_size = 511,
                          BufferPoolManager *buffer_pool = nullptr);
  static BPlusTree create(pb_disk_manager *disk,
                          BufferPoolManager *buffer_pool,
                          std::uint16_t leaf_max_size = 340,
                          std::uint16_t internal_max_size = 511);

  std::int32_t root_page_id() const noexcept { return root_page_id_; }
  std::optional<RecordId> search(std::int32_t key) const;
  void insert(std::int32_t key, RecordId value);
  bool erase(std::int32_t key);
  std::vector<std::pair<std::int32_t, RecordId>> scan(
      std::optional<std::int32_t> low = std::nullopt,
      std::optional<std::int32_t> high = std::nullopt) const;

 private:
  pb_disk_manager *disk_;
  BufferPoolManager *buffer_pool_;
  std::int32_t root_page_id_;
  std::uint16_t internal_max_size_;

  std::int32_t allocate_page();
  std::int32_t find_leaf(std::int32_t key) const;
  std::int32_t find_parent(std::int32_t page_id, std::int32_t child_id) const;
  void insert_parent(std::int32_t left_id, std::int32_t key,
                     std::int32_t right_id);
  void grow_root(std::int32_t left_id, std::int32_t key,
                 std::int32_t right_id);
  std::pair<std::int32_t, std::int32_t> split_leaf_and_insert(
      std::int32_t leaf_id, std::int32_t key, RecordId value);
  std::pair<std::int32_t, std::int32_t> split_internal_and_insert(
      std::int32_t node_id, std::int32_t left_child_id, std::int32_t key,
      std::int32_t right_id);
};

}  // namespace pebble

#endif
