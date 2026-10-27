#ifndef PEBBLE_DISK_SCHEDULER_HPP
#define PEBBLE_DISK_SCHEDULER_HPP

#include "pebble/storage.h"

#include <condition_variable>
#include <cstdint>
#include <future>
#include <memory>
#include <mutex>
#include <queue>
#include <string>
#include <thread>

namespace pebble {

class DiskScheduler {
 public:
  explicit DiskScheduler(pb_disk_manager *disk);
  ~DiskScheduler();
  DiskScheduler(const DiskScheduler &) = delete;
  DiskScheduler &operator=(const DiskScheduler &) = delete;

  pb_page read_page(std::int32_t page_id);
  void write_page(const pb_page &page);

 private:
  struct Result {
    pb_page page{};
    pb_status status{PB_STATUS_OK};
    std::string error;
  };
  struct Request {
    bool write{};
    std::int32_t page_id{};
    pb_page page{};
    std::promise<Result> completion;
  };

  pb_disk_manager *disk_;
  std::mutex mutex_;
  std::condition_variable ready_;
  std::queue<std::shared_ptr<Request>> requests_;
  bool stopping_{};
  std::thread worker_;

  Result submit(const std::shared_ptr<Request> &request);
  static void check_result(const Result &result);
  void run();
};

}  // namespace pebble

#endif
