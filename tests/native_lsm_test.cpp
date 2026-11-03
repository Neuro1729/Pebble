#include "pebble/index.hpp"

#include <cassert>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <limits>
#include <map>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

class TemporaryDirectory {
 public:
  TemporaryDirectory() {
    const auto nonce =
        std::chrono::steady_clock::now().time_since_epoch().count();
    path_ = std::filesystem::temp_directory_path() /
            ("pebble-lsm-test-" + std::to_string(nonce));
    std::filesystem::create_directories(path_);
  }

  ~TemporaryDirectory() {
    std::error_code ignored;
    std::filesystem::remove_all(path_, ignored);
  }

  const std::filesystem::path &path() const noexcept { return path_; }

 private:
  std::filesystem::path path_;
};

bool same_rid(const pebble::RecordId &left, const pebble::RecordId &right) {
  return left.page_id == right.page_id && left.slot_num == right.slot_num;
}

void check_model(
    const pebble::LSMTree &tree,
    const std::map<std::int32_t, pebble::RecordId> &model) {
  const auto entries = tree.scan();
  assert(entries.size() == model.size());

  auto expected = model.begin();
  for (const auto &[key, rid] : entries) {
    assert(expected != model.end());
    assert(key == expected->first);
    assert(same_rid(rid, expected->second));
    ++expected;
  }
  assert(expected == model.end());

  for (const auto &[key, rid] : model) {
    const auto actual = tree.search(key);
    assert(actual.has_value());
    assert(same_rid(*actual, rid));
  }

  for (const auto key : {-1000, -1, 0, 1, 1000}) {
    if (model.find(key) == model.end()) assert(!tree.search(key).has_value());
  }
}

void test_signed_order_ranges_and_reopen() {
  TemporaryDirectory directory;
  const auto index_path = directory.path() / "signed";
  {
    pebble::LSMTree tree(index_path, 3);
    tree.insert(std::numeric_limits<std::int32_t>::min(), {0, 1});
    tree.insert(-1, {0, 2});
    tree.insert(0, {0, 3});
    tree.insert(1, {0, 4});
    tree.insert(std::numeric_limits<std::int32_t>::max(), {0, 5});
    tree.flush();

    const auto range = tree.scan(-1, 1);
    assert(range.size() == 3);
    assert(range[0].first == -1 && range[1].first == 0 &&
           range[2].first == 1);
    assert(tree.scan(2, 1).empty());
    assert(tree.scan(std::numeric_limits<std::int32_t>::max(),
                     std::numeric_limits<std::int32_t>::max())
               .size() == 1);
  }
  {
    pebble::LSMTree tree(index_path, 3, false);
    assert(tree.scan().size() == 5);
    assert(tree.search(std::numeric_limits<std::int32_t>::min()).has_value());
    assert(tree.search(std::numeric_limits<std::int32_t>::max()).has_value());
  }
}

void test_tombstone_reinsert_and_duplicate_rules() {
  TemporaryDirectory directory;
  pebble::LSMTree tree(directory.path() / "updates", 2);

  tree.insert(7, {1, 10});
  tree.flush();
  assert(tree.erase(7));
  tree.flush();
  assert(!tree.search(7).has_value());
  assert(!tree.erase(7));
  assert(tree.scan().empty());

  tree.insert(7, {2, 20});
  assert(tree.search(7).has_value());
  const auto current = tree.search(7);
  assert(current && current->page_id == 2 && current->slot_num == 20);
  tree.flush();
  bool duplicate_rejected = false;
  try {
    tree.insert(7, {9, 9});
  } catch (const std::runtime_error &) {
    duplicate_rejected = true;
  }
  assert(duplicate_rejected);

  pebble::LSMTree reopened(directory.path() / "updates", 2, false);
  const auto restored = reopened.search(7);
  assert(restored && restored->page_id == 2 && restored->slot_num == 20);
}

void test_compaction_preserves_latest_values_and_deletes() {
  TemporaryDirectory directory;
  const auto index_path = directory.path() / "compact";
  std::map<std::int32_t, pebble::RecordId> model;
  {
    pebble::LSMTree tree(index_path, 2);
    tree.insert(1, {1, 1});
    tree.insert(2, {2, 2});
    tree.flush();
    tree.erase(1);
    tree.insert(3, {3, 3});
    tree.flush();
    tree.insert(1, {4, 4});
    tree.insert(4, {4, 5});
    tree.flush();
    tree.erase(2);
    tree.insert(5, {5, 5});
    tree.flush();
    model = {{1, {4, 4}}, {3, {3, 3}}, {4, {4, 5}}, {5, {5, 5}}};
    check_model(tree, model);
  }

  {
    pebble::LSMTree tree(index_path, 2, false);
    check_model(tree, model);
    tree.insert(2, {9, 2});
    model[2] = {9, 2};
    tree.flush();
    check_model(tree, model);
  }
}

