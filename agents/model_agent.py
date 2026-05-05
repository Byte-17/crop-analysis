"""
agents/model_agent.py — Crop growth simulation agent.

Simulates daily crop development with iterative state updates:
  - LAI (Leaf Area Index)
  - Soil moisture
  - ET (Evapotranspiration)

Usage:
    python agents/model_agent.py
"""

import logging
import math
import os
import sys
from datetime import datetime, timedelta

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from utils.token_tracker import TokenTracker


# ---------------------------------------------------------------------------
# Weather generator
# ---------------------------------------------------------------------------

class WeatherGenerator:
    """Daily weather generator with seasonal patterns."""

    SEASONS = {
        "temperate": {"temp_base": 15, "temp_amp": 10, "rain_peak_doy": 150, "rain_base": 1.0, "rain_amp": 2.0},
        "tropical":  {"temp_base": 28, "temp_amp": 3,  "rain_peak_doy": 180, "rain_base": 4.0, "rain_amp": 6.0},
        "dry":       {"temp_base": 25, "temp_amp": 8,  "rain_peak_doy": 90,  "rain_base": 0.2, "rain_amp": 1.0},
    }

    def __init__(self, climate="temperate", seed=42):
        import random
        self._rng = random.Random(seed)
        self.climate = self.SEASONS.get(climate, self.SEASONS["temperate"])

    def generate(self, date):
        """Generate weather for a given date: (temp_celsius, rainfall_mm)."""
        doy = date.timetuple().tm_yday
        c = self.climate
        # Temperature: sinusoidal seasonal cycle + noise
        temp = (c["temp_base"]
                - c["temp_amp"] * math.cos(2 * math.pi * (doy - 10) / 365)
                + self._rng.gauss(0, 2))
        # Rainfall: seasonal peak + random occurrence
        rain_base = (c["rain_base"]
                     + c["rain_amp"] * max(0, math.sin(2 * math.pi * (doy - c["rain_peak_doy"]) / 365)))
        rain = max(0, rain_base + self._rng.gauss(0, rain_base * 0.5))
        # Rainfall only ~40% of days
        if self._rng.random() > 0.4:
            rain = 0.0
        return round(temp, 2), round(rain, 2)


# ---------------------------------------------------------------------------
# CropModel
# ---------------------------------------------------------------------------

