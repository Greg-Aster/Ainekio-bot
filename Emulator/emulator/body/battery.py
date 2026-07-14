from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from statistics import fmean
from typing import Iterable


MIN_SAMPLES_PER_SET = 16
QUALIFYING_SAMPLE_SETS = 3
WARN_VOLTS = 7.0
CUTOFF_VOLTS = 6.8
RECOVERY_VOLTS = 7.2


class BatteryState(str, Enum):
    NORMAL = "normal"
    MOVE_LOCKED = "move_locked"
    CUTOFF = "cutoff"


@dataclass(frozen=True)
class BatteryUpdate:
    state: BatteryState
    volts: float
    events: tuple[str, ...] = ()


class BatteryMonitor:
    """Debounces battery thresholds from bounded ADC sample sets."""

    def __init__(self, initial_volts: float = 8.0) -> None:
        self._volts = _valid_voltage(initial_volts)
        self._warn_active = False
        self._cutoff_active = False
        self._warn_streak = 0
        self._cutoff_streak = 0
        self._recovery_streak = 0

    @property
    def volts(self) -> float:
        return self._volts

    @property
    def state(self) -> BatteryState:
        if self._cutoff_active:
            return BatteryState.CUTOFF
        if self._warn_active:
            return BatteryState.MOVE_LOCKED
        return BatteryState.NORMAL

    def observe(self, samples: Iterable[float]) -> BatteryUpdate:
        values = tuple(_valid_voltage(value) for value in samples)
        if len(values) < MIN_SAMPLES_PER_SET:
            raise ValueError(
                f"battery sample set needs at least {MIN_SAMPLES_PER_SET} readings"
            )
        self._volts = fmean(values)
        events: list[str] = []

        self._warn_streak = self._warn_streak + 1 if self._volts < WARN_VOLTS else 0
        self._cutoff_streak = (
            self._cutoff_streak + 1 if self._volts < CUTOFF_VOLTS else 0
        )
        self._recovery_streak = (
            self._recovery_streak + 1
            if self.state != BatteryState.NORMAL and self._volts >= RECOVERY_VOLTS
            else 0
        )

        if (
            not self._warn_active
            and self._warn_streak >= QUALIFYING_SAMPLE_SETS
        ):
            self._warn_active = True
            events.append("battery_warn")

        if (
            not self._cutoff_active
            and self._cutoff_streak >= QUALIFYING_SAMPLE_SETS
        ):
            self._cutoff_active = True
            if not self._warn_active:
                self._warn_active = True
                events.append("battery_warn")
            events.append("battery_cutoff")

        if self._recovery_streak >= QUALIFYING_SAMPLE_SETS:
            was_cutoff = self._cutoff_active
            self._warn_active = False
            self._cutoff_active = False
            self._warn_streak = 0
            self._cutoff_streak = 0
            self._recovery_streak = 0
            if was_cutoff:
                events.append("brownout_recovered")

        return BatteryUpdate(self.state, self._volts, tuple(events))

    def observe_constant(self, volts: float) -> BatteryUpdate:
        value = _valid_voltage(volts)
        return self.observe((value,) * MIN_SAMPLES_PER_SET)


def _valid_voltage(value: float) -> float:
    voltage = float(value)
    if not math.isfinite(voltage) or not 0.0 <= voltage <= 20.0:
        raise ValueError("battery voltage must be finite and between 0 and 20 V")
    return voltage
