# Native firmware unit tests

Run `make -C firmware/tests test` from the repository root. The runner compiles
the four production C modules with minimal HAL GPIO mocks, then runs the existing
barrier regressions and new detector, spot, manager, and barrier safety tests.
It uses C11, `-Wall -Wextra -Werror`, fails on compile or assertion errors, and
keeps temporary binaries outside tracked source directories.

Use `make -C firmware/tests sanitize` for AddressSanitizer and
UndefinedBehaviorSanitizer. `make -C firmware/tests analyze` requires
`clang-tidy` (found on `PATH` or through Homebrew LLVM) and treats all reported
`clang-analyzer-*` and `bugprone-*` diagnostics as errors. GitHub Actions runs
all three targets. `make -C firmware/tests check` runs them locally in order.
`CC` and `CFLAGS` can be overridden as normal Make variables.

The analysis target excludes only CubeMX-generated `Core/Inc/main.h`, whose
`__MAIN_H` guard triggers `bugprone-reserved-identifier`. The existing public
`VehicleDetector_Init` signature triggers
`bugprone-easily-swappable-parameters`; a check-specific `NOLINTBEGIN` /
`NOLINTEND` pair wraps only that declaration in `vehicle_detector.c`. No source
lines are filtered, so other enabled diagnostics on those lines remain active.
The function signature and behavior are unchanged.

The mocks enforce explicit sensor input setup and record GPIO reads and writes.
They use the GPIO symbols and pin mappings from the production `main.h`.

The hybrid suite also verifies that RTU dequeue checks the caller's capacity
against the queued frame length, even while a shorter subsequent frame is
being collected, and that a rejected dequeue preserves the queued frame.

These host tests do not compile generated `main.c`, validate GPIO wiring,
interrupt timing, ARM builds, real sensor fault detection, or physical servo
control. A reported fault freezes the barrier's logical position. Gate motion,
motor current limits, startup with an obstructed beam, and concurrent sensor
changes still need on-board validation.
