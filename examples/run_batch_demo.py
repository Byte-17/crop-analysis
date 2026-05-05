"""
examples/run_batch_demo.py — Entry point for batch pipeline demo.

Runs the BatchPipeline on 55 fields, saves structured multi-step logs
to ``logs/realistic_logs.txt``, then prints a summary.

Usage:
    python examples/run_batch_demo.py
"""

import os
import sys
import time

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from workflows.pipeline import BatchPipeline


def main():
    print("=" * 60)
    print("  MIMO Batch Pipeline Demo")
    print("=" * 60)
    print()

    # Log file path
    log_path = os.path.join(_project_root, "logs", "realistic_logs.txt")

    # Ensure log directory exists
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    # Initialise pipeline with 55 fields
    pipeline = BatchPipeline(
        num_fields=55,
        model="sonnet",
        log_file=log_path,
        verbose=True,
    )

    t_start = time.time()

    # Run the batch
    report = pipeline.run(consolidate_every=20)

    t_elapsed = time.time() - t_start

    # Ensure logs are flushed to file
    pipeline.save_logs(log_path)

    # Print summary to console
    print()
    pipeline.print_summary()

    # Additional metadata
    print(f"  Batch demo complete.")
    print(f"  Elapsed:       {t_elapsed:.1f}s")
    print(f"  Log file:      {log_path}")
    print(f"  Log lines:     {len(pipeline._logs)}")
    print(f"  Token total:   {report['token_usage']['total']}")
    print(f"  Memory final:  {report['memory']['final_size']} entries")
    print(f"  Fields:        {report['num_fields']}")

    # Verify log file
    if os.path.exists(log_path):
        size_kb = round(os.path.getsize(log_path) / 1024, 1)
        with open(log_path, "r", encoding="utf-8") as f:
            line_count = len(f.readlines())
        print(f"  Log file size: {size_kb} KB ({line_count} lines)")
    print()

    print("=" * 60)
    print("  Demo complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
