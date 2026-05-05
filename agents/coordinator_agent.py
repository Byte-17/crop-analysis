"""
agents/coordinator_agent.py — Top-level orchestrator.

Loops over multiple fields and, for each field, runs:
  1. Memory retrieval (past insights)
  2. DataAgent        (NDVI / NPMI time series)
  3. ModelAgent       (LAI / soil-moisture / ET simulation)
  4. ReasoningAgent   (anomaly → trend → causality → decision)
  5. Memory storage   (save results for future fields)

After all fields are processed, produces a cross-field comparison report.

Usage:
    python agents/coordinator_agent.py
"""

import logging
import os
import sys
from datetime import datetime

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from agents.data_agent import DataAgent
from agents.model_agent import ModelAgent
from agents.reasoning_agent import ReasoningAgent
from memory.memory_system import MemorySystem
from utils.token_tracker import TokenTracker, MODEL_FACTORS


# ---------------------------------------------------------------------------
# Field definition
# ---------------------------------------------------------------------------

FIELD_DEFAULTS = {
    "climate":      "temperate",
    "plant_date":   "2024-04-01",
    "days":         120,
    "region":       "default",
}


def _make_fields():
    """Return a list of field config dicts for demonstration."""
    return [
        {"name": "Field-A (Temperate Maize)",   "climate": "temperate", "plant_date": "2024-04-01", "days": 120, "region": "NA"},
        {"name": "Field-B (Tropical Rice)",      "climate": "tropical",  "plant_date": "2024-04-01", "days": 120, "region": "SEA"},
        {"name": "Field-C (Dry Wheat)",          "climate": "dry",       "plant_date": "2024-04-01", "days": 120, "region": "AU"},
        {"name": "Field-D (Temperate Soy, Late)", "climate": "temperate","plant_date": "2024-06-01", "days": 90,  "region": "NA"},
    ]


# ---------------------------------------------------------------------------
# CoordinatorAgent
# ---------------------------------------------------------------------------

