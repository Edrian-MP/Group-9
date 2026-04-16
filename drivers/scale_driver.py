import threading
import time
import serial
import os
from collections import deque
from statistics import median

import config

class SmartScale:
    def __init__(self, port='/dev/ttyACM0', baudrate=9600, *args, **kwargs):
        self.current_weight = 0.0
        self._raw_weight_kg = 0.0
        self._tare_offset_kg = 0.0
        self._smoothed_weight_kg = None
        self._lock = threading.Lock()

        self._median_window = max(3, int(getattr(config, "SCALE_MEDIAN_WINDOW", 5)))
        self._stability_window = max(4, int(getattr(config, "SCALE_STABILITY_WINDOW", 8)))
        self._alpha = float(getattr(config, "SCALE_SMOOTHING_ALPHA", 0.35))
        self._alpha = min(0.95, max(0.05, self._alpha))
        self._zero_threshold = float(getattr(config, "SCALE_ZERO_THRESHOLD_KG", 0.0020))
        self._deadband = float(getattr(config, "SCALE_DEADBAND_KG", 0.0015))
        self._stable_range = float(getattr(config, "SCALE_STABLE_RANGE_KG", 0.0020))
        self._jump_threshold = float(getattr(config, "SCALE_JUMP_THRESHOLD_KG", 0.0080))
        self._fast_alpha = min(0.98, max(self._alpha, 0.75))

        self._median_samples = deque(maxlen=self._median_window)
        self._stability_samples = deque(maxlen=self._stability_window)

        self._calibration_factor = self._load_calibration_factor()

        self.running = True
        self.serial_port = port
        self.baudrate = baudrate
        # Connect to the Arduino via USB Serial
        self.ser = serial.Serial(self.serial_port, self.baudrate, timeout=1)
        time.sleep(2) # Wait for Arduino to reset on connection
        print(f"[Scale] Connected to Arduino via {self.serial_port}")
        self.hardware_active = True

        self.thread = threading.Thread(target=self._update_loop, daemon=True)
        self.thread.start()

    def _load_calibration_factor(self):
        path = getattr(config, "SCALE_CONFIG_PATH", "")
        if not path:
            return 1.0
        try:
            if not os.path.exists(path):
                return 1.0
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
            if not text:
                return 1.0
            factor = float(text)
            if factor <= 0:
                return 1.0
            return factor
        except Exception:
            return 1.0

    def _save_calibration_factor(self):
        path = getattr(config, "SCALE_CONFIG_PATH", "")
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"{self._calibration_factor:.10f}\n")
        except Exception:
            pass

    def _update_loop(self):
        while self.running:
            if self.hardware_active and self.ser and self.ser.in_waiting > 0:
                try:
                    line = self.ser.readline().decode('utf-8').strip()
                    if line:
                        val = float(line)
                        # Arduino sends grams, we convert to kg for the UI
                        raw_weight_kg = val / 1000.0
                        with self._lock:
                            self._raw_weight_kg = raw_weight_kg
                            self._apply_filter_locked(raw_weight_kg)
                except (ValueError, UnicodeDecodeError):
                    pass
            else:
                time.sleep(0.05)

    def _apply_filter_locked(self, raw_weight_kg):
        net_weight = max(0.0, raw_weight_kg - self._tare_offset_kg) * self._calibration_factor
        self._median_samples.append(net_weight)

        med = float(median(self._median_samples))
        delta_from_display = abs(med - self.current_weight)
        alpha = self._fast_alpha if delta_from_display >= self._jump_threshold else self._alpha

        if self._smoothed_weight_kg is None:
            smoothed = med
        else:
            smoothed = (alpha * med) + ((1.0 - alpha) * self._smoothed_weight_kg)

        if smoothed < self._zero_threshold:
            smoothed = 0.0

        if abs(smoothed - self.current_weight) < self._deadband:
            candidate = self.current_weight
        else:
            candidate = smoothed

        # Always follow filtered weight to keep UI responsive.
        self.current_weight = max(0.0, candidate)

        self._stability_samples.append(candidate)
        if len(self._stability_samples) >= 3:
            spread = max(self._stability_samples) - min(self._stability_samples)
        else:
            spread = 0.0

        if len(self._stability_samples) >= self._stability_window and spread <= self._stable_range:
            stabilized = sum(self._stability_samples) / float(len(self._stability_samples))
            if abs(stabilized - self.current_weight) < self._deadband:
                self.current_weight = max(0.0, stabilized)

        self._smoothed_weight_kg = smoothed

    def get_weight(self):
        with self._lock:
            return self.current_weight

    def get_calibration_factor(self):
        with self._lock:
            return float(self._calibration_factor)

    def set_calibration_factor(self, factor, persist=True):
        try:
            factor_val = float(factor)
        except (TypeError, ValueError):
            return False
        if factor_val <= 0:
            return False

        with self._lock:
            self._calibration_factor = factor_val
            self._smoothed_weight_kg = None
            self._median_samples.clear()
            self._stability_samples.clear()

        if persist:
            self._save_calibration_factor()
        return True

    def tare(self):
        # Capture current load as the new zero point so displayed weight becomes ~0.
        baseline_samples = []
        start = time.time()
        while time.time() - start < 0.4:
            with self._lock:
                baseline_samples.append(self._raw_weight_kg)
            time.sleep(0.05)

        baseline = sum(baseline_samples) / len(baseline_samples) if baseline_samples else 0.0

        with self._lock:
            self._tare_offset_kg = baseline
            self.current_weight = 0.0
            self._smoothed_weight_kg = 0.0
            self._median_samples.clear()
            self._stability_samples.clear()

        # Optional firmware support: if Arduino accepts this command, it can also zero at sensor level.
        try:
            if self.hardware_active and self.ser and self.ser.is_open:
                self.ser.write(b"TARE\n")
                self.ser.flush()
        except Exception:
            pass

    def stop(self):
        self.running = False
        if self.ser and self.ser.is_open:
            self.ser.close()

