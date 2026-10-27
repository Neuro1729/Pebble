#include "pebble/storage.h"

#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct pb_disk_manager {
  FILE *file;
  uint32_t page_count;
};

static void set_error(char *out, size_t capacity, const char *message) {
  if (out == NULL || capacity == 0) {
    return;
  }
  (void)snprintf(out, capacity, "%s", message == NULL ? "" : message);
}

static void set_errno_error(char *out, size_t capacity, const char *operation) {
  if (out == NULL || capacity == 0) {
    return;
  }
  (void)snprintf(out, capacity, "%s: %s", operation, strerror(errno));
}

static int page_offset(int32_t page_id, long *offset_out) {
  long id = (long)page_id;
  if (page_id < 0 || id > LONG_MAX / (long)PB_PAGE_SIZE) {
    return 0;
  }
  *offset_out = id * (long)PB_PAGE_SIZE;
  return 1;
}

void pb_page_init(pb_page *page, int32_t page_id) {
  if (page == NULL) {
    return;
  }
  page->page_id = page_id;
  memset(page->data, 0, sizeof(page->data));
}

const char *pb_status_name(pb_status status) {
  switch (status) {
  case PB_STATUS_OK:
    return "ok";
  case PB_STATUS_INVALID_ARGUMENT:
    return "invalid argument";
  case PB_STATUS_IO_ERROR:
    return "I/O error";
  case PB_STATUS_CORRUPT_FILE:
    return "corrupt page file";
  case PB_STATUS_OUT_OF_MEMORY:
    return "out of memory";
  }
  return "unknown status";
}

pb_disk_manager *pb_disk_open(const char *path, pb_status *status,
                              char *error_out, size_t error_capacity) {
  FILE *file;
  long file_size;
  pb_disk_manager *disk;

  if (status != NULL) {
    *status = PB_STATUS_INVALID_ARGUMENT;
  }
  if (path == NULL || path[0] == '\0') {
    set_error(error_out, error_capacity, "database path must be non-empty");
    return NULL;
  }

  file = fopen(path, "r+b");
  if (file == NULL && errno == ENOENT) {
    file = fopen(path, "w+b");
  }
  if (file == NULL) {
    set_errno_error(error_out, error_capacity, "opening database file");
    if (status != NULL) {
      *status = PB_STATUS_IO_ERROR;
    }
    return NULL;
  }

  if (fseek(file, 0L, SEEK_END) != 0 || (file_size = ftell(file)) < 0L) {
    set_errno_error(error_out, error_capacity, "measuring database file");
    (void)fclose(file);
    if (status != NULL) {
      *status = PB_STATUS_IO_ERROR;
    }
    return NULL;
  }
  if (file_size % (long)PB_PAGE_SIZE != 0L ||
      (unsigned long)(file_size / (long)PB_PAGE_SIZE) > UINT32_MAX) {
    set_error(error_out, error_capacity,
              "database file size is not a valid page count");
    (void)fclose(file);
    if (status != NULL) {
      *status = PB_STATUS_CORRUPT_FILE;
    }
    return NULL;
  }

  disk = (pb_disk_manager *)malloc(sizeof(*disk));
  if (disk == NULL) {
    set_error(error_out, error_capacity, "allocating disk manager");
    (void)fclose(file);
    if (status != NULL) {
      *status = PB_STATUS_OUT_OF_MEMORY;
    }
    return NULL;
  }
  disk->file = file;
  disk->page_count = (uint32_t)(file_size / (long)PB_PAGE_SIZE);
  set_error(error_out, error_capacity, "");
  if (status != NULL) {
    *status = PB_STATUS_OK;
  }
  return disk;
}

pb_status pb_disk_close(pb_disk_manager *disk, char *error_out,
                        size_t error_capacity) {
  int failed;
  if (disk == NULL) {
    set_error(error_out, error_capacity, "disk manager is null");
    return PB_STATUS_INVALID_ARGUMENT;
  }
  failed = fflush(disk->file) != 0;
  if (fclose(disk->file) != 0) {
    failed = 1;
  }
  free(disk);
  if (failed) {
    set_errno_error(error_out, error_capacity, "closing database file");
    return PB_STATUS_IO_ERROR;
  }
  set_error(error_out, error_capacity, "");
  return PB_STATUS_OK;
}

pb_status pb_disk_page_count(pb_disk_manager *disk, uint32_t *count_out,
                             char *error_out, size_t error_capacity) {
  if (disk == NULL || count_out == NULL) {
    set_error(error_out, error_capacity, "disk manager/count output is null");
    return PB_STATUS_INVALID_ARGUMENT;
  }
  *count_out = disk->page_count;
  set_error(error_out, error_capacity, "");
  return PB_STATUS_OK;
}

pb_status pb_disk_allocate_page(pb_disk_manager *disk, int32_t *page_id_out,
                                char *error_out, size_t error_capacity) {
  pb_page page;
  if (disk == NULL || page_id_out == NULL) {
    set_error(error_out, error_capacity, "disk manager/page output is null");
    return PB_STATUS_INVALID_ARGUMENT;
  }
  if (disk->page_count > (uint32_t)INT32_MAX) {
    set_error(error_out, error_capacity, "page id space is exhausted");
    return PB_STATUS_IO_ERROR;
  }
  *page_id_out = (int32_t)disk->page_count;
  pb_page_init(&page, *page_id_out);
  return pb_disk_write_page(disk, &page, error_out, error_capacity);
}

pb_status pb_disk_read_page(pb_disk_manager *disk, int32_t page_id,
                            pb_page *page_out, char *error_out,
                            size_t error_capacity) {
  long offset;
  size_t read_count;
  if (disk == NULL || page_out == NULL || !page_offset(page_id, &offset)) {
    set_error(error_out, error_capacity, "invalid disk manager, page, or id");
    return PB_STATUS_INVALID_ARGUMENT;
  }
  if ((uint32_t)page_id >= disk->page_count) {
    set_error(error_out, error_capacity, "page id does not exist");
    return PB_STATUS_INVALID_ARGUMENT;
  }
  if (fseek(disk->file, offset, SEEK_SET) != 0) {
    set_errno_error(error_out, error_capacity, "seeking to page");
    return PB_STATUS_IO_ERROR;
  }
  read_count = fread(page_out->data, 1u, PB_PAGE_SIZE, disk->file);
  if (read_count != PB_PAGE_SIZE) {
    set_error(error_out, error_capacity,
              ferror(disk->file) ? "reading page failed" : "short page read");
    return PB_STATUS_IO_ERROR;
  }
  page_out->page_id = page_id;
  set_error(error_out, error_capacity, "");
  return PB_STATUS_OK;
}

pb_status pb_disk_write_page(pb_disk_manager *disk, const pb_page *page,
                             char *error_out, size_t error_capacity) {
  long offset;
  if (disk == NULL || page == NULL || !page_offset(page->page_id, &offset)) {
    set_error(error_out, error_capacity, "invalid disk manager, page, or id");
    return PB_STATUS_INVALID_ARGUMENT;
  }
  if (fseek(disk->file, offset, SEEK_SET) != 0 ||
      fwrite(page->data, 1u, PB_PAGE_SIZE, disk->file) != PB_PAGE_SIZE ||
      fflush(disk->file) != 0) {
    set_errno_error(error_out, error_capacity, "writing page");
    return PB_STATUS_IO_ERROR;
  }
  if ((uint32_t)page->page_id >= disk->page_count) {
    disk->page_count = (uint32_t)page->page_id + 1u;
  }
  set_error(error_out, error_capacity, "");
  return PB_STATUS_OK;
}