void test_size_tiered_compaction_keeps_tombstones_for_older_runs() {
  TemporaryDirectory directory;
  const auto index_path = directory.path() / "tiered-tombstones";
  {
    pebble::LSMTree tree(index_path, 4);
    for (std::int32_t key = 1; key <= 4; ++key)
      tree.insert(key, {key, 1});
    tree.erase(1);
    tree.flush();
    tree.insert(5, {5, 1});
    tree.flush();
    tree.insert(6, {6, 1});
    tree.flush();
    tree.insert(7, {7, 1});
    tree.flush();

    assert(!tree.search(1).has_value());
    const auto entries = tree.scan();
    assert(entries.size() == 6);
    assert(entries.front().first == 2 && entries.back().first == 7);
  }
  {
    pebble::LSMTree reopened(index_path, 4, false);
    assert(!reopened.search(1).has_value());
    const auto entries = reopened.scan();
    assert(entries.size() == 6);
    assert(entries.front().first == 2 && entries.back().first == 7);
  }
}

void test_legacy_manifest_is_upgraded_on_open() {
  TemporaryDirectory directory;
  const auto index_path = directory.path() / "legacy-manifest";
  {
    pebble::LSMTree tree(index_path, 2);
    tree.insert(10, {1, 1});
    tree.insert(20, {1, 2});
    tree.flush();
  }

  const auto manifest_path = index_path / "MANIFEST";
  std::string magic;
  std::uint32_t version{};
  std::uint64_t next_sequence{};
  std::uint64_t next_file_id{};
  std::size_t count{};
  std::vector<std::uint64_t> run_ids;
  {
    std::ifstream in(manifest_path);
    assert(in >> magic >> version >> next_sequence >> next_file_id >> count);
    assert(magic == "PEBBLE_LSM" && version == 2);
    for (std::size_t i = 0; i < count; ++i) {
      std::uint64_t id{}, max_sequence{};
      assert(in >> id >> max_sequence);
      run_ids.push_back(id);
    }
  }
  {
    std::ofstream out(manifest_path, std::ios::trunc);
    assert(out.good());
    out << "PEBBLE_LSM 1 " << next_sequence << ' ' << next_file_id << ' '
        << count << '\n';
    for (const auto id : run_ids) out << id << '\n';
  }

  {
    pebble::LSMTree reopened(index_path, 2, false);
    assert(reopened.search(10).has_value());
    assert(reopened.search(20).has_value());
  }
  {
    std::ifstream in(manifest_path);
    assert(in >> magic >> version);
    assert(magic == "PEBBLE_LSM" && version == 2);
  }
}

void test_randomized_operations_against_ordered_map() {
  TemporaryDirectory directory;
  const auto index_path = directory.path() / "random";
  std::map<std::int32_t, pebble::RecordId> model;
  std::mt19937 random(0x5eed);
  std::uniform_int_distribution<std::int32_t> key_distribution(-80, 80);

  {
    pebble::LSMTree tree(index_path, 9);
    for (std::uint16_t step = 0; step < 1200; ++step) {
      const auto key = key_distribution(random);
      if ((random() % 3) == 0) {
        const auto removed = tree.erase(key);
        const auto found = model.find(key);
        assert(removed == (found != model.end()));
        if (found != model.end()) model.erase(found);
      } else {
        const pebble::RecordId value{
            static_cast<std::int32_t>(step / 200),
            static_cast<std::uint16_t>(step)};
        const auto found = model.find(key);
        if (found == model.end()) {
          tree.insert(key, value);
          model.emplace(key, value);
        } else {
          bool duplicate_rejected = false;
          try {
            tree.insert(key, value);
          } catch (const std::runtime_error &) {
            duplicate_rejected = true;
          }
          assert(duplicate_rejected);
        }
      }

      if (step % 41 == 0) {
        tree.flush();
        check_model(tree, model);
        const auto low = key_distribution(random);
        const auto high = key_distribution(random);
        const auto range = tree.scan(std::min(low, high), std::max(low, high));
        std::vector<std::pair<std::int32_t, pebble::RecordId>> expected;
        for (auto it = model.lower_bound(std::min(low, high));
             it != model.end() && it->first <= std::max(low, high); ++it)
          expected.push_back(*it);
        assert(range.size() == expected.size());
        for (std::size_t i = 0; i < range.size(); ++i) {
          assert(range[i].first == expected[i].first);
          assert(same_rid(range[i].second, expected[i].second));
        }
      }
    }
    tree.flush();
    check_model(tree, model);
  }

  {
    pebble::LSMTree reopened(index_path, 9, false);
    check_model(reopened, model);
  }
}

void test_existing_directory_requires_manifest_when_opening() {
  TemporaryDirectory directory;
  bool missing_manifest_rejected = false;
  try {
    pebble::LSMTree tree(directory.path() / "missing", 8, false);
  } catch (const std::runtime_error &) {
    missing_manifest_rejected = true;
  }
  assert(missing_manifest_rejected);
}

}  // namespace

int main() {
  test_signed_order_ranges_and_reopen();
  test_tombstone_reinsert_and_duplicate_rules();
  test_compaction_preserves_latest_values_and_deletes();
  test_size_tiered_compaction_keeps_tombstones_for_older_runs();
  test_legacy_manifest_is_upgraded_on_open();
  test_randomized_operations_against_ordered_map();
  test_existing_directory_requires_manifest_when_opening();
  return 0;
}
