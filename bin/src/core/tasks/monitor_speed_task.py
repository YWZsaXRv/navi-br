import logging
import os
import sys
import time

import psutil
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


class _LinuxDiskIOMonitor:

    def __init__(self, target_path):
        self.target_path = os.path.realpath(os.path.abspath(target_path))
        self.device_label = "Disk"
        self.counter_keys = self._resolve_counter_keys()
        self._last_bytes = self._read_total_bytes()

    def sample(self, interval):
        current_bytes = self._read_total_bytes()
        speed = (current_bytes - self._last_bytes) / interval
        self._last_bytes = current_bytes
        return max(speed, 0.0)

    def close(self):
        """No-op for interface parity with the Windows monitor."""

    def _resolve_counter_keys(self):
        counters = psutil.disk_io_counters(perdisk=True) or {}
        if not counters:
            raise RuntimeError("Per-disk I/O counters are unavailable")

        partition = self._find_matching_partition()
        if not partition:
            raise RuntimeError(f"Could not resolve a disk for path: {self.target_path}")

        device_path = os.path.realpath(partition.device)
        device_name = os.path.basename(device_path)
        self.device_label = device_name or partition.mountpoint

        candidates = []
        if device_name:
            candidates.append(device_name)

            base_name = self._derive_linux_base_device_name(device_name)
            if base_name and base_name not in candidates:
                candidates.append(base_name)

        matched = self._match_counter_keys(counters, candidates)
        if matched:
            return matched

        raise RuntimeError(
            f"No Linux disk counter matched device '{device_path}' for path {self.target_path}"
        )

    def _find_matching_partition(self):
        matched_partition = None
        matched_mountpoint_len = -1

        for partition in psutil.disk_partitions(all=True):
            mountpoint = os.path.realpath(os.path.abspath(partition.mountpoint))
            if not self._path_is_within_mountpoint(self.target_path, mountpoint):
                continue

            if len(mountpoint) > matched_mountpoint_len:
                matched_partition = partition
                matched_mountpoint_len = len(mountpoint)

        return matched_partition

    @staticmethod
    def _path_is_within_mountpoint(path, mountpoint):
        normalized_path = os.path.normcase(path)
        normalized_mountpoint = os.path.normcase(mountpoint)
        return normalized_path == normalized_mountpoint or normalized_path.startswith(
            normalized_mountpoint.rstrip(os.sep) + os.sep
        )

    @staticmethod
    def _derive_linux_base_device_name(device_name):
        if device_name.startswith(("nvme", "mmcblk")) and "p" in device_name:
            return device_name.rsplit("p", 1)[0]

        stripped = device_name.rstrip("0123456789")
        return stripped or device_name

    @staticmethod
    def _match_counter_keys(counters, candidates):
        lower_key_map = {key.lower(): key for key in counters}
        matched = []

        for candidate in candidates:
            actual_key = lower_key_map.get(candidate.lower())
            if actual_key and actual_key not in matched:
                matched.append(actual_key)

        return matched

    def _read_total_bytes(self):
        counters = psutil.disk_io_counters(perdisk=True) or {}
        total_bytes = 0
        for key in self.counter_keys:
            counter = counters.get(key)
            if counter is None:
                continue
            total_bytes += counter.read_bytes + counter.write_bytes
        return total_bytes


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _PDHCounterValueUnion(ctypes.Union):
        _fields_ = [
            ("longValue", ctypes.c_long),
            ("doubleValue", ctypes.c_double),
            ("largeValue", ctypes.c_longlong),
            ("ansiStringValue", ctypes.c_char_p),
            ("wideStringValue", ctypes.c_wchar_p),
        ]

    class _PDHFormattedCounterValue(ctypes.Structure):
        _anonymous_ = ("value",)
        _fields_ = [
            ("CStatus", wintypes.DWORD),
            ("value", _PDHCounterValueUnion),
        ]

    class _WindowsDiskIOMonitor:

        PDH_FMT_DOUBLE = 0x00000200

        def __init__(self, target_path):
            drive = os.path.splitdrive(os.path.abspath(target_path))[0].rstrip("\\/")
            if not drive:
                raise RuntimeError(f"Could not determine drive for path: {target_path}")

            self.device_label = drive
            self._query = ctypes.c_void_p()
            self._counter = ctypes.c_void_p()
            self._pdh = ctypes.WinDLL("pdh")
            self._configure_api()

            counter_path = f"\\LogicalDisk({drive})\\Disk Bytes/sec"
            status = self._pdh.PdhOpenQueryW(None, None, ctypes.byref(self._query))
            self._check_status(status, "PdhOpenQueryW")

            add_counter = getattr(self._pdh, "PdhAddEnglishCounterW", None)
            if add_counter is None:
                raise RuntimeError("PdhAddEnglishCounterW is unavailable on this system")

            status = add_counter(
                self._query, counter_path, None, ctypes.byref(self._counter)
            )
            self._check_status(status, f"PdhAddEnglishCounterW({counter_path})")

            status = self._pdh.PdhCollectQueryData(self._query)
            self._check_status(status, "PdhCollectQueryData")

        def _configure_api(self):
            self._pdh.PdhOpenQueryW.argtypes = [
                ctypes.c_wchar_p,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            self._pdh.PdhOpenQueryW.restype = wintypes.DWORD

            self._pdh.PdhAddEnglishCounterW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_wchar_p,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            self._pdh.PdhAddEnglishCounterW.restype = wintypes.DWORD

            self._pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
            self._pdh.PdhCollectQueryData.restype = wintypes.DWORD

            self._pdh.PdhGetFormattedCounterValue.argtypes = [
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
                ctypes.POINTER(_PDHFormattedCounterValue),
            ]
            self._pdh.PdhGetFormattedCounterValue.restype = wintypes.DWORD

            self._pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]
            self._pdh.PdhCloseQuery.restype = wintypes.DWORD

        def sample(self, _interval):
            status = self._pdh.PdhCollectQueryData(self._query)
            self._check_status(status, "PdhCollectQueryData")

            counter_type = wintypes.DWORD()
            counter_value = _PDHFormattedCounterValue()
            status = self._pdh.PdhGetFormattedCounterValue(
                self._counter,
                self.PDH_FMT_DOUBLE,
                ctypes.byref(counter_type),
                ctypes.byref(counter_value),
            )
            self._check_status(status, "PdhGetFormattedCounterValue")
            return max(counter_value.doubleValue, 0.0)

        def close(self):
            if self._query:
                self._pdh.PdhCloseQuery(self._query)
                self._query = ctypes.c_void_p()
                self._counter = ctypes.c_void_p()

        @staticmethod
        def _check_status(status, operation):
            if status == 0:
                return
            raise RuntimeError(f"{operation} failed with PDH status 0x{status:08X}")


