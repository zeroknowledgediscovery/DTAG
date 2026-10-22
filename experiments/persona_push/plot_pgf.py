#!/usr/bin/env python3
"""Export reproducible native PGFPlots figures from DTAG CSV results.

The item-index optimization is display-only: a single global permutation
minimizes within-position cross-repetition absolute index distances across
all 18 nonrandom panels. IDs are categorical, not a semantic metric.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

PERSONAS = (
    'cm_rural_alabama', 'wf_new_york_city',
    'religious_conservative_woman_texas', 'secular_liberal_man_seattle',
    'hispanic_catholic_man_arizona', 'black_churchgoing_woman_atlanta',
)
LABELS = ('Alabama', 'New York', 'Texas', 'Seattle', 'Arizona', 'Atlanta')
PAIRS = (('cm_rural_alabama','wf_new_york_city'),
         ('religious_conservative_woman_texas','secular_liberal_man_seattle'),
         ('hispanic_catholic_man_arizona','black_churchgoing_woman_atlanta'))
POLICIES = ('right','left','neutral')
ALL = ('right','left','neutral','random')
COLORS = {'right':'red!75!black','left':'blue!75!black',
          'neutral':'teal!75!black','random':'black!45'}
SIGNS = {'right':'Right','left':'Left','neutral':'Neutral'}


def csv_out(file, rows, headers=None):
    file.parent.mkdir(parents=True, exist_ok=True)
    if headers is None:
        headers=list(rows[0])
    with file.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=headers)
        w.writeheader(); w.writerows(rows)


def _validate_trajectory(df, steps, reps):
    needed={'persona','rep','policy','step','variable','answer'}
    if missing:=needed-set(df.columns):
        raise ValueError(f'Missing {sorted(missing)} from trajectory CSV')
    if set(df.policy)!=set(ALL):
        raise ValueError(f'Expected four policies; found {set(df.policy)}')
    if set(df.persona)!=set(PERSONAS):
        raise ValueError(f'Expected six personas; found {set(df.persona)}')
    selected=df[df.step>0]
    if selected.variable.isna().any() or selected.variable.astype(str).str.strip().eq('').any():
        raise ValueError('Empty question in trajectory: incomplete experiment')
    counts=selected.groupby(['persona','policy','rep']).step.agg(['count','nunique','min','max'])
    if len(counts)!=6*4*reps or (counts['count']!=steps).any() or (counts['nunique']!=steps).any():
        raise ValueError('Incomplete number of runs/questions')
    if (counts['nunique']!=steps).any() or (counts['min']!=1).any() or (counts['max']!=steps).any():
        raise ValueError('Malformed step indices')
    if selected.groupby(['persona','policy','rep']).variable.nunique().ne(steps).any():
        raise ValueError('Repeated question in a single trajectory')
    return selected


def _matrices(data, variables, steps, reps):
    ids={v:i for i,v in enumerate(variables)}
    mats={}
    for persona in PERSONAS:
        for pol in POLICIES:
            chunk=data[(data.persona==persona)&(data.policy==pol)]
            raw=chunk.pivot(index='rep',columns='step',values='variable')
            raw=raw.reindex(index=range(reps),columns=range(1,steps+1))
            if raw.isna().any().any():
                raise ValueError(f'Wrong dimensions for {persona}/{pol}')
            mats[(persona,pol)]=np.asarray([[ids[v] for v in row] for row in raw.to_numpy()],dtype=int)
    return mats


def _weight_graph(mats,n,mode):
    graph=np.zeros((n,n),dtype=float)
    for mat in mats.values():
        for j in range(mat.shape[1]):
            x=mat[:,j]
            if mode=='adjacent':
                np.add.at(graph,(x[:-1],x[1:]),1)
            else:
                counts=np.bincount(x,minlength=n).astype(float)
                graph+=np.outer(counts,counts)
    if mode=='adjacent':graph+=graph.T
    np.fill_diagonal(graph,0)
    return graph


def _cost(order,graph):
    pos=np.empty(len(order),dtype=int);pos[order]=np.arange(len(order))
    return float((np.triu(graph*np.abs(pos[:,None]-pos[None,:]),1)).sum())


def _refine(order,graph,max_swaps):
    order=np.array(order,dtype=int)
    n=len(order)
    pos=np.empty(n,dtype=int);pos[order]=np.arange(n)
    for _ in range(max_swaps):
        best, bi, bj=-1e-9,-1,-1
        for i in range(n-1):
            a=order[i]
            for j in range(i+1,n):
                b=order[j]
                delta=np.abs(j-pos)-np.abs(i-pos)
                delta[a]=delta[b]=0
                improvement=float((graph[a]-graph[b])@delta)
                if improvement<best:
                    best,bi,bj=improvement,i,j
        if bi<0:break
        a,b=order[bi],order[bj]
        order[bi],order[bj]=b,a;pos[a],pos[b]=bj,bi
    return order


def question_index(data,steps,reps,out,mode='allpairs',max_swaps=10,seed=17):
    # Baseline ranks use all FOUR policies, including random. All IDs are stable
    # across personas and policies within this run, even though random is not drawn.
    totals=data.variable.value_counts().to_dict()
    variables=sorted(totals,key=lambda v:(-totals[v],v))
    mats=_matrices(data,variables,steps,reps)
    active=np.unique(np.concatenate([m.ravel() for m in mats.values()]))
    inactive=np.setdiff1d(np.arange(len(variables)),active)
    graph=_weight_graph(mats,len(variables),mode)
    weights=graph[np.ix_(active,active)]
    m=len(active)
    starts=[np.arange(m,dtype=int)]
    if m>2 and weights.sum()>0:
        lap=np.diag(weights.sum(axis=1))-weights
        eigvals,eigvecs=np.linalg.eigh(lap)
        positive=np.flatnonzero(eigvals>max(1e-9,eigvals[-1]*1e-10))
        for j in positive[:2]:starts.append(np.lexsort((np.arange(m),eigvecs[:,j])))
    starts.append(np.random.default_rng(seed).permutation(m))
    results=[_refine(z,weights,max_swaps) for z in starts]
    local=min(results,key=lambda z:_cost(z,weights))
    order=np.r_[active[local],inactive]
    assert len(set(order))==len(variables)
    new_to_old=order.tolist()
    rank=np.empty(len(variables),dtype=int);rank[order]=np.arange(1,len(variables)+1)
    report={'mode':mode,'total_questions':len(variables),'displayed_questions':m,
            'baseline_cost':_cost(np.arange(len(variables)),graph),
            'optimized_cost':_cost(order,graph),'reps':reps,'steps':steps,
            'swaps_per_start':max_swaps,'starts':len(starts)}
    report['reduction']=1-report['optimized_cost']/report['baseline_cost'] if report['baseline_cost'] else 0
    texts=data[['variable','question']].drop_duplicates(subset=['variable']).set_index('variable')['question'].to_dict()
    rows=[]
    for i,old in enumerate(new_to_old):
        v=variables[old]
        rows.append({'question_index':i+1,'variable':v,'frequency_index':old+1,
                     'total_uses':totals[v],'question':texts.get(v,'')})
    csv_out(out/'question_index.csv',rows)
    (out/'optimization_report.json').write_text(json.dumps(report,indent=2)+'\n')
    indexed=[]
    for (persona,pol),mat in mats.items():
        reindexed=rank[mat]
        for r in range(reps):
            for step in range(steps):
                indexed.append({'persona':persona,'policy':pol,'rep':r,'step':step+1,
                                'question_index':int(reindexed[r,step]),
                                'variable':variables[mat[r,step]]})
        points=[{'x':step+1,'y':r+1,'value':int(reindexed[r,step])}
                for r in range(reps) for step in range(steps)]
        csv_out(out/f'heatmap_{persona}_{pol}.csv',points)
    csv_out(out/'indexed_question_sequences.csv',indexed)
    return m,report


def trajectories_plot(ci,out,steps):
    if ci.empty:raise ValueError('No trajectory CI data')
    for persona in PERSONAS:
        for policy in ALL:
            s=ci[(ci.persona==persona)&(ci.policy==policy)].sort_values('step')
            if len(s)!=steps+1:raise ValueError(f'Missing CI data {persona}/{policy}')
            csv_out(out/f'trajectory_{persona}_{policy}.csv',
                    [{'step':int(z.step),'mean':float(z.mean_net_delta),
                      'lo':float(z.ci_low),'hi':float(z.ci_high)} for z in s.itertuples()])
    parts=[r'\begin{tikzpicture}',r'\begin{groupplot}[group style={group size=2 by 3,horizontal sep=1.25cm,vertical sep=1.15cm},'
           r'width=.45\textwidth,height=3.15cm,xmin=0,xmax='+str(steps)+r',xlabel={Question position},'
           r'ylabel={$\Delta I_\Phi$},grid=major,tick label style={font=\scriptsize},label style={font=\scriptsize},'
           r'title style={font=\footnotesize}]']
    for p in [x for row in PAIRS for x in row]:
        label=LABELS[PERSONAS.index(p)]
        parts.append(r'\nextgroupplot[title={'+label+r'}]')
        parts.append(r'\addplot[black!40,densely dashed,forget plot] coordinates {(0,0) ('+str(steps)+r',0)};')
        for policy in ALL:
            fn=f'trajectory_{p}_{policy}.csv'
            path=f'../experiments/persona_push/data/figures/{fn}'
            col=COLORS[policy]
            if policy!='neutral':
                key=p.replace('_','')+policy
                parts += [r'\addplot[draw=none,forget plot,name path=low'+key+r'] table[x=step,y=lo,col sep=comma]{'+path+r'};',
                          r'\addplot[draw=none,forget plot,name path=high'+key+r'] table[x=step,y=hi,col sep=comma]{'+path+r'};',
                          r'\addplot[draw=none,fill='+col+r',fill opacity=.12,forget plot] fill between[of=high'+key+' and low'+key+r'];']
            parts.append(r'\addplot['+col+r',thick,no marks,forget plot] table[x=step,y=mean,col sep=comma]{'+path+r'};')
    parts.append(r'\end{groupplot}')
    # Fixed legend above/inside figure; separate to avoid multi-panel duplicate legends.
    parts+= [r'\node[font=\scriptsize,anchor=south] at (current bounding box.north) {\textcolor{red!75!black}{\rule{6mm}{.7pt}} Right \quad \textcolor{blue!75!black}{\rule{6mm}{.7pt}} Left \quad \textcolor{teal!75!black}{\rule{6mm}{.7pt}} Neutral \quad \textcolor{black!45}{\rule{6mm}{.7pt}} Random};',r'\end{tikzpicture}']
    (out/'fig1_trajectories_pgfplots.tex').write_text('\n'.join(parts)+'\n')


def heatmaps_plot(out,steps,reps,nactive):
    parts=[r'\begin{tikzpicture}',r'\begin{groupplot}[group style={group size=3 by 6,horizontal sep=.27cm,vertical sep=.55cm},'
           r'width=.275\textwidth,height=2.18cm,xmin=.5,xmax='+str(steps)+'.5,ymin=.5,ymax='+str(reps)+'.5,'
           r'axis on top,enlargelimits=false,xtick={1,...,'+str(steps)+r'},'
           r'tick label style={font=\tiny},label style={font=\scriptsize},'
           r'colormap/viridis,point meta min=1,point meta max='+str(nactive)+r']']
    for persona in PERSONAS:
        for pol in POLICIES:
            filename=f'heatmap_{persona}_{pol}.csv'
            title=SIGNS[pol] if persona==PERSONAS[0] else ''
            ylabel=LABELS[PERSONAS.index(persona)] if pol=='right' else ''
            opts=[]
            if title:opts.append('title={'+title+'}')
            if ylabel:opts.append('ylabel={'+ylabel+'}')
            if persona!=PERSONAS[-1]:opts.append('xticklabels={}')
            opts.append('ytick={1,'+str(reps)+'}' if pol=='right' else 'ytick=\\empty')
            parts.append(r'\nextgroupplot['+','.join(opts)+']')
            parts.append(r'\addplot[matrix plot*,mesh/cols='+str(steps)+r',point meta=explicit] table[x=x,y=y,meta=value,col sep=comma]{../experiments/persona_push/data/figures/'+filename+r'};')
    parts.append(r'\end{groupplot}')
    parts.append(r'\node[anchor=north,font=\scriptsize] at (current bounding box.south) {Question position (columns); realization index (rows). Common item--color map across all panels; item IDs are categorical.};')
    parts.append(r'\end{tikzpicture}')
    (out/'fig2_question_heatmaps_pgfplots.tex').write_text('\n'.join(parts)+'\n')


def flip_analysis(df,out,eps=1e-9):
    needed={'persona','source_policy','rep','order','final_I','initial_I','net_delta'}
    if needed-set(df.columns):raise ValueError('Missing order replay endpoint fields')
    pairs=df.pivot(index=['persona','source_policy','rep'],columns='order',values=['final_I','net_delta'])
    for var in ['final_I','net_delta']:
        for ord in ['original','reverse','shuffle1','shuffle2']:
            if (var,ord) not in pairs:raise ValueError('Missing original/order pair')
            if pairs[(var,ord)].isna().any():raise ValueError('Missing order observations')
    table=[];detail=[]
    for persona in PERSONAS:
        for pol in POLICIES:
            sub=pairs.loc[(persona,pol)]
            for perm in ['reverse','shuffle1','shuffle2']:
                b=sub[('final_I','original')].to_numpy(dtype=float)
                a=sub[('final_I',perm)].to_numpy(dtype=float)
                start=df[(df.persona==persona)&(df.source_policy==pol)&(df.order=='original')].sort_values('rep').initial_I.to_numpy(dtype=float)
                if len(start)!=len(b):raise ValueError('Wrong initial-state count')
                delta=a-b
                # Directional movement differs iff both changes exceed tolerance
                bmove=b-start;amove=a-start
                end_flip=((b>eps)&(a<-eps))|((b<-eps)&(a>eps))
                movement_flip=((bmove>eps)&(amove<-eps))|((bmove<-eps)&(amove>eps))
                for i in range(len(b)):
                    detail.append({'persona':persona,'policy':pol,'rep':int(sub.index[i]),
                                   'alternate_order':perm,'original_final_I':b[i],
                                   'permuted_final_I':a[i],'absolute_change':abs(delta[i]),
                                   'final_sign_flip':int(end_flip[i]),
                                   'direction_sign_flip':int(movement_flip[i])})
                table.append({'persona':persona,'policy':pol,'alternate_order':perm,'n':len(b),
                              'mean_abs_change':float(np.abs(delta).mean()),
                              'endpoint_flip_count':int(end_flip.sum()),
                              'direction_flip_count':int(movement_flip.sum())})
    csv_out(out/'permutation_sign_flips_detailed.csv',detail)
    csv_out(out/'permutation_sign_flips_by_order.csv',table)
    summary=[]
    for persona in PERSONAS:
        for pol in POLICIES:
            rows=[x for x in table if x['persona']==persona and x['policy']==pol]
            n=sum(x['n'] for x in rows)
            summary.append({'persona':persona,'label':LABELS[PERSONAS.index(persona)],'policy':pol,
                            'n_comparisons':n,
                            'final_sign_flip_pct':100*sum(x['endpoint_flip_count'] for x in rows)/n,
                            'direction_sign_flip_pct':100*sum(x['direction_flip_count'] for x in rows)/n,
                            'mean_abs_change':sum(x['mean_abs_change']*x['n'] for x in rows)/n})
    csv_out(out/'permutation_sign_flips.csv',summary)
    # Plot both exact-sign reversal summaries, not signed mean differences.
    parts=[r'\begin{tikzpicture}',r'\begin{groupplot}[group style={group size=2 by 1,horizontal sep=1.0cm},'
           r'width=.46\textwidth,height=5cm,xtick={1,2,3,4,5,6},'
           r'xticklabels={AL,NY,TX,SEA,AZ,ATL},xticklabel style={font=\scriptsize},'
           r'yticklabel style={font=\scriptsize},ylabel={Percent of paired comparisons},'
           r'ymin=0,grid=major,legend style={font=\scriptsize,at={(.5,1.02)},anchor=south,legend columns=3}]']
    for j,(field,title) in enumerate([('direction_sign_flip_pct','Reversal of displacement'),('final_sign_flip_pct','Reversal of final ideological sign')]):
        parts.append(r'\nextgroupplot[title={'+title+r'},title style={font=\footnotesize}]')
        for k,pol in enumerate(POLICIES):
            data=' '.join('('+str(i+1)+','+f'{next(v for v in summary if v["persona"]==p and v["policy"]==pol)[field]:.7f}'+')' for i,p in enumerate(PERSONAS))
            parts.append(r'\addplot+[ybar,bar width=3.2pt,bar shift='+str((k-1)*4)+'pt,fill='+COLORS[pol]+',draw=none] coordinates {'+data+'};')
            if j==0:parts.append(r'\addlegendentry{'+SIGNS[pol]+'-derived}')
    parts.extend([r'\end{groupplot}',r'\end{tikzpicture}'])
    (out/'fig3_order_sign_reversal_pgfplots.tex').write_text('\n'.join(parts)+'\n')
    return summary


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--trajectories',type=Path,required=True)
    ap.add_argument('--trajectory-ci',type=Path,required=True)
    ap.add_argument('--order-endpoints',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--steps',type=int,required=True)
    ap.add_argument('--reps',type=int,required=True)
    ap.add_argument('--objective',choices=['adjacent','allpairs'],default='allpairs')
    ap.add_argument('--max-swaps',type=int,default=12)
    ap.add_argument('--seed',type=int,default=17)
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    tr=pd.read_csv(args.trajectories)
    asked=_validate_trajectory(tr,args.steps,args.reps)
    ci=pd.read_csv(args.trajectory_ci)
    order=pd.read_csv(args.order_endpoints)
    nactive, report=question_index(asked,args.steps,args.reps,args.out,args.objective,args.max_swaps,args.seed)
    trajectories_plot(ci,args.out,args.steps)
    heatmaps_plot(args.out,args.steps,args.reps,nactive)
    summary=flip_analysis(order,args.out)
    print(json.dumps({'total_questions':report['total_questions'],
                      'displayed_questions':nactive,'optimization_reduction':report['reduction'],
                      'order_flip_groups':len(summary),'figure_files':3},indent=2))


if __name__=='__main__':main()