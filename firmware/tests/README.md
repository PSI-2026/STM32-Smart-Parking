# Native firmware unit tests

Run `make -C firmware/tests test` from the repository root. The runner compiles
the four production C modules with minimal HAL GPIO mocks, then runs the existing
barrier regressions and new detector, spot, manager, and barrier safety tests.
It uses C11, `-Wall -Wextra -Werror`, fails on compile or assertion errors, and
keeps temporary binaries outside tracked source directories.

Use `make -C firmware/tests sanitize` for AddressSanitizer and
UndefinedBehaviorSanitizer, if supported by the host compiler. Use
`make -C firmware/tests analyze` when `clang-tidy` is installed.
`make -C firmware/tests check` runs all three targets. `CC` and `CFLAGS` can be
overridden as normal Make variables.

The mocks enforce explicit sensor input setup and record GPIO reads and writes.
They use the GPIO symbols and pin mappings from the production `main.h`.

These host tests do not compile generated `main.c`, validate GPIO wiring,
interrupt timing, ARM builds, real sensor fault detection, or physical servo
control. A reported fault freezes the barrier's logical position. Gate motion,
motor current limits, startup with an obstructed beam, and concurrent sensor
changes still need on-board validation.