class SpeedMonitorTask(QObject):
    speed_update = pyqtSignal(str)

    def __init__(self, interval=1, target_path=None):
        super().__init__()
        self.interval = interval
        self.target_path = target_path
        self._is_running = True
        self._disk_monitor = None

    def run(self):
        logger.info("Speed monitor task starting.")
        try:
            last_bytes = psutil.net_io_counters().bytes_recv
        except Exception as e:
            logger.error(f"Could not initialize psutil for speed monitoring: {e}")
            return

        self._disk_monitor = self._create_disk_monitor()
        initial_disk_speed = 0.0 if self._disk_monitor else None
        self.speed_update.emit(self._build_status_text(0.0, initial_disk_speed))

        while self._is_running:
            time.sleep(self.interval)
            if not self._is_running:
                break
            try:
                current_bytes = psutil.net_io_counters().bytes_recv
                speed = (current_bytes - last_bytes) / self.interval
                last_bytes = current_bytes
                disk_speed = self._sample_disk_speed()
                self.speed_update.emit(self._build_status_text(speed, disk_speed))
            except Exception as e:
                logger.warning(f"Error during speed update loop: {e}")
                self.stop()

        if self._disk_monitor:
            self._disk_monitor.close()
            self._disk_monitor = None

        logger.info("Speed monitor task finished.")

    def _create_disk_monitor(self):
        if not self.target_path:
            return None

        try:
            if sys.platform == "win32":
                return _WindowsDiskIOMonitor(self.target_path)
            return _LinuxDiskIOMonitor(self.target_path)
        except Exception as e:
            logger.warning(
                f"Disk I/O monitor unavailable for '{self.target_path}': {e}"
            )
            return None

    def _sample_disk_speed(self):
        if not self._disk_monitor:
            return None

        try:
            return self._disk_monitor.sample(self.interval)
        except Exception as e:
            logger.warning(f"Error sampling disk I/O: {e}")
            self._disk_monitor.close()
            self._disk_monitor = None
            return None

    def _build_status_text(self, download_speed, disk_speed):
        status = f"Download Speed: {SpeedMonitorTask._format_speed(download_speed)}"
        if disk_speed is None:
            return f"{status} | Disk I/O: N/A"

        device_label = getattr(self._disk_monitor, "device_label", "Disk")
        return (
            f"{status} | Disk I/O ({device_label}): "
            f"{SpeedMonitorTask._format_speed(disk_speed)}"
        )

    @staticmethod
    def _format_speed(speed_bps):
        if speed_bps < 1024:
            return f"{speed_bps:.2f} B/s"
        if speed_bps < 1024**2:
            return f"{(speed_bps / 1024):.2f} KB/s"
        return f"{(speed_bps / 1024**2):.2f} MB/s"

    def stop(self):
        logger.debug("Stop signal received by speed monitor.")
        self._is_running = False
