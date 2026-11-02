// Tracks page use and chooses which buffer frame to replace when space is
// needed. It remembers recent evictions to adapt its choices over time.

#include "pebble/arc_replacer.hpp"

#include <algorithm>
#include <stdexcept>

namespace pebble {

// Sets the maximum number of frames the replacer can track.
ArcReplacer::ArcReplacer(std::size_t capacity) : capacity_(capacity) {
  if (capacity_ == 0) throw std::invalid_argument("ARC capacity must be positive");
}

// Updates the frame's history when its page is accessed.
void ArcReplacer::record_access(std::size_t frame_id, std::int32_t page_id) {
  if (alive_.contains(frame_id)) {
    move_alive_to_mfu_front(frame_id);
    alive_.at(frame_id).page_id = page_id;
    return;
  }
  const auto ghost = ghost_.find(page_id);
  if (ghost != ghost_.end()) {
    const auto b1 = mru_ghost_.size();
    const auto b2 = mfu_ghost_.size();
    if (ghost->second == "mru") {
      const auto delta = b1 >= b2 ? 1 : std::max<std::size_t>(b2 / b1, 1);
      target_mru_ = std::min(capacity_, target_mru_ + delta);
    } else {
      const auto delta = b2 >= b1 ? 1 : std::max<std::size_t>(b1 / b2, 1);
      target_mru_ = target_mru_ > delta ? target_mru_ - delta : 0;
    }
    remove_ghost(page_id);
    add_alive(frame_id, page_id, Status::Mfu, false);
    return;
  }
  case4_miss(frame_id, page_id);
}

// Marks a frame as in use so it cannot be selected for replacement.
void ArcReplacer::pin(std::size_t frame_id) { set_evictable(frame_id, false); }

// Marks a frame as available for replacement.
void ArcReplacer::unpin(std::size_t frame_id) { set_evictable(frame_id, true); }

// Chooses an available frame to replace based on recent access history.
std::optional<std::size_t> ArcReplacer::victim() {
  const bool prefer_mru = mru_.size() >= target_mru_;
  auto frame = prefer_mru ? evict_from_mru() : evict_from_mfu();
  if (!frame) frame = prefer_mru ? evict_from_mfu() : evict_from_mru();
  return frame;
}

// Removes a frame from the replacer when it is no longer tracked.
void ArcReplacer::remove(std::size_t frame_id) {
  const auto entry = alive_.find(frame_id);
  if (entry == alive_.end()) return;
  if (!entry->second.evictable)
    throw std::runtime_error("cannot remove non-evictable ARC frame");
  unlink_alive(frame_id);
  --evictable_count_;
  alive_.erase(entry);
}

// Changes whether a tracked frame can be selected for replacement.
void ArcReplacer::set_evictable(std::size_t frame_id, bool evictable) {
  const auto entry = alive_.find(frame_id);
  if (entry == alive_.end() || entry->second.evictable == evictable) return;
  entry->second.evictable = evictable;
  if (evictable) ++evictable_count_;
  else --evictable_count_;
}

// Adds a newly seen page to the recent-use list and trims old history as needed.
void ArcReplacer::case4_miss(std::size_t frame_id, std::int32_t page_id) {
  if (mru_.size() + mru_ghost_.size() == capacity_) {
    if (!mru_ghost_.empty()) remove_ghost(mru_ghost_.front());
    add_alive(frame_id, page_id, Status::Mru, false);
    return;
  }
  const auto total = mru_.size() + mfu_.size() + mru_ghost_.size() + mfu_ghost_.size();
  if (total == 2 * capacity_ && !mfu_ghost_.empty())
    remove_ghost(mfu_ghost_.back());
  add_alive(frame_id, page_id, Status::Mru, false);
}

// Adds a frame to the active history lists.
void ArcReplacer::add_alive(std::size_t frame_id, std::int32_t page_id,
                            Status status, bool evictable) {
  if (alive_.contains(frame_id)) throw std::runtime_error("ARC frame already alive");
  alive_.emplace(frame_id, Entry{page_id, evictable, status});
  if (status == Status::Mru) mru_.push_back(frame_id);
  else mfu_.push_front(frame_id);
  if (evictable) ++evictable_count_;
}

// Moves an accessed frame into the frequently used list.
void ArcReplacer::move_alive_to_mfu_front(std::size_t frame_id) {
  auto &entry = alive_.at(frame_id);
  unlink_alive(frame_id);
  entry.status = Status::Mfu;
  mfu_.push_front(frame_id);
}

// Removes a frame from its current active history list.
void ArcReplacer::unlink_alive(std::size_t frame_id) {
  const auto status = alive_.at(frame_id).status;
  auto &list = status == Status::Mru ? mru_ : mfu_;
  list.remove(frame_id);
}

// Removes an evicted page from the remembered history lists.
void ArcReplacer::remove_ghost(std::int32_t page_id) {
  const auto ghost = ghost_.find(page_id);
  if (ghost == ghost_.end()) return;
  auto &list = ghost->second == "mru" ? mru_ghost_ : mfu_ghost_;
  list.remove(page_id);
  ghost_.erase(ghost);
}

// Selects an available frame from the recent-use list.
std::optional<std::size_t> ArcReplacer::evict_from_mru() {
  for (auto it = mru_.begin(); it != mru_.end(); ++it) {
    const auto frame_id = *it;
    const auto entry = alive_.at(frame_id);
    if (!entry.evictable) continue;
    mru_.erase(it);
    alive_.erase(frame_id);
    --evictable_count_;
    mru_ghost_.push_back(entry.page_id);
    ghost_[entry.page_id] = "mru";
    return frame_id;
  }
  return std::nullopt;
}

// Selects an available frame from the frequently used list.
std::optional<std::size_t> ArcReplacer::evict_from_mfu() {
  for (auto it = mfu_.rbegin(); it != mfu_.rend(); ++it) {
    const auto frame_id = *it;
    const auto entry = alive_.at(frame_id);
    if (!entry.evictable) continue;
    mfu_.erase(std::next(it).base());
    alive_.erase(frame_id);
    --evictable_count_;
    mfu_ghost_.push_front(entry.page_id);
    ghost_[entry.page_id] = "mfu";
    return frame_id;
  }
  return std::nullopt;
}

}  // namespace pebble
