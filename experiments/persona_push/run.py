#!/usr/bin/env python3
"""Integrated native DTAG survey experiment and PGFPlots export.

Two controlling parameters: --steps (number of questions) and --reps
(independent repetitions for EACH policy and EACH fixed permutation).

Stages:
  1. Adaptive question selection (6 personas x 4 policies x reps).
  2. Freeze 18 sets from rep=0; replay original, reverse and two shuffles
     (6 personas x 3 source policies x 4 permutations x reps).
  3. Globally seriate question IDs across all 18 nonrandom heatmaps,
     then export three reproducible PGFPlots figures and CSVs.

No CI run, tests, or git commits are triggered by this program.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PERSONAS = ('cm_rural_alabama','wf_new_york_city',
            'religious_conservative_woman_texas','secular_liberal_man_seattle',
            'hispanic_catholic_man_arizona','black_churchgoing_woman_atlanta')
POLICIES = ('right','left','neutral')


def freeze_sets(path, steps, reps, destination):
    """Predeclare observed rep-0 item sets, WITHOUT consulting endpoints.

    The observed variable/order/answer data from rep 0 supply item identities
    and a fixed-answer invariance control, not an estimand or optimized
    permutation. No participant or answer is selected by final index.
    """
    with path.open(newline='',encoding='utf-8') as f:
        rd = csv.DictReader(f)
        cols=set(rd.fieldnames or [])
        missing={'persona','policy','rep','step','variable','answer'}-cols
        if missing:
            raise ValueError(f'Missing source columns: {sorted(missing)}')
        subset = {}
        for line in rd:
            if int(line['rep'])!=0 or int(line['step'])<1:
                continue
            key=(line['persona'],line['policy'])
            subset.setdefault(key,[]).append(line)
    entries=[]
    for p in PERSONAS:
        for pol in POLICIES:
            rows=sorted(subset.get((p,pol),[]),key=lambda z:int(z['step']))
            if len(rows)!=steps or [int(z['step']) for z in rows]!=list(range(1,steps+1)):
                raise ValueError(f'{p}/{pol}: expected {steps} completed questions from rep 0')
            qs=[z['variable'] for z in rows]
            if len(set(qs))!=steps:
                raise ValueError(f'{p}/{pol}: repeated variable')
            entries.append(dict(persona=p,source_policy=pol,source_rep=0,
                                questions=qs,source_answers={z['variable']:z['answer'] for z in rows}))
    result={'schema':'DTAG frozen question sets for permutation replay v2',
            'steps':steps,'repetitions_of_source':reps,
            'selection_rule':'rep0 observed questions; do not select by outcome',
            'sets':entries}
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return destination


def launch(argv):
    print('+', ' '.join(map(str,argv)),flush=True)
    subprocess.run([str(x) for x in argv],cwd=ROOT,check=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--steps',type=int,default=10,help='questions per run')
    p.add_argument('--reps',type=int,default=40,help='independent repetitions per arm')
    p.add_argument('--model',default='gss/gss_2024')
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--seed',type=int,default=20261021)
    p.add_argument('--bootstrap',type=int,default=2000)
    p.add_argument('--objective',choices=('allpairs','adjacent'),default='allpairs')
    p.add_argument('--max-swaps',type=int,default=12)
    p.add_argument('--out',type=Path,help='Output directory; default indexed by steps and reps')
    p.add_argument('--figures-only',action='store_true',
                   help='Reuse CSVs already under --out, skipping native simulations')
    p.add_argument('--resume',action='store_true',
                   help='Recover standalone order PDF plus the three PGFPlots figures '
                        'from completed CSV outputs; never rerun native simulations')
    p.add_argument('--skip-plot',action='store_true',help='Run native stages only')
    args=p.parse_args()
    if args.steps<3 or args.reps<2 or args.workers<1 or args.bootstrap<100:
        p.error('steps>=3, reps>=2, workers>=1, bootstrap>=100 required')
    out=(args.out or HERE/'runs'/f'q{args.steps}_r{args.reps}').expanduser()
    if not out.is_absolute(): out=ROOT/out
    out.mkdir(parents=True,exist_ok=True)
    adaptive=out/'adaptive'
    order=out/'order'
    fixed=out/'fixed_question_sets.json'
    figures=out/'figures'
    if not (args.figures_only or args.resume):
        launch([sys.executable,ROOT/'scripts/dtag_persona_push_study.py',
                '--model',args.model,'--steps',args.steps,'--reps',args.reps,
                '--bootstrap',args.bootstrap,'--workers',args.workers,
                '--seed',args.seed,'--out',adaptive])
        freeze_sets(adaptive/'trajectories.csv',args.steps,args.reps,fixed)
        launch([sys.executable,ROOT/'scripts/dtag_fixed_10q_order_test.py',
                '--model',args.model,'--steps',args.steps,'--sets',fixed,
                '--reps',args.reps,'--bootstrap',args.bootstrap,
                '--workers',args.workers,'--seed',args.seed,'--out',order])
    else:
        for file in [adaptive/'trajectories.csv',adaptive/'trajectory_ci.csv',
                     order/'run_endpoints.csv',order/'question_draws.csv']:
            if not file.is_file():raise FileNotFoundError(file)
        if args.resume:
            if not fixed.is_file():
                freeze_sets(adaptive/'trajectories.csv',args.steps,args.reps,fixed)
            launch([sys.executable,ROOT/'scripts/dtag_fixed_10q_order_test.py',
                    '--finalize-only','--steps',args.steps,'--reps',args.reps,
                    '--sets',fixed,'--bootstrap',args.bootstrap,
                    '--seed',args.seed,'--out',order])
    if not args.skip_plot:
        launch([sys.executable,HERE/'plot_pgf.py',
                '--trajectories',adaptive/'trajectories.csv',
                '--trajectory-ci',adaptive/'trajectory_ci.csv',
                '--order-endpoints',order/'run_endpoints.csv',
                '--steps',args.steps,'--reps',args.reps,
                '--objective',args.objective,'--max-swaps',args.max_swaps,
                '--seed',args.seed,'--out',figures])
    manifest={'model':args.model,'steps':args.steps,'reps':args.reps,
              'seed':args.seed,'bootstrap':args.bootstrap,'workers':args.workers,
              'objective':args.objective,'max_swaps':args.max_swaps,
              'figures_only':args.figures_only,'resume':args.resume,
              'adaptive':str(adaptive),'fixed_sets':str(fixed),
              'order':str(order),'figures':str(figures)}
    (out/'integrated_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Integrated experiment outputs:',out)


if __name__=='__main__':main()