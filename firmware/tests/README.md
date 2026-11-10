# Barrier controller regression tests

These tests compile the production controller as native C, without STM32 HAL
or hardware. Run from the repository root with GCC:

```sh
gcc -std=c11 -Wall -Wextra -Werror -Ifirmware/STM32_SmartParking/App/Inc firmware/tests/test_barrier_controller.c firmware/STM32_SmartParking/App/Src/barrier_controller.c -o /tmp/test_barrier_controller
/tmp/test_barrier_controller
```

With an x64 Native Tools Command Prompt for Visual Studio on Windows:

```bat
cl /nologo /std:c11 /W4 /WX /Ifirmware\STM32_SmartParking\App\Inc firmware\tests\test_barrier_controller.c firmware\STM32_SmartParking\App\Src\barrier_controller.c /Fe:%TEMP%\test_barrier_controller.exe /Fo:%TEMP%\
%TEMP%\test_barrier_controller.exe
```

Alternatively, with `uv` installed, use Zig's portable C compiler in PowerShell:

```powershell
uv run --no-project --python 3.12 --with ziglang python -m ziglang cc -std=c11 -Wall -Wextra -Werror -Ifirmware/STM32_SmartParking/App/Inc firmware/tests/test_barrier_controller.c firmware/STM32_SmartParking/App/Src/barrier_controller.c -o "$env:TEMP/test_barrier_controller.exe"
& "$env:TEMP/test_barrier_controller.exe"
```

Coverage includes capacity rejection, waiting for passage, 499/500 ms clearance,
redetection at the deadline, repeated opening requests during a cycle, latched
faults while closed/open, and the 32-bit tick counter wrapping.

The main loop propagates faults from either detector for each lane before
processing opening requests and passage updates. A fault freezes that barrier's
logical position until reinitialization; automatic fault detection and physical
servo control remain outside this implementation. Native tests do not validate
GPIO wiring, the ARM build, Renode, or hardware timing.
