CC ?= cc
CXX ?= c++
AR ?= ar
ARFLAGS = rcs
THREADFLAGS ?= -pthread

CONFIG ?= debug
BUILD_DIR ?= build/$(CONFIG)
PREFIX ?= /usr/local
DESTDIR ?=
DB_PATH ?= $(BUILD_DIR)/pebble.db
RUN_ARGS ?= --database "$(DB_PATH)"

CPPFLAGS += -Inative/include
WARNFLAGS = -Wall -Wextra -Wpedantic
DEPFLAGS = -MMD -MP

ifeq ($(CONFIG),debug)
MODEFLAGS = -O0 -g
else ifeq ($(CONFIG),release)
MODEFLAGS = -O3 -DNDEBUG
else
$(error CONFIG must be 'debug' or 'release')
endif

ifeq ($(SANITIZE),address)
MODEFLAGS += -fsanitize=address,undefined -fno-omit-frame-pointer
endif
TEST_MODEFLAGS = $(filter-out -DNDEBUG,$(MODEFLAGS))

C_SOURCES = native/c/storage.c
CXX_SOURCES = native/cpp/arc_replacer.cpp native/cpp/buffer_pool.cpp native/cpp/disk_scheduler.cpp native/cpp/engine.cpp native/cpp/index.cpp native/cpp/main.cpp
C_OBJECTS = $(patsubst native/c/%.c,$(BUILD_DIR)/obj/c/%.o,$(C_SOURCES))
CXX_OBJECTS = $(patsubst native/cpp/%.cpp,$(BUILD_DIR)/obj/cpp/%.o,$(CXX_SOURCES))
LIBRARY = $(BUILD_DIR)/lib/libpebble_storage.a
DBMS = $(BUILD_DIR)/bin/dbms
DEPS = $(C_OBJECTS:.o=.d) $(CXX_OBJECTS:.o=.d)
TEST_OBJECTS = $(filter-out $(BUILD_DIR)/obj/cpp/main.o,$(CXX_OBJECTS))

.PHONY: all lib test check bench clean run debug release help install studio

all: $(DBMS)

lib: $(LIBRARY)

$(BUILD_DIR)/obj/c/%.o: native/c/%.c
	@mkdir -p "$(@D)"
	$(CC) $(CPPFLAGS) $(CFLAGS) $(WARNFLAGS) $(MODEFLAGS) -std=c17 $(DEPFLAGS) -c $< -o $@

$(BUILD_DIR)/obj/cpp/%.o: native/cpp/%.cpp
	@mkdir -p "$(@D)"
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(WARNFLAGS) $(MODEFLAGS) $(THREADFLAGS) -std=c++20 $(DEPFLAGS) -c $< -o $@

$(LIBRARY): $(C_OBJECTS)
	@mkdir -p "$(@D)"
	$(AR) $(ARFLAGS) $@ $(C_OBJECTS)

$(DBMS): $(CXX_OBJECTS) $(LIBRARY)
	@mkdir -p "$(@D)"
	$(CXX) $(LDFLAGS) $(MODEFLAGS) $(THREADFLAGS) $(CXX_OBJECTS) $(LIBRARY) $(LDLIBS) -o $@

test: $(DBMS) $(TEST_OBJECTS)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(WARNFLAGS) $(TEST_MODEFLAGS) $(THREADFLAGS) -std=c++20 tests/native_engine_test.cpp $(TEST_OBJECTS) $(LIBRARY) $(LDFLAGS) $(LDLIBS) -o $(BUILD_DIR)/bin/native_engine_test
	$(BUILD_DIR)/bin/native_engine_test
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(WARNFLAGS) $(TEST_MODEFLAGS) $(THREADFLAGS) -std=c++20 tests/native_lsm_test.cpp $(TEST_OBJECTS) $(LIBRARY) $(LDFLAGS) $(LDLIBS) -o $(BUILD_DIR)/bin/native_lsm_test
	$(BUILD_DIR)/bin/native_lsm_test
	sh tests/native_integration.sh "$(DBMS)"

check: test

bench:
	@echo "No benchmark suite is implemented yet."

run: $(DBMS)
	$(DBMS) $(RUN_ARGS)

studio: $(DBMS)
	python3 scripts/studio.py

debug:
	$(MAKE) CONFIG=debug all

release:
	$(MAKE) CONFIG=release all

install: $(DBMS)
	install -d "$(DESTDIR)$(PREFIX)/bin"
	install -m 755 "$(DBMS)" "$(DESTDIR)$(PREFIX)/bin/dbms"

clean:
	rm -rf build
	@if test "$(BUILD_DIR)" != "build"; then rm -rf "$(BUILD_DIR)"; fi

help:
	@echo "Targets: all lib test check bench run studio debug release clean install help"
	@echo "Settings: CONFIG=debug|release BUILD_DIR=... PREFIX=... CC=... CXX=..."
	@echo "          DB_PATH=... RUN_ARGS='--database-dir ./data'"
	@echo "          CFLAGS=... CXXFLAGS=... CPPFLAGS=... LDFLAGS=... LDLIBS=..."
	@echo "          THREADFLAGS=-pthread (override for a custom toolchain)"
	@echo "          SANITIZE=address enables AddressSanitizer and UBSan"

-include $(DEPS)
