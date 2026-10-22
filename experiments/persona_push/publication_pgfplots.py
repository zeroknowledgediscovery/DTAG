#!/usr/bin/env python3
"""Generate publication-grade native PGFPlots figures for DTAG persona-push studies.

Five substantive figures:
1. Endpoints by persona and question-selection policy, with bootstrap CIs.
2. Six-panel trajectories with 95% pointwise bands.
3. Globally optimized categorical question heatmaps; two sheets of nine square panels.
4. Paired order effects EXACTLY as the Python figure: 6x3 panels with three
   pointwise paired-mean bootstrap intervals; two sheets of nine panels.
5. Probabilities of endpoint-ideology and direction-of-displacement reversals;
   cluster bootstrap intervals over independent rep indices.

No simulations or fabricated numbers. Input must be CSVs from the completed
native experiments. External plot data are emitted in CSV, and every visual is
LaTeX PGFPlots (no pre-rendered bitmap/PDF embedded in the manuscript).
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PERSONAS=["cm_rural_alabama","wf_new_york_city","religious_conservative_woman_texas",
          "secular_liberal_man_seattle","hispanic_catholic_man_arizona","black_churchgoing_woman_atlanta"]
LABELS=["Alabama","New York","Texas","Seattle","Arizona","Atlanta"]
POLICIES=["right","left","neutral"]
ARMS=["right","left","neutral","random"]
SHIFTS={"right":-.27,"left":-.09,"neutral":.09,"random":.27}
STYLES={
 "right":r"black,very thick,mark=*,mark size=1.9pt",
 "left":r"black,dashed,very thick,mark=o,mark size=2pt",
 "neutral":r"teal!65!black,thick,mark=square*,mark size=1.8pt",
 "random":r"black!40,thick,densely dotted,mark=triangle*,mark size=1.9pt",
}
STYLE_LINES={"right":"black,very thick","left":"black,thick,dashed",
             "neutral":"teal!65!black,thick","random":"black!50,thick,dash dot"}
PALETTE=("black","black!60","teal!65!black")
PALETTE_MAP=("black!14","black!10","teal!15")
STYLE_OPTS=r"tick label style={font=\scriptsize},label style={font=\footnotesize},title style={font=\footnotesize\bfseries},grid=major,grid style={draw=black!8},axis line style={black!55},tick style={black!55},enlargelimits=false"
HEATMAP_COLORMAP=r"colormap={questionmap}{rgb255=(35,48,70);rgb255=(67,93,123);rgb255=(100,158,173);rgb255=(169,210,201);rgb255=(239,224,171);rgb255=(231,164,154);rgb255=(159,91,113)}"


def csv_write(df,out):
    out.parent.mkdir(parents=True,exist_ok=True)
    df.to_csv(out,index=False,float_format="%.12g")


def rel(out):
    return Path(os.path.relpath(out,ROOT/'tex')).as_posix()


def plot_path(out,filename):
    return rel(out)+'/'+filename


def put(out,basename,body):
    (out/basename).write_text(body.strip()+"\n",encoding="utf-8")


def go_endpoints(df,out,steps):
    required={'persona','policy','mean_delta','ci_low','ci_high'}
    if required-set(df.columns):raise ValueError('End point input missing columns '+str(required-set(df.columns)))
    xx=[]
    for k,pol in enumerate(ARMS):
        rows=[]
        for i,person in enumerate(PERSONAS):
            z=df[(df.persona==person)&(df.policy==pol)]
            if len(z)!=1:raise ValueError('Missing/duplicate adaptive endpoint '+person+pol)
            r=z.iloc[0];mean=float(r.mean_delta);lo=float(r.ci_low);hi=float(r.ci_high)
            if not (lo<=mean+1e-9 and mean<=hi+1e-9):raise ValueError('Invalid CI')
            rows.append({'y':6-i+SHIFTS[pol],'mean':mean,'minus':max(0,mean-lo),'plus':max(0,hi-mean)})
        name=f'pub_endpoint_{pol}.csv';csv_write(pd.DataFrame(rows),out/name)
        # Fine hairline confidence whiskers and strong black markers
        style=STYLES[pol]
        xx.append(r'\addplot['+style+r',only marks,error bars/.cd,x dir=both,x explicit,error bar style={line width=.85pt,black!65},error mark options={rotate=90,mark size=2pt}] '
             +r'table[x=mean,y=y,x error minus=minus,x error plus=plus,col sep=comma]{'+plot_path(out,name)+r'};')
        xx.append(r'\addlegendentry{'+{'right':'Right push','left':'Left push','neutral':'Neutral drift','random':'Random questions'}[pol]+'}')
    lines=[r'\begin{tikzpicture}',(r'\begin{axis}[width=.93\textwidth,height=9.2cm,xmin=-.095,xmax=.11,ymin=.38,ymax=6.7,'
           r'ytick={1,2,3,4,5,6},yticklabels={Atlanta,Arizona,Seattle,Texas,New York,Alabama},'
           r'xtick={-.08,-.04,0,.04,.08},scaled x ticks=false,xticklabel={\pgfmathprintnumber[fixed,precision=2]{\tick}},xticklabel style={font=\footnotesize},'
           r'xlabel={Mean displacement after '+str(steps)+r' questions, $\overline{\Delta I_\Phi}$},'
           r'legend style={draw=none,fill=none,font=\footnotesize,legend columns=4,column sep=11pt,at={(.5,1.03)},anchor=south},'
           +STYLE_OPTS+r']'),r'\addplot[black!60,thick,forget plot] coordinates{(0,.5)(0,6.6)};']
    lines+=xx+[r'\end{axis}',r'\end{tikzpicture}']
    put(out,'fig1_endpoints_pgfplots.tex','\n'.join(lines))


def go_trajectories(df,out,steps):
    necessary={'persona','policy','step','mean_net_delta','ci_low','ci_high'}
    if necessary-set(df.columns):raise ValueError('Trajectory data missing '+str(necessary-set(df.columns)))
    lo=[]; hi=[]
    for person in PERSONAS:
        for pol in ARMS:
            x=df[(df.persona==person)&(df.policy==pol)].sort_values('step')
            if list(x.step)!=list(range(steps+1)):raise ValueError('Missing steps '+person+pol)
            csv_write(pd.DataFrame({'step':x.step,'mean':x.mean_net_delta,'lo':x.ci_low,'hi':x.ci_high}),out/f'pub_trajectory_{person}_{pol}.csv')
            lo.extend(x.ci_low.to_numpy());hi.extend(x.ci_high.to_numpy())
    low=min(lo); high=max(hi);delta=(high-low)*.06
    ax=r'\begin{groupplot}[group style={group size=2 by 3,horizontal sep=1.4cm,vertical sep=1.2cm},width=.425\textwidth,height=3.55cm,'+f'xmin=0,xmax={steps},ymin={low-delta:.5f},ymax={high+delta:.5f},'+STYLE_OPTS+r']'
    parts=[r'\begin{tikzpicture}',ax]
    # Pair conservatives and liberals per row
    order=[PERSONAS[i] for i in [0,1,2,3,4,5]]
    for i,p in enumerate(order):
        opts=['title={'+LABELS[i]+'}']
        if i%2==0:opts.append(r'ylabel={$\Delta I_\Phi$}')
        if i>=4:opts.append('xlabel={Question position}')
        else:opts.append('xticklabels={}')
        parts.append(r'\nextgroupplot['+','.join(opts)+']')
        parts.append(f'\\addplot[black!32,densely dotted,forget plot] coordinates{{(0,0) ({steps},0)}};')
        for pol in ARMS:
            fn=plot_path(out,f'pub_trajectory_{p}_{pol}.csv')
            key=(''.join(x for x in p if x.isalpha())+pol)
            if pol in ('right','left'):
                for j,col in [('lo','lo'),('hi','hi')]:
                    parts.append(r'\addplot[draw=none,forget plot,name path='+j+key+r'] table[x=step,y='+col+r',col sep=comma]{'+fn+r'};')
                parts.append(r'\addplot[draw=none,fill='+('black!14' if pol=='right' else 'black!7')+r',forget plot] fill between[of=h i];'.replace('h i','hi'+key+' and lo'+key))
            parts.append(r'\addplot['+STYLE_LINES[pol]+r',no marks,forget plot] table[x=step,y=mean,col sep=comma]{'+fn+r'};')
    parts.extend([r'\end{groupplot}',
                  r'\node[anchor=south,font=\scriptsize] at ([yshift=3mm]current bounding box.north) {\textbf{Right}: solid black\quad \textbf{Left}: dashed black\quad \textbf{Neutral}: muted teal\quad \textbf{Random}: dot--dash grey};',
                  r'\end{tikzpicture}'])
    put(out,'fig2_trajectories_pgfplots.tex','\n'.join(parts))


def go_heatmaps(out,steps,reps,nactive):
    # Data is written by existing global-index optimizer; preserve optimized IDs.
    for sheet,persons in [('a',PERSONAS[:3]),('b',PERSONAS[3:])]:
        parts=[r'\begin{tikzpicture}',
               (r'\begin{groupplot}[group style={group size=3 by 3,horizontal sep=.85cm,vertical sep=.90cm},'
               r'width=.273\textwidth,height=.273\textwidth,'
               +f'xmin=.5,xmax={steps+.5},ymin=.5,ymax={reps+.5},'
               r'y dir=reverse,axis on top,enlargelimits=false,scale only axis,'
               r'xtick={1,'+str(max(2,steps//2))+','+str(steps)+r'},ytick={1,'+str(max(2,reps//2))+','+str(reps)+r'},'
               r'xticklabel style={font=\tiny},yticklabel style={font=\tiny},label style={font=\scriptsize},'
               r'axis line style={draw=black!20},tick style={draw=black!35},'
               +HEATMAP_COLORMAP+f',point meta min=1,point meta max={nactive}]')]
        for i,p in enumerate(persons):
            for j,pol in enumerate(POLICIES):
                opts=[]
                if i==0:opts.append('title={'+{'right':'Right push','left':'Left push','neutral':'Neutral'}[pol]+r'}')
                if j==0:opts.append('ylabel={'+LABELS[PERSONAS.index(p)]+r'}')
                else:opts.append('yticklabels={}')
                if i<2:opts.append('xticklabels={}')
                else:opts.append('xlabel={Question position}')
                parts.append(r'\nextgroupplot['+','.join(opts)+']')
                parts.append(r'\addplot[matrix plot*,mesh/cols='+str(steps)+r',point meta=explicit] table[x=x,y=y,meta=value,col sep=comma]{'+plot_path(out,f'heatmap_{p}_{pol}.csv')+r'};')
        parts.extend([r'\end{groupplot}',r'\node[anchor=north,font=\footnotesize] at ([yshift=-6mm]current bounding box.south) {Globally optimized question IDs (1--'+str(nactive)+r'); identical colour scale for all 18 panels. Rows are independent runs.};',r'\end{tikzpicture}'])
        put(out,'fig3'+sheet+'_heatmaps_pgfplots.tex','\n'.join(parts))


def go_order_forest(df,out):
    needed={'persona','source_policy','order','mean_final_I_difference','ci_low','ci_high'}
    if needed-set(df.columns):raise ValueError('Order contrasts missing '+str(needed-set(df.columns)))
    extrema=float(max(df.ci_high.abs().max(),df.ci_low.abs().max()))
    lim=max(.012,round(extrema*1.25,3))
    for p in PERSONAS:
        for pol in POLICIES:
            sub=df[(df.persona==p)&(df.source_policy==pol)].set_index('order')
            rows=[]
            for i,perm in enumerate(['reverse','shuffle1','shuffle2']):
                r=sub.loc[perm];mean=float(r.mean_final_I_difference)
                rows.append({'y':3-i,'mean':mean,'minus':mean-float(r.ci_low),'plus':float(r.ci_high)-mean})
            csv_write(pd.DataFrame(rows),out/f'pub_order_{p}_{pol}.csv')
    for sheet,persons in [('a',PERSONAS[:3]),('b',PERSONAS[3:])]:
        parts=[r'\begin{tikzpicture}',
               (r'\begin{groupplot}[group style={group size=3 by 3,horizontal sep=1.12cm,vertical sep=.92cm},'
               r'width=.265\textwidth,height=3.50cm,'
               f'xmin={-lim:.4f},xmax={lim:.4f},ymin=.5,ymax=3.5,'
               r'ytick={1,2,3},yticklabels={Shuffle 2,Shuffle 1,Reverse},'
               r'xticklabel style={font=\tiny},yticklabel style={font=\scriptsize},'
               r'label style={font=\scriptsize},title style={font=\footnotesize\bfseries},'
               r'grid=major,grid style={draw=black!7},axis line style={draw=black!35},'
               r'tick style={draw=black!30},scaled x ticks=false,xticklabel={\pgfmathprintnumber[fixed,precision=2]{\tick}}]')]
        for i,p in enumerate(persons):
            for j,pol in enumerate(POLICIES):
                opts=[]
                if i==0:opts.append('title={'+{'right':'Right-derived','left':'Left-derived','neutral':'Neutral-derived'}[pol]+'}')
                if j!=0:opts.append('yticklabels={}')
                else:opts.append('ylabel={'+LABELS[PERSONAS.index(p)]+'}')
                if i!=2:opts.append('xticklabels={}')
                else:opts.append(r'xlabel={$I_{\mathrm{order}}-I_{\mathrm{original}}$}')
                parts.append(r'\nextgroupplot['+','.join(opts)+']')
                parts.append(r'\addplot[black!35,thin,forget plot] coordinates {(0,.5)(0,3.5)};')
                name=plot_path(out,f'pub_order_{p}_{pol}.csv')
                # 3 observed order contrasts with 95% bootstrap intervals.
                parts.append(r'\addplot[only marks,black,mark=*,mark size=1.9pt,error bars/.cd,x dir=both,x explicit,error bar style={line width=1.1pt,black!75},error mark options={mark size=1.6pt}] table[x=mean,y=y,x error minus=minus,x error plus=plus,col sep=comma]{'+name+'};')
        parts += [r'\end{groupplot}',r'\end{tikzpicture}']
        put(out,'fig4'+sheet+'_order_effects_pgfplots.tex','\n'.join(parts))


def flips_and_ci(df,out,reps,eps=1e-9,B=3000,seed=20261022):
    if df.empty:raise ValueError('Empty order endpoints')
    needed={'persona','source_policy','rep','order','final_I','initial_I'}
    if needed-set(df.columns):raise ValueError('Order endpoints missing fields '+str(needed-set(df.columns)))
    rows=[]
    for p in PERSONAS:
        for pol in POLICIES:
            d=df[(df.persona==p)&(df.source_policy==pol)]
            if len(d)!=4*reps:raise ValueError('Expected exact 4*reps replay rows for '+p+pol)
            pivot=d.pivot(index='rep',columns='order',values='final_I').reindex(index=range(reps))
            initial=d[d.order=='original'].set_index('rep').reindex(index=range(reps)).initial_I.to_numpy()
            if pivot.isna().any().any() or np.isnan(initial).any():raise ValueError('Missing comparisons '+p+pol)
            b=pivot.original.to_numpy()
            tests=[]
            for other in ['reverse','shuffle1','shuffle2']:
                a=pivot[other].to_numpy()
                f=((b>eps)&(a < -eps))|((b < -eps)&(a > eps))
                br=b-initial;ar=a-initial
                g=((br>eps)&(ar < -eps))|((br < -eps)&(ar > eps))
                tests.append(np.c_[f.astype(int),g.astype(int)])
            tests=np.stack(tests,axis=1) # reps x 3 orders x 2 outcomes
            count=tests.sum(axis=(0,1)); prob=tests.mean(axis=(0,1))
            rng=np.random.default_rng(seed+100*PERSONAS.index(p)+POLICIES.index(pol))
            ci=np.empty((B,2),float)
            for i in range(B):
                ix=rng.integers(reps,size=reps)
                ci[i]=tests[ix].mean(axis=(0,1))
            lo=np.quantile(ci,.025,axis=0);hi=np.quantile(ci,.975,axis=0)
            for outcome,k in [('final_sign',0),('displacement_direction',1)]:
                rows.append({'persona':p,'label':LABELS[PERSONAS.index(p)],'policy':pol,
                             'outcome':outcome,'repetitions':reps,'paired_comparisons':3*reps,
                             'flip_count':int(count[k]),'probability':float(prob[k]),
                             'ci_low':float(lo[k]),'ci_high':float(hi[k])})
    stats=pd.DataFrame(rows)
    csv_write(stats,out/'pub_sign_reversal_probabilities.csv')
    # 2 panels; no barcharts. Six-persona dot-and-whisker comparison, with
    # matched-run cluster bootstraps, black-on-pastel format.
    content=[r'\begin{tikzpicture}',
             (r'\begin{groupplot}[group style={group size=2 by 1,horizontal sep=1.60cm},'
             r'width=.40\textwidth,height=8.0cm,xmin=0,xmax=.56,ymin=.45,ymax=6.55,'
             r'ytick={1,2,3,4,5,6},yticklabels={Atlanta,Arizona,Seattle,Texas,New York,Alabama},'
             r'xtick={0,.1,.2,.3,.4,.5},xticklabel style={font=\scriptsize},'
             r'yticklabel style={font=\scriptsize},label style={font=\footnotesize},'
             r'grid=major,grid style={draw=black!8},'
             r'xlabel={Reversal probability},'
             r'legend style={draw=none,fill=none,font=\scriptsize,at={(.5,1.25)},anchor=south,legend columns=3,column sep=9pt}]')]
    for f,title in [('displacement_direction','Direction of movement'),('final_sign','Final ideology sign')]:
        content.append(r'\nextgroupplot[title={'+title+r'},title style={font=\footnotesize\bfseries}'+(',yticklabels={}' if f=='final_sign' else '')+']')
        for pol,sh,sty in [('right',-.21,'black,mark=*,mark size=2.1pt'),('left',0,'black,mark=o,mark size=2.1pt'),('neutral',.21,'teal!70!black,mark=square*,mark size=2.1pt')]:
            subset=stats[(stats.policy==pol)&(stats.outcome==f)]
            rr=[]
            for _,r in subset.iterrows():
                y=6-PERSONAS.index(r.persona)+sh
                rr.append({'y':y,'prob':r.probability,'minus':r.probability-r.ci_low,'plus':r.ci_high-r.probability})
            nm=f'pub_flip_{f}_{pol}.csv';csv_write(pd.DataFrame(rr),out/nm)
            content.append(r'\addplot['+sty+r',only marks,error bars/.cd,x dir=both,x explicit,error bar style={line width=.9pt,black!55},error mark options={mark size=1.6pt}] table[x=prob,y=y,x error minus=minus,x error plus=plus,col sep=comma]{'+plot_path(out,nm)+r'};')
            if f=='displacement_direction':content.append(r'\addlegendentry{'+{'right':'Right set','left':'Left set','neutral':'Neutral set'}[pol]+'}')
    content += [r'\end{groupplot}',r'\end{tikzpicture}']
    put(out,'fig5_sign_reversal_probabilities_pgfplots.tex','\n'.join(content))
    return stats


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--adaptive-endpoints',type=Path,required=True)
    ap.add_argument('--trajectory-ci',type=Path,required=True)
    ap.add_argument('--order-endpoints',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--steps',type=int,required=True)
    ap.add_argument('--reps',type=int,required=True)
    ap.add_argument('--nactive',type=int,default=0)
    a=ap.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    if a.nactive<=0:
        qfile=a.out/'question_index.csv'
        if not qfile.exists():raise ValueError('Missing global optimized question_index.csv. Run plot_pgf.py first')
        # Sorted index is 1..nactive for all displayed policies; random-only questions last.
        q=pd.read_csv(qfile)
        keys=set()
        for p in PERSONAS:
            for pol in POLICIES:
                h=pd.read_csv(a.out/f'heatmap_{p}_{pol}.csv')
                if len(h)!=a.steps*a.reps:raise ValueError('Incomplete heatmap')
                keys.update(h.value.astype(int))
        a.nactive=len(keys)
        if max(keys)!=a.nactive:raise ValueError('Optimized IDs are not contiguous 1..nactive')
    go_endpoints(pd.read_csv(a.adaptive_endpoints),a.out,a.steps)
    go_trajectories(pd.read_csv(a.trajectory_ci),a.out,a.steps)
    go_heatmaps(a.out,a.steps,a.reps,a.nactive)
    go_order_forest(pd.read_csv(a.order_endpoints.parent/'paired_order_contrasts.csv'),a.out)
    x=flips_and_ci(pd.read_csv(a.order_endpoints),a.out,a.reps)
    print('Five publication-quality PGFPlots figure groups (seven sheet files) generated.')
    print('Reversal summaries:',x.groupby(['policy','outcome']).agg({'flip_count':'sum','paired_comparisons':'sum'}).to_string())

if __name__=='__main__':main()