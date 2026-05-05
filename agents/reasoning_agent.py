"""
agents/reasoning_agent.py — Multi-step reasoning engine.

Steps (each receives state from previous):
  1. Anomaly Detection      — identify outliers and sudden changes
  2. Temporal Comparison    — trend analysis across time windows
  3. Causality Hypothesis   — primary + alternative causal explanations
  4. Decision Output        — actionable recommendations with uncertainty

Usage:
    python agents/reasoning_agent.py
"""

import logging
import math
import os
import statistics
import sys
from datetime import datetime, timedelta

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from agents.data_agent import DataAgent
from agents.model_agent import ModelAgent


# ---------------------------------------------------------------------------
# ReasoningState — mutable context passed between steps
# ---------------------------------------------------------------------------

class ReasoningState:
    """
    Accumulates reasoning results across all four steps.

    Each reasoning step reads from and writes to this object.
    """

    def __init__(self, time_series, metadata=None):
        """
        Parameters
        ----------
        time_series : dict of {str: list of (datetime, float)}
            Named time series to analyse.
        metadata : dict, optional
            Contextual info (region, crop, period, etc.).
        """
        self.time_series = time_series
        self.metadata = metadata or {}
        self.results = {}

    def add_result(self, step_name, result):
        self.results[step_name] = result
        return self

    def get(self, step_name, default=None):
        return self.results.get(step_name, default)

    @property
    def step_count(self):
        return len(self.results)

    def summary(self):
        return {
            "series_count": len(self.time_series),
            "series_names": list(self.time_series.keys()),
            "steps_completed": list(self.results.keys()),
            "metadata": self.metadata,
            "results": self.results,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _z_score(val, mean, std):
    return (val - mean) / std if std > 1e-8 else 0.0


def _linear_trend(values):
    """Simple linear regression slope. Returns (slope, intercept, r_squared)."""
    n = len(values)
    if n < 3:
        return 0.0, 0.0, 0.0
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(values) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, values))
    den = sum((x - mx) ** 2 for x in xs)
    slope = num / den if den != 0 else 0.0
    intercept = my - slope * mx
    # R^2
    ss_tot = sum((y - my) ** 2 for y in values)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, values))
    r2 = 1 - ss_res / ss_tot if ss_tot > 1e-8 else 0.0
    return slope, intercept, r2


def _describe_trend(slope):
    if abs(slope) < 1e-4:
        return "stable"
    return "increasing" if slope > 0 else "decreasing"


def _clip(v, lo, hi):
    return max(lo, min(hi, v))


def _fmt_d(dt):
    return dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)


# ---------------------------------------------------------------------------
# Step 1 — Anomaly Detection
# ---------------------------------------------------------------------------

