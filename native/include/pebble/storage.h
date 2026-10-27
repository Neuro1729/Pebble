#ifndef PEBBLE_STORAGE_H
#define PEBBLE_STORAGE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PB_PAGE_SIZE 4096u
#define PB_INVALID_PAGE_ID (-1)

typedef struct pb_page {
  int32_t page_id;
  uint8_t data[PB_PAGE_SIZE];
} pb_page;

typedef struct pb_disk_manager pb_disk_manager;

typedef enum pb_status {
  PB_STATUS_OK = 0,
  PB_STATUS_INVALID_ARGUMENT,
  PB_STATUS_IO_ERROR,
  PB_STATUS_CORRUPT_FILE,
  PB_STATUS_OUT_OF_MEMORY
} pb_status;

/* Open an existing page file or create it. Parent directories must exist. */
pb_disk_manager *pb_disk_open(const char *path, pb_status *status,
                              char *error_out, size_t error_capacity);
pb_status pb_disk_close(pb_disk_manager *disk, char *error_out,
                        size_t error_capacity);
pb_status pb_disk_page_count(pb_disk_manager *disk, uint32_t *count_out,
                             char *error_out, size_t error_capacity);
pb_status pb_disk_allocate_page(pb_disk_manager *disk, int32_t *page_id_out,
                                char *error_out, size_t error_capacity);
pb_status pb_disk_read_page(pb_disk_manager *disk, int32_t page_id,
                            pb_page *page_out, char *error_out,
                            size_t error_capacity);
pb_status pb_disk_write_page(pb_disk_manager *disk, const pb_page *page,
                             char *error_out, size_t error_capacity);

void pb_page_init(pb_page *page, int32_t page_id);
const char *pb_status_name(pb_status status);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* PEBBLE_STORAGE_H */
