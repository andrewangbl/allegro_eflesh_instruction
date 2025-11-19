#!/usr/bin/env python3
"""Terminal viewer for the Allegro eFlesh tactile stream (QtPy SAMD)."""
from __future__ import annotations

import argparse
import csv
import select
import struct
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import serial  # type: ignore
except ImportError as exc:  # pragma: no cover - optional dependency
    serial = None

MUX_CHANNELS = 4
SENSORS_PER_CHANNEL = 5
VALUES_PER_SENSOR = 4  # T, X, Y, Z
TOTAL_SENSORS = MUX_CHANNELS * SENSORS_PER_CHANNEL
FRAME_VALUES = TOTAL_SENSORS * VALUES_PER_SENSOR
FRAME_BYTES = FRAME_VALUES * 4  # float32 per value
BAR_CHAR = "█"
BG_CHAR = "░"


class EFleshStream:
    """Binary serial stream reader that matches wire_4mag.py framing."""

    def __init__(self, port: str, baudrate: int) -> None:
        if serial is None:
            raise RuntimeError("pyserial is required: pip install pyserial")

        self.serial = serial.Serial(port, baudrate=baudrate, timeout=1.0)
        self.serial.reset_input_buffer()
        time.sleep(1.0)  # allow QtPy SAMD CDC stack to settle

    def read_frame(self) -> Optional[np.ndarray]:
        # Frames are newline-delimited followed by 20 * 4 float32 payload
        self.serial.read_until(b"\n")
        payload = self.serial.read(FRAME_BYTES)
        if len(payload) != FRAME_BYTES:
            return None
        floats = struct.unpack("<" + "f" * FRAME_VALUES, payload)
        frame = np.array(floats, dtype=np.float32).reshape(TOTAL_SENSORS, VALUES_PER_SENSOR)
        return frame

    def close(self) -> None:
        self.serial.close()


def acquire_baseline(stream: EFleshStream, frames: int) -> np.ndarray:
    collected = []
    while len(collected) < frames:
        data = stream.read_frame()
        if data is None:
            continue
        collected.append(data[:, 1:])  # X, Y, Z only
    baseline = np.mean(collected, axis=0)
    print(f"Baseline locked with {frames} frames")
    return baseline


def format_bar(value: float, max_abs: float, width: int = 40) -> str:
    if max_abs <= 0:
        return BG_CHAR * width
    ratio = min(abs(value) / max_abs, 1.0)
    filled = int(ratio * width)
    return BAR_CHAR * filled + BG_CHAR * (width - filled)


def print_sensor_panel(sensor_data: np.ndarray, baseline_xyz: np.ndarray, label: str, fps: float, frames: int) -> None:
    xyz = sensor_data[:, 1:]
    delta = xyz - baseline_xyz
    norms = np.linalg.norm(delta, axis=1)
    max_scale = max(50.0, np.max(norms))

    # Clear screen
    print("\033[H\033[J", end="")
    print("=" * 80)
    print(f"{'Allegro eFlesh tactile stream':^80}")
    print(f"{'4 magnetometers × 5 sensors (XYZ)':^80}")
    print(f"{label:^80}")
    print(f"{'Timestamp: ' + datetime.now().strftime('%Y-%m-%d %H:%M:%S'):^80}")
    print(f"{'FPS: ' + f'{fps:.1f}' + ' | Frames: ' + str(frames):^80}")
    print("=" * 80)

    for mux in range(MUX_CHANNELS):
        print(f"\n╔════ Magnetometer Branch {mux} ════╗")
        for sensor in range(SENSORS_PER_CHANNEL):
            idx = mux * SENSORS_PER_CHANNEL + sensor
            delta_vec = delta[idx]
            norm = norms[idx]
            bar = format_bar(norm, max_scale, width=50)
            print(
                f"  Sensor {sensor} | ΔX {delta_vec[0]:7.2f} ΔY {delta_vec[1]:7.2f} ΔZ {delta_vec[2]:7.2f} "
                f"|{bar}| |‖Δ‖={norm:6.2f}"
            )

    print("\n" + "=" * 80)
    print(f"Total norm (XYZ): {np.linalg.norm(delta):7.2f}")
    print(f"Average sensor norm: {np.mean(norms):7.2f}")
    print(f"Max sensor norm: {np.max(norms):7.2f}")
    print("Press 'b' + Enter to reset baseline • Ctrl+C to exit")


def log_frame(writer: Optional[csv.writer], sensor_data: np.ndarray, baseline_xyz: np.ndarray) -> None:
    if writer is None:
        return
    timestamp = datetime.now().isoformat()
    xyz = sensor_data[:, 1:].reshape(-1)
    delta = (sensor_data[:, 1:] - baseline_xyz).reshape(-1)
    row = [timestamp] + xyz.tolist() + delta.tolist()
    writer.writerow(row)


def poll_keyboard() -> Optional[str]:
    if not sys.stdin.isatty():
        return None
    ready, _, _ = select.select([sys.stdin], [], [], 0)
    if ready:
        return sys.stdin.readline().strip().lower()
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize Allegro eFlesh tactile data stream")
    parser.add_argument("-p", "--port", type=str, default="/dev/cu.usbmodem1101", help="QtPy SAMD serial port")
    parser.add_argument("-b", "--baudrate", type=int, default=115200, help="Serial baud rate")
    parser.add_argument("--baseline", type=int, default=50, help="Frames to average when locking baseline")
    parser.add_argument("--log", type=Path, help="Optional CSV log output")
    parser.add_argument("--update", type=int, default=30, help="Display refresh rate (Hz)")
    args = parser.parse_args()

    print("Connecting to QtPy SAMD ...")
    stream = EFleshStream(args.port, args.baudrate)
    baseline_xyz = acquire_baseline(stream, args.baseline)

    log_writer = None
    log_file = None
    if args.log:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        log_file = args.log.open("w", newline="")
        header = ["timestamp"]
        header += [f"ch{i+1}_x" for i in range(TOTAL_SENSORS)]
        header += [f"ch{i+1}_delta_x" for i in range(TOTAL_SENSORS)]
        log_writer = csv.writer(log_file)
        log_writer.writerow(header)

    last_display = time.time()
    fps_counter = 0
    fps_window_start = time.time()
    fps = 0.0
    frame_count = 0
    display_interval = 1.0 / max(args.update, 1)

    try:
        while True:
            frame = stream.read_frame()
            if frame is None:
                continue
            frame_count += 1
            fps_counter += 1

            now = time.time()
            if now - fps_window_start >= 1.0:
                fps = fps_counter / (now - fps_window_start)
                fps_counter = 0
                fps_window_start = now

            if now - last_display >= display_interval:
                label = f"port={args.port} baud={args.baudrate}"
                print_sensor_panel(frame, baseline_xyz, label, fps, frame_count)
                last_display = now

            log_frame(log_writer, frame, baseline_xyz)

            command = poll_keyboard()
            if command == "b":
                print("\nRe-locking baseline ...")
                baseline_xyz = acquire_baseline(stream, args.baseline)

    except KeyboardInterrupt:
        print("\nStopping stream ...")
    finally:
        stream.close()
        if log_file:
            log_file.close()
        print("Goodbye")


if __name__ == "__main__":
    main()
