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
`__MAIN_H` guard triggers `bugprone-reserved-identifier`, and lines 7–8 of
`vehicle_detector.c`, where the existing `VehicleDetector_Init` signature
triggers `bugprone-easily-swappable-parameters`. The latter API is retained to
keep this PR limited to test infrastructure. The full check families remain
enabled for every other production line, and new diagnostics fail the target.

The mocks enforce explicit sensor input setup and record GPIO reads and writes.
They use the GPIO symbols and pin mappings from the production `main.h`.

These host tests do not compile generated `main.c`, validate GPIO wiring,
interrupt timing, ARM builds, real sensor fault detection, or physical servo
control. A reported fault freezes the barrier's logical position. Gate motion,
motor current limits, startup with an obstructed beam, and concurrent sensor
changes still need on-board validation.
