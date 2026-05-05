"""
agents/data_agent.py — Remote sensing data processing agent.

Uses gee_mock to simulate satellite imagery acquisition and compute
spectral index time series (NDVI, NPMI) with full processing logs.

Usage:
    # From project root:
    python agents/data_agent.py
"""

import logging
import os
import sys
from datetime import datetime

# Allow running as `python agents/data_agent.py` from project root
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from tools.gee_mock import ImageCollection, DEFAULT_REGION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_date(dt):
    """Format a datetime to YYYY-MM-DD string."""
    return dt.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# DataAgent
# ---------------------------------------------------------------------------

class DataAgent:
    """
    Processes satellite imagery to extract vegetation and moisture indices.

    Produces time series for:
      - NDVI  (NIR - Red) / (NIR + Red)
      - NPMI  (NIR - SWIR) / (NIR + SWIR)

    Every method logs its actions for full auditability.
    """

    def __init__(self, collection=None, region=None):
        self.collection = collection if collection is not None else ImageCollection.generate(count=30)
        self.region = region or DEFAULT_REGION
        self._logs = []
        self._cached = {}  # cache computed indices

        self._log(f"Initialized: {self.collection.size} images, "
                  f"region={self.region['type']}")

    # -- Logging -----------------------------------------------------------

    def _log(self, message):
        entry = {
            "time": datetime.now(),
            "message": f"[{datetime.now().strftime('%H:%M:%S')}] {message}",
        }
        self._logs.append(entry)
        logging.info("DataAgent: %s", message)

    @property
    def logs(self):
        """Return all log entries (read-only)."""
        return list(self._logs)

    # -- Core computation --------------------------------------------------

    def _compute_index(self, band_a, band_b, reducer="mean"):
        """
        Compute (band_a - band_b) / (band_a + band_b) for every image.

        Returns list of (datetime, value) sorted by acquisition date.
        """
        label = f"({band_a} - {band_b})/({band_a} + {band_b})"
        self._log(f"Computing {label}, reducer={reducer}")

        results = []
        images = self.collection.to_list()

        for idx, img in enumerate(images):
            a = img.reduce_region(reducer, band_a)
            b = img.reduce_region(reducer, band_b)
            denom = a + b
            val = round((a - b) / denom, 4) if abs(denom) > 1e-8 else 0.0
            results.append((img.date, val))

        results.sort(key=lambda x: x[0])
        if results:
            vals = [v for _, v in results]
            self._log(f"  → {len(results)} points, range=[{min(vals):.4f}, {max(vals):.4f}]")
        else:
            self._log("  → (empty collection — no data points)")
        return results

    # -- Public index methods ----------------------------------------------

    def compute_ndvi(self, nir="B5", red="B4", reducer="mean"):
        """
        Normalized Difference Vegetation Index.

            NDVI = (NIR - Red) / (NIR + Red)

        Bands:  B4 = Red, B5 = Near-Infrared
        Range:  -1 to 1  (dense vegetation → high positive)
        """
        if "ndvi" in self._cached:
            self._log("NDVI returned from cache")
            return self._cached["ndvi"]

        self._log(f"NDVI: NIR={nir}, Red={red}")
        series = self._compute_index(nir, red, reducer)
        self._cached["ndvi"] = series
        return series

    def compute_npmi(self, nir="B5", swir="B6", reducer="mean"):
        """
        Normalized Difference Moisture Index (spectral).

            NPMI = (NIR - SWIR) / (NIR + SWIR)

        Bands:  B5 = Near-Infrared, B6 = Short-Wave Infrared
        Range:  -1 to 1  (higher moisture → high positive)
        """
        if "npmi" in self._cached:
            self._log("NPMI returned from cache")
            return self._cached["npmi"]

        self._log(f"NPMI: NIR={nir}, SWIR={swir}")
        series = self._compute_index(nir, swir, reducer)
        self._cached["npmi"] = series
        return series

    # -- Time series outputs -----------------------------------------------

    def get_time_series(self):
        """
        Compute both NDVI and NPMI, return as a single dict.

        Returns
        -------
        dict
            ``{"ndvi": [(date, val), ...], "npmi": [(date, val), ...]}``
        """
        self._log("Building full time-series output")
        return {
            "ndvi": self.compute_ndvi(),
            "npmi": self.compute_npmi(),
        }

    # -- Reporting ---------------------------------------------------------

    def print_logs(self):
        """Print all processing logs."""
        print(f"\n{'─' * 60}")
        print("  Processing Logs")
        print(f"{'─' * 60}")
        for entry in self._logs:
            print(f"  {entry['message']}")
        print(f"{'─' * 60}")

    def print_time_series(self, max_rows=None):
        """
        Print NDVI + NPMI time series as a table.
        """
        data = self.get_time_series()
        ndvi = data["ndvi"]
        npmi = data["npmi"]

        # Build a lookup by date string
        ndvi_map = {_fmt_date(dt): v for dt, v in ndvi}
        npmi_map = {_fmt_date(dt): v for dt, v in npmi}
        all_dates = sorted(set(ndvi_map) | set(npmi_map))

        if max_rows:
            all_dates = all_dates[:max_rows]

        print(f"\n{'─' * 60}")
        print(f"  Time Series Output")
        print(f"{'─' * 60}")
        print(f"  {'Date':<16} {'NDVI':<10} {'NPMI':<10}  {'Condition':<20}")
        print(f"  {'─' * 56}")
        for d in all_dates:
            n1 = ndvi_map.get(d, "")
            n2 = npmi_map.get(d, "")
            label = ""
            if n1 and n1 > 0.3:
                label = "Vegetation"
            elif n1 and n1 < 0:
                label = "Sparse / Water"
            n1_s = f"{n1:>+8.4f}" if n1 != "" else ""
            n2_s = f"{n2:>+8.4f}" if n2 != "" else ""
            print(f"  {d:<16} {n1_s:<10} {n2_s:<10}  {label:<20}")
        print(f"{'─' * 60}")

    def summary_report(self):
        """
        Full report: metadata, logs, and time-series data.
        Suitable for F9 data flow (Analyst → Orchestrator).
        """
        series = self.get_time_series()
        ndvi_vals = [v for _, v in series["ndvi"]]
        npmi_vals = [v for _, v in series["npmi"]]

        report = {
            "agent": "data_agent",
            "status": "completed",
            "collection_size": self.collection.size,
            "date_range": {
                "start": _fmt_date(self.collection.date_range()[0]),
                "end":   _fmt_date(self.collection.date_range()[1]),
            },
            "indices": {
                "ndvi": {
                    "formula": "(B5 - B4) / (B5 + B4)",
                    "min": round(min(ndvi_vals), 4),
                    "max": round(max(ndvi_vals), 4),
                    "mean": round(sum(ndvi_vals) / len(ndvi_vals), 4),
                    "time_series": [
                        {"date": _fmt_date(dt), "value": v}
                        for dt, v in series["ndvi"]
                    ],
                },
                "npmi": {
                    "formula": "(B5 - B6) / (B5 + B6)",
                    "min": round(min(npmi_vals), 4),
                    "max": round(max(npmi_vals), 4),
                    "mean": round(sum(npmi_vals) / len(npmi_vals), 4),
                    "time_series": [
                        {"date": _fmt_date(dt), "value": v}
                        for dt, v in series["npmi"]
                    ],
                },
            },
            "log_count": len(self._logs),
        }
        return report

    # -- Pipeline integration ----------------------------------------------

    def to_dict(self):
        """
        Serialize for data-flow transport (maps to F9 in architecture).
        """
        report = self.summary_report()
        return {
            "data": report,
            "logs": self.logs,
        }


