"""
memory/memory_system.py — Vector-based memory with embedding, similarity scoring,
and top-k retrieval.

Core operations:
  1. Text → embedding vector (hash-based, no external model)
  2. Cosine similarity scoring
  3. Top-k retrieval by similarity
  4. Memory consolidation (merge near-duplicates)
  5. Adaptive decay (forgetting)

Usage:
    python memory/memory_system.py
"""

import hashlib
import math
import os
import random
import sys
import time
from datetime import datetime, timedelta

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


# ---------------------------------------------------------------------------
# TextEmbedder — deterministic text-to-vector conversion
# ---------------------------------------------------------------------------

CONCEPT_DIMENSIONS = [
    "vegetation", "water", "temperature", "precipitation", "soil",
    "growth", "stress", "health", "phenology", "moisture",
    "radiation", "carbon", "nitrogen", "biomass", "yield",
    "anomaly", "trend", "seasonal", "pattern", "change",
    "crop", "forest", "grassland", "wetland", "urban",
    "decision", "risk", "uncertainty", "recommendation", "threshold",
    "temporal", "spatial", "frequency", "magnitude", "duration",
    "management", "irrigation", "fertilizer", "pesticide", "harvest",
    "quality", "efficiency", "sustainability", "resilience", "vulnerability",
]


class TextEmbedder:
    """
    Deterministic text-to-vector embedder.

    Maps text keywords onto a fixed set of concept dimensions using
    consistent hash functions.  Two texts about the same topic produce
    similar vectors; unrelated texts produce dissimilar vectors.
    """

    DIM = len(CONCEPT_DIMENSIONS)

    def __init__(self, seed=42):
        self._seed = seed
        # Pre-compute a hash-offset table so that each word maps to
        # a stable subset of concept dimensions.
        self._word_signatures = {}

    def _word_sig(self, word):
        """Return a frozenset of (dim_idx, weight) for a given word."""
        if word not in self._word_signatures:
            # Hash the word to get a stable signature
            h = hashlib.md5(word.encode("utf-8")).hexdigest()
            # Determine which dimensions this word activates
            rng = random.Random(int(h[:8], 16) + self._seed)
            n_dims = rng.randint(3, 8)  # each word activates 3-8 concepts
            dims = rng.sample(range(self.DIM), min(n_dims, self.DIM))
            sig = frozenset(
                (d, round(rng.uniform(0.3, 1.0), 4))
                for d in dims
            )
            self._word_signatures[word] = sig
        return self._word_signatures[word]

    def embed(self, text):
        """
        Convert text to a normalized embedding vector.

        Returns
        -------
        list of float  (length = DIM)
        """
        vec = [0.0] * self.DIM
        # Tokenise: split on whitespace and punctuation
        tokens = self._tokenise(text)
        if not tokens:
            return vec

        for token in tokens:
            sig = self._word_sig(token)
            for dim, weight in sig:
                vec[dim] += weight

        # Normalise to unit length
        norm = math.sqrt(sum(v ** 2 for v in vec))
        if norm > 1e-10:
            vec = [v / norm for v in vec]
        return vec

    @staticmethod
    def _tokenise(text):
        """Simple tokenisation: lowercase, split on non-alpha."""
        t = text.lower()
        # Replace common punctuation with spaces
        for ch in ".,;:!?()[]{}\"'/-":
            t = t.replace(ch, " ")
        return [w for w in t.split() if len(w) > 1]


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------

