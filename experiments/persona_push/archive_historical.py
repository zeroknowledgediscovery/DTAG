#!/usr/bin/env python3
"""Materialize the frozen original 10q x 40-repetition results locally.

No native model access, no re-simulation, and no network access are needed.
The archived CI zip is stored in the repository as base64-encoded text to
preserve the byte-for-byte original GitHub Actions artifact in a UTF-8 Git
content API upload. It is decoded and extracted, not recomputed.
"""
from __future__ import annotations

import argparse
import base64
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
LOCAL=HERE/'data/historical_local_20261021'
CI_B64=HERE/'data/historical_order_20261021/CI_results.zip.b64.txt'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,default=HERE/'runs/historical_q10_r40')
    ap.add_argument('--plot',action='store_true',help='Regenerate PGFPlots from archived CSVs')
    ap.add_argument('--max-swaps',type=int,default=12)
    args=ap.parse_args()
    out=args.out.resolve()
    adaptive=out/'adaptive';order=out/'order';figures=out/'figures'
    adaptive.mkdir(parents=True,exist_ok=True)
    order.mkdir(parents=True,exist_ok=True)
    needed=('trajectories.csv','trajectory_ci.csv','endpoints.csv',
            'versus_random.csv','question_counts.csv','manifest.json')
    for name in needed:
        src=LOCAL/name
        if not src.exists():raise FileNotFoundError(src)
        shutil.copy2(src,adaptive/name)
    if not CI_B64.exists():raise FileNotFoundError(CI_B64)
    archive=base64.b64decode(CI_B64.read_text().encode('ascii'))
    zip_path=out/'original_order_CI_results.zip'
    zip_path.write_bytes(archive)
    with zipfile.ZipFile(zip_path) as z:
        for member in z.infolist():
            dest=(order/member.filename).resolve()
            if not dest.is_relative_to(order.resolve()):
                raise ValueError(f'Unsafe entry in CI artifact: {member.filename}')
            if member.filename.startswith('native_cache/'):
                continue  # runtime-derived cache, not required for plots
            z.extract(member,order)
    if args.plot:
        cmd=[sys.executable,str(HERE/'plot_pgf.py'),
             '--trajectories',str(adaptive/'trajectories.csv'),
             '--trajectory-ci',str(adaptive/'trajectory_ci.csv'),
             '--order-endpoints',str(order/'run_endpoints.csv'),
             '--steps','10','--reps','40','--objective','allpairs',
             '--max-swaps',str(args.max_swaps),'--out',str(figures)]
        subprocess.run(cmd,cwd=ROOT,check=True)
        publication=[sys.executable,str(HERE/'publication_pgfplots.py'),
                     '--adaptive-endpoints',str(adaptive/'endpoints.csv'),
                     '--trajectory-ci',str(adaptive/'trajectory_ci.csv'),
                     '--order-endpoints',str(order/'run_endpoints.csv'),
                     '--steps','10','--reps','40','--out',str(figures)]
        subprocess.run(publication,cwd=ROOT,check=True)
    print('Recovered verified historical 10-question datasets under',out)


if __name__=='__main__':main()