"""System memory sampling and low-memory threshold logic for scrape orchestration.

The scrape host has two memory-exhaustion vectors the orchestrator watches at
round boundaries: available physical memory (worker Python RSS plus everything
else) and kernel nonpaged pool, which leaks via a device driver during heavy
Playwright/Chromium activity and is only reclaimed by a reboot. The ctypes
probe is a thin untested shim; the threshold decision is pure and unit-tested.
"""

import ctypes
from dataclasses import dataclass


DEFAULT_AVAILABLE_FLOOR_BYTES: int = 2 * 1024**3
DEFAULT_NONPAGED_DELTA_BYTES: int = int(1.25 * 1024**3)


@dataclass(frozen=True)
class MemoryThresholds:
    """Limits below/beyond which the orchestrator stops spawning rounds."""

    available_floor_bytes: int = DEFAULT_AVAILABLE_FLOOR_BYTES
    nonpaged_delta_bytes: int = DEFAULT_NONPAGED_DELTA_BYTES


@dataclass(frozen=True)
class MemorySample:
    """A point-in-time reading of system memory."""

    available_bytes: int
    nonpaged_bytes: int


def is_memory_low(
    available_bytes: int,
    nonpaged_bytes: int,
    baseline_nonpaged: int,
    thresholds: MemoryThresholds,
) -> bool:
    """Return True when the host is too close to exhaustion to start a round."""

    if available_bytes < thresholds.available_floor_bytes:
        return True
    if nonpaged_bytes - baseline_nonpaged > thresholds.nonpaged_delta_bytes:
        return True
    return False


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_uint32),
        ("dwMemoryLoad", ctypes.c_uint32),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


class _PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("CommitTotal", ctypes.c_size_t),
        ("CommitLimit", ctypes.c_size_t),
        ("CommitPeak", ctypes.c_size_t),
        ("PhysicalTotal", ctypes.c_size_t),
        ("PhysicalAvailable", ctypes.c_size_t),
        ("SystemCache", ctypes.c_size_t),
        ("KernelTotal", ctypes.c_size_t),
        ("KernelPaged", ctypes.c_size_t),
        ("KernelNonpaged", ctypes.c_size_t),
        ("PageSize", ctypes.c_size_t),
        ("HandleCount", ctypes.c_uint32),
        ("ProcessCount", ctypes.c_uint32),
        ("ThreadCount", ctypes.c_uint32),
    ]


def sample_system_memory() -> MemorySample:
    """Read available physical bytes and nonpaged pool bytes from Windows."""

    status = _MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError()

    perf = _PERFORMANCE_INFORMATION()
    perf.cb = ctypes.sizeof(_PERFORMANCE_INFORMATION)
    if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(perf), perf.cb):
        raise ctypes.WinError()

    return MemorySample(
        available_bytes=int(status.ullAvailPhys),
        nonpaged_bytes=int(perf.KernelNonpaged) * int(perf.PageSize),
    )