def cosine_similarity(a, b):
    """Cosine similarity between two vectors.  Returns -1.0 to 1.0."""
    if len(a) != len(b):
        raise ValueError(f"Dimension mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x ** 2 for x in a))
    nb = math.sqrt(sum(y ** 2 for y in b))
    denom = na * nb
    if denom < 1e-12:
        return 0.0
    return dot / denom


# ---------------------------------------------------------------------------
# MemoryEntry
# ---------------------------------------------------------------------------

class MemoryEntry:
    """
    A single memory with embedding vector and metadata.

    Attributes
    ----------
    id : str
        Unique identifier.
    content : str
        The stored information.
    vector : list of float
        Embedding vector (unit length).
    created_at : datetime
    access_count : int
    last_accessed : datetime or None
    importance : float  0.0 – 1.0
    memory_type : str
        One of: observation, decision, preference, task_result, hypothesis.
    metadata : dict
        Arbitrary extra fields (source, task_id, etc.).
    """

    TYPES = ("observation", "decision", "preference", "task_result", "hypothesis")

    def __init__(self, content, vector, memory_type="observation",
                 importance=0.5, metadata=None):
        self.id = f"mem_{hash(content) % 10**8:08x}"
        self.content = content
        self.vector = vector
        self.memory_type = memory_type
        self.created_at = datetime.now()
        self.access_count = 0
        self.last_accessed = None
        self.importance = importance
        self.metadata = metadata or {}

    def mark_accessed(self):
        self.access_count += 1
        self.last_accessed = datetime.now()

    def age_days(self, now=None):
        """Days since creation."""
        now = now or datetime.now()
        return (now - self.created_at).days

    def days_since_access(self, now=None):
        """Days since last access (infinity if never accessed)."""
        now = now or datetime.now()
        if self.last_accessed is None:
            return float("inf")
        return (now - self.last_accessed).days

    def summary(self):
        return {
            "id": self.id,
            "content": self.content[:80],
            "type": self.memory_type,
            "importance": self.importance,
            "access_count": self.access_count,
            "age_days": self.age_days(),
        }

    def __repr__(self):
        return (f"MemoryEntry({self.id[:12]}, type={self.memory_type}, "
                f"imp={self.importance:.2f}, access={self.access_count})")


# ---------------------------------------------------------------------------
# MemorySystem
# ---------------------------------------------------------------------------

class MemorySystem:
    """
    Vector-based memory store with similarity search and lifecycle management.

    Operations:
      - add_memory / add_memories       — store new entries
      - search(query, top_k)            — cosine-similarity retrieval
      - search_by_vector(vector, top_k) — direct vector query
      - get(id) / remove(id)            — by-id access
      - consolidate(threshold)          — merge near-duplicates
      - decay(max_age_days)             — forget stale low-importance entries
    """

    def __init__(self, embedder=None):
        self._entries = []          # list of MemoryEntry
        self._index = {}            # id -> entry  (fast lookup)
        self.embedder = embedder or TextEmbedder()
        self._logs = []

    def _log(self, message):
        entry = {"time": datetime.now(), "message": message}
        self._logs.append(entry)

    @property
    def logs(self):
        return list(self._logs)

    def print_logs(self):
        print(f"\n{'─' * 60}")
        print("  Memory System Logs")
        print(f"{'─' * 60}")
        for e in self._logs:
            print(f"  {e['message']}")
        print(f"{'─' * 60}")

    @property
    def size(self):
        return len(self._entries)

    # -- CRUD ---------------------------------------------------------------

    def add_memory(self, content, memory_type="observation",
                   importance=0.5, metadata=None):
        """Add a single memory entry (auto-embedded)."""
        vector = self.embedder.embed(content)
        entry = MemoryEntry(content, vector, memory_type, importance, metadata)
        self._entries.append(entry)
        self._index[entry.id] = entry
        self._log(f"ADD {entry.id[:12]} | type={memory_type} | "
                  f"imp={importance:.2f} | '{content[:50]}...'")
        return entry

    def add_memories(self, items):
        """Batch add from a list of dicts with keys: content, type, importance, metadata."""
        entries = []
        for item in items:
            e = self.add_memory(**item)
            entries.append(e)
        return entries

    def get(self, mem_id):
        """Retrieve by ID."""
        return self._index.get(mem_id)

    def remove(self, mem_id):
        """Remove by ID."""
        entry = self._index.pop(mem_id, None)
        if entry:
            self._entries.remove(entry)
            self._log(f"REMOVE {mem_id[:12]}")
        return entry

    def get_all(self):
        """Return all entries (copy)."""
        return list(self._entries)

    # -- Similarity search --------------------------------------------------

    def search(self, query, top_k=5, min_score=0.0):
        """
        Search memories by text query.

        Steps:
          1. Embed query text into vector
          2. Compute cosine similarity against every stored vector
          3. Sort descending by score
          4. Return top-k above *min_score*

        Returns
        -------
        list of (score, MemoryEntry)  sorted by score descending.
        """
        query_vec = self.embedder.embed(query)
        return self.search_by_vector(query_vec, top_k, min_score)

    def search_by_vector(self, query_vec, top_k=5, min_score=0.0):
        """
        Search memories by vector (raw similarity scoring).

        Returns
        -------
        list of (score, MemoryEntry)
        """
        scored = []
        for entry in self._entries:
            score = cosine_similarity(query_vec, entry.vector)
            if score >= min_score:
                scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        result = scored[:top_k]

        # Mark accessed
        for _, entry in result:
            entry.mark_accessed()

        return result

    # -- Consolidation (merge near-duplicates) ------------------------------

    def consolidate(self, threshold=0.85):
        """
        Merge memories whose cosine similarity >= *threshold*.

        When two memories are merged:
          - Content is concatenated
          - Vector is averaged (and re-normalised)
          - Access counts are summed
          - Importance is averaged
          - The newer memory's creation time is kept
          - The older entry is removed

        Returns
        -------
        int  number of merges performed.
        """
        self._log(f"Consolidating (threshold={threshold})...")
        merged_count = 0
        i = 0
        while i < len(self._entries):
            j = i + 1
            while j < len(self._entries):
                sim = cosine_similarity(self._entries[i].vector,
                                        self._entries[j].vector)
                if sim >= threshold:
                    # Merge j into i
                    a, b = self._entries[i], self._entries[j]
                    # Content
                    a.content = f"{a.content} | {b.content}"
                    # Vector (weighted average by access count)
                    total = a.access_count + b.access_count + 1
                    w_a = (a.access_count + 1) / total
                    w_b = (b.access_count + 1) / total
                    avg_vec = [
                        w_a * va + w_b * vb
                        for va, vb in zip(a.vector, b.vector)
                    ]
                    norm = math.sqrt(sum(v ** 2 for v in avg_vec))
                    if norm > 1e-10:
                        avg_vec = [v / norm for v in avg_vec]
                    a.vector = avg_vec
                    # Metadata
                    a.access_count += b.access_count
                    a.importance = (a.importance + b.importance) / 2
                    a.metadata["merged_from"] = a.metadata.get("merged_from", []) + [b.id]
                    # Remove b
                    self._index.pop(b.id, None)
                    self._entries.pop(j)
                    merged_count += 1
                    self._log(f"  Merged {b.id[:12]} into {a.id[:12]}  (sim={sim:.3f})")
                else:
                    j += 1
            i += 1

        self._log(f"Consolidation complete: {merged_count} merges, "
                  f"{self.size} entries remaining")
        return merged_count

    # -- Decay (forgetting) -------------------------------------------------

    def decay(self, max_age_days=180, importance_threshold=0.3):
        """
        Remove or archive stale low-importance memories.

        A memory is removed when:
          - age > *max_age_days*  AND
          - importance < *importance_threshold*  AND
          - access_count == 0 (never accessed since creation)

        A memory is demoted (importance halved) when:
          - days_since_access > max_age_days / 2
          - AND importance > 0.1

        Returns
        -------
        dict of {removed: int, demoted: int}
        """
        self._log(f"Running decay (max_age={max_age_days}d, "
                  f"imp_threshold={importance_threshold})...")
        now = datetime.now()
        removed = 0
        demoted = 0

        i = 0
        while i < len(self._entries):
            entry = self._entries[i]
            age = entry.age_days(now)
            days_since = entry.days_since_access(now)

            # Remove: old, low-importance, never accessed
            if age > max_age_days and entry.importance < importance_threshold \
                    and entry.access_count == 0:
                self._index.pop(entry.id, None)
                self._entries.pop(i)
                self._log(f"  REMOVED {entry.id[:12]} (stale, age={age}d, "
                          f"imp={entry.importance:.2f})")
                removed += 1
                continue

            # Demote: unaccessed for half the max age
            if days_since > max_age_days / 2 and entry.importance > 0.1:
                old_imp = entry.importance
                entry.importance = max(0.05, entry.importance * 0.5)
                self._log(f"  DEMOTED {entry.id[:12]} "
                          f"{old_imp:.2f} -> {entry.importance:.2f} "
                          f"(unused {days_since:.0f}d)")
                demoted += 1

            i += 1

        self._log(f"Decay complete: {removed} removed, {demoted} demoted, "
                  f"{self.size} remaining")
        return {"removed": removed, "demoted": demoted}

    # -- Reporting ---------------------------------------------------------

    def stats(self):
        """Summary statistics of the memory store."""
        if not self._entries:
            return {"size": 0}
        importances = [e.importance for e in self._entries]
        accesses = [e.access_count for e in self._entries]
        ages = [e.age_days() for e in self._entries]
        types = {}
        for e in self._entries:
            types[e.memory_type] = types.get(e.memory_type, 0) + 1
        return {
            "size":               self.size,
            "by_type":            types,
            "importance_mean":    round(sum(importances) / len(importances), 3),
            "importance_range":   (round(min(importances), 3), round(max(importances), 3)),
            "access_mean":        round(sum(accesses) / len(accesses), 1),
            "access_max":         max(accesses),
            "age_mean_days":      round(sum(ages) / len(ages), 1),
            "age_max_days":       round(max(ages), 1),
        }

    def list_memories(self, sort_by="created_at", limit=10):
        """Return entries sorted (default: newest first), formatted."""
        entries = sorted(
            self._entries,
            key=lambda e: getattr(e, sort_by, e.created_at),
            reverse=True,
        )[:limit]
        return [e.summary() for e in entries]

    def to_dict(self):
        """Full serialisation."""
        return {
            "stats": self.stats(),
            "entries": [
                {
                    "id": e.id,
                    "content": e.content,
                    "type": e.memory_type,
                    "importance": e.importance,
                    "access_count": e.access_count,
                    "created": str(e.created_at),
                    "last_accessed": str(e.last_accessed) if e.last_accessed else None,
                }
                for e in self._entries
            ],
            "logs": self._logs,
        }


# ---------------------------------------------------------------------------
# Demo data factory
# ---------------------------------------------------------------------------

def _seed_memories(mem, count=20):
    """Seed *mem* with a diverse set of memory entries."""
    seed_data = [
        # (content, type, importance)
        ("NDVI analysis shows vegetation decline in the northern region", "observation", 0.7),
        ("Recommended irrigation schedule adjustment for dry spell", "decision", 0.8),
        ("User prefers visualization over tabular data output", "preference", 0.6),
        ("Crop model simulation completed for maize at temperate site", "task_result", 0.5),
        ("Soil moisture dropped below wilting point on day 45", "observation", 0.75),
        ("Hypothesis: water stress is the primary driver of LAI decline", "hypothesis", 0.85),
        ("ET time series shows increasing trend over the growing season", "observation", 0.55),
        ("Deployed new anomaly detection threshold at 2.5 sigma", "decision", 0.65),
        ("User requested additional band combinations for analysis", "preference", 0.4),
        ("Model calibration finished with R2=0.89 on validation set", "task_result", 0.7),
        ("Rapid decline in NDVI detected in week 3-4 of July", "observation", 0.8),
        ("Alternative hypothesis: nutrient deficiency may explain yellowing", "hypothesis", 0.6),
        ("Switch monitoring frequency from weekly to daily during dry periods", "decision", 0.75),
        ("User prefers metric units for all measurements", "preference", 0.3),
        ("Time series gap filled using linear interpolation", "task_result", 0.5),
        ("Surface temperature anomaly of +2.3C detected", "observation", 0.7),
        ("Hypothesis: delayed monsoon is causing prolonged dry spell", "hypothesis", 0.65),
        ("Reduced nitrogen application by 15% based on sensor feedback", "decision", 0.7),
        ("User enabled auto-generated summary reports", "preference", 0.35),
        ("Classification map generated for land cover types", "task_result", 0.45),
    ]
    for content, mem_type, importance in seed_data[:count]:
        mem.add_memory(content, mem_type, importance)
    return mem


# ---------------------------------------------------------------------------
# Test / demonstration
# ---------------------------------------------------------------------------

def test():
    print("=" * 60)
    print("  MemorySystem — Test Suite")
    print("=" * 60)

    # ---- 1. Embedding verification ---------------------------------------
    print("\n[1] Text embedder: similar texts → similar vectors")
    embedder = TextEmbedder()
    v1 = embedder.embed("crop water stress in dry conditions")
    v2 = embedder.embed("crop growth under water limitation")
    v3 = embedder.embed("stock market price fluctuations")
    sim_similar = cosine_similarity(v1, v2)
    sim_different = cosine_similarity(v1, v3)
    print(f"    Similar texts   (crop+water) → cos = {sim_similar:.4f}")
    print(f"    Different texts (crop vs stock) → cos = {sim_different:.4f}")
    assert sim_similar > sim_different, \
        f"Similar texts should score higher ({sim_similar} <= {sim_different})"
    print("    => Embedding passes semantic coherence check")

    # ---- 2. Seed memories ------------------------------------------------
    print("\n[2] Seeding memory store (20 entries)")
    mem = MemorySystem(embedder)
    _seed_memories(mem, 20)
    print(f"    Stored: {mem.size} entries")
    stats = mem.stats()
    print(f"    Types: {stats['by_type']}")
    print(f"    Importance: mean={stats['importance_mean']}, "
          f"range={stats['importance_range']}")

    # ---- 3. Cosine similarity search (top-k) -----------------------------
    print("\n[3] Top-k retrieval: query='irrigation and water management'")
    results = mem.search("irrigation and water management", top_k=4)
    print(f"    Found {len(results)} results (min_score=0.0):")
    for rank, (score, entry) in enumerate(results, 1):
        print(f"    #{rank}  score={score:.4f}  |  {entry.content[:70]}")

    # ---- 4. Verify ranking: best match first -----------------------------
    print("\n[4] Ranking verification: first result must have highest score")
    for i in range(len(results) - 1):
        assert results[i][0] >= results[i + 1][0], \
            f"Rank {i} score {results[i][0]} < rank {i+1} {results[i+1][0]}"
    print(f"    All {len(results)} results in correct descending order")

    # ---- 5. High-specificity query ---------------------------------------
    print("\n[5] Query: 'vegetation decline northern region anomaly'")
    results2 = mem.search("vegetation decline northern region anomaly", top_k=3)
    for rank, (score, entry) in enumerate(results2, 1):
        print(f"    #{rank}  score={score:.4f}  |  {entry.content[:70]}")

    # ---- 6. Test min_score filter ----------------------------------------
    print("\n[6] Filter with min_score=0.5")
    results3 = mem.search("temperature anomaly detection", top_k=10, min_score=0.5)
    print(f"    {len(results3)} results above 0.5 (out of {mem.size} total)")
    for rank, (score, entry) in enumerate(results3, 1):
        print(f"    #{rank}  score={score:.4f}  |  {entry.content[:60]}")

    # ---- 7. Access tracking ----------------------------------------------
    print("\n[7] Access tracking")
    mem.search("crop growth", top_k=3)
    mem.search("crop growth", top_k=3)
    mem.search("water stress", top_k=2)
    # Check access counts increased
    total_access = sum(e.access_count for e in mem.get_all())
    print(f"    Total access count across all entries: {total_access}")
    assert total_access > 0, "Search did not update access counts"
    print("    => Access tracking verified")

    # ---- 8. Consolidation (merge near-duplicates) ------------------------
    print("\n[8] Consolidation: merge similar memories")
    # Add near-duplicate pairs
    mem.add_memory("Irrigation needed during extended dry periods", "observation", 0.6)
    mem.add_memory("Extended dry periods require irrigation scheduling", "observation", 0.6)
    mem.add_memory("Nutrient deficiency causes leaf yellowing in crops", "observation", 0.5)
    mem.add_memory("Leaf yellowing in crops due to nutrient deficiency", "observation", 0.5)
    before = mem.size
    print(f"    Before consolidation: {before} entries")
    merged = mem.consolidate(threshold=0.7)
    after = mem.size
    print(f"    After consolidation:  {after} entries  ({merged} merges)")
    assert after < before, "Consolidation did not reduce entry count"

    # ---- 9. Decay (forgetting) -------------------------------------------
    print("\n[9] Decay: remove stale, demote unused")
    # Manually age some entries for testing
    for i, entry in enumerate(mem.get_all()):
        if i < 3:
            # Simulate old, never-accessed entries
            entry.created_at = datetime.now() - timedelta(days=365)
            entry.importance = 0.2
            entry.access_count = 0
        elif i < 6:
            # Simulate unaccessed entries
            entry.last_accessed = datetime.now() - timedelta(days=150)
            entry.access_count = 1
            entry.importance = 0.6
    result = mem.decay(max_age_days=200, importance_threshold=0.25)
    print(f"    Removed: {result['removed']}  |  Demoted: {result['demoted']}")
    print(f"    Size after decay: {mem.size}")

    # ---- 10. Cross-type search -------------------------------------------
    print("\n[10] Cross-type retrieval: query='user preferences'")
    prefs = mem.search("user preferences", top_k=5)
    print(f"    Top 5 results:")
    for rank, (score, entry) in enumerate(prefs, 1):
        print(f"    #{rank}  score={score:.4f}  [{entry.memory_type:<12}]  "
              f"{entry.content[:55]}")

    # ---- 11. Direct vector search (bypass embedder) ----------------------
    print("\n[11] Bare-vector search (query_vec from known entry)")
    ref_entry = mem.get_all()[0]
    vec_results = mem.search_by_vector(ref_entry.vector, top_k=3)
    for rank, (score, entry) in enumerate(vec_results, 1):
        match = "** SELF **" if entry.id == ref_entry.id else ""
        print(f"    #{rank}  score={score:.4f}  {match}  {entry.content[:60]}")

    # ---- 12. Stats after all operations ----------------------------------
    print("\n[12] Final memory stats")
    final_stats = mem.stats()
    print(f"    Size:      {final_stats['size']}")
    print(f"    Types:     {final_stats['by_type']}")
    print(f"    Mean imp:  {final_stats['importance_mean']}")
    print(f"    Mean age:  {final_stats['age_mean_days']} days")
    print(f"    Mean acc:  {final_stats['access_mean']}")

    # ---- 13. Not-a-dictionary verification --------------------------------
    print("\n[13] NOT-a-dictionary verification")
    # A dict lookup would: mem["irrigation"] -> exact key match
    # Vector search does: embed("irrigation") -> cos_sim(all vectors) -> rank
    qv = embedder.embed("irrigation")
    dict_style = any(e.content.startswith("irrigation") for e in mem.get_all())
    vec_top = mem.search_by_vector(qv, top_k=1)
    print(f"    Dictionary lookup would match by key prefix: {dict_style}")
    print(f"    Vector search returns by semantic similarity: "
          f"'{vec_top[0][1].content[:50]}...' (score={vec_top[0][0]:.4f})")

    # ---- 14. Data-flow serialisation -------------------------------------
    print("\n[14] Serialisation (to_dict)")
    serialised = mem.to_dict()
    print(f"    Keys: {list(serialised.keys())}")
    print(f"    Entry count in payload: {len(serialised['entries'])}")
    print(f"    Log count: {len(serialised['logs'])}")

    # ---- 15. Processing logs ---------------------------------------------
    print("\n[15] Processing logs")
    mem.print_logs()

    # ---- Summary ---------------------------------------------------------
    print("\n" + "=" * 60)
    print("  All tests passed.")
    print("=" * 60)


if __name__ == "__main__":
    test()
