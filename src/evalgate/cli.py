"""
evalgate report  RUN.json  [--baseline BASE.json] [--out report.md]

Renders the Markdown report from saved run files, e.g. to compare two
historical runs or to rebuild a PR comment without re-running the suite.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="evalgate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="render a Markdown report from run files")
    r.add_argument("run")
    r.add_argument("--baseline")
    r.add_argument("--out")
    r.add_argument("--cost-tolerance", type=float, default=0.20)
    args = ap.parse_args(argv)

    run = results.load(args.run)
    if run is None:
        print(f"no such run file: {args.run}", file=sys.stderr)
        return 2
    base = results.load(args.baseline) if args.baseline else None
    comp = results.compare(base, run, args.cost_tolerance) if base else None
    md = results.render_markdown(run, comp, base)
    if args.out:
        Path(args.out).write_text(md)
    else:
        print(md)
    return 1 if comp and comp.gate_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