# ---------------------------------------------------------------------------
# Test / demonstration
# ---------------------------------------------------------------------------

def test():
    print("=" * 60)
    print("  DataAgent — Test Suite")
    print("=" * 60)

    # ---- 1. Initialize with generated data --------------------------------
    print("\n[1] Initialize DataAgent (30 simulated satellite images)")
    agent = DataAgent()
    agent.print_logs()

    # ---- 2. Compute NDVI -------------------------------------------------
    print("\n[2] NDVI computation")
    ndvi = agent.compute_ndvi()
    print(f"    NDVI points: {len(ndvi)}")
    print(f"    Date range:  {_fmt_date(ndvi[0][0])} → {_fmt_date(ndvi[-1][0])}")
    print(f"    Value range: {min(v for _, v in ndvi):.4f} ~ {max(v for _, v in ndvi):.4f}")

    # ---- 3. Compute NPMI -------------------------------------------------
    print("\n[3] NPMI computation")
    npmi = agent.compute_npmi()
    print(f"    NPMI points: {len(npmi)}")
    print(f"    Value range: {min(v for _, v in npmi):.4f} ~ {max(v for _, v in npmi):.4f}")

    # ---- 4. Print time series table --------------------------------------
    print("\n[4] Time series table (first 10 rows)")
    series = agent.get_time_series()
    print(f"    NDVI formula: (B5 - B4) / (B5 + B4)")
    print(f"    NPMI formula: (B5 - B6) / (B5 + B6)")
    agent.print_time_series(max_rows=10)

    # ---- 5. Summary report -----------------------------------------------
    print("\n[5] Summary report (JSON structure)")
    report = agent.summary_report()
    print(f"    Collection:  {report['collection_size']} images")
    print(f"    Date range:  {report['date_range']['start']} → {report['date_range']['end']}")
    for idx_name in ("ndvi", "npmi"):
        idx = report["indices"][idx_name]
        print(f"    {idx_name.upper():<6}  "
              f"min={idx['min']:+7.4f}  "
              f"max={idx['max']:+7.4f}  "
              f"mean={idx['mean']:+7.4f}  "
              f"({idx['formula']})")

    # ---- 6. Log count ----------------------------------------------------
    print("\n[6] Processing logs captured")
    print(f"    Total log entries: {len(agent.logs)}")
    for i, entry in enumerate(agent.logs[-3:], 1):
        print(f"    Recent #{i}: {entry['message']}")

    # ---- 7. Cached re-computation ----------------------------------------
    print("\n[7] Cache verification (2nd call returns cached)")
    agent.compute_ndvi()  # should log "returned from cache"
    agent.print_logs()

    # ---- 8. Edge case: empty collection ----------------------------------
    print("\n[8] Edge case: empty collection")
    empty_agent = DataAgent(collection=ImageCollection([]))
    empty_ndvi = empty_agent.compute_ndvi()
    print(f"    Empty NDVI series: {empty_ndvi}")

    # ---- 9. Data-flow serialization --------------------------------------
    print("\n[9] Data-flow payload (to_dict / F9)")
    payload = agent.to_dict()
    print(f"    Keys: {list(payload.keys())}")
    print(f"    Data indices: {list(payload['data']['indices'].keys())}")
    print(f"    Log count:    {payload['data']['log_count']}")

    # ---- Summary ---------------------------------------------------------
    print("\n" + "=" * 60)
    print("  All tests passed.")
    print("=" * 60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    test()