class CropModel:
    """
    Daily crop growth simulation with iterative state updates.

    Tracks three output variables each day:
      - LAI             Leaf Area Index (m2/m2)
      - soil_moisture   Root-zone soil moisture (mm)
      - et              Actual evapotranspiration (mm/day)
    """

    # Default crop parameters
    PARAM_DEFAULTS = {
        "gdd_base":         10.0,     # base temp for GDD (°C)
        "gdd_emergence":     50.0,    # GDD to emergence
        "gdd_max_lai":     600.0,    # GDD to max LAI
        "gdd_maturity":    1200.0,   # GDD to maturity
        "lai_max":           5.0,    # max LAI
        "lai_growth_rate":   0.08,   # LAI growth rate per GDD
        "kc_init":           0.4,    # initial crop coefficient
        "kc_mid":            1.15,   # mid-season crop coefficient
        "kc_end":            0.5,    # end-season crop coefficient
        "sm_field_cap":    150.0,    # field capacity (mm)
        "sm_wilting":        50.0,   # wilting point (mm)
        "sm_init":          120.0,   # initial soil moisture (mm)
        "root_depth_max":   600.0,   # max root depth (mm)
        "senescence_slope":  0.01,   # LAI decline rate after max
    }

    def __init__(self, start_date, params=None):
        self.date = start_date
        self.params = dict(self.PARAM_DEFAULTS)
        if params:
            self.params.update(params)

        # Accumulated thermal time
        self._gdd = 0.0

        # State variables (updated each step)
        self.state = {
            "lai":            0.1,
            "soil_moisture":  self.params["sm_init"],
            "et":             0.0,
        }

        # Internal state tracking
        self._growth_phase = "emergence"  # emergence → vegetative → reproductive → senescence
        self._cumulative_et = 0.0
        self._cumulative_rain = 0.0
        self._water_stress_days = 0

        # History
        self.history = []

        self._logs = []
        self._log(f"CropModel initialized: start={start_date.date()}, "
                  f"params={len(self.params)}")

    # -- Logging -----------------------------------------------------------

    def _log(self, message):
        entry = {
            "time": datetime.now(),
            "message": f"[{datetime.now().strftime('%H:%M:%S')}] {message}",
        }
        self._logs.append(entry)
        logging.info("CropModel: %s", message)

    @property
    def logs(self):
        return list(self._logs)

    # -- Core physics ------------------------------------------------------

    def _calc_gdd(self, temp):
        """Growing degree-days for one day."""
        return max(0, temp - self.params["gdd_base"])

    def _calc_kc(self):
        """Crop coefficient based on growth phase."""
        p = self.params
        if self._growth_phase == "emergence":
            return p["kc_init"]
        elif self._growth_phase == "vegetative":
            frac = min(1, self._gdd / p["gdd_max_lai"])
            return p["kc_init"] + (p["kc_mid"] - p["kc_init"]) * frac
        elif self._growth_phase == "reproductive":
            return p["kc_mid"]
        else:  # senescence
            frac = min(1, (self._gdd - p["gdd_maturity"]) / 200)
            return p["kc_mid"] - (p["kc_mid"] - p["kc_end"]) * frac

    def _water_stress_factor(self):
        """Stress factor 0-1: 1 = no stress, 0 = full stress."""
        p = self.params
        awc = p["sm_field_cap"] - p["sm_wilting"]  # available water capacity
        if awc <= 0:
            return 1.0
        frac = (self.state["soil_moisture"] - p["sm_wilting"]) / awc
        return max(0.0, min(1.0, frac / 0.65))  # stress starts below 65% AWC

    def _calc_pet(self, temp):
        """Simplified reference ET (mm/day) from temperature (Hargreaves-style)."""
        return max(0, 0.0023 * (temp + 17.8) * 15 * math.sqrt(temp + 20))

    def _calc_lai_growth(self, gdd):
        """Daily LAI increment based on current phase."""
        p = self.params
        lai = self.state["lai"]

        if self._growth_phase == "emergence":
            # Emergence: slow initial growth
            lai_new = lai + 0.01 * gdd
            if self._gdd >= p["gdd_emergence"]:
                self._growth_phase = "vegetative"
            return lai_new

        elif self._growth_phase == "vegetative":
            # Logistic growth modulated by water stress
            stress = self._water_stress_factor()
            increment = p["lai_growth_rate"] * gdd * stress * (1 - lai / p["lai_max"])
            lai_new = lai + max(0, increment)
            if lai_new >= p["lai_max"] * 0.95 or self._gdd >= p["gdd_max_lai"]:
                self._growth_phase = "reproductive"
            return lai_new

        elif self._growth_phase == "reproductive":
            # Stable LAI at peak, then gradual decline
            if self._gdd < p["gdd_maturity"]:
                return lai
            self._growth_phase = "senescence"
            return lai

        else:  # senescence
            # Linear decline
            return max(0.05, lai - p["senescence_slope"] * gdd)

    # -- Public API --------------------------------------------------------

    def step(self, temp, rainfall):
        """
        Advance the simulation by one day.

        Parameters
        ----------
        temp : float
            Mean daily temperature (°C).
        rainfall : float
            Daily rainfall (mm).

        Updates ``self.state`` with new LAI, soil_moisture, and ET.
        """
        p = self.params
        gdd = self._calc_gdd(temp)

        # 1. Update LAI
        self.state["lai"] = self._calc_lai_growth(gdd)

        # 2. Calculate ET
        kc = self._calc_kc()
        pet = self._calc_pet(temp)
        stress = self._water_stress_factor()
        self.state["et"] = round(pet * kc * stress, 3)

        # 3. Update soil moisture (water balance)
        sm = self.state["soil_moisture"]
        sm = sm + rainfall - self.state["et"]
        # Drainage: if above field capacity, excess drains
        if sm > p["sm_field_cap"]:
            sm = p["sm_field_cap"]
        # Lower bound: wilting point
        sm = max(p["sm_wilting"], sm)
        self.state["soil_moisture"] = round(sm, 2)

        # 4. Accumulate GDD
        self._gdd += gdd

        # 5. Track cumulative
        self._cumulative_et += self.state["et"]
        self._cumulative_rain += rainfall
        if stress < 0.5:
            self._water_stress_days += 1

        # 6. Record history
        record = {
            "date":           self.date,
            "doy":            self.date.timetuple().tm_yday,
            "gdd":            round(self._gdd, 1),
            "temp":           temp,
            "rainfall":       rainfall,
            "lai":            round(self.state["lai"], 4),
            "soil_moisture":  self.state["soil_moisture"],
            "et":             self.state["et"],
            "kc":             round(kc, 3),
            "water_stress":   round(1 - stress, 3),
            "phase":          self._growth_phase,
        }
        self.history.append(record)

        # 7. Advance date
        self.date += timedelta(days=1)

        return record

    def run(self, days, weather_gen):
        """
        Run simulation for *days* consecutive days.

        Parameters
        ----------
        days : int
            Number of days to simulate.
        weather_gen : WeatherGenerator
            Source of daily temperature and rainfall.
        """
        self._log(f"Starting {days}-day simulation")
        for i in range(days):
            temp, rain = weather_gen.generate(self.date)
            self.step(temp, rain)
        self._log(f"Completed {days} days: LAI={self.state['lai']:.2f}, "
                  f"SM={self.state['soil_moisture']:.1f}mm, "
                  f"cumulET={self._cumulative_et:.0f}mm")
        return self.history

    # -- Reporting ---------------------------------------------------------

    def get_time_series(self, variables=("lai", "soil_moisture", "et")):
        """Return time series for specified variables."""
        result = {var: [] for var in variables}
        for rec in self.history:
            for var in variables:
                result[var].append((rec["date"], rec[var]))
        return result

    def summary_report(self):
        """Generate full simulation report."""
        if not self.history:
            return {"status": "not_run"}

        lai_vals   = [r["lai"] for r in self.history]
        sm_vals    = [r["soil_moisture"] for r in self.history]
        et_vals    = [r["et"] for r in self.history]

        return {
            "status":     "completed",
            "date_range": {
                "start": self.history[0]["date"].strftime("%Y-%m-%d"),
                "end":   self.history[-1]["date"].strftime("%Y-%m-%d"),
            },
            "total_days": len(self.history),
            "lai": {
                "min":  round(min(lai_vals), 3),
                "max":  round(max(lai_vals), 3),
                "mean": round(sum(lai_vals) / len(lai_vals), 3),
                "peak": round(max(lai_vals), 3),
            },
            "soil_moisture": {
                "min":  round(min(sm_vals), 1),
                "max":  round(max(sm_vals), 1),
                "mean": round(sum(sm_vals) / len(sm_vals), 1),
            },
            "et": {
                "min":  round(min(et_vals), 2),
                "max":  round(max(et_vals), 2),
                "mean": round(sum(et_vals), 2),
                "total": round(self._cumulative_et, 1),
            },
            "water_balance": {
                "total_rainfall": round(self._cumulative_rain, 1),
                "total_et":       round(self._cumulative_et, 1),
                "water_stress_days": self._water_stress_days,
            },
            "final_state": {
                "lai":            round(self.state["lai"], 3),
                "soil_moisture":  self.state["soil_moisture"],
                "gdd":            round(self._gdd, 1),
                "phase":          self._growth_phase,
            },
        }

    def print_logs(self):
        """Print all processing logs."""
        print(f"\n{'─' * 60}")
        print("  Processing Logs")
        print(f"{'─' * 60}")
        for entry in self._logs:
            print(f"  {entry['message']}")
        print(f"{'─' * 60}")

    def print_time_series(self, max_rows=20):
        """Print a formatted table of the simulation history."""
        if not self.history:
            print("  (no data)")
            return

        rows = self.history[:max_rows]
        print(f"\n{'─' * 75}")
        print(f"  Simulation Time Series  (showing {len(rows)} of {len(self.history)} days)")
        print(f"{'─' * 75}")
        print(f"  {'Date':<14} {'DOY':<5} {'Temp':<7} {'Rain':<7} {'LAI':<8} {'SM':<8} {'ET':<8} {'Phase':<14}")
        print(f"  {'─' * 71}")
        for r in rows:
            d = r["date"].strftime("%Y-%m-%d")
            print(f"  {d:<14} {r['doy']:<5} {r['temp']:<7} {r['rainfall']:<7} "
                  f"{r['lai']:<8} {r['soil_moisture']:<8} {r['et']:<8} {r['phase']:<14}")
        if len(self.history) > max_rows:
            print(f"  ... ({len(self.history) - max_rows} more rows)")
        print(f"{'─' * 75}")

    def to_dict(self):
        """Serialize for data-flow transport."""
        return {
            "data": self.summary_report(),
            "history": [
                {k: str(v) if isinstance(v, datetime) else v
                 for k, v in rec.items()}
                for rec in self.history
            ],
            "logs": self.logs,
        }