class CoordinatorAgent:
    """
    Orchestrates the full multi-agent pipeline across multiple fields.

    Flow per field:
      memory_retrieve → data_agent → model_agent → reasoning_agent → memory_store

    After loop:
      cross-field comparison report
    """

    def __init__(self, fields=None, model="sonnet"):
        self.fields = fields or _make_fields()
        self.model = model
        self.memory = MemorySystem()
        self.tokens = TokenTracker()
        self.results = {}       # field_name → per-field report
        self._logs = []

        self._log(f"CoordinatorAgent initialized: {len(self.fields)} fields, "
                  f"model={model}")

    # -- Logging -----------------------------------------------------------

    def _log(self, message):
        entry = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        self._logs.append(entry)
        logging.info("Coordinator: %s", message)

    def print_logs(self):
        print(f"\n{'─' * 60}")
        print("  Coordinator Logs")
        print(f"{'─' * 60}")
        for entry in self._logs:
            print(f"  {entry}")
        print(f"{'─' * 60}")

    # -- Per-field pipeline ------------------------------------------------

    def _process_field(self, field):
        """
        Run the full pipeline for a single field.

        Steps
        -----
        1. Memory retrieve — pull past insights relevant to this field
        2. DataAgent      — compute NDVI and NPMI time series
        3. ModelAgent     — simulate LAI, soil moisture, ET
        4. ReasoningAgent — anomaly → trend → causality → decision
        5. Memory store   — persist results for cross-field reuse
        """
        name = field["name"]
        self._log(f"{'=' * 50}")
        self._log(f"Processing: {name}")

        # -- Step 1: Memory retrieval --------------------------------------
        self._log(f"  [1/5] Memory retrieve: context for '{name}'")
        context = self.memory.search(
            f"field {name} crop simulation",
            top_k=3,
            min_score=0.35,
        )
        self._log(f"        Found {len(context)} relevant past memories")
        for score, mem in context:
            self._log(f"          ({score:.3f}) {mem.content[:60]}")

        # Track token cost for this step
        self.tokens.record("memory", fields=len(self.fields), steps=1,
                           factor=MODEL_FACTORS.get(self.model, 120))

        # -- Step 2: DataAgent (remote sensing) ----------------------------
        self._log(f"  [2/5] DataAgent: NDVI / NPMI time series")
        da = DataAgent()
        ndvi = da.compute_ndvi()
        npmi = da.compute_npmi()
        ndvi_mean = sum(v for _, v in ndvi) / len(ndvi) if ndvi else 0
        npmi_mean = sum(v for _, v in npmi) / len(npmi) if npmi else 0
        self._log(f"        NDVI mean={ndvi_mean:.4f}, NPMI mean={npmi_mean:.4f}")

        self.tokens.record("data_agent", fields=2, steps=1,
                           factor=MODEL_FACTORS.get(self.model, 120))

        # -- Step 3: ModelAgent (crop simulation) --------------------------
        self._log(f"  [3/5] ModelAgent: {field.get('climate')} crop simulation, "
                  f"{field['days']} days")
        ma = ModelAgent(climate=field.get("climate", "temperate"))
        sim = ma.run_simulation(field["plant_date"], field["days"])

        lai_peak = sim.get("lai", {}).get("peak", 0)
        et_total = sim.get("et", {}).get("total", 0)
        sm_mean  = sim.get("soil_moisture", {}).get("mean", 0)
        stress   = sim.get("water_balance", {}).get("water_stress_days", 0)
        self._log(f"        LAI peak={lai_peak:.2f}, ET total={et_total:.0f}mm, "
                  f"stress={stress}d")

        self.tokens.record("model_agent", fields=3, steps=field["days"],
                           factor=1)

        # -- Step 4: ReasoningAgent (analysis) -----------------------------
        self._log(f"  [4/5] ReasoningAgent: multi-step analysis")
        ra = ReasoningAgent()

        # Build time-series dict from data + model outputs
        ts = {}
        ts["ndvi"] = ndvi
        ts["npmi"] = npmi
        if ma.model:
            model_ts = ma.model.get_time_series()
            for k in ("lai", "soil_moisture", "et"):
                if k in model_ts:
                    ts[k] = model_ts[k]

        ra.feed_time_series(ts, {"field": name, "source": "coordinator"})
        ra.run()

        decision = ra.state.get("decision_output", {})
        assessment = decision.get("assessment", {}).get("status", "unknown")
        confidence = decision.get("final_confidence", 0)
        recommendations = decision.get("recommendations", [])
        self._log(f"        Assessment: {assessment}, confidence={confidence:.3f}")

        self.tokens.record("reasoning_agent", fields=len(ts), steps=4,
                           factor=MODEL_FACTORS.get(self.model, 120))

        # -- Step 5: Memory store ------------------------------------------
        self._log(f"  [5/5] Memory store: saving results for {name}")
        summary_parts = [
            f"Field: {name}",
            f"Climate: {field.get('climate')}",
            f"NDVI_mean={ndvi_mean:.3f}",
            f"NPMI_mean={npmi_mean:.3f}",
            f"LAI_peak={lai_peak:.2f}",
            f"ET_total={et_total:.0f}mm",
            f"Soil_moisture_mean={sm_mean:.1f}mm",
            f"Stress_days={stress}",
            f"Assessment={assessment}",
            f"Confidence={confidence:.2f}",
        ]
        summary = " | ".join(summary_parts)

        self.memory.add_memory(
            content=summary,
            memory_type="task_result",
            importance=0.7,
            metadata={
                "field": name,
                "climate": field.get("climate"),
                "assessment": assessment,
                "confidence": confidence,
            },
        )

        # Also store key decisions as separate memories
        for rec in recommendations[:2]:
            self.memory.add_memory(
                content=f"[{name}] {rec['action']} ({rec['rationale']})",
                memory_type="decision",
                importance=0.6,
                metadata={"field": name, "priority": rec["priority"]},
            )

        # -- Assemble per-field report -------------------------------------
        field_report = {
            "field":         name,
            "climate":       field.get("climate"),
            "plant_date":    field["plant_date"],
            "sim_days":      field["days"],
            "region":        field.get("region", "unknown"),
            "ndvi":          {"mean": round(ndvi_mean, 4), "points": len(ndvi)},
            "npmi":          {"mean": round(npmi_mean, 4), "points": len(npmi)},
            "simulation":    sim,
            "reasoning": {
                "assessment":   assessment,
                "confidence":   confidence,
                "recommendations": [
                    {"priority": r["priority"], "action": r["action"]}
                    for r in recommendations
                ],
            },
            "memories_retrieved": len(context),
        }
        self.results[name] = field_report
        self._log(f"  => {name} complete")
        return field_report

    # -- Run all fields ----------------------------------------------------

    def run_all(self):
        """Loop over all fields and run the pipeline for each."""
        self._log(f"Starting run: {len(self.fields)} fields")

        for idx, field in enumerate(self.fields, 1):
            self._log(f"\n--- Field {idx}/{len(self.fields)} ---")
            self._process_field(field)

        self._log(f"\nAll {len(self.fields)} fields processed")

        # Final token recording
        self.tokens.record("coordinator", fields=len(self.fields),
                           steps=len(self.fields),
                           factor=MODEL_FACTORS.get(self.model, 120))

        # Consolidate memory after all fields
        merged = self.memory.consolidate(threshold=0.75)
        self._log(f"Memory consolidation: {merged} merges")

        return self.results

    # -- Cross-field comparison --------------------------------------------

    def comparison_report(self):
        """Produce a side-by-side comparison across all fields."""
        if not self.results:
            return {"error": "no results"}

        rows = []
        for name, r in self.results.items():
            sim = r.get("simulation", {})
            rows.append({
                "field":         name,
                "climate":       r["climate"],
                "region":        r["region"],
                "ndvi_mean":     r["ndvi"]["mean"],
                "npmi_mean":     r["npmi"]["mean"],
                "lai_peak":      sim.get("lai", {}).get("peak", "N/A"),
                "et_total":      sim.get("et", {}).get("total", "N/A"),
                "sm_mean":       sim.get("soil_moisture", {}).get("mean", "N/A"),
                "stress_days":   sim.get("water_balance", {}).get("water_stress_days", "N/A"),
                "assessment":    r["reasoning"]["assessment"],
                "confidence":    r["reasoning"]["confidence"],
            })

        # Rank by confidence
        rows.sort(key=lambda x: x["confidence"] if isinstance(x["confidence"], (int, float)) else 0,
                  reverse=True)

        return {
            "field_count":   len(rows),
            "top_field":     rows[0]["field"] if rows else None,
            "assessments":   {r["field"]: r["assessment"] for r in rows},
            "ranked_fields": rows,
        }

    # -- Reporting ---------------------------------------------------------

    def summary_report(self):
        """Full coordinator report."""
        comp = self.comparison_report()
        mem_stats = self.memory.stats()

        return {
            "agent":            "coordinator_agent",
            "model":            self.model,
            "fields_processed": len(self.results),
            "total_fields":     len(self.fields),
            "comparison":       comp,
            "memory":           mem_stats,
            "token_usage": {
                "total": self.tokens.total,
                "calls": self.tokens.count,
            },
            "log_count":        len(self._logs),
        }

    def print_comparison(self):
        """Print a formatted comparison table."""
        comp = self.comparison_report()
        rows = comp["ranked_fields"]

        print(f"\n{'=' * 100}")
        print(f"  Cross-Field Comparison  ({len(rows)} fields)")
        print(f"{'=' * 100}")
        header = f"  {'Field':<28} {'Climate':<12} {'NDVI':<8} {'LAI':<8} {'ET':<8} {'SM':<8} {'Stress':<8} {'Assessment':<12} {'Conf':<6}"
        print(header)
        print(f"  {'─' * 96}")
        for r in rows:
            ndvi = r["ndvi_mean"]
            lai  = r["lai_peak"]
            et   = r["et_total"]
            sm   = r["sm_mean"]
            stress = r["stress_days"]
            ass = r["assessment"]
            conf = r["confidence"]
            print(f"  {r['field']:<28} {r['climate']:<12} "
                  f"{ndvi:<8.4f} "
                  f"{lai:<8} {et:<8} {sm:<8} {stress:<8} "
                  f"{ass:<12} {conf:<6.3f}")
        print(f"{'=' * 100}\n")

    def print_token_report(self):
        """Print per-agent and total token usage."""
        print(f"{'─' * 50}")
        print("  Token Usage Summary")
        print(f"{'─' * 50}")
        for agent, tokens in sorted(self.tokens.per_agent().items()):
            calls = self.tokens.per_agent_count()[agent]
            print(f"  {agent:<18} {calls} calls, {tokens} tokens")
        print(f"  {'─' * 40}")
        print(f"  {'TOTAL':<18} {self.tokens.total} tokens ({self.tokens.count} calls)")
        print(f"{'─' * 50}")

    def print_memory_stats(self):
        """Print memory system statistics."""
        stats = self.memory.stats()
        print(f"{'─' * 50}")
        print("  Memory System Stats")
        print(f"{'─' * 50}")
        print(f"  Entries:     {stats['size']}")
        print(f"  By type:     {stats['by_type']}")
        print(f"  Mean imp:    {stats['importance_mean']}")
        print(f"  Mean access: {stats['access_mean']}")

    def to_dict(self):
        """Serialize for data-flow transport."""
        return {
            "data": self.summary_report(),
            "comparison": self.comparison_report(),
            "field_results": self.results,
            "logs": self._logs,
        }


