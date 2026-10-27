#include "pebble/disk_scheduler.hpp"

#include <stdexcept>
#include <utility>

namespace pebble {

DiskScheduler::DiskScheduler(pb_disk_manager *disk) : disk_(disk) {
  if (disk_ == nullptr) throw std::invalid_argument("disk manager is null");
  worker_ = std::thread(&DiskScheduler::run, this);
}

DiskScheduler::~DiskScheduler() {
  {
    std::lock_guard lock(mutex_);
    stopping_ = true;
  }
  ready_.notify_all();
  if (worker_.joinable()) worker_.join();
}

pb_page DiskScheduler::read_page(std::int32_t page_id) {
  auto request = std::make_shared<Request>();
  request->page_id = page_id;
  const auto result = submit(request);
  check_result(result);
  return result.page;
}

void DiskScheduler::write_page(const pb_page &page) {
  auto request = std::make_shared<Request>();
  request->write = true;
  request->page_id = page.page_id;
  request->page = page;
  check_result(submit(request));
}

DiskScheduler::Result DiskScheduler::submit(
    const std::shared_ptr<Request> &request) {
  auto future = request->completion.get_future();
  {
    std::lock_guard lock(mutex_);
    if (stopping_) throw std::runtime_error("disk scheduler is stopping");
    requests_.push(request);
  }
  ready_.notify_one();
  return future.get();
}

void DiskScheduler::check_result(const Result &result) {
  if (result.status != PB_STATUS_OK)
    throw std::runtime_error(std::string(pb_status_name(result.status)) + ": " +
                             result.error);
}

void DiskScheduler::run() {
  for (;;) {
    std::shared_ptr<Request> request;
    {
      std::unique_lock lock(mutex_);
      ready_.wait(lock, [&] { return stopping_ || !requests_.empty(); });
      if (requests_.empty() && stopping_) return;
      request = std::move(requests_.front());
      requests_.pop();
    }

    Result result;
    char error[256]{};
    if (request->write) {
      result.status = pb_disk_write_page(disk_, &request->page, error, sizeof(error));
    } else {
      result.status = pb_disk_read_page(disk_, request->page_id, &result.page,
                                        error, sizeof(error));
    }
    result.error = error;
    request->completion.set_value(std::move(result));
  }
}

}  // namespace pebble
