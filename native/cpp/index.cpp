#include "pebble/index.hpp"

#include <algorithm>
#include <stdexcept>
#include <string>

namespace pebble {
namespace {

constexpr std::uint8_t kLeaf = 1;
constexpr std::uint8_t kInternal = 2;
constexpr std::size_t kLeafHeaderSize = 12;
constexpr std::size_t kInternalHeaderSize = 8;
constexpr std::size_t kKeySize = 4;
constexpr std::size_t kRidSize = 8;
constexpr std::size_t kInternalSlotSize = 8;
constexpr std::uint16_t kLeafMax = (PB_PAGE_SIZE - kLeafHeaderSize) / (kKeySize + kRidSize);
constexpr std::uint16_t kInternalMax = (PB_PAGE_SIZE - kInternalHeaderSize) / kInternalSlotSize;

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
std::int32_t signed_i32(const std::uint8_t *in) {
  const auto bits = get_u32(in);
  const auto value = bits <= 0x7fffffffu ? static_cast<std::int64_t>(bits)
                                         : static_cast<std::int64_t>(bits) - 0x100000000ll;
  return static_cast<std::int32_t>(value);
}
void put_i32(std::uint8_t *out, std::int32_t value) {
  put_u32(out, static_cast<std::uint32_t>(value));
}

void check_status(pb_status status, const char *error) {
  if (status != PB_STATUS_OK)
    throw std::runtime_error(std::string(pb_status_name(status)) + ": " + error);
}
pb_page read_page(pb_disk_manager *disk, std::int32_t id,
                  BufferPoolManager *buffer_pool) {
  if (buffer_pool != nullptr) return buffer_pool->read_page(id);
  pb_page page{};
  char error[256]{};
  check_status(pb_disk_read_page(disk, id, &page, error, sizeof(error)), error);
  return page;
}
void write_page(pb_disk_manager *disk, const pb_page &page,
                BufferPoolManager *buffer_pool) {
  if (buffer_pool != nullptr) {
    buffer_pool->write_page(page);
    return;
  }
  char error[256]{};
  check_status(pb_disk_write_page(disk, &page, error, sizeof(error)), error);
}
std::uint8_t page_type(const pb_page &page) { return page.data[0]; }
std::uint16_t leaf_size(const pb_page &page) { return get_u16(page.data + 1); }
std::uint16_t leaf_max(const pb_page &page) { return get_u16(page.data + 3); }
std::int32_t leaf_next(const pb_page &page) { return signed_i32(page.data + 5); }
std::uint16_t internal_size(const pb_page &page) { return get_u16(page.data + 1); }
std::uint16_t internal_max(const pb_page &page) { return get_u16(page.data + 3); }

void initialize_leaf(pb_page &page, std::uint16_t max_size = kLeafMax,
                     std::int32_t next_id = PB_INVALID_PAGE_ID) {
  if (max_size == 0 || max_size > kLeafMax) throw std::runtime_error("invalid leaf max size");
  pb_page_init(&page, page.page_id);
  page.data[0] = kLeaf;
  put_u16(page.data + 1, 0);
  put_u16(page.data + 3, max_size);
  put_i32(page.data + 5, next_id);
}
void initialize_internal(pb_page &page, std::uint16_t max_size = kInternalMax) {
  if (max_size < 2 || max_size > kInternalMax) throw std::runtime_error("invalid internal max size");
  pb_page_init(&page, page.page_id);
  page.data[0] = kInternal;
  put_u16(page.data + 1, 0);
  put_u16(page.data + 3, max_size);
}
void set_leaf_size(pb_page &page, std::uint16_t size) {
  if (size > leaf_max(page)) throw std::runtime_error("leaf size exceeds capacity");
  put_u16(page.data + 1, size);
}
void set_internal_size(pb_page &page, std::uint16_t size) {
  if (size > internal_max(page)) throw std::runtime_error("internal size exceeds capacity");
  put_u16(page.data + 1, size);
}
std::int32_t leaf_key(const pb_page &page, std::uint16_t index) {
  if (page_type(page) != kLeaf || index >= leaf_size(page)) throw std::runtime_error("invalid leaf key index");
  return signed_i32(page.data + kLeafHeaderSize + static_cast<std::size_t>(index) * kKeySize);
}
RecordId leaf_rid(const pb_page &page, std::uint16_t index) {
  if (page_type(page) != kLeaf || index >= leaf_size(page)) throw std::runtime_error("invalid leaf RID index");
  const auto offset = kLeafHeaderSize + static_cast<std::size_t>(leaf_max(page)) * kKeySize +
                      static_cast<std::size_t>(index) * kRidSize;
  return {signed_i32(page.data + offset), get_u16(page.data + offset + 4)};
}
void set_leaf_entry(pb_page &page, std::uint16_t index, std::int32_t key, RecordId rid) {
  if (page_type(page) != kLeaf || index >= leaf_max(page)) throw std::runtime_error("invalid leaf entry index");
  const auto key_offset = kLeafHeaderSize + static_cast<std::size_t>(index) * kKeySize;
  const auto rid_offset = kLeafHeaderSize + static_cast<std::size_t>(leaf_max(page)) * kKeySize +
                          static_cast<std::size_t>(index) * kRidSize;
  put_i32(page.data + key_offset, key);
  put_i32(page.data + rid_offset, rid.page_id);
  put_u16(page.data + rid_offset + 4, rid.slot_num);
  page.data[rid_offset + 6] = page.data[rid_offset + 7] = 0;
}
std::int32_t internal_key(const pb_page &page, std::uint16_t index) {
  if (page_type(page) != kInternal || index >= internal_size(page)) throw std::runtime_error("invalid internal key index");
  return signed_i32(page.data + kInternalHeaderSize + static_cast<std::size_t>(index) * kInternalSlotSize);
}
std::int32_t internal_child(const pb_page &page, std::uint16_t index) {
  if (page_type(page) != kInternal || index >= internal_size(page)) throw std::runtime_error("invalid internal child index");
  return signed_i32(page.data + kInternalHeaderSize + static_cast<std::size_t>(index) * kInternalSlotSize + 4);
}
void set_internal_entry(pb_page &page, std::uint16_t index, std::int32_t key, std::int32_t child) {
  if (page_type(page) != kInternal || index >= internal_max(page)) throw std::runtime_error("invalid internal entry index");
  const auto offset = kInternalHeaderSize + static_cast<std::size_t>(index) * kInternalSlotSize;
  put_i32(page.data + offset, key);
  put_i32(page.data + offset + 4, child);
}
std::uint16_t leaf_lower_bound(const pb_page &page, std::int32_t key) {
  std::uint16_t lo = 0, hi = leaf_size(page);
  while (lo < hi) {
    const auto mid = static_cast<std::uint16_t>((lo + hi) / 2);
    if (leaf_key(page, mid) < key) lo = static_cast<std::uint16_t>(mid + 1);
    else hi = mid;
  }
  return lo;
}
std::uint16_t child_index(const pb_page &page, std::int32_t key) {
  const auto size = internal_size(page);
  if (size == 0) throw std::runtime_error("empty internal page");
  std::uint16_t lo = 1, hi = size;
  while (lo < hi) {
    const auto mid = static_cast<std::uint16_t>((lo + hi) / 2);
    if (internal_key(page, mid) <= key) lo = static_cast<std::uint16_t>(mid + 1);
    else hi = mid;
  }
  return static_cast<std::uint16_t>(lo - 1);
}

}  // namespace

BPlusTree::BPlusTree(pb_disk_manager *disk, std::int32_t root_page_id,
                     std::uint16_t internal_max_size,
                     BufferPoolManager *buffer_pool)
    : disk_(disk), buffer_pool_(buffer_pool), root_page_id_(root_page_id),
      internal_max_size_(internal_max_size) {
  if (disk_ == nullptr || root_page_id_ < 0 || internal_max_size_ < 2 ||
      internal_max_size_ > kInternalMax)
    throw std::runtime_error("invalid B+Tree root or internal max size");
}

BPlusTree::BPlusTree(pb_disk_manager *disk, std::int32_t root_page_id,
                     BufferPoolManager *buffer_pool)
    : BPlusTree(disk, root_page_id, kInternalMax, buffer_pool) {}

BPlusTree BPlusTree::create(pb_disk_manager *disk, std::uint16_t leaf_max_size,
                            std::uint16_t internal_max_size,
                            BufferPoolManager *buffer_pool) {
  if (disk == nullptr) throw std::runtime_error("disk manager is null");
  char error[256]{};
  std::int32_t id{};
  check_status(pb_disk_allocate_page(disk, &id, error, sizeof(error)), error);
  pb_page page{};
  page.page_id = id;
  initialize_leaf(page, leaf_max_size);
  write_page(disk, page, buffer_pool);
  return BPlusTree(disk, id, internal_max_size, buffer_pool);
}

BPlusTree BPlusTree::create(pb_disk_manager *disk,
                            BufferPoolManager *buffer_pool,
                            std::uint16_t leaf_max_size,
                            std::uint16_t internal_max_size) {
  return create(disk, leaf_max_size, internal_max_size, buffer_pool);
}

std::int32_t BPlusTree::allocate_page() {
  char error[256]{};
  std::int32_t id{};
  check_status(pb_disk_allocate_page(disk_, &id, error, sizeof(error)), error);
  return id;
}

std::int32_t BPlusTree::find_leaf(std::int32_t key) const {
  auto page_id = root_page_id_;
  std::uint64_t depth = 0;
  std::uint32_t page_count{};
  char error[256]{};
  check_status(pb_disk_page_count(disk_, &page_count, error, sizeof(error)), error);
  while (true) {
    if (page_id < 0 || static_cast<std::uint32_t>(page_id) >= page_count || ++depth > page_count)
      throw std::runtime_error("invalid or cyclic B+Tree path");
    const auto page = read_page(disk_, page_id, buffer_pool_);
    if (page_type(page) == kLeaf) return page_id;
    if (page_type(page) != kInternal) throw std::runtime_error("unknown B+Tree page type");
    page_id = internal_child(page, child_index(page, key));
  }
}

std::optional<RecordId> BPlusTree::search(std::int32_t key) const {
  const auto page_id = find_leaf(key);
  const auto page = read_page(disk_, page_id, buffer_pool_);
  const auto index = leaf_lower_bound(page, key);
  if (index >= leaf_size(page) || leaf_key(page, index) != key) return std::nullopt;
  return leaf_rid(page, index);
}

void BPlusTree::insert(std::int32_t key, RecordId value) {
  if (value.page_id < 0) throw std::runtime_error("invalid RID page id");
  if (search(key).has_value()) throw std::runtime_error("duplicate index key: " + std::to_string(key));
  const auto leaf_id = find_leaf(key);
  auto leaf = read_page(disk_, leaf_id, buffer_pool_);
  const auto index = leaf_lower_bound(leaf, key);
  const auto size = leaf_size(leaf);
  if (size < leaf_max(leaf)) {
    for (std::uint16_t i = size; i > index; --i) set_leaf_entry(leaf, i, leaf_key(leaf, i - 1), leaf_rid(leaf, i - 1));
    set_leaf_entry(leaf, index, key, value);
    set_leaf_size(leaf, static_cast<std::uint16_t>(size + 1));
    write_page(disk_, leaf, buffer_pool_);
    return;
  }
  const auto [separator, right_id] = split_leaf_and_insert(leaf_id, key, value);
  insert_parent(leaf_id, separator, right_id);
}

std::pair<std::int32_t, std::int32_t> BPlusTree::split_leaf_and_insert(
    std::int32_t leaf_id, std::int32_t key, RecordId value) {
  auto leaf = read_page(disk_, leaf_id, buffer_pool_);
  std::vector<std::pair<std::int32_t, RecordId>> entries;
  entries.reserve(static_cast<std::size_t>(leaf_size(leaf)) + 1);
  for (std::uint16_t i = 0; i < leaf_size(leaf); ++i) entries.emplace_back(leaf_key(leaf, i), leaf_rid(leaf, i));
  entries.emplace_back(key, value);
  std::sort(entries.begin(), entries.end(), [](const auto &a, const auto &b) { return a.first < b.first; });
  const auto mid = entries.size() / 2;
  const auto old_next = leaf_next(leaf);
  set_leaf_size(leaf, static_cast<std::uint16_t>(mid));
  for (std::size_t i = 0; i < mid; ++i) set_leaf_entry(leaf, static_cast<std::uint16_t>(i), entries[i].first, entries[i].second);

  const auto right_id = allocate_page();
  pb_page right{};
  right.page_id = right_id;
  initialize_leaf(right, leaf_max(leaf), old_next);
  set_leaf_size(right, static_cast<std::uint16_t>(entries.size() - mid));
  for (std::size_t i = mid; i < entries.size(); ++i)
    set_leaf_entry(right, static_cast<std::uint16_t>(i - mid), entries[i].first, entries[i].second);
  put_i32(leaf.data + 5, right_id);
  write_page(disk_, leaf, buffer_pool_);
  write_page(disk_, right, buffer_pool_);
  return {entries[mid].first, right_id};
}

void BPlusTree::insert_parent(std::int32_t left_id, std::int32_t key,
                              std::int32_t right_id) {
  if (left_id == root_page_id_) {
    grow_root(left_id, key, right_id);
    return;
  }
  const auto parent_id = find_parent(root_page_id_, left_id);
  if (parent_id == PB_INVALID_PAGE_ID) throw std::runtime_error("B+Tree parent not found");
  auto parent = read_page(disk_, parent_id, buffer_pool_);
  std::uint16_t index = 0;
  while (index < internal_size(parent) && internal_child(parent, index) != left_id) ++index;
  if (index == internal_size(parent)) throw std::runtime_error("B+Tree child not in parent");
  if (internal_size(parent) < internal_max(parent)) {
    const auto size = internal_size(parent);
    set_internal_size(parent, static_cast<std::uint16_t>(size + 1));
    for (std::uint16_t i = size; i > index + 1; --i)
      set_internal_entry(parent, i, internal_key(parent, i - 1), internal_child(parent, i - 1));
    set_internal_entry(parent, static_cast<std::uint16_t>(index + 1), key, right_id);
    write_page(disk_, parent, buffer_pool_);
    return;
  }
  const auto [middle_key, new_right_id] = split_internal_and_insert(parent_id, left_id, key, right_id);
  insert_parent(parent_id, middle_key, new_right_id);
}

void BPlusTree::grow_root(std::int32_t left_id, std::int32_t key,
                          std::int32_t right_id) {
  const auto new_root_id = allocate_page();
  pb_page root{};
  root.page_id = new_root_id;
  initialize_internal(root, internal_max_size_);
  set_internal_size(root, 2);
  set_internal_entry(root, 0, 0, left_id);
  set_internal_entry(root, 1, key, right_id);
  write_page(disk_, root, buffer_pool_);
  root_page_id_ = new_root_id;
}

std::int32_t BPlusTree::find_parent(std::int32_t page_id,
                                    std::int32_t child_id) const {
  const auto page = read_page(disk_, page_id, buffer_pool_);
  if (page_type(page) != kInternal) return PB_INVALID_PAGE_ID;
  const auto size = internal_size(page);
  std::vector<std::int32_t> children;
  children.reserve(size);
  for (std::uint16_t i = 0; i < size; ++i) {
    const auto id = internal_child(page, i);
    if (id == child_id) return page_id;
    children.push_back(id);
  }
  for (const auto id : children) {
    const auto found = find_parent(id, child_id);
    if (found != PB_INVALID_PAGE_ID) return found;
  }
  return PB_INVALID_PAGE_ID;
}

std::pair<std::int32_t, std::int32_t> BPlusTree::split_internal_and_insert(
    std::int32_t node_id, std::int32_t left_child_id, std::int32_t key,
    std::int32_t right_id) {
  const auto node = read_page(disk_, node_id, buffer_pool_);
  const auto size = internal_size(node);
  std::vector<std::int32_t> values, keys;
  values.reserve(static_cast<std::size_t>(size) + 1);
  keys.reserve(static_cast<std::size_t>(size) + 1);
  for (std::uint16_t i = 0; i < size; ++i) {
    keys.push_back(internal_key(node, i));
    values.push_back(internal_child(node, i));
  }
  const auto found = std::find(values.begin(), values.end(), left_child_id);
  if (found == values.end()) throw std::runtime_error("split child not in internal node");
  const auto child_index_value = static_cast<std::size_t>(found - values.begin());
  values.insert(values.begin() + static_cast<std::ptrdiff_t>(child_index_value + 1), right_id);
  keys.insert(keys.begin() + static_cast<std::ptrdiff_t>(child_index_value + 1), key);
  const auto mid = values.size() / 2;
  const auto middle_key = keys[mid];

  auto left = read_page(disk_, node_id, buffer_pool_);
  set_internal_size(left, static_cast<std::uint16_t>(mid));
  for (std::size_t i = 0; i < mid; ++i)
    set_internal_entry(left, static_cast<std::uint16_t>(i), keys[i], values[i]);
  write_page(disk_, left, buffer_pool_);

  const auto new_right_id = allocate_page();
  pb_page right{};
  right.page_id = new_right_id;
  initialize_internal(right, internal_max(node));
  const auto right_size = values.size() - mid;
  set_internal_size(right, static_cast<std::uint16_t>(right_size));
  set_internal_entry(right, 0, 0, values[mid]);
  for (std::size_t i = 1; i < right_size; ++i)
    set_internal_entry(right, static_cast<std::uint16_t>(i), keys[mid + i], values[mid + i]);
  write_page(disk_, right, buffer_pool_);
  return {middle_key, new_right_id};
}

bool BPlusTree::erase(std::int32_t key) {
  const auto page_id = find_leaf(key);
  auto page = read_page(disk_, page_id, buffer_pool_);
  const auto index = leaf_lower_bound(page, key);
  const auto size = leaf_size(page);
  if (index == size || leaf_key(page, index) != key) return false;
  for (std::uint16_t i = index; i + 1 < size; ++i)
    set_leaf_entry(page, i, leaf_key(page, static_cast<std::uint16_t>(i + 1)), leaf_rid(page, static_cast<std::uint16_t>(i + 1)));
  set_leaf_size(page, static_cast<std::uint16_t>(size - 1));
  write_page(disk_, page, buffer_pool_);
  return true;
}

std::vector<std::pair<std::int32_t, RecordId>> BPlusTree::scan(
    std::optional<std::int32_t> low, std::optional<std::int32_t> high) const {
  auto page_id = low.has_value() ? find_leaf(*low) : root_page_id_;
  if (!low.has_value()) {
    while (true) {
      const auto page = read_page(disk_, page_id, buffer_pool_);
      if (page_type(page) == kLeaf) break;
      page_id = internal_child(page, 0);
    }
  }
  std::vector<std::pair<std::int32_t, RecordId>> result;
  std::uint32_t page_count{};
  char error[256]{};
  check_status(pb_disk_page_count(disk_, &page_count, error, sizeof(error)), error);
  for (std::uint32_t seen = 0; page_id != PB_INVALID_PAGE_ID; ++seen) {
    if (page_id < 0 || static_cast<std::uint32_t>(page_id) >= page_count || seen >= page_count)
      throw std::runtime_error("invalid or cyclic B+Tree leaf chain");
    const auto page = read_page(disk_, page_id, buffer_pool_);
    if (page_type(page) != kLeaf) throw std::runtime_error("non-leaf in B+Tree leaf chain");
    auto index = low.has_value() ? leaf_lower_bound(page, *low) : 0;
    for (; index < leaf_size(page); ++index) {
      const auto key = leaf_key(page, index);
      if (high.has_value() && key > *high) return result;
      result.emplace_back(key, leaf_rid(page, index));
    }
    page_id = leaf_next(page);
    low.reset();
  }
  return result;
}

}  // namespace pebble
