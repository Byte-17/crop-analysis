"""
workflows/pipeline.py — Batch pipeline for processing 50+ fields.

Calls all agents (DataAgent, ModelAgent, ReasoningAgent, MemorySystem)
and accumulates token usage across the entire batch.

Usage:
    from workflows.pipeline import BatchPipeline
    pipeline = BatchPipeline(num_fields=50)
    report = pipeline.run()
"""

import math
import os
import random
import statistics
import sys
import time
from datetime import datetime, timedelta

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from agents.data_agent import DataAgent
from agents.model_agent import ModelAgent, WeatherGenerator, CropModel
from agents.reasoning_agent import ReasoningAgent
from memory.memory_system import MemorySystem, TextEmbedder, cosine_similarity
from utils.token_tracker import TokenTracker, MODEL_FACTORS, AGENT_BASE


# ---------------------------------------------------------------------------
# Field generator
# ---------------------------------------------------------------------------

CLIMATES = ["temperate", "tropical", "dry"]
REGIONS  = ["NA", "SA", "EU", "AF", "AS", "AU"]
CROPS    = ["Maize", "Rice", "Wheat", "Soybean", "Cotton", "Sorghum"]

_rng = random.Random(0)


def _pick(seq):
    return seq[_rng.randint(0, len(seq) - 1)]


def generate_batch_fields(num_fields):
    """
    Generate *num_fields* varied field configurations.

    Each field has:
      name, climate, plant_date, days, region, crop
    """
    fields = []
    for i in range(num_fields):
        climate = _pick(CLIMATES)
        region  = _pick(REGIONS)
        crop    = _pick(CROPS)
        # Spread planting dates across the year
        month = _rng.randint(3, 7)
        day   = _rng.randint(1, 28)
        days  = _rng.choice([90, 105, 120, 135, 150])
        name = f"F{str(i).zfill(3)}-{crop[:2]}{region}"

        fields.append({
            "name":       name,
            "climate":    climate,
            "plant_date": f"2024-{month:02d}-{day:02d}",
            "days":       days,
            "region":     region,
            "crop":       crop,
        })
    return fields


# ---------------------------------------------------------------------------
# BatchPipeline
# ---------------------------------------------------------------------------