# ---------------------------------------------------------------------------
# ModelAgent (pipeline wrapper)
# ---------------------------------------------------------------------------

class ModelAgent:
    """
    Pipeline-compatible wrapper around CropModel.

    Handles simulation setup, execution, and reporting with token tracking.
    """

    def __init__(self, climate="temperate", crop_params=None):
        self.climate = climate
        self.crop_params = crop_params or {}
        self.model = None
        self._logs = []
        self._token_tracker = TokenTracker()
        self._log(f"ModelAgent initialized: climate={climate}")

    def _log(self, message):
        entry = {
            "time": datetime.now(),
            "message": f"[{datetime.now().strftime('%H:%M:%S')}] {message}",
        }
        self._logs.append(entry)
        logging.info("ModelAgent: %s", message)

    @property
    def logs(self):
        return list(self._logs)

    def run_simulation(self, start_date, days=120):
        """
        Run a full crop simulation.

        Parameters
        ----------
        start_date : str or datetime
            Planting date.
        days : int
            Simulation length in days.

        Returns
        -------
        dict
            Simulation report with all outputs.
        """
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, "%Y-%m-%d")

        self._log(f"Starting simulation: plant={start_date.date()}, days={days}, climate={self.climate}")

        weather = WeatherGenerator(climate=self.climate)
        self.model = CropModel(start_date, params=self.crop_params)
        self.model.run(days, weather)
        self._log("Simulation complete")

        # Track token usage (simulation complexity scales with days)
        fields = 3  # LAI, SM, ET
        steps = days
        factor = 1  # minimal per-step cost for simulation
        self._token_tracker.record("model_agent", fields, steps, factor)

        return self.model.summary_report()

    def run_scenario(self, name, start_date, days=120, climate=None, crop_params=None):
        """Run a named scenario and return results."""
        self._log(f"Scenario '{name}'")
        old_climate = self.climate
        old_params = self.crop_params
        if climate:
            self.climate = climate
        if crop_params:
            self.crop_params = {**self.crop_params, **crop_params}

        report = self.run_simulation(start_date, days)

        self.climate = old_climate
        self.crop_params = old_params
        return {"scenario": name, **report}

    def compare_scenarios(self, scenarios):
        """Run multiple scenarios and return comparison."""
        results = []
        for s in scenarios:
            r = self.run_scenario(**s)
            results.append(r)
        return results

    def get_time_series(self):
        """Delegate to the underlying model."""
        if self.model:
            return self.model.get_time_series()
        return {}

    def summary_report(self):
        """Full agent report including token usage."""
        base = {
            "agent": "model_agent",
            "climate": self.climate,
            "has_run": self.model is not None,
        }
        if self.model:
            base["simulation"] = self.model.summary_report()
        base["token_usage"] = {
            "total": self._token_tracker.total,
            "calls": self._token_tracker.count,
        }
        base["log_count"] = len(self._logs)
        return base

    def to_dict(self):
        """Serialize for data-flow transport."""
        return {
            "data": self.summary_report(),
            "logs": self.logs,
        }


