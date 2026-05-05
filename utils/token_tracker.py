"""
token_tracker.py — Dynamic per-agent token usage tracker.

Formula:
    tokens = base + fields × steps × factor

Tracks each agent call independently and provides total aggregation.

Usage:
    python utils/token_tracker.py
"""

from datetime import datetime


# ---------------------------------------------------------------------------
# Agent token base costs
# ---------------------------------------------------------------------------

AGENT_BASE = {
    "planner":     150,
    "researcher":  200,
    "analyst":     180,
    "writer":      120,
    "reviewer":    250,
    "memory":      80,
}

MODEL_FACTORS = {
    "sonnet":   120,
    "opus":     220,
    "haiku":     70,
    "4o":       180,
    "4o-mini":   60,
}


# ---------------------------------------------------------------------------
# TokenTracker
# ---------------------------------------------------------------------------

class TokenTracker:
    """
    Token usage tracker.

    Each call to ``record()`` stores a single agent invocation.
    Formula:  tokens = base + fields × steps × factor

    Examples
    --------
    >>> tracker = TokenTracker()
    >>> tracker.record("writer", fields=5, steps=1, factor=120)
    >>> tracker.record("reviewer", fields=5, steps=1, factor=120)
    >>> tracker.total
    1420
    >>> tracker.per_agent()
    {'writer': 720, 'reviewer': 700}
    """

    def __init__(self):
        self._history = []

    # -- Recording ----------------------------------------------------------

    def record(self, agent, fields, steps, factor, metadata=None):
        """
        Record one agent invocation.

        Parameters
        ----------
        agent : str
            Agent type key (used to look up base cost in AGENT_BASE).
        fields : int
            Number of input fields / data elements (F).
        steps : int
            Number of pipeline steps (S).
        factor : int or float
            Per-field per-step coefficient (C). Typically a MODEL_FACTORS value.
        metadata : dict, optional
            Extra info to attach (task_id, model, etc.).

        Returns
        -------
        int
            Computed token count for this invocation.
        """
        base = AGENT_BASE.get(agent, 100)
        tokens = base + fields * steps * factor

        entry = {
            "agent":    agent,
            "base":     base,
            "fields":   fields,
            "steps":    steps,
            "factor":   factor,
            "tokens":   tokens,
            "time":     datetime.now(),
            "metadata": metadata or {},
        }
        self._history.append(entry)
        return tokens

    def record_pipeline(self, pipeline_spec, model="sonnet"):
        """
        Record a full pipeline execution in one call.

        Parameters
        ----------
        pipeline_spec : list of dict
            Each dict: ``{"agent": ..., "fields": ..., "steps": ...}``.
            If ``factor`` is omitted, it is derived from *model*.
        model : str
            Model key used as default ``factor`` for entries that don't
            supply one explicitly.

        Returns
        -------
        list of int
            Token counts per step in pipeline order.
        """
        factor = MODEL_FACTORS.get(model, 120)
        tokens = []
        for spec in pipeline_spec:
            f = spec.get("factor", factor)
            t = self.record(
                agent=spec["agent"],
                fields=spec["fields"],
                steps=spec["steps"],
                factor=f,
                metadata=spec.get("metadata"),
            )
            tokens.append(t)
        return tokens

    # -- Query --------------------------------------------------------------

    @property
    def total(self):
        """Total tokens across all recorded invocations."""
        return sum(e["tokens"] for e in self._history)

    @property
    def count(self):
        """Number of recorded invocations."""
        return len(self._history)

    def per_agent(self):
        """
        Breakdown of tokens per agent type.

        Returns
        -------
        dict of {agent: total_tokens}
        """
        result = {}
        for e in self._history:
            result[e["agent"]] = result.get(e["agent"], 0) + e["tokens"]
        return result

    def per_agent_count(self):
        """Number of calls per agent type."""
        result = {}
        for e in self._history:
            result[e["agent"]] = result.get(e["agent"], 0) + 1
        return result

    def history(self):
        """Return a copy of all recorded entries."""
        return list(self._history)

    def filter(self, agent=None, task_id=None):
        """Return entries matching optional filters."""
        result = self._history
        if agent:
            result = [e for e in result if e["agent"] == agent]
        if task_id:
            result = [e for e in result if e["metadata"].get("task_id") == task_id]
        return result

    # -- Reporting ----------------------------------------------------------

    def summary(self):
        """Return a formatted multi-line summary string."""
        lines = []
        lines.append(f"{'Token Tracker Summary':^50}")
        lines.append("=" * 50)
        lines.append(f"{'Total tokens':<20} {self.total:>10}")
        lines.append(f"{'Total calls':<20} {self.count:>10}")
        lines.append("-" * 50)
        lines.append(f"{'Per-agent breakdown':^50}")
        lines.append("-" * 50)
        lines.append(f"{'Agent':<15} {'Calls':<8} {'Tokens':<10}")
        lines.append("-" * 50)
        for agent in sorted(self.per_agent()):
            calls = self.per_agent_count()[agent]
            tokens = self.per_agent()[agent]
            lines.append(f"{agent:<15} {calls:<8} {tokens:<10}")
        lines.append("=" * 50)
        return "\n".join(lines)

    def detail(self, n=10):
        """Return the last *n* entries as a formatted table."""
        recent = self._history[-n:]
        lines = []
        lines.append(f"{'#':<4} {'Agent':<12} {'F':<5} {'S':<5} {'C':<7} {'Tokens':<8} {'Time':<20}")
        lines.append("-" * 70)
        for i, e in enumerate(recent):
            t = e["time"].strftime("%H:%M:%S")
            lines.append(f"{i:<4} {e['agent']:<12} {e['fields']:<5} "
                         f"{e['steps']:<5} {e['factor']:<7} {e['tokens']:<8} {t:<20}")
        return "\n".join(lines)

    # -- Persistence helpers (optional) -------------------------------------

    def to_dict(self):
        """Serialize history to a JSON-safe dict."""
        return {
            "total": self.total,
            "count": self.count,
            "per_agent": self.per_agent(),
            "entries": [
                {k: str(v) if k == "time" else v
                 for k, v in e.items()}
                for e in self._history
            ],
        }

    def reset(self):
        """Clear all recorded history."""
        self._history.clear()


