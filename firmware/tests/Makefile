CC ?= cc
CFLAGS ?= -O1 -g
APP := ../STM32_SmartParking/App
INCLUDES := -Imocks -I$(APP)/Inc -I../STM32_SmartParking/Core/Inc
STRICT := -std=c11 -Wall -Wextra -Werror -UNDEBUG
COMMON := mocks/mock_hal.c

.PHONY: test sanitize analyze check
test sanitize:
	@set -eu; out=$$(mktemp -d "$${TMPDIR:-/tmp}/stm32-parking-tests.XXXXXX"); \
	trap 'rm -rf "$$out"' EXIT HUP INT TERM; \
	flags=''; if [ '$@' = sanitize ]; then flags='-fsanitize=address,undefined -fno-omit-frame-pointer'; fi; \
	$(CC) $(STRICT) $(CFLAGS) $$flags $(INCLUDES) test_vehicle_detector.c $(APP)/Src/vehicle_detector.c $(COMMON) -o "$$out/vehicle"; "$$out/vehicle"; \
	$(CC) $(STRICT) $(CFLAGS) $$flags $(INCLUDES) test_parking_spot.c $(APP)/Src/parking_spot.c $(COMMON) -o "$$out/spot"; "$$out/spot"; \
	$(CC) $(STRICT) $(CFLAGS) $$flags $(INCLUDES) test_parking_manager.c $(APP)/Src/parking_manager.c $(APP)/Src/parking_spot.c $(COMMON) -o "$$out/manager"; "$$out/manager"; \
	$(CC) $(STRICT) $(CFLAGS) $$flags $(INCLUDES) test_barrier_controller.c $(APP)/Src/barrier_controller.c -o "$$out/barrier_regression"; "$$out/barrier_regression"; \
	$(CC) $(STRICT) $(CFLAGS) $$flags $(INCLUDES) test_barrier_safety.c $(APP)/Src/barrier_controller.c -o "$$out/barrier_safety"; "$$out/barrier_safety"

analyze:
	@set -eu; tidy=$$(command -v clang-tidy || true); \
	if [ -z "$$tidy" ] && command -v brew >/dev/null 2>&1; then tidy="$$(brew --prefix llvm 2>/dev/null)/bin/clang-tidy"; fi; \
	if [ ! -x "$$tidy" ]; then echo 'clang-tidy is unavailable' >&2; exit 1; fi; \
	for source in $(APP)/Src/vehicle_detector.c $(APP)/Src/parking_spot.c $(APP)/Src/parking_manager.c $(APP)/Src/barrier_controller.c; do \
	  set --; \
	  if [ "$$source" = "$(APP)/Src/vehicle_detector.c" ]; then \
	    set -- --line-filter='[{"name":"vehicle_detector.c","lines":[[1,6],[9,999999]]},{"name":"vehicle_detector.h","lines":[[1,999999]]}]'; \
	  fi; \
	  "$$tidy" "$$source" -quiet -checks='-*,clang-analyzer-*,bugprone-*' \
	    --warnings-as-errors='*' --header-filter='.*' \
	    --exclude-header-filter='(^|/)Core/Inc/main\.h$$' "$$@" -- $(STRICT) $(INCLUDES); \
	done

check: test sanitize analyze