# ---------------------------------------------------------------------------
# Test / demonstration
# ---------------------------------------------------------------------------

def test():
    print("=" * 60)
    print("  CoordinatorAgent — Test Suite")
    print("=" * 60)

    # ---- 1. Initialize with 4 fields -------------------------------------
    print("\n[1] Initialize coordinator with 4 fields")
    fields = _make_fields()
    coord = CoordinatorAgent(fields=fields, model="sonnet")
    print(f"    Fields:")
    for f in fields:
        print(f"      {f['name']:<30} climate={f['climate']:<12} "
              f"plant={f['plant_date']}  days={f['days']}")
    print(f"    Model: {coord.model}")

    # ---- 2. Run all fields -----------------------------------------------
    print("\n[2] Run pipeline across all fields")
    results = coord.run_all()
    print(f"\n    Fields completed: {len(results)}")
    for name, r in results.items():
        print(f"      {name:<30}  "
              f"assessment={r['reasoning']['assessment']:<8}  "
              f"confidence={r['reasoning']['confidence']:.3f}")

    # ---- 3. Cross-field comparison ---------------------------------------
    print("\n[3] Cross-field comparison")
    coord.print_comparison()

    # ---- 4. Verify comparison ranking ------------------------------------
    comp = coord.comparison_report()
    print(f"    Top-ranked field: {comp['top_field']}")
    print(f"    Assessments:      {comp['assessments']}")
    assert len(comp["ranked_fields"]) == len(fields), \
        f"Expected {len(fields)} rows, got {len(comp['ranked_fields'])}"

    # ---- 5. Token tracking across fields ---------------------------------
    print("\n[5] Token usage across all agents")
    coord.print_token_report()

    # ---- 6. Memory system state after all fields -------------------------
    print("\n[6] Memory system after run")
    coord.print_memory_stats()
    print(f"\n    Recent memories:")
    for m in coord.memory.list_memories(sort_by="created_at", limit=4):
        print(f"      [{m['type']:<12}] imp={m['importance']:.2f}  {m['content'][:60]}")

    # ---- 7. Search memory for a specific field ---------------------------
    print("\n[7] Memory retrieval: 'Field-A results'")
    hits = coord.memory.search("Field-A Temperate Maize", top_k=3)
    for score, entry in hits:
        print(f"    ({score:.4f}) [{entry.memory_type:<12}] {entry.content[:70]}")

    # ---- 8. Verify cross-field insight propagation -----------------------
    print("\n[8] Cross-field insight propagation")
    # The last field should have more context memories than the first
    first_name = fields[0]["name"]
    last_name  = fields[-1]["name"]
    first_mems = coord.results[first_name]["memories_retrieved"]
    last_mems  = coord.results[last_name]["memories_retrieved"]
    print(f"    {first_name}: {first_mems} memories retrieved")
    print(f"    {last_name}:  {last_mems} memories retrieved")
    # Later fields benefit from earlier fields' stored memories
    print(f"    => Cross-field memory propagation {'active' if last_mems >= first_mems else 'limited'}")

    # ---- 9. Sequential vs. parallel considerations -----------------------
    print("\n[9] Pipeline execution order")
    field_names = [r["field"] for r in comp["ranked_fields"]]
    print(f"    Processing order: {[f['name'] for f in fields]}")
    print(f"    Confidence rank:  {field_names}")
    for i, f in enumerate(fields):
        r = results[f["name"]]
        print(f"    {i+1}. {f['name']:<30} → {r['reasoning']['assessment']} "
              f"(conf={r['reasoning']['confidence']:.3f})")

    # ---- 10. Summary report ----------------------------------------------
    print("\n[10] Coordinator summary report")
    report = coord.summary_report()
    print(f"    Agent:              {report['agent']}")
    print(f"    Fields processed:   {report['fields_processed']}")
    print(f"    Memory entries:     {report['memory']['size']}")
    print(f"    Token total:        {report['token_usage']['total']}")
    print(f"    Token calls:        {report['token_usage']['calls']}")
    print(f"    Log entries:        {report['log_count']}")
    print(f"    Top field:          {report['comparison']['top_field']}")

    # ---- 11. Data-flow serialisation -------------------------------------
    print("\n[11] Data-flow payload (to_dict)")
    payload = coord.to_dict()
    print(f"    Top-level keys: {list(payload.keys())}")
    print(f"    Field results:  {len(payload['field_results'])}")
    print(f"    Log entries:    {len(payload['logs'])}")

    # ---- 12. Processing logs ---------------------------------------------
    print("\n[12] Full coordinator logs (last 6)")
    for entry in coord._logs[-6:]:
        print(f"    {entry}")

    # ---- Summary ---------------------------------------------------------
    print("\n" + "=" * 60)
    print("  All tests passed.")
    print("=" * 60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    test()