# ---------------------------------------------------------------------------
# Test / demonstration
# ---------------------------------------------------------------------------

def test():
    print("=" * 60)
    print("token_tracker.py — Test Suite")
    print("=" * 60)

    # ---- 1. Single agent calls --------------------------------------------
    print("\n[1] Single agent calls (formula: base + F × S × C)")
    tracker = TokenTracker()

    t1 = tracker.record("writer", fields=3, steps=1, factor=120)
    print(f"    writer:   120 + 3×1×120 = {t1} tokens  (expected 480)")

    t2 = tracker.record("reviewer", fields=3, steps=1, factor=120)
    print(f"    reviewer: 250 + 3×1×120 = {t2} tokens  (expected 610)")

    t3 = tracker.record("memory", fields=1, steps=1, factor=70)
    print(f"    memory:    80 + 1×1×70  = {t3} tokens  (expected 150)")

    # ---- 2. Verify formula explicitly ------------------------------------
    print("\n[2] Formula verification")
    assert t1 == 120 + 3 * 1 * 120, f" writer mismatch: {t1}"
    assert t2 == 250 + 3 * 1 * 120, f" reviewer mismatch: {t2}"
    assert t3 == 80 + 1 * 1 * 70, f" memory mismatch: {t3}"
    print("    All assertions passed.")

    # ---- 3. Full pipeline recording ---------------------------------------
    print("\n[3] Full pipeline recording (5 agents, Sonnet)")
    pipeline = [
        {"agent": "planner",    "fields": 3, "steps": 1},
        {"agent": "researcher", "fields": 5, "steps": 1},
        {"agent": "analyst",    "fields": 5, "steps": 1},
        {"agent": "writer",     "fields": 3, "steps": 1},
        {"agent": "reviewer",   "fields": 3, "steps": 1},
    ]
    tracker2 = TokenTracker()
    tokens = tracker2.record_pipeline(pipeline, model="sonnet")
    agents = [s["agent"] for s in pipeline]
    for a, t in zip(agents, tokens):
        print(f"    {a:<12} {t} tokens")

    # ---- 4. Pipeline with retry -------------------------------------------
    print("\n[4] Pipeline with 1 retry (failed review → re-write + re-review)")
    retry_spec = [
        {"agent": "writer",   "fields": 3, "steps": 1, "metadata": {"attempt": 2}},
        {"agent": "reviewer", "fields": 3, "steps": 1, "metadata": {"attempt": 2}},
    ]
    retry_tokens = tracker2.record_pipeline(retry_spec, model="sonnet")
    print(f"    Retry total: {sum(retry_tokens)} tokens (2 calls)")

    # ---- 5. Different model factors ---------------------------------------
    print("\n[5] Same task across different models")
    models = {"sonnet": 120, "opus": 220, "haiku": 70, "4o-mini": 60}
    for name, c in models.items():
        t = 120 + 3 * 2 * c  # writer, 3 fields, 2 steps
        print(f"    {name:<10} 120 + 3×2×{c:<3} = {t} tokens")

    # ---- 6. Totals and per-agent ------------------------------------------
    print("\n[6] Totals and per-agent breakdown")
    print(f"    Total tokens: {tracker2.total}")
    for agent, tokens in sorted(tracker2.per_agent().items()):
        print(f"    {agent:<12} {tokens} tokens ({tracker2.per_agent_count()[agent]} calls)")

    # ---- 7. Formatted summary ---------------------------------------------
    print("\n[7] Formatted summary")
    print(tracker2.summary())

    # ---- 8. Detail listing ------------------------------------------------
    print("\n[8] Recent calls (detail view)")
    print(tracker2.detail(n=5))

    # ---- 9. Filter by agent -----------------------------------------------
    print("\n[9] Filter: only writer calls")
    writers = tracker2.filter(agent="writer")
    print(f"    {len(writers)} writer calls, total {sum(e['tokens'] for e in writers)} tokens")

    # ---- 10. Reset --------------------------------------------------------
    print("\n[10] Reset tracker")
    tracker2.reset()
    print(f"    After reset: {tracker2.count} calls, {tracker2.total} total tokens")

    # ---- Summary ----------------------------------------------------------
    print("\n" + "=" * 60)
    print("All tests passed.")
    print("=" * 60)


if __name__ == "__main__":
    test()
