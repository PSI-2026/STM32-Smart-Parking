# Parking entry and exit integration test

Run the test on a fresh Renode instance with a hybrid v1 firmware ELF. The firmware must use the active-low PARK1 Tracking input on PE2. The test drives the simulated gate sensor and virtual parking slots through the existing Modbus RTU write registers.

On macOS or Linux, open the Renode monitor on port 43109. Run these commands in the monitor, substituting the path to the ELF you built:

```text
mach create "parking-isolated"
machine LoadPlatformDescription @platforms/cpus/stm32f4.repl
machine LoadPlatformDescriptionFromString "dwt: Miscellaneous.DWT @ sysbus 0xE0001000 { frequency: 16000000 }"
sysbus LoadELF @/tmp/smart-parking-v1.elf
emulation CreateUartPtyTerminal "parkingPty" "/tmp/parking-renode-uart"
connector Connect sysbus.usart1 parkingPty
sysbus.gpioPortE OnGPIO 2 true
start
```

Start Renode headlessly with `renode --disable-gui --plain --port 43109` and send the commands through a local monitor session. Run the test from the repository root while Renode owns the PTY master:

```sh
python3 simulation/renode/test_parking_rtu.py /tmp/parking-renode-uart --passage-timeout
```

Keep the backend disconnected from this PTY while the test runs. The test process is the RTU master. Restart the simulated machine before repeating the test so command sequence numbers start fresh. Omit `--passage-timeout` to skip waiting for the 30-second gate timeout.

The suite verifies entry and exit, movement through the gate, completion and event history, duplicate protection, full-lot rejection, separate PARK1 and virtual occupancy, and expiry of virtual occupancy. The optional timeout case confirms that an abandoned passage does not complete an entry and that the virtual gate can reset.

For a backend smoke test, stop the test process and point PR #14's `hybrid-v1-readonly` profile at the same PTY. Its diagnostics API reports PARK1. Extended slot and gate telemetry is available in the RTU registers exercised by this test and requires a backend reader for those registers.
