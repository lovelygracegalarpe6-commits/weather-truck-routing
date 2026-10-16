"""Weather risk classification for a single checkpoint.

Thresholds come straight from the assessment brief. The brief's table repeats the
boundary values between columns (e.g. rain "0.10-0.25" then "0.25-0.50"), so the
boundary convention is derived from the endpoints it states explicitly:

* Wind: "No Travel >= 55 mph" -> each band is **lower-bound inclusive**
  (25 <= w < 35 is Moderate, 35 <= w < 45 is High, ...).
* Rain / snow: "Low < 0.10" and "No Travel > 1.00" -> each band is
  **upper-bound inclusive** (0.10 <= r <= 0.25 is Moderate, 0.25 < r <= 0.50 is
  High, 0.50 < r <= 1.00 is Severe, r > 1.00 is No Travel).

A checkpoint's level is the worst of its wind (after load rules), rain and snow levels.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from enum import IntEnum


class RiskLevel(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def key(self) -> str:
        return self.name.lower()


_LABELS = {
    RiskLevel.LOW: "Low",
    RiskLevel.MODERATE: "Moderate",
    RiskLevel.HIGH: "High",
    RiskLevel.SEVERE: "Severe",
    RiskLevel.NO_TRAVEL: "No Travel",
}

# Wind (mph): level = number of thresholds that are <= the value.
WIND_THRESHOLDS_MPH = (25.0, 35.0, 45.0, 55.0)

# Rain / snow (in/hr): below `low_below` is Low; otherwise the first upper bound the
# value does not exceed decides the level, and anything above the last is No Travel.
RAIN_LOW_BELOW_IN_HR = 0.10
RAIN_UPPER_BOUNDS_IN_HR = (0.25, 0.50, 1.00)  # Moderate, High, Severe
SNOW_LOW_BELOW_IN_HR = 0.5
SNOW_UPPER_BOUNDS_IN_HR = (1.0, 2.0, 3.0)  # Moderate, High, Severe


@dataclass(frozen=True)
class LoadRule:
    """Escalates the wind level for heavy loads inside a wind band."""

    min_wind_mph: float  # inclusive
    max_wind_mph: float  # exclusive
    min_load_lb_exclusive: float
    level: RiskLevel

    def applies(self, wind_mph: float, load_lb: float) -> bool:
        return (
            self.min_wind_mph <= wind_mph < self.max_wind_mph
            and load_lb > self.min_load_lb_exclusive
        )


# ">= 55 mph -> No Travel for any load" is already the wind table's top band.
LOAD_RULES = (
    LoadRule(45.0, 55.0, 30_000, RiskLevel.NO_TRAVEL),
    LoadRule(35.0, 45.0, 40_000, RiskLevel.SEVERE),
)


def classify_wind(wind_mph: float) -> RiskLevel:
    return RiskLevel(bisect_right(WIND_THRESHOLDS_MPH, wind_mph))


def _classify_precip(rate: float, low_below: float, upper_bounds: tuple[float, ...]) -> RiskLevel:
    if rate < low_below:
        return RiskLevel.LOW
    return RiskLevel(1 + bisect_left(upper_bounds, rate))


def classify_rain(rain_in_hr: float) -> RiskLevel:
    return _classify_precip(rain_in_hr, RAIN_LOW_BELOW_IN_HR, RAIN_UPPER_BOUNDS_IN_HR)


def classify_snow(snow_in_hr: float) -> RiskLevel:
    return _classify_precip(snow_in_hr, SNOW_LOW_BELOW_IN_HR, SNOW_UPPER_BOUNDS_IN_HR)


def wind_level_for_load(wind_mph: float, load_lb: float) -> tuple[RiskLevel, LoadRule | None]:
    """Wind level after load rules, plus the rule that escalated it (if any)."""
    level = classify_wind(wind_mph)
    for rule in LOAD_RULES:
        if rule.applies(wind_mph, load_lb) and rule.level > level:
            return rule.level, rule
    return level, None


@dataclass(frozen=True)
class WeatherSample:
    """Hourly weather at one place and time, in the units the rules use."""

    wind_mph: float
    gust_mph: float
    rain_in_hr: float
    snow_in_hr: float

    def wind_for(self, metric: str) -> float:
        return self.gust_mph if metric == "gust" else self.wind_mph


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel
    wind: RiskLevel
    rain: RiskLevel
    snow: RiskLevel
    reasons: tuple[str, ...]


def risk_level(sample: WeatherSample, load_lb: float, wind_metric: str = "sustained") -> RiskLevel:
    """Just the level (no reasons): the heatmap needs this for ~10k samples per request."""
    wind, _ = wind_level_for_load(sample.wind_for(wind_metric), load_lb)
    return max(wind, classify_rain(sample.rain_in_hr), classify_snow(sample.snow_in_hr))


def assess(sample: WeatherSample, load_lb: float, wind_metric: str = "sustained") -> RiskAssessment:
    wind_mph = sample.wind_for(wind_metric)
    wind, load_rule = wind_level_for_load(wind_mph, load_lb)
    rain = classify_rain(sample.rain_in_hr)
    snow = classify_snow(sample.snow_in_hr)
    level = max(wind, rain, snow)

    reasons: list[str] = []
    if level > RiskLevel.LOW:
        wind_name = "Wind gusts" if wind_metric == "gust" else "Wind"
        if wind == level:
            text = f"{wind_name} {wind_mph:.0f} mph"
            if load_rule is not None:
                limit = load_rule.min_load_lb_exclusive
                text += f" with {load_lb:,.0f} lb load (> {limit:,.0f} lb)"
            reasons.append(text)
        if rain == level:
            reasons.append(f"Rain {sample.rain_in_hr:.2f} in/hr")
        if snow == level:
            reasons.append(f"Snow {sample.snow_in_hr:.2f} in/hr")

    return RiskAssessment(level=level, wind=wind, rain=rain, snow=snow, reasons=tuple(reasons))