class BatchPipeline:
    """
    Batch processing pipeline for N fields.

    For each field:
      Memory retrieve → DataAgent → ModelAgent → ReasoningAgent → Memory store

    Accumulates:
      - Per-field results
      - Token usage (all agents)
      - Memory state (cross-field knowledge)
      - Multi-step logs (console + file)
    """

    def __init__(self, num_fields=50, model="sonnet",
                 log_file=None, verbose=True):
        self.num_fields = num_fields
        self.model = model
        self.fields = generate_batch_fields(num_fields)
        self.verbose = verbose

        # Sub-systems
        self.memory = MemorySystem()
        self.tokens = TokenTracker()

        # Results
        self.results = {}
        self._step_times = []
        self._logs = []
        self._log_file = log_file

        self._log(f"Pipeline initialized: {num_fields} fields, model={model}")

    # -- Logging -----------------------------------------------------------

    def _log(self, message, console=True):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {message}"
        self._logs.append(line)
        if self.verbose and console:
            print(line)
        if self._log_file:
            os.makedirs(os.path.dirname(self._log_file), exist_ok=True)
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def save_logs(self, path=None):
        """Write all accumulated logs to a file."""
        path = path or self._log_file
        if not path:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for line in self._logs:
                f.write(line + "\n")
        self._log(f"Logs saved to {path}")

    # -- Per-field pipeline ------------------------------------------------

    def _process_field(self, field, field_idx):
        """Run full pipeline for one field."""
        name = field["name"]
        t0 = time.time()
        self._log(f"[{field_idx}/{self.num_fields}] Processing {name}  "
                  f"({field['climate']}, {field['crop']}, {field['days']}d)")

        # Step 1: Memory retrieve
        context = self.memory.search(
            f"{field['crop']} {field['climate']} {field['region']}",
            top_k=3, min_score=0.30,
        )
        self.tokens.record("memory", fields=1, steps=1,
                           factor=MODEL_FACTORS.get(self.model, 120))
        self._log(f"  |-> memory: {len(context)} past insights retrieved")

        # Step 2: DataAgent
        da = DataAgent()
        ndvi = da.compute_ndvi()
        npmi = da.compute_npmi()
        self.tokens.record("data_agent", fields=2, steps=1,
                           factor=MODEL_FACTORS.get(self.model, 120))
        ndvi_mu = statistics.mean([v for _, v in ndvi]) if ndvi else 0
        npmi_mu = statistics.mean([v for _, v in npmi]) if npmi else 0
        self._log(f"  |-> data:    NDVI={ndvi_mu:+.4f}  NPMI={npmi_mu:+.4f}")

        # Step 3: ModelAgent
        ma = ModelAgent(climate=field["climate"])
        sim = ma.run_simulation(field["plant_date"], field["days"])
        self.tokens.record("model_agent", fields=3, steps=field["days"], factor=1)
        lai_p = sim.get("lai", {}).get("peak", 0)
        et_t  = sim.get("et", {}).get("total", 0)
        sm_m  = sim.get("soil_moisture", {}).get("mean", 0)
        stress = sim.get("water_balance", {}).get("water_stress_days", 0)
        self._log(f"  |-> model:   LAI={lai_p:.2f}  ET={et_t:.0f}mm  "
                  f"SM={sm_m:.1f}mm  stress={stress}d")

        # Step 4: ReasoningAgent
        ra = ReasoningAgent()
        ts = {"ndvi": ndvi, "npmi": npmi}
        if ma.model:
            mts = ma.model.get_time_series()
            for k in ("lai", "soil_moisture", "et"):
                if k in mts:
                    ts[k] = mts[k]
        ra.feed_time_series(ts, {"field": name})
        ra.run()
        self.tokens.record("reasoning_agent", fields=len(ts), steps=4,
                           factor=MODEL_FACTORS.get(self.model, 120))
        decision = ra.state.get("decision_output", {})
        assessment = decision.get("assessment", {}).get("status", "unknown")
        confidence = decision.get("final_confidence", 0)
        recs = decision.get("recommendations", [])
        self._log(f"  |-> reason:  {assessment} (conf={confidence:.3f})  "
                  f"{len(recs)} recs")

        # Step 5: Memory store
        summary = (f"Field: {name} | Climate: {field['climate']} | "
                   f"Crop: {field['crop']} | Region: {field['region']} | "
                   f"NDVI={ndvi_mu:.3f} | NPMI={npmi_mu:.3f} | "
                   f"LAI_peak={lai_p:.2f} | ET_total={et_t:.0f}mm | "
                   f"SM_mean={sm_m:.1f}mm | Stress_days={stress} | "
                   f"Assessment={assessment} | Confidence={confidence:.2f}")
        self.memory.add_memory(content=summary, memory_type="task_result",
                               importance=0.65,
                               metadata={"field": name, "climate": field["climate"]})
        for rec in recs[:1]:
            self.memory.add_memory(
                content=f"[{name}] {rec['action']} ({rec['rationale']})",
                memory_type="decision", importance=0.55,
            )
        self._log(f"  |-> memory:  results stored ({self.memory.size} total)")

        # Assemble field report
        elapsed = time.time() - t0
        self._step_times.append(elapsed)
        self.results[name] = {
            "field":      name,
            "climate":    field["climate"],
            "crop":       field["crop"],
            "region":     field["region"],
            "plant_date": field["plant_date"],
            "days":       field["days"],
            "ndvi_mean":  round(ndvi_mu, 4),
            "npmi_mean":  round(npmi_mu, 4),
            "lai_peak":   round(lai_p, 2),
            "et_total":   round(et_t, 1),
            "sm_mean":    round(sm_m, 1),
            "stress":     stress,
            "assessment": assessment,
            "confidence": round(confidence, 3),
            "elapsed_s":  round(elapsed, 3),
        }
        return self.results[name]

    # -- Run batch ---------------------------------------------------------

    def run(self, consolidate_every=25):
        """
        Process all fields in sequence.

        Parameters
        ----------
        consolidate_every : int
            Run memory consolidation every N fields (0 = never).

        Returns
        -------
        dict  full batch report
        """
        self._log(f"Starting batch: {self.num_fields} fields, "
                  f"{len(CLIMATES)} climates, {len(REGIONS)} regions")

        t_start = time.time()

        for idx, field in enumerate(self.fields, 1):
            self._process_field(field, idx)

            # Periodic consolidation
            if consolidate_every and idx % consolidate_every == 0:
                merged = self.memory.consolidate(threshold=0.75)
                self._log(f"[BATCH] Consolidation at field {idx}: "
                          f"{merged} merges, {self.memory.size} entries")

        elapsed_total = time.time() - t_start

        # Final consolidation
        merged = self.memory.consolidate(threshold=0.75)
        decayed = self.memory.decay(max_age_days=365, importance_threshold=0.2)

        # Record coordinator token
        self.tokens.record("coordinator", fields=self.num_fields,
                           steps=self.num_fields,
                           factor=MODEL_FACTORS.get(self.model, 120))

        # Build report
        report = self._build_report(elapsed_total, merged, decayed)
        self._log(f"Batch complete: {self.num_fields} fields, "
                  f"{elapsed_total:.1f}s, {self.tokens.total} tokens")
        return report

    # -- Reporting ---------------------------------------------------------

    def _build_report(self, elapsed_total, merged, decayed):
        """Aggregate results across all fields."""
        # Climate breakdown
        by_climate = {}
        for r in self.results.values():
            c = r["climate"]
            by_climate.setdefault(c, []).append(r)

        climate_summary = {}
        for c, entries in by_climate.items():
            confs = [e["confidence"] for e in entries]
            climate_summary[c] = {
                "count":        len(entries),
                "mean_conf":    round(statistics.mean(confs), 3),
                "max_conf":     round(max(confs), 3),
                "min_conf":     round(min(confs), 3),
            }

        # Field timing
        times = self._step_times
        mem_stats = self.memory.stats()

        return {
            "agent":          "batch_pipeline",
            "model":          self.model,
            "num_fields":     self.num_fields,
            "total_time_s":   round(elapsed_total, 1),
            "mean_field_s":   round(statistics.mean(times), 3) if times else 0,
            "total_fields_completed": len(self.results),
            "token_usage": {
                "total":    self.tokens.total,
                "calls":    self.tokens.count,
                "per_agent": self.tokens.per_agent(),
            },
            "memory": {
                "final_size":    mem_stats["size"],
                "by_type":       mem_stats["by_type"],
                "merges":        merged,
                "decay_removed": decayed["removed"],
                "decay_demoted": decayed["demoted"],
            },
            "climate_summary":  climate_summary,
            "avg_confidence":   round(statistics.mean(
                [r["confidence"] for r in self.results.values()]), 3),
            "assessments":      {r["field"]: r["assessment"]
                                 for r in self.results.values()},
            "fields":           [
                {k: v for k, v in r.items() if k != "elapsed_s"}
                for r in self.results.values()
            ],
        }

    def print_summary(self):
        """Print a condensed summary to console."""
        report = self._build_report(
            sum(self._step_times),
            self.memory.size,
            {"removed": 0, "demoted": 0},
        )

        print(f"\n{'=' * 60}")
        print(f"  Batch Pipeline Summary")
        print(f"{'=' * 60}")
        print(f"  Fields:      {report['num_fields']}")
        print(f"  Time:        {report['total_time_s']:.1f}s "
              f"({report['mean_field_s']:.2f}s/field)")
        print(f"  Tokens:      {report['token_usage']['total']} "
              f"({report['token_usage']['calls']} calls)")
        print(f"  Avg conf:    {report['avg_confidence']:.3f}")
        print(f"  Memory:      {report['memory']['final_size']} entries "
              f"(merges={report['memory']['merges']})")
        print(f"\n  Climate breakdown:")
        for c, s in report["climate_summary"].items():
            print(f"    {c:<12} {s['count']:>3} fields  "
                  f"conf: mean={s['mean_conf']:.3f}  "
                  f"range=[{s['min_conf']:.3f}, {s['max_conf']:.3f}]")

        print(f"\n  Token breakdown:")
        for agent, t in sorted(report["token_usage"]["per_agent"].items()):
            print(f"    {agent:<18} {t}")

        print(f"\n  Assessment distribution:")
        ass_counts = {}
        for a in report["assessments"].values():
            ass_counts[a] = ass_counts.get(a, 0) + 1
        for a, c in sorted(ass_counts.items()):
            print(f"    {a:<12} {c} fields ({c/report['num_fields']*100:.0f}%)")

        print(f"\n  Top 5 fields (by confidence):")
        ranked = sorted(report["fields"],
                        key=lambda x: x["confidence"], reverse=True)[:5]
        for r in ranked:
            print(f"    {r['field']:<12} conf={r['confidence']:.3f}  "
                  f"{r['assessment']:<8}  {r['climate']:<10}  "
                  f"LAI={r['lai_peak']:<5}  ET={r['et_total']}mm")

        print(f"{'=' * 60}\n")

    def to_dict(self):
        """Full serialisation."""
        return {
            "report": self._build_report(
                sum(self._step_times), 0, {"removed": 0, "demoted": 0}
            ),
            "logs": self._logs,
        }
