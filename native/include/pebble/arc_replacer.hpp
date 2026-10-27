#ifndef PEBBLE_ARC_REPLACER_HPP
#define PEBBLE_ARC_REPLACER_HPP

#include <cstddef>
#include <cstdint>
#include <list>
#include <optional>
#include <string>
#include <unordered_map>

namespace pebble {

class ArcReplacer {
 public:
  explicit ArcReplacer(std::size_t capacity);

  std::size_t size() const noexcept { return evictable_count_; }
  void record_access(std::size_t frame_id, std::int32_t page_id);
  void pin(std::size_t frame_id);
  void unpin(std::size_t frame_id);
  std::optional<std::size_t> victim();
  void remove(std::size_t frame_id);

 private:
  enum class Status { Mru, Mfu };
  struct Entry {
    std::int32_t page_id;
    bool evictable;
    Status status;
  };

  std::size_t capacity_;
  std::size_t target_mru_{};
  std::size_t evictable_count_{};
  std::list<std::size_t> mru_;
  std::list<std::size_t> mfu_;
  std::list<std::int32_t> mru_ghost_;
  std::list<std::int32_t> mfu_ghost_;
  std::unordered_map<std::size_t, Entry> alive_;
  std::unordered_map<std::int32_t, std::string> ghost_;

  void set_evictable(std::size_t frame_id, bool evictable);
  void case4_miss(std::size_t frame_id, std::int32_t page_id);
  void add_alive(std::size_t frame_id, std::int32_t page_id, Status status,
                 bool evictable);
  void move_alive_to_mfu_front(std::size_t frame_id);
  void unlink_alive(std::size_t frame_id);
  void remove_ghost(std::int32_t page_id);
  std::optional<std::size_t> evict_from_mru();
  std::optional<std::size_t> evict_from_mfu();
};

}  // namespace pebble

#endif
