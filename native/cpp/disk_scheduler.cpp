// Sends database page reads and writes to a worker thread so disk operations
// are handled through one request queue.

#include "pebble/disk_scheduler.hpp"

#include <stdexcept>
#include <utility>

namespace pebble {

// Starts the worker that handles page requests.
DiskScheduler::DiskScheduler(pb_disk_manager *disk) : disk_(disk) {
  if (disk_ == nullptr) throw std::invalid_argument("disk manager is null");
  worker_ = std::thread(&DiskScheduler::run, this);
}

// Stops the worker and waits for queued requests to finish.
DiskScheduler::~DiskScheduler() {
  {
    std::lock_guard lock(mutex_);
    stopping_ = true;
  }
  ready_.notify_all();
  if (worker_.joinable()) worker_.join();
}

// Requests a page from disk and returns it after the read completes.
pb_page DiskScheduler::read_page(std::int32_t page_id) {
  auto request = std::make_shared<Request>();
  request->page_id = page_id;
  const auto result = submit(request);
  check_result(result);
  return result.page;
}

// Requests that a page be written to disk.
void DiskScheduler::write_page(const pb_page &page) {
  auto request = std::make_shared<Request>();
  request->write = true;
  request->page_id = page.page_id;
  request->page = page;
  check_result(submit(request));
}

// Queues a request and waits for the worker to return its result.
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

// Turns a failed disk operation into an exception.
void DiskScheduler::check_result(const Result &result) {
  if (result.status != PB_STATUS_OK)
    throw std::runtime_error(std::string(pb_status_name(result.status)) + ": " +
                             result.error);
}

// Processes queued read and write requests until shutdown.
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