# ---------------------------------------------------------------------------
# Test / demonstration
# ---------------------------------------------------------------------------

def test():
    print("=" * 60)
    print("  ModelAgent — Test Suite")
    print("=" * 60)

    # ---- 1. Initialize weather generator ---------------------------------
    print("\n[1] Weather generator (temperate climate)")
    w = WeatherGenerator(climate="temperate")
    sample_date = datetime(2024, 4, 1)
    for i in range(5):
        d = sample_date + timedelta(days=i)
        t, r = w.generate(d)
        print(f"    {d.strftime('%Y-%m-%d')}  temp={t:>5.1f}°C  rain={r:>4.1f}mm")

    # ---- 2. Single day step ----------------------------------------------
    print("\n[2] Single day step")
    model = CropModel(start_date=datetime(2024, 4, 1))
    rec = model.step(temp=22, rainfall=5)
    print(f"    LAI={rec['lai']:.4f}  SM={rec['soil_moisture']}mm  ET={rec['et']}mm  phase={rec['phase']}")

    # ---- 3. Full simulation ----------------------------------------------
    print("\n[3] Full 120-day simulation (temperate, planted Apr 1)")
    agent = ModelAgent(climate="temperate")
    report = agent.run_simulation("2024-04-01", days=120)
    model = agent.model
    print(f"    Total days: {report['total_days']}")
    print(f"    LAI:   min={report['lai']['min']:.3f}  max={report['lai']['max']:.3f}  peak={report['lai']['peak']:.3f}")
    print(f"    SM:    min={report['soil_moisture']['min']:.1f}  max={report['soil_moisture']['max']:.1f}  mean={report['soil_moisture']['mean']:.1f}")
    print(f"    ET:    min={report['et']['min']:.2f}  max={report['et']['max']:.2f}  total={report['et']['total']:.1f}mm")
    print(f"    Water: rain={report['water_balance']['total_rainfall']:.0f}mm  "
          f"ET={report['water_balance']['total_et']:.0f}mm  "
          f"stress_days={report['water_balance']['water_stress_days']}")

    # ---- 4. Time series table --------------------------------------------
    print("\n[4] Time series sample (first 8 days)")
    model.print_time_series(max_rows=8)

    # ---- 5. Check iterative update logic ---------------------------------
    print("\n[5] Iterative update verification (days 1-5 state transitions)")
    model2 = CropModel(start_date=datetime(2024, 4, 1))
    w2 = WeatherGenerator(climate="temperate", seed=1)
    for i in range(5):
        d = datetime(2024, 4, 1) + timedelta(days=i)
        t, r = w2.generate(d)
        rec = model2.step(t, r)
        print(f"    Day {i+1}: temp={t:>5.1f}  rain={r:>4.1f}  "
              f"LAI={rec['lai']:.4f}  SM={rec['soil_moisture']:.1f}  ET={rec['et']:.3f}")
    # Verify state changed
    states = [model2.history[i]["lai"] for i in range(5)]
    assert len(set(round(s, 2) for s in states)) > 1, "LAI did not change over time"
    print(f"    => State changed across iterations (LAI: {states[0]:.4f} -> {states[-1]:.4f})")

    # ---- 6. Climate comparison -------------------------------------------
    print("\n[6] Climate comparison (same planting date, 90 days)")
    climates = ["temperate", "tropical", "dry"]
    results = {}
    for climate in climates:
        a = ModelAgent(climate=climate)
        r = a.run_simulation("2024-04-01", days=90)
        results[climate] = {
            "lai_peak": r["lai"]["peak"],
            "lai_max": r["lai"]["max"],
            "et_total": r["et"]["total"],
            "stress_days": r["water_balance"]["water_stress_days"],
        }
        print(f"    {climate:<12}  LAI peak={r['lai']['peak']:.2f}  "
              f"ET total={r['et']['total']:.0f}mm  "
              f"stress={r['water_balance']['water_stress_days']}d")

    # ---- 7. Edge case: different planting dates --------------------------
    print("\n[7] Planting date effect (temperate, 120 days)")
    for planting in ["2024-03-01", "2024-05-01", "2024-07-01"]:
        a = ModelAgent(climate="temperate")
        r = a.run_simulation(planting, days=120)
        print(f"    Plant {planting}: LAI peak={r['lai']['peak']:.2f}  "
              f"ET total={r['et']['total']:.0f}mm")

    # ---- 8. ModelAgent full report ---------------------------------------
    print("\n[8] ModelAgent full summary report")
    report = agent.summary_report()
    print(f"    Agent:     {report['agent']}")
    print(f"    Climate:   {report['climate']}")
    print(f"    Has run:   {report['has_run']}")
    print(f"    Log count: {report['log_count']}")
    print(f"    Token:     {report['token_usage']['total']} tokens ({report['token_usage']['calls']} calls)")

    # ---- 9. Data-flow serialization --------------------------------------
    print("\n[9] Data-flow payload (to_dict)")
    payload = agent.to_dict()
    print(f"    Keys: {list(payload.keys())}")
    print(f"    Data keys: {list(payload['data'].keys())}")
    print(f"    Log count: {payload['data']['log_count']}")

    # ---- 10. Processing logs ---------------------------------------------
    print("\n[10] Processing logs")
    agent2 = ModelAgent(climate="dry")
    agent2.run_simulation("2024-06-01", days=60)
    agent2.model.print_logs()

    # ---- Summary ---------------------------------------------------------
    print("\n" + "=" * 60)
    print("  All tests passed.")
    print("=" * 60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    test()
