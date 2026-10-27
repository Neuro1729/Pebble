#ifndef PEBBLE_BUFFER_POOL_HPP
#define PEBBLE_BUFFER_POOL_HPP

#include "pebble/arc_replacer.hpp"
#include "pebble/disk_scheduler.hpp"
#include "pebble/storage.h"

#include <cstddef>
#include <cstdint>
#include <unordered_map>
#include <vector>

namespace pebble {

class BufferPoolManager;

class PageGuard {
 public:
  PageGuard() = default;
  PageGuard(BufferPoolManager *manager, std::size_t frame_id, bool dirty);
  ~PageGuard();
  PageGuard(const PageGuard &) = delete;
  PageGuard &operator=(const PageGuard &) = delete;
  PageGuard(PageGuard &&other) noexcept;
  PageGuard &operator=(PageGuard &&other) noexcept;

  pb_page &page();
  const pb_page &page() const;
  void mark_dirty() noexcept { dirty_ = true; }
  void mark_clean() noexcept { dirty_ = false; }
  void drop() noexcept;

 private:
  BufferPoolManager *manager_{};
  std::size_t frame_id_{};
  bool dirty_{};
  friend class BufferPoolManager;
};

class BufferPoolManager {
 public:
  BufferPoolManager(pb_disk_manager *disk, std::size_t pool_size);
  ~BufferPoolManager();
  BufferPoolManager(const BufferPoolManager &) = delete;
  BufferPoolManager &operator=(const BufferPoolManager &) = delete;

  PageGuard fetch_page(std::int32_t page_id);
  PageGuard new_page(std::int32_t *page_id_out);
  pb_page read_page(std::int32_t page_id);
  void write_page(const pb_page &page);
  bool flush_page(std::int32_t page_id);
  void flush_all_pages();
  std::size_t pool_size() const noexcept { return frames_.size(); }

 private:
  struct Frame {
    pb_page page{};
    std::size_t pin_count{};
    bool valid{};
    bool dirty{};
  };

  pb_disk_manager *disk_;
  DiskScheduler scheduler_;
  std::vector<Frame> frames_;
  std::vector<std::size_t> free_frames_;
  std::unordered_map<std::int32_t, std::size_t> page_table_;
  ArcReplacer replacer_;

  pb_page &frame_page(std::size_t frame_id);
  const pb_page &frame_page(std::size_t frame_id) const;
  void unpin_page(std::size_t frame_id, bool dirty);
  void flush_frame(std::size_t frame_id);
  std::size_t acquire_frame();
  friend class PageGuard;
};

}  // namespace pebble

#endif