def step_anomaly_detection(state):
    """
    Detect statistical outliers and sudden changes in each time series.

    Output per series:
      - global_anomalies: points with |z-score| > 2.0
      - sudden_changes:   inter-point jumps exceeding 2.5 × IQR
      - anomaly_score:    0-1 summary of how anomalous the series is
      - uncertainty:      0-1 (higher = less certain)
    """
    result = {}
    all_scores = []

    for name, series in state.time_series.items():
        if not series:
            result[name] = {"error": "empty series", "anomaly_score": 0.0, "uncertainty": 1.0}
            continue

        dates  = [s[0] for s in series]
        values = [s[1] for s in series]

        # -- Global anomalies (z-score) --
        mu = statistics.mean(values)
        sd = statistics.stdev(values) if len(values) > 1 else 0.0
        global_anoms = []
        for d, v in zip(dates, values):
            z = _z_score(v, mu, sd)
            if abs(z) > 2.0:
                global_anoms.append({
                    "date": _fmt_d(d),
                    "value": round(v, 4),
                    "z_score": round(z, 3),
                    "severity": "high" if abs(z) > 3.0 else "moderate",
                })

        # -- Sudden changes (consecutive difference) --
        diffs = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
        sudden = []
        if diffs:
            q1 = statistics.median(sorted(diffs)[:len(diffs)//2]) if len(diffs) > 1 else 0
            q3 = statistics.median(sorted(diffs)[len(diffs)//2:]) if len(diffs) > 1 else 0
            iqr = q3 - q1
            threshold = 2.5 * iqr if iqr > 1e-8 else 2.0 * statistics.mean(diffs) if diffs else 999
            for i, d in enumerate(diffs):
                if d > threshold:
                    idx = i + 1  # point after the jump
                    sudden.append({
                        "date_from": _fmt_d(dates[i]),
                        "date_to": _fmt_d(dates[idx]),
                        "change": round(values[idx] - values[i], 4),
                        "magnitude": round(d, 4),
                    })

        # -- Composite anomaly score --
        n_global = len(global_anoms)
        n_sudden = len(sudden)
        n = len(values)
        raw_score = (n_global / n) * 0.6 + (n_sudden / max(n - 1, 1)) * 0.4
        anomaly_score = _clip(raw_score * 3.0, 0.0, 1.0)  # amplify

        # -- Uncertainty: inversely related to series length and clarity --
        uncertainty = _clip(0.5 + 0.3 * (sd / max(abs(mu), 0.01)) - 0.1 * math.log10(n), 0.1, 0.9)

        entry = {
            "series_length":  n,
            "mean":           round(mu, 4),
            "std":            round(sd, 4),
            "global_anomalies_count": n_global,
            "global_anomalies":       global_anoms[:5],  # top 5
            "sudden_changes_count":   n_sudden,
            "sudden_changes":         sudden[:3],
            "anomaly_score":  round(anomaly_score, 3),
            "uncertainty":    round(uncertainty, 3),
        }
        result[name] = entry
        all_scores.append(anomaly_score)

    # -- Cross-series summary --
    summary_score = statistics.mean(all_scores) if all_scores else 0.0

    state.add_result("anomaly_detection", {
        "series": result,
        "overall_anomaly_score": round(summary_score, 3),
        "overall_uncertainty":   round(statistics.mean(
            [v["uncertainty"] for v in result.values() if isinstance(v, dict) and "uncertainty" in v]
        ), 3) if any(isinstance(v, dict) and "uncertainty" in v for v in result.values()) else 1.0,
    })
    return state


# ---------------------------------------------------------------------------
# Step 2 — Temporal Comparison
# ---------------------------------------------------------------------------

def step_temporal_comparison(state):
    """
    Compare early vs late halves of each time series.

    Output per series:
      - early_mean, late_mean, delta
      - trend (slope, direction, r_squared)
      - regime_change: true if means differ significantly
    """
    prev = state.get("anomaly_detection")
    if not prev:
        raise RuntimeError("temporal_comparison requires anomaly_detection first")

    result = {}

    for name, series in state.time_series.items():
        if not series or len(series) < 4:
            result[name] = {"error": "insufficient data", "trend": "unknown"}
            continue

        values = [s[1] for s in series]
        n = len(values)
        half = n // 2

        early = values[:half]
        late  = values[half:]

        early_mean = statistics.mean(early)
        late_mean  = statistics.mean(late)
        delta = late_mean - early_mean

        # -- Trend --
        slope, intercept, r2 = _linear_trend(values)
        direction = _describe_trend(slope)

        # -- Regime change: check if split means differ > 1 combined std --
        combined_std = math.sqrt(
            (statistics.stdev(early) ** 2 if len(early) > 1 else 0) +
            (statistics.stdev(late) ** 2 if len(late) > 1 else 0)
        )
        regime_change = abs(delta) > combined_std * 0.5 if combined_std > 1e-8 else False

        # -- Uncertainty: function of data scatter and trend strength --
        uncertainty = _clip(0.6 - 0.5 * abs(r2) + 0.1 * (combined_std / max(abs(early_mean), 0.01)), 0.1, 0.9)

        result[name] = {
            "periods": {
                "early": {"start": _fmt_d(series[0][0]),  "end": _fmt_d(series[half - 1][0]),  "mean": round(early_mean, 4)},
                "late":  {"start": _fmt_d(series[half][0]), "end": _fmt_d(series[-1][0]),       "mean": round(late_mean, 4)},
            },
            "delta":          round(delta, 4),
            "delta_pct":      round(delta / max(abs(early_mean), 0.001) * 100, 1),
            "trend_slope":    round(slope, 6),
            "trend_direction": direction,
            "r_squared":      round(r2, 4),
            "regime_change":  regime_change,
            "uncertainty":    round(uncertainty, 3),
        }

    state.add_result("temporal_comparison", {
        "series": result,
        "overall_uncertainty": round(statistics.mean(
            [v["uncertainty"] for v in result.values() if isinstance(v, dict) and "uncertainty" in v]
        ), 3) if any(isinstance(v, dict) and "uncertainty" in v for v in result.values()) else 1.0,
    })
    return state


# ---------------------------------------------------------------------------
# Step 3 — Causality Hypothesis
# ---------------------------------------------------------------------------

def step_causality_hypothesis(state):
    """
    Generate primary and alternative causal hypotheses.

    Uses:
      - Temporal precedence (which variable changes first)
      - Correlation between variables
      - Known physical relationships (encoded as domain rules)

    Output:
      - primary_hypothesis: most likely explanation
      - alternative_hypotheses: 1-2 other plausible explanations
      - evidence_strength: 0-1
    """
    prev_ad = state.get("anomaly_detection")
    prev_tc = state.get("temporal_comparison")
    if not prev_ad or not prev_tc:
        raise RuntimeError("causality_hypothesis requires steps 1 & 2")

    series_names = list(state.time_series.keys())
    hypotheses = []
    evidence_scores = []

    # -- Build pairwise relationships --
    names = list(state.time_series.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a_name, b_name = names[i], names[j]
            a_vals = [s[1] for s in state.time_series[a_name]]
            b_vals = [s[1] for s in state.time_series[b_name]]
            n = min(len(a_vals), len(b_vals))
            if n < 3:
                continue
            a_vals, b_vals = a_vals[:n], b_vals[:n]

            # Pearson correlation
            ma, mb = statistics.mean(a_vals), statistics.mean(b_vals)
            num = sum((x - ma) * (y - mb) for x, y in zip(a_vals, b_vals))
            den = math.sqrt(sum((x - ma) ** 2 for x in a_vals) * sum((y - mb) ** 2 for y in b_vals))
            corr = num / den if den > 1e-8 else 0.0

            # Lag detection: which leads?
            lag = None
            if len(a_vals) > 5:
                # Simple heuristic: compare early trends
                ha = a_vals[:n // 2]
                hb = b_vals[:n // 2]
                if abs(statistics.mean(ha) - statistics.mean(a_vals)) > abs(statistics.mean(hb) - statistics.mean(b_vals)):
                    lag = f"{a_name} leads (stronger early trend)"

            strength = _clip(abs(corr), 0.0, 1.0)
            evidence_scores.append(strength)

            # -- Hypothesis template --
            if abs(corr) > 0.5:
                direction = "positive" if corr > 0 else "negative"
                causal_dir = f"{a_name} covaries {direction}ly with {b_name}"

                hypotheses.append({
                    "relation": f"{a_name} <-> {b_name}",
                    "correlation": round(corr, 3),
                    "interpretation": causal_dir,
                    "evidence_strength": round(strength, 3),
                    "lag_analysis": lag,
                })

    # -- Determine primary and alternative --
    if not hypotheses:
        # Fallback: single-variable inference
        primary = {
            "title": "No significant cross-variable relationships detected",
            "explanation": "Each variable behaves independently within expected bounds.",
            "confidence": 0.5,
        }
        alternatives = []
    else:
        hypotheses.sort(key=lambda h: h["evidence_strength"], reverse=True)
        best = hypotheses[0]
        primary = {
            "title": f"Primary: {best['relation']}",
            "explanation": f"Strong {best['interpretation']} "
                          f"(r={best['correlation']}). {best.get('lag_analysis', '')}",
            "confidence": round(best["evidence_strength"], 3),
            "supporting_evidence": best,
        }
        alternatives = []
        for alt_h in hypotheses[1:3]:
            alternatives.append({
                "title": f"Alternative: {alt_h['relation']}",
                "explanation": f"Weaker {alt_h['interpretation']} (r={alt_h['correlation']})",
                "confidence": round(alt_h["evidence_strength"] * 0.7, 3),
            })

    overall_evidence = statistics.mean(evidence_scores) if evidence_scores else 0.0
    overall_uncertainty = _clip(1.0 - overall_evidence + 0.2, 0.1, 0.9)

    state.add_result("causality_hypothesis", {
        "primary_hypothesis": primary,
        "alternative_hypotheses": alternatives,
        "all_relationships": hypotheses,
        "overall_evidence_strength": round(overall_evidence, 3),
        "overall_uncertainty": round(overall_uncertainty, 3),
    })
    return state


# ---------------------------------------------------------------------------
# Step 4 — Decision Output
# ---------------------------------------------------------------------------

def step_decision_output(state):
    """
    Aggregate all previous steps into an actionable decision.

    Output:
      - assessment: summary of the situation
      - recommendations: ordered list of actions
      - risk: things to watch
      - final_confidence: 0-1
    """
    ad = state.get("anomaly_detection")
    tc = state.get("temporal_comparison")
    ch = state.get("causality_hypothesis")

    missing = [s for s, v in [("anomaly_detection", ad), ("temporal_comparison", tc), ("causality_hypothesis", ch)] if not v]
    if missing:
        raise RuntimeError(f"decision_output requires prior steps: {missing}")

    anomaly_score = ad["overall_anomaly_score"]
    temporal_uncertainty = tc["overall_uncertainty"]
    evidence = ch["overall_evidence_strength"]

    # -- Build recommendations --
    recommendations = []

    if anomaly_score > 0.5:
        recommendations.append({
            "priority": "high",
            "action": "Investigate anomalous signals",
            "rationale": f"Overall anomaly score {anomaly_score:.2f} exceeds threshold",
        })
    else:
        recommendations.append({
            "priority": "low",
            "action": "Continue routine monitoring",
            "rationale": "No significant anomalies detected",
        })

    # Check regime changes
    regime_series = []
    for sname, sinfo in tc["series"].items():
        if isinstance(sinfo, dict) and sinfo.get("regime_change"):
            regime_series.append(sname)
    if regime_series:
        recommendations.append({
            "priority": "medium",
            "action": f"Review regime change in {', '.join(regime_series)}",
            "rationale": "Statistical shift detected between early and late periods",
        })

    # Trend-based
    declining = [sname for sname, sinfo in tc["series"].items()
                 if isinstance(sinfo, dict) and sinfo.get("trend_direction") == "decreasing"]
    if declining:
        recommendations.append({
            "priority": "medium",
            "action": f"Monitor declining trend in {', '.join(declining)}",
            "rationale": "Sustained decrease may indicate systemic change",
        })

    # Hypothesis-based
    if ch.get("alternative_hypotheses"):
        recommendations.append({
            "priority": "info",
            "action": "Consider alternative hypotheses before acting",
            "rationale": f"{len(ch['alternative_hypotheses'])} alternative explanations exist",
        })

    # -- Final confidence --
    final_confidence = _clip(
        0.5
        + 0.2 * (1.0 - anomaly_score if anomaly_score > 0.5 else anomaly_score)
        + 0.2 * evidence
        - 0.1 * temporal_uncertainty,
        0.1, 0.95
    )

    decision = {
        "assessment": {
            "status": "anomalous" if anomaly_score > 0.5 else "normal",
            "anomaly_level": round(anomaly_score, 3),
            "trend_summary": {
                sname: sinfo.get("trend_direction", "unknown")
                for sname, sinfo in tc["series"].items()
                if isinstance(sinfo, dict)
            },
        },
        "primary_hypothesis": ch["primary_hypothesis"],
        "recommendations": recommendations,
        "final_confidence": round(final_confidence, 3),
        "uncertainty_sources": [
            f"Anomaly detection: {ad['overall_uncertainty']}",
            f"Temporal comparison: {temporal_uncertainty}",
            f"Causality evidence: {ch['overall_evidence_strength']}",
        ],
    }

    state.add_result("decision_output", decision)
    return state


# ---------------------------------------------------------------------------
# ReasoningAgent — orchestrates the four-step pipeline
# ---------------------------------------------------------------------------

STEP_REGISTRY = [
    ("anomaly_detection",    step_anomaly_detection),
    ("temporal_comparison",  step_temporal_comparison),
    ("causality_hypothesis", step_causality_hypothesis),
    ("decision_output",      step_decision_output),
]


class ReasoningAgent:
    """
    Multi-step reasoning agent.

    Runs four sequential reasoning steps, each receiving the accumulated
    state from the previous step.  Produces a final decision with
    uncertainty and alternative hypotheses.
    """

    def __init__(self):
        self.state = None
        self._logs = []
        self._log("ReasoningAgent initialized")

    def _log(self, message):
        entry = {
            "time": datetime.now(),
            "message": message,
        }
        self._logs.append(entry)
        logging.info("ReasoningAgent: %s", message)

    @property
    def logs(self):
        return list(self._logs)

    # -- Feed data ----------------------------------------------------------

    def feed_time_series(self, time_series, metadata=None):
        """
        Load time-series data for reasoning.

        Parameters
        ----------
        time_series : dict of {str: list of (datetime, float)}
        metadata : dict, optional
        """
        self.state = ReasoningState(time_series, metadata)
        n = sum(len(v) for v in time_series.values())
        self._log(f"Loaded {len(time_series)} series, {n} total data points")
        return self

    def feed_from_data_agent(self, data_agent):
        """Convenience: extract time series from a DataAgent instance."""
        series = {}
        for name in ("ndvi", "npmi"):
            raw = data_agent.get_time_series().get(name, [])
            dates = [s[0] for s in raw]
            vals  = [s[1] for s in raw]
            series[name] = list(zip(dates, vals))
        return self.feed_time_series(series, {"source": "data_agent"})

    def feed_from_model_agent(self, model_agent):
        """Convenience: extract time series from a ModelAgent instance."""
        series = {}
        if model_agent.model:
            raw = model_agent.model.get_time_series()
            for name in ("lai", "soil_moisture", "et", "gdd"):
                if name in raw:
                    series[name] = raw[name]
        return self.feed_time_series(series, {"source": "model_agent"})

    # -- Run reasoning -----------------------------------------------------

    def run(self, steps=None):
        """
        Execute the reasoning pipeline.

        Parameters
        ----------
        steps : list of str, optional
            Subset of steps to run (default: all four).
            Options: anomaly_detection, temporal_comparison,
                     causality_hypothesis, decision_output.

        Returns
        -------
        ReasoningState
        """
        if self.state is None:
            raise RuntimeError("No data loaded. Call feed_time_series() first.")

        step_names = steps or [s[0] for s in STEP_REGISTRY]

        for step_name, step_fn in STEP_REGISTRY:
            if step_name not in step_names:
                continue

            self._log(f"Running step: {step_name}")
            try:
                step_fn(self.state)
                n_findings = len(self.state.get(step_name)) if self.state.get(step_name) else 0
                self._log(f"  -> {step_name} completed")
            except Exception as e:
                self._log(f"  -> {step_name} FAILED: {e}")
                raise

        self._log("Reasoning pipeline complete")
        return self.state

    # -- Reporting ---------------------------------------------------------

    def summary_report(self):
        """Full report of all reasoning steps."""
        if not self.state:
            return {"status": "no_data"}

        return {
            "agent": "reasoning_agent",
            "status": "completed",
            "steps_completed": self.state.step_count,
            "results": {
                name: self.state.get(name)
                for name, _ in STEP_REGISTRY
                if self.state.get(name)
            },
            "log_count": len(self._logs),
        }

    def print_logs(self):
        """Print all processing logs."""
        print(f"\n{'-' * 60}")
        print("  Processing Logs")
        print(f"{'-' * 60}")
        for entry in self._logs:
            print(f"  {entry['message']}")
        print(f"{'-' * 60}")

    def print_step(self, step_name):
        """Pretty-print a single step's results."""
        data = self.state.get(step_name) if self.state else None
        if not data:
            print(f"  (no data for step '{step_name}')")
            return

        print(f"\n{'=' * 70}")
        print(f"  Step: {step_name}")
        print(f"{'=' * 70}")

        if step_name == "anomaly_detection":
            print(f"  Overall anomaly score: {data['overall_anomaly_score']}")
            print(f"  Overall uncertainty:   {data['overall_uncertainty']}")
            for sname, sinfo in data["series"].items():
                if isinstance(sinfo, dict) and "anomaly_score" in sinfo:
                    print(f"\n  [{sname}]")
                    print(f"    Score: {sinfo['anomaly_score']}  |  "
                          f"Anomalies: {sinfo['global_anomalies_count']} global, "
                          f"{sinfo['sudden_changes_count']} sudden")
                    for a in sinfo.get("global_anomalies", [])[:2]:
                        print(f"    [!] {a['date']}  value={a['value']}  z={a['z_score']} ({a['severity']})")

        elif step_name == "temporal_comparison":
            print(f"  Overall uncertainty: {data['overall_uncertainty']}")
            for sname, sinfo in data["series"].items():
                if isinstance(sinfo, dict) and "trend_direction" in sinfo:
                    p = sinfo["periods"]
                    print(f"\n  [{sname}]")
                    print(f"    Early: mean={p['early']['mean']}  |  Late: mean={p['late']['mean']}")
                    print(f"    Delta: {sinfo['delta_pct']}%  |  "
                          f"Trend: {sinfo['trend_direction']}  |  "
                          f"R^2={sinfo['r_squared']}")
                    print(f"    Regime change: {sinfo['regime_change']}")

        elif step_name == "causality_hypothesis":
            p = data.get("primary_hypothesis", {})
            print(f"  Evidence strength: {data['overall_evidence_strength']}")
            print(f"  Uncertainty: {data['overall_uncertainty']}")
            print(f"\n  Primary hypothesis:")
            print(f"    {p.get('title', 'N/A')}")
            print(f"    Confidence: {p.get('confidence', 'N/A')}")
            for i, alt in enumerate(data.get("alternative_hypotheses", []), 1):
                print(f"\n  Alternative #{i}:")
                print(f"    {alt.get('title', 'N/A')}")
                print(f"    Confidence: {alt.get('confidence', 'N/A')}")

        elif step_name == "decision_output":
            print(f"  Assessment: {data['assessment']['status']}")
            print(f"  Confidence: {data['final_confidence']}")
            print(f"\n  Trends:")
            for var, trend in data["assessment"]["trend_summary"].items():
                print(f"    {var}: {trend}")
            print(f"\n  Recommendations:")
            for r in data.get("recommendations", []):
                print(f"    [{r['priority']:<6}] {r['action']}")
            print(f"\n  Primary hypothesis:")
            print(f"    {data['primary_hypothesis'].get('explanation', '')}")

        print(f"{'=' * 70}")

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
    print("  ReasoningAgent — Test Suite")
    print("=" * 60)

    # ---- 0. Prepare synthetic data for deterministic tests ---------------
    # Build controlled time series with known anomalies and trends
    import random
    rng = random.Random(42)

    base_date = datetime(2024, 1, 1)
    dates = [base_date + timedelta(days=i * 16) for i in range(25)]

    # NDVI: normal vegetation cycle with an injected anomaly
    ndvi_values = []
    for i in range(len(dates)):
        doy = dates[i].timetuple().tm_yday
        seasonal = 0.3 * math.sin(2 * math.pi * (doy - 80) / 365)  # seasonal pattern
        noise = rng.gauss(0, 0.05)
        val = 0.4 + seasonal + noise
        if i == 7:
            val = -0.3  # inject anomaly: sudden drop
        ndvi_values.append(round(val, 4))

    # NPMI: related to NDVI with lag, plus trend
    npmi_values = []
    for i in range(len(dates)):
        base_v = ndvi_values[i] * 0.7 + 0.1 + 0.003 * i  # upward trend
        npmi_values.append(round(base_v + rng.gauss(0, 0.03), 4))

    # LAI: smooth growth then decline with a flat period
    lai_values = []
    for i in range(len(dates)):
        progress = i / len(dates)
        val = 3.0 * math.sin(progress * math.pi) + rng.gauss(0, 0.1)
        lai_values.append(round(val, 4))

    # Soil moisture: declining trend with a sudden drop
    sm_values = []
    for i in range(len(dates)):
        val = 110 - 1.5 * i + rng.gauss(0, 3)
        if i == 12:
            val = 40  # inject anomaly: sudden drop
        sm_values.append(round(max(30, val), 1))

    # ET: follows LAI
    et_values = []
    for i in range(len(dates)):
        val = 1.0 + 2.0 * math.sin(i / len(dates) * math.pi) + rng.gauss(0, 0.2)
        et_values.append(round(val, 3))

    test_series = {
        "ndvi":           list(zip(dates, ndvi_values)),
        "npmi":           list(zip(dates, npmi_values)),
        "lai":            list(zip(dates, lai_values)),
        "soil_moisture":  list(zip(dates, sm_values)),
        "et":             list(zip(dates, et_values)),
    }

    # ---- 1. Initialize agent and load data --------------------------------
    print("\n[1] Initialize and load time series")
    agent = ReasoningAgent()
    agent.feed_time_series(test_series, {"crop": "maize", "region": "test"})
    agent.print_logs()
    print(f"\n    Loaded: {len(agent.state.time_series)} series")
    for name, series in agent.state.time_series.items():
        print(f"      {name:<16} {len(series):>3} points  "
              f"[{_fmt_d(series[0][0])} -> {_fmt_d(series[-1][0])}]")

    # ---- 2. Step 1: Anomaly detection ------------------------------------
    print("\n[2] Anomaly Detection")
    agent.run(steps=["anomaly_detection"])
    agent.print_step("anomaly_detection")

    # ---- 3. Step 2: Temporal comparison ----------------------------------
    print("\n[3] Temporal Comparison")
    agent.run(steps=["temporal_comparison"])
    agent.print_step("temporal_comparison")

    # ---- 4. Step 3: Causality hypothesis ---------------------------------
    print("\n[4] Causality Hypothesis")
    agent.run(steps=["causality_hypothesis"])
    agent.print_step("causality_hypothesis")

    # ---- 5. Step 4: Decision output --------------------------------------
    print("\n[5] Decision Output")
    agent.run(steps=["decision_output"])
    agent.print_step("decision_output")

    # ---- 6. Verify state passing -----------------------------------------
    print("\n[6] State passing verification")
    assert agent.state.step_count == 4, f"Expected 4 steps, got {agent.state.step_count}"
    for name, _ in STEP_REGISTRY:
        assert agent.state.get(name) is not None, f"Step {name} missing from state"
    print("    All 4 steps present in state: [ok]")

    # ---- 7. Verify uncertainty in every step -----------------------------
    print("\n[7] Uncertainty tracking")
    for name, _ in STEP_REGISTRY:
        data = agent.state.get(name)
        if data and "overall_uncertainty" in data:
            u = data["overall_uncertainty"]
            print(f"    {name:<25} uncertainty = {u}")
        elif data and "final_confidence" in data:
            c = data["final_confidence"]
            print(f"    {name:<25} confidence = {c}  (uncertainty = {1 - c:.3f})")

    # ---- 8. Verify alternative hypotheses --------------------------------
    print("\n[8] Alternative hypotheses")
    ch = agent.state.get("causality_hypothesis")
    primary = ch.get("primary_hypothesis", {})
    alt = ch.get("alternative_hypotheses", [])
    print(f"    Primary:   {primary.get('title', 'N/A')}")
    print(f"    Confidence: {primary.get('confidence', 'N/A')}")
    for i, a in enumerate(alt, 1):
        print(f"    Alt #{i}:    {a.get('title', 'N/A')}")
        print(f"               Confidence: {a.get('confidence', 'N/A')}")

    # ---- 9. Edge: empty series -------------------------------------------
    print("\n[9] Edge case: empty time series")
    empty_agent = ReasoningAgent()
    empty_agent.feed_time_series({"empty": []}, {})
    empty_agent.run()
    print(f"    Steps completed: {empty_agent.state.step_count}")
    print(f"    Decision status: {empty_agent.state.get('decision_output')['assessment']['status']}")

    # ---- 10. Full report -------------------------------------------------
    print("\n[10] Summary report")
    report = agent.summary_report()
    print(f"    Agent:  {report['agent']}")
    print(f"    Status: {report['status']}")
    print(f"    Steps:  {report['steps_completed']}")
    print(f"    Logs:   {report['log_count']}")
    print(f"    Keys:   {list(report['results'].keys())}")

    # ---- 11. Data-flow serialization -------------------------------------
    print("\n[11] Data-flow payload (to_dict)")
    payload = agent.to_dict()
    print(f"    Top-level keys: {list(payload.keys())}")
    print(f"    Log entries: {len(payload['logs'])}")

    # ---- Summary ---------------------------------------------------------
    print("\n" + "=" * 60)
    print("  All tests passed.")
    print("=" * 60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    test()
