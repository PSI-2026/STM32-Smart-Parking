#!/usr/bin/env python3
"""Exercise simulated parking cycles against an isolated Renode UART PTY."""

import argparse
import os
import select
import socket
import struct
import termios
import time
import tty
from pathlib import Path


def crc(data):
    value = 0xFFFF
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0xA001 if value & 1 else 0)
    return struct.pack("<H", value)


def check(observed, expected, label):
    if observed != expected:
        raise RuntimeError(f"{label}: expected {expected!r}, got {observed!r}")


class Rtu:
    def __init__(self, fd):
        self.fd = fd

    def exchange(self, function, address, value, exception=None):
        # Leave an idle interval between RTU frames on the virtual UART.
        time.sleep(0.02)
        request = struct.pack(">BBHH", 1, function, address, value)
        frame = request + crc(request)
        check(os.write(self.fd, frame), len(frame), "request length")
        response = bytearray()
        deadline = time.monotonic() + 2
        length = 2
        while len(response) < length:
            remaining = max(0, deadline - time.monotonic())
            if not remaining or not select.select([self.fd], [], [], remaining)[0]:
                raise RuntimeError(f"RTU timeout for FC{function:02d} at 0x{address:04x}: {response.hex()}")
            response.extend(os.read(self.fd, length - len(response)))
            if len(response) >= 2:
                length = 5 if response[1] & 0x80 else (5 + 2 * value if function == 3 else 8)
        check(response[-2:], crc(response[:-2]), "response CRC")
        check(response[0], 1, "unit ID")
        if exception is not None:
            check(tuple(response[1:3]), (function | 0x80, exception), "exception")
        elif function == 6:
            check(response, frame, "write acknowledgement")
        else:
            check(tuple(response[1:3]), (3, value * 2), "read header")
        return response

    def read(self, address, count):
        response = self.exchange(3, address, count)
        return struct.unpack(f">{count}H", response[3:-2])

    def write(self, address, value, exception=None):
        self.exchange(6, address, value, exception)

    def wait(self, address, expected, timeout=3):
        deadline = time.monotonic() + timeout
        while True:
            observed, = self.read(address, 1)
            if observed == expected:
                return
            if time.monotonic() >= deadline:
                check(observed, expected, f"register 0x{address:04x}")
            time.sleep(0.05)


def run(rtu, monitor, check_timeout):
    def set_sensor(high):
        monitor.sendall(f"sysbus.gpioPortE OnGPIO 2 {str(high).lower()}\n".encode())
        rtu.wait(3, int(not high))

    def set_slots(sequence, mask):
        rtu.write(0x100, sequence)
        rtu.write(0x102, mask)
        rtu.write(0x103, 0xE)

    def passage(sequence, direction, completed):
        rtu.write(0x100, sequence)
        rtu.write(0x101, direction)
        check(rtu.read(7, 2), (1, direction), "gate waiting for passage")
        rtu.write(0x104, 1)
        rtu.wait(7, 2)
        rtu.write(0x104, 0)
        rtu.wait(7, 3)
        rtu.wait(12, completed)
        check(rtu.read(7, 2), (0, 0), "gate closes")
        check(rtu.read(14, 1), (4 + direction,), "completion event")
        events = rtu.read(0x20, 16)[1::2]
        check(events[:5], (4 + direction, 4, 3, 2, 1), "event history")
        rtu.write(0x101, direction)
        check(rtu.read(12, 1), (completed,), "duplicate command leaves completion count unchanged")

    set_sensor(True)
    check(rtu.read(0, 2), (1, 256), "firmware identity")
    baseline, = rtu.read(12, 1)
    rtu.write(0x102, 1, exception=3)
    set_slots(1, 0)
    check(rtu.read(4, 3), (0, 15, 4), "empty parking lot and valid slots")

    passage(2, 1, baseline + 1)
    set_slots(3, 2)
    check(rtu.read(4, 3), (2, 15, 3), "PARK2 occupied after entry")
    print("PASS entry, passage, clearance, close, event history and duplicate protection", flush=True)

    set_sensor(False)
    set_slots(4, 14)
    check(rtu.read(4, 3), (15, 15, 0), "physical PARK1 plus all virtual slots occupied")
    rtu.write(0x100, 5)
    rtu.write(0x101, 1, exception=3)
    check(rtu.read(12, 4)[::2], (baseline + 1, 7), "full lot rejects entry")
    print("PASS independent PARK1, PARK2–PARK4 telemetry and full-lot rejection", flush=True)

    passage(6, 2, baseline + 2)
    set_slots(7, 12)
    check(rtu.read(4, 3), (13, 15, 1), "PARK2 free after exit")
    set_sensor(True)
    check(rtu.read(4, 3), (12, 15, 2), "PARK1 free independently of virtual slots")
    print("PASS exit, PARK2 release and capacity update", flush=True)

    rtu.wait(5, 1, timeout=9)
    check(rtu.read(4, 3), (0, 1, 1), "expired simulated slots become unknown")
    print("PASS simulated occupancy freshness timeout", flush=True)

    if check_timeout:
        set_slots(8, 0)
        rtu.write(0x100, 9)
        rtu.write(0x101, 1)
        rtu.wait(7, 4, timeout=40)
        check(rtu.read(12, 1), (baseline + 2,), "aborted passage does not complete entry")
        check(rtu.read(14, 1), (11,), "passage timeout event")
        rtu.write(0x105, 0xA55A)
        rtu.wait(7, 0)
        print("PASS abandoned passage, fault event and reset", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pty", type=Path, help="Renode UART PTY link")
    parser.add_argument("--monitor-port", default=43109, type=int)
    parser.add_argument("--passage-timeout", action="store_true", help="also wait for the 30 s gate timeout")
    args = parser.parse_args()
    if not str(args.pty.resolve()).startswith(("/dev/ttys", "/dev/pts/")):
        parser.error("the serial port must be a virtual PTY")
    with socket.create_connection(("127.0.0.1", args.monitor_port), timeout=2) as monitor:
        fd = os.open(args.pty, os.O_RDWR | os.O_NOCTTY)
        original = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            attrs = termios.tcgetattr(fd)
            attrs[4:6] = [termios.B115200] * 2
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
            termios.tcflush(fd, termios.TCIOFLUSH)
            run(Rtu(fd), monitor, args.passage_timeout)
        finally:
            termios.tcsetattr(fd, termios.TCSANOW, original)
            os.close(fd)


if __name__ == "__main__":
    main()
