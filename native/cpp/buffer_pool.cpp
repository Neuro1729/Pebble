// Manages cached database pages and controls when pages are loaded from or
// saved to disk. PageGuard tracks page use and releases pages safely.

#include "pebble/buffer_pool.hpp"

#include <stdexcept>
#include <string>
#include <utility>

namespace pebble {
namespace {

// Reports errors returned by the storage layer.
void check_status(pb_status status, const char *error) {
  if (status != PB_STATUS_OK)
    throw std::runtime_error(std::string(pb_status_name(status)) + ": " + error);
}

}  // namespace
namespace {

}  // namespace

// Keeps track of a page held by a caller.
PageGuard::PageGuard(BufferPoolManager *manager, std::size_t frame_id, bool dirty)
    : manager_(manager), frame_id_(frame_id), dirty_(dirty) {}

// Releases the page when the guard goes out of scope.
PageGuard::~PageGuard() { drop(); }

// Transfers page ownership from another guard.
PageGuard::PageGuard(PageGuard &&other) noexcept
    : manager_(std::exchange(other.manager_, nullptr)),
      frame_id_(other.frame_id_), dirty_(other.dirty_) {}

// Releases this guard's page before taking ownership of another one.
PageGuard &PageGuard::operator=(PageGuard &&other) noexcept {
  if (this != &other) {
    drop();
    manager_ = std::exchange(other.manager_, nullptr);
    frame_id_ = other.frame_id_;
    dirty_ = other.dirty_;
  }
  return *this;
}

// Returns the page held by this guard.
pb_page &PageGuard::page() {
  if (manager_ == nullptr) throw std::runtime_error("page guard has been dropped");
  return manager_->frame_page(frame_id_);
}

// Returns the page held by this guard for reading.
const pb_page &PageGuard::page() const {
  if (manager_ == nullptr) throw std::runtime_error("page guard has been dropped");
  return manager_->frame_page(frame_id_);
}

// Marks the page as no longer in use by this guard.
void PageGuard::drop() noexcept {
  if (manager_ == nullptr) return;
  manager_->unpin_page(frame_id_, dirty_);
  manager_ = nullptr;
}

// Creates a page cache with the requested number of frames.
BufferPoolManager::BufferPoolManager(pb_disk_manager *disk, std::size_t pool_size)
    : disk_(disk), scheduler_(disk), frames_(pool_size), replacer_(pool_size) {
  if (disk_ == nullptr || pool_size == 0)
    throw std::invalid_argument("disk manager and positive pool size are required");
  free_frames_.reserve(pool_size);
  for (std::size_t i = pool_size; i > 0; --i) free_frames_.push_back(i - 1);
}

// Writes changed pages back to disk when the manager is destroyed.
BufferPoolManager::~BufferPoolManager() {
  try {
    flush_all_pages();
  } catch (...) {
    // Explicit flush_all_pages reports I/O errors; destruction is best-effort.
  }
}

// Returns a cached page or loads it from disk, keeping it in use.
PageGuard BufferPoolManager::fetch_page(std::int32_t page_id) {
  const auto found = page_table_.find(page_id);
  if (found != page_table_.end()) {
    const auto frame_id = found->second;
    auto &frame = frames_[frame_id];
    replacer_.record_access(frame_id, page_id);
    if (frame.pin_count == 0) replacer_.pin(frame_id);
    ++frame.pin_count;
    return PageGuard(this, frame_id, false);
  }

  const auto frame_id = acquire_frame();
  auto &frame = frames_[frame_id];
  pb_page page{};
  try {
    page = scheduler_.read_page(page_id);
  } catch (...) {
    frame = Frame{};
    free_frames_.push_back(frame_id);
    throw;
  }
  frame.page = page;
  frame.pin_count = 1;
  frame.valid = true;
  frame.dirty = false;
  page_table_[page_id] = frame_id;
  replacer_.record_access(frame_id, page_id);
  return PageGuard(this, frame_id, false);
}

// Allocates a database page and returns it through a guard.
PageGuard BufferPoolManager::new_page(std::int32_t *page_id_out) {
  if (page_id_out == nullptr) throw std::invalid_argument("page id output is null");
  char error[256]{};
  check_status(pb_disk_allocate_page(disk_, page_id_out, error, sizeof(error)), error);
  return fetch_page(*page_id_out);
}

// Reads a page and returns a copy without marking it as changed.
pb_page BufferPoolManager::read_page(std::int32_t page_id) {
  auto guard = fetch_page(page_id);
  const auto page = guard.page();
  guard.mark_clean();
  return page;
}

// Replaces a cached page and marks it to be saved to disk.
void BufferPoolManager::write_page(const pb_page &page) {
  auto guard = fetch_page(page.page_id);
  guard.page() = page;
  guard.mark_dirty();
}

// Saves a cached page to disk if it is currently in the pool.
bool BufferPoolManager::flush_page(std::int32_t page_id) {
  const auto found = page_table_.find(page_id);
  if (found == page_table_.end()) return false;
  flush_frame(found->second);
  return true;
}

// Saves every changed page currently held in the pool.
void BufferPoolManager::flush_all_pages() {
  for (std::size_t i = 0; i < frames_.size(); ++i)
    if (frames_[i].valid) flush_frame(i);
}

// Provides access to a valid page in a buffer frame.
pb_page &BufferPoolManager::frame_page(std::size_t frame_id) {
  if (frame_id >= frames_.size() || !frames_[frame_id].valid)
    throw std::runtime_error("invalid buffer pool frame");
  return frames_[frame_id].page;
}

// Provides read-only access to a valid page in a buffer frame.
const pb_page &BufferPoolManager::frame_page(std::size_t frame_id) const {
  if (frame_id >= frames_.size() || !frames_[frame_id].valid)
    throw std::runtime_error("invalid buffer pool frame");
  return frames_[frame_id].page;
}

// Releases a frame and records whether its page needs saving.
void BufferPoolManager::unpin_page(std::size_t frame_id, bool dirty) {
  if (frame_id >= frames_.size()) return;
  auto &frame = frames_[frame_id];
  if (!frame.valid || frame.pin_count == 0) return;
  frame.dirty = frame.dirty || dirty;
  --frame.pin_count;
  if (frame.pin_count == 0) replacer_.unpin(frame_id);
}

// Writes a changed frame to disk and marks it as saved.
void BufferPoolManager::flush_frame(std::size_t frame_id) {
  auto &frame = frames_.at(frame_id);
  if (!frame.valid || !frame.dirty) return;
  scheduler_.write_page(frame.page);
  frame.dirty = false;
}

// Finds a free frame or replaces an unused cached page.
std::size_t BufferPoolManager::acquire_frame() {
  if (!free_frames_.empty()) {
    const auto frame_id = free_frames_.back();
    free_frames_.pop_back();
    return frame_id;
  }
  const auto victim = replacer_.victim();
  if (!victim) throw std::runtime_error("all buffer pool frames are pinned");
  auto &frame = frames_[*victim];
  if (frame.pin_count != 0 || !frame.valid)
    throw std::runtime_error("ARC selected an invalid or pinned frame");
  try {
    flush_frame(*victim);
  } catch (...) {
    const auto page_id = frame.page.page_id;
    replacer_.record_access(*victim, page_id);
    replacer_.unpin(*victim);
    throw;
  }
  page_table_.erase(frame.page.page_id);
  frame.valid = false;
  return *victim;
}

}  // namespace pebble
