"""§4b: separate B/10 KenLM training/test sensitivity for named universes.

Inputs are supplied jobs with word-corpus-v1 files, never discovered corpora.
Each file additionally declares source_units (stable original-unit IDs) and
source_ends (cumulative syllable endpoints). These let all language options use
the SAME first-listed source cut-off even when their token counts differ.
Validation membership/settings/seed remain fixed. Default: 100 paired refits,
training cap floor(B/10), original test membership sampled in full, compared
ONLY with unresampled B/10. An optional --test-budget cuts shared source units.
Every unsupported/failed job and unavailable universe draw is recorded.

Example after the freeze (use --freeze-archive/--freeze-proof/--block-headers):
python -I -B src/stage6/refit_sensitivity.py JOBS.json NAMED.json OUT.json --budget 10000000
"""
# Retain the executed module code and source for the freeze lock (src/stage3/freeze.py).
import sys as _freeze_sys
from pathlib import Path as _FreezePath
__freeze_module_code__ = _freeze_sys._getframe().f_code
__freeze_source__ = _FreezePath(__file__).read_bytes()
# All public inputs use the same recursive iterable boundary.
import importlib.util as _boundary_import
from pathlib import Path as _BoundaryPath
_boundary_spec = _boundary_import.spec_from_file_location("stage6_refit_sensitivity_iterables", _BoundaryPath(__file__).resolve().parents[1] / "stage5/iterables.py")
_boundary_module = _boundary_import.module_from_spec(_boundary_spec)
_boundary_spec.loader.exec_module(_boundary_module)
_boundary = _boundary_module.boundary

import os
for _key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS',
             'VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_key]='1'
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import time
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
@_boundary
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module
R=load('sensitivity_runner',ROOT/'src/stage5/runner.py')
W=load('sensitivity_rungs',ROOT/'src/stage5/rungs.py')
P=load('sensitivity_pipeline',ROOT/'src/stage4/pipeline.py')
A=load('sensitivity_analysis',ROOT/'src/stage6/analysis.py')
NAMED=load('sensitivity_named',ROOT/'src/stage6/named_universes.py')
RUNGS=R.RUNGS


@_boundary
def read_documents(job):
    """Require source-unit provenance; option-specific token caps are forbidden."""
    result={}
    membership=job['documents']
    if set(membership)!={'train','validation','test'}:
        raise ValueError('declare train, validation and test membership')
    seen=set()
    for split in ('train','validation','test'):
        ids=membership[split]
        entries=job['word_corpora'][split]
        if not ids or len(set(ids))!=len(ids) or tuple(e['document'] for e in entries)!=ids or seen.intersection(ids):
            raise ValueError('unique disjoint document membership in declared order required')
        seen.update(ids); documents={}
        for entry in entries:
            value=json.loads(R.local(entry['path']).read_text())
            if value.get('schema')!='word-corpus-v1' or value.get('document')!=entry['document']:
                raise ValueError('word corpus has wrong document identity')
            vectors=[value.get(k) for k in ('syllables','initial','starts')]
            if any(not isinstance(v,list) or any(type(x) is not int for x in v) for v in vectors):
                raise ValueError('integer word corpus vectors required')
            corpus=W.Corpus(*vectors)
            units,ends=value.get('source_units'),value.get('source_ends')
            if (not isinstance(units,list) or not units or any(not isinstance(u,str) or not u for u in units)
                    or len(set(units))!=len(units) or not isinstance(ends,list) or len(ends)!=len(units)
                    or any(type(e) is not int or e<0 for e in ends)
                    or any(a>b for a,b in zip(ends,ends[1:])) or ends[-1]!=len(corpus.s)):
                raise ValueError('source_units/source_ends are required for shared source cut-offs')
            resets=value.get('reset_starts')
            if resets is not None and (not isinstance(resets,list) or not resets or resets[0]!=0
                    or any(type(x) is not int for x in resets) or resets!=sorted(set(resets))
                    or not set(resets).issubset(set(vectors[2]))):
                raise ValueError('word-corpus reset starts must be ordered declared sequence starts')
            documents[entry['document']]=dict(corpus=corpus,source_units=units,source_ends=ends,reset_starts=resets)
        result[split]=documents
    return result


@_boundary
def source_plan(reference, draw, budget):
    """Cut once in first-listed source units, including repeated document copies."""
    if type(budget) is not int or budget<1:
        raise ValueError('positive integer reduced source budget required')
    plan=[]; used=0
    for document in draw:
        ends=reference[document]['source_ends']; stop=0
        while stop<len(ends) and used+ends[stop]<=budget:
            stop+=1
        if stop:
            plan.append(dict(document=document,source_units=stop))
            used+=ends[stop-1]
        if stop<len(ends):
            break
    if not plan or used==0:
        raise ValueError('source budget retains no supported syllables')
    return plan


@_boundary
def materialize(documents, reference, plan, treatment):
    """Copies preserve line treatment; every document copy resets context.

    Running treatment keeps each document's declared resets (masked-line gaps)
    as well as its start; ordinary line starts are crossed.
    """
    if treatment not in ('bounded','running'):
        raise ValueError('declare bounded or running line treatment')
    corpora=[]
    for row in plan:
        name,n=row['document'],row['source_units']
        value=documents[name]; base=reference[name]
        if value['source_units']!=base['source_units']:
            raise ValueError('options do not share the same original source units')
        end=value['source_ends'][n-1]
        if end==0:
            raise ValueError('sampled source document unavailable under an option')
        original=value['corpus']
        if treatment=='bounded':
            starts=original.starts[original.starts<end]
        else:
            resets=value.get('reset_starts')
            if resets is None:
                if [int(x) for x in original.starts]!=[0]:
                    raise ValueError('running-context word corpora must declare reset_starts')
                resets=(0,)
            resets=np.asarray(resets,dtype=original.starts.dtype)
            starts=resets[resets<end]
        corpora.append(W.Corpus(original.s[:end],original.b[:end],starts))
    syllables=[]; flags=[]; starts=[]
    for corpus in corpora:
        starts.extend((corpus.starts+len(syllables)).tolist())
        syllables.extend(corpus.s); flags.extend(corpus.b)
    return W.Corpus(syllables,flags,starts),corpora


@_boundary
def fit_ladder(job,train,validation,test_documents,scratch,rungs):
    """Held-out models at every rung; training plug-ins reported separately.

    The existing candidate scorer supplies the outcome normalisation; plain
    2--4 use the pipeline's adapter. Effective corpus starts already include
    all required line/document resets, so the scorer uses bounded treatment.
    """
    settings=R.estimator_settings(job)
    if settings.get('name')!='kenlm':
        raise ValueError('reduced-budget sensitivity supports KenLM only')
    guard=R.DiskGuard(work=scratch)
    guard.mkdir(scratch)
    test_s=[]; test_b=[]; starts=[]
    for corpus in test_documents:
        starts.extend((corpus.starts+len(test_s)).tolist()); test_s.extend(corpus.s); test_b.extend(corpus.b)
    test=W.Corpus(test_s,test_b,starts)
    peak=job.get('peak_bytes')
    if type(peak) is not int or peak<=0:
        raise ValueError('declare a positive measured/declared peak_bytes per fit')
    scores={}; started=time.monotonic()
    for rung in rungs:
        if rung not in RUNGS:
            raise ValueError('unsupported sensitivity rung')
        mode = job['rungs'][rung]['score_mode']
        if mode not in ('raw', 'normalised'):
            raise ValueError('declare score_mode: raw or normalised')
        counts=dict(n_train=len(train.s),n_validation=sum(len(v['corpus'].s) for v in validation.values()),n_test=len(test.s))
        encoding=rung if rung not in ('2','3','4') else '1'
        arpa=scratch/'model.arpa'; binary=scratch/'model.bin'; tmp=scratch/'tmp'
        training=testing=None
        try:
            guard.mkdir(tmp)
            training,testing=W.write_files(train,test,encoding,'bounded',scratch)
            order=1 if rung=='0' else int(rung[0])+1
            command=[str(R.KENLM/'lmplz'),'-o',str(order),'-S',settings['memory'],'-T',str(tmp)]
            guard.check(peak)
            with training.open('rb') as source, arpa.open('wb') as destination:
                built=R.kenlm_child(command,guard,None,peak,stdin=source,stdout=destination,stderr=subprocess.PIPE)
            log=built.stderr.decode()
            if built.returncode:
                if 'BadDiscountException' not in log and 'Could not calculate Kneser-Ney discounts' not in log:
                    raise RuntimeError(log[-2000:])
                with training.open('rb') as source, arpa.open('wb') as destination:
                    built=R.kenlm_child(command+['--discount_fallback']+list(map(str,settings['fallback'])),
                        guard,None,peak,stdin=source,stdout=destination,stderr=subprocess.PIPE)
                log+=built.stderr.decode()
                if built.returncode:
                    raise RuntimeError(log[-2000:])
            if order>1:
                built=R.kenlm_child([str(R.KENLM/'build_binary'),str(arpa),str(binary)],guard,None,peak,
                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                if built.returncode:
                    raise RuntimeError(built.stderr.decode()[-2000:])
            import kenlm
            model=kenlm.Model(str(binary)) if order>1 and mode=='normalised' else None; losses=[]
            for corpus in test_documents:
                if mode=='raw':
                    # Use the runner's own OOV route and target vocabulary.
                    # Re-encode each document separately to reset its context.
                    training,testing=W.write_files(train,corpus,encoding,'bounded',scratch)
                    prefix='b' if '-free' in rung or '-charged' in rung else ('s' if rung=='1w' else None)
                    kwargs={'outcome_policy':'current-boundary'} if rung.endswith('-free') else {}
                    raw,norm,n,oov=R.score(arpa,binary,testing,order,prefix,**kwargs)
                    result=dict(raw_bits=raw,test_bits=norm,n_scored=n,oov=oov)
                else:
                    result=P.score_candidate(W,model,arpa,corpus,rung,'bounded')
                if result['n_scored']!=len(corpus.s) or (mode=='normalised' and result['oov']):
                    raise ValueError('unsupported or incomplete refit score')
                losses.append(dict(loss_sum_bits=result['raw_bits' if mode=='raw' else 'test_bits']*len(corpus.s),n_tokens=len(corpus.s)))
            del model
            score=sum(row['loss_sum_bits'] for row in losses)/len(test.s)
            scores[rung]=dict(counts,id_bits=score,density_source='heldout_model',n_scored=len(test.s),document_copies=losses,
                             fallback_orders=R.F.discounts(log)[0],discounts=R.F.discounts(log)[1])
            if rung in ('0','1w'):
                scores[rung]['plugin']=dict(id_bits=W.plugin(train,rung,'bounded'),
                    density_source='training_plugin',n_train=len(train.s),definition='maximum-likelihood training entropy')
        finally:
            for path in (arpa,binary,training,testing):
                if path is not None:
                    path.unlink(missing_ok=True)
            shutil.rmtree(tmp,ignore_errors=True)
    return dict(scores=scores,seconds=time.monotonic()-started)


@_boundary
def selected_universes(jobs,named):
    """Collapse identical named combinations; never choose a result's extrema."""
    declarations=NAMED.consume(named).get('kenlm',[])
    if not declarations:
        raise ValueError('declare KenLM named universes')
    choices={}; references={}; declared=set()
    for declaration in declarations:
        if declaration.get('status')=='pending':
            continue
        selected=[]
        for language,options in sorted(declaration['options'].items()):
            matches=[j for j in jobs if j['language']==language and j['options']==options
                     and j.get('estimator',{}).get('name','kenlm')=='kenlm'
                     and ('shared' not in declaration or j['shared']==declaration['shared'])]
            if len(matches)!=1:
                raise ValueError('named sensitivity universe must identify exactly one job per language/setting')
            selected.append(matches[0])
        if len(selected)<3 or any(j['shared']!=selected[0]['shared'] for j in selected):
            raise ValueError('named universe needs three languages at one shared setting')
        name_key=R.canonical([selected[0]['shared'],declaration['name']])
        if name_key in declared:
            raise ValueError('duplicate named sensitivity universe')
        declared.add(name_key)
        key=R.digest([(j['language'],j['shared'],j['options']) for j in selected])
        choices.setdefault(key,dict(names=[],jobs=selected))['names'].append(declaration['name'])
        if declaration['name']=='first-listed':
            for job in selected:
                references[R.canonical([job['language'],job['shared']])]=job
    return choices,references


@_boundary
def draw_documents(job,split,documents,replicate,seed):
    alignment=job.get('document_alignment' if split=='test' else 'training_document_alignment')
    units=alignment['source_units'] if alignment else {d:d for d in documents}
    if set(units)!=set(documents) or len(set(units.values()))!=len(units):
        raise ValueError('invalid sensitivity document alignment')
    order=sorted(documents,key=units.get)
    namespace=['aligned',alignment['group']] if alignment else ['language',job['language']]
    block=R.digest([seed,replicate,split,namespace,[units[d] for d in order]])
    draw_seed=int(block[:16],16)
    if replicate==-1:
        return list(documents),None
    draw=np.random.default_rng(draw_seed).integers(0,len(order),len(order))
    return [order[i] for i in draw],draw_seed


@_boundary
def run(jobs,named,work,budget,n_refits=100,seed=2026101011,test_budget=None,
        rungs=RUNGS,fit_score=None,checkpoint=None,freeze_archive=None,freeze_proof=None,block_headers=None,
        fit_score_version='simulated-callback-v1'):
    """Sequential refits. A callback is injectable for small simulated unit tests."""
    if not jobs or type(budget) is not int or budget<10 or type(n_refits) is not int or n_refits<2:
        raise ValueError('positive full budget >=10 and at least two refits required')
    authorization=None
    if any(j.get('simulated') is not True for j in jobs):
        E=load('sensitivity_freeze_gate',ROOT/'src/stage3/segment_entropy.py')
        authorization=E.entropy_authorization(freeze_archive=freeze_archive,freeze_proof=freeze_proof,block_headers=block_headers)
        for j in jobs:
            t=j.get('tokenisation') if isinstance(j.get('tokenisation'),dict) else {}
            if j.get('simulated') is not True and (t.get('production_ready') is not True or not t.get('mask_sha256')):
                raise ValueError('real jobs require production-ready tokenisation under a frozen removal mask')
        R.one_mask_per_language(jobs)
        if fit_score is not None:
            raise ValueError('custom sensitivity callbacks are simulated-only')
    reduced=budget//10
    if (test_budget is not None and (type(test_budget) is not int or test_budget<1)) or not rungs or len(set(rungs))!=len(rungs):
        raise ValueError('positive test budget and distinct rungs required')
    choices,references=selected_universes(jobs,named)
    active={R.digest([j['language'],j['shared'],j['options']]):j for c in choices.values() for j in c['jobs']}
    if any(R.canonical([j['language'],j['shared']]) not in references for j in active.values()):
        raise ValueError('first-listed reference jobs must be declared for every language/setting')
    rates={}
    for job in active.values():
        rate=job.get('rates',{}).get('mean_sr')
        if not isinstance(rate,(int,float)) or not np.isfinite(rate) or rate<=0:
            raise ValueError('declare finite positive canonical language rates')
        key=R.canonical([job['language'],job['shared']])
        if key in rates and rate!=rates[key]:
            raise ValueError('canonical SR must agree across language options')
        rates[key]=rate
    documents={}; preparation={}
    for key,job in active.items():
        try:
            documents[key]=read_documents(job)
        except (ValueError,KeyError,OSError) as error:
            preparation[key]=str(error)
    work=R.local(work)
    if work==R.ROOT:
        raise ValueError('dedicated sensitivity work directory required')
    guard=R.DiskGuard(work=work); guard.mkdir(work)
    source_hashes={}
    for key,job in active.items():
        for entries in job.get('word_corpora',{}).values():
            for entry in entries:
                try:
                    source_hashes[entry['path']]=R.file_hash(R.local(entry['path']))
                except (OSError,ValueError) as error:
                    source_hashes[entry['path']]=dict(unavailable=str(error))
                    preparation.setdefault(key,str(error))
    config=dict(schema='kenlm-reduced-sensitivity-4b-v1',budget_full=budget,budget_train=reduced,budget_test=test_budget,
                n_refits=n_refits,seed=seed,rungs=list(rungs),named=named,jobs=jobs,
                source_sha256=source_hashes,
                code_sha256={Path(m.__file__).name:R.file_hash(m.__file__) for m in (R,W,P,A,NAMED,_boundary_module)},
                driver_sha256=R.file_hash(__file__),custom_callback=fit_score is not None,
                callback_version=fit_score_version if fit_score is not None else None,
                backend_version=R.kenlm_version() if fit_score is None else fit_score_version,
                numpy=np.__version__)
    config=json.loads(R.canonical(config))  # Persist/compare the existing JSON schema.
    run_id=R.digest(config)
    report=dict(config=config,run_id=run_id,kind='separate reduced-budget sensitivity distribution',rows=[],universes=[],
                compared_with='unresampled B/10 only',not_in_full_budget_interval=True,
                fixed=['original split membership','validation documents','settings','model seed','reading panel'],
                unquantified='neural training-sample variation',n_refits=n_refits,approximate_tail_count=n_refits*.05)
    checkpoint=R.local(checkpoint) if checkpoint is not None else None
    def save():
        report['rows_sha256']=R.digest(report['rows'])
        if checkpoint is not None:
            # Charge the output's OWN artifacts on its destination filesystem,
            # as well as the fit directory. Atomic old/new copies coexist.
            size=len((R.canonical(report)+'\n').encode())
            W.disk_guard(checkpoint.parent,size+16384,owned_paths=[checkpoint,checkpoint.with_suffix(checkpoint.suffix+'.tmp')])
            R.write_json(checkpoint,report,guard)
    if checkpoint is not None and checkpoint.exists():
        saved=json.loads(checkpoint.read_text())
        if saved.get('run_id')!=run_id or saved.get('config')!=config:
            raise ValueError('refit resume configuration/source/code mismatch')
        if saved.get('rows_sha256')!=R.digest(saved['rows']):
            raise ValueError('damaged saved sensitivity rows')
        report['rows']=saved['rows']
    finished={(r['replicate'],r['job_key']):r for r in report['rows']}
    if len(finished)!=len(report['rows']):
        raise ValueError('duplicate saved sensitivity rows')
    if any(rep not in range(-1,n_refits) or key not in active or row['status'] not in ('ok','unsupported','failed')
           for (rep,key),row in finished.items()):
        raise ValueError('saved sensitivity row outside declared grid')
    fit_score=fit_score or fit_ladder
    for rep in range(-1,n_refits):
        for key,job in sorted(active.items()):
            if (rep,key) in finished:
                continue
            row=dict(replicate=rep,job_key=key,language=job['language'],shared=job['shared'],options=job['options'],
                     estimator_settings=R.estimator_settings(job),model_seed=job.get('estimator',{}).get('seed',0),
                     original_membership=job['documents'],budget_train=reduced,budget_test=test_budget,
                     n_train=None,n_test=None,n_validation=None)
            scratch=work/'scratch'; started=time.monotonic()
            try:
                if key in preparation:
                    raise ValueError(preparation[key])
                own=documents[key]
                ref_job=references[R.canonical([job['language'],job['shared']])]
                ref_key=R.digest([ref_job['language'],ref_job['shared'],ref_job['options']])
                if ref_key not in documents:
                    raise ValueError('first-listed source reference unavailable')
                reference=documents[ref_key]
                if job['documents']!=ref_job['documents']:
                    raise ValueError('language options have different original split membership')
                treatment=job['shared'].get('line','bounded')
                treatment={'line-bounded':'bounded','cross-line':'running'}.get(treatment,treatment)
                plans={}; seeds={}; combined={}; copies={}
                for split,cap in (('train',reduced),('test',test_budget)):
                    draw,ds=draw_documents(ref_job,split,reference[split],rep,seed)
                    if cap is None:
                        cap=sum(reference[split][doc]['source_ends'][-1] for doc in draw)
                    plan=source_plan(reference[split],draw,cap)
                    plans[split]=plan; seeds[split]=ds
                    combined[split],copies[split]=materialize(own[split],reference[split],plan,treatment)
                row.update(source_plans=plans,draw_seeds=seeds,n_train=len(combined['train'].s),n_test=len(combined['test'].s),
                           n_validation=sum(len(v['corpus'].s) for v in own['validation'].values()))
                guard.mkdir(scratch)
                result=fit_score(job,combined['train'],own['validation'],copies['test'],scratch,rungs)
                scores=result['scores']
                if set(scores)!=set(rungs) or any(not np.isfinite(s['id_bits']) or s['id_bits']<=0 for s in scores.values()):
                    raise ValueError('unsupported/incomplete refit rung scores')
                if any(s['n_train']!=row['n_train'] or s['n_test']!=row['n_test'] for s in scores.values()):
                    raise ValueError('refit scores have incorrect actual token counts')
                row.update(status='ok',scores=scores)
            except (ValueError,KeyError,OSError,RuntimeError) as error:
                row.update(status='unsupported' if isinstance(error,(ValueError,KeyError)) else 'failed',error=str(error))
            finally:
                if scratch.exists():
                    R.empty(scratch)
            row['seconds']=time.monotonic()-started
            report['rows'].append(row); finished[rep,key]=row
            if checkpoint is not None:
                save()
    for key,choice in choices.items():
        job_keys=[R.digest([j['language'],j['shared'],j['options']]) for j in choice['jobs']]
        sr=np.log([j['rates']['mean_sr'] for j in choice['jobs']])
        values=[]; failures=[]; baseline=None
        for rep in range(-1,n_refits):
            own=[finished[rep,k] for k in job_keys]
            if any(r['status']!='ok' for r in own) or np.std(sr)==0:
                failures.append(dict(replicate=rep,unavailable=[r['language'] for r in own if r['status']!='ok'],
                                     reason='unavailable job or zero canonical SR spread'))
                continue
            ids=np.log([[r['scores'][rung]['id_bits'] for rung in rungs] for r in own])
            point,names=A.paired_values(A.ladder(ids,sr)[0],rungs)
            if rep==-1:
                baseline=point
            else:
                values.append(dict(replicate=rep,estimate=point.tolist()))
        universe=dict(names=choice['names'],quantities=A.paired_values(np.zeros(len(rungs)),rungs)[1],
                      baseline=None if baseline is None else baseline.tolist(),draws=values,unavailable=failures,
                      requested_refits=n_refits,usable_refits=len(values),failed_refits=n_refits-len(values))
        if values and baseline is not None:
            sample=np.array([v['estimate'] for v in values])
            universe['sensitivity_quantiles']=np.quantile(sample,[.05,.5,.95],axis=0).tolist()
            universe['refit_minus_unresampled']=dict(mean=(sample.mean(0)-baseline).tolist(),
                sd=sample.std(0,ddof=1).tolist() if len(sample)>1 else None,
                quantiles=np.quantile(sample-baseline,[.05,.5,.95],axis=0).tolist())
        report['universes'].append(universe)
    report['failed_job_refits']=sum(r['status']!='ok' for r in report['rows'] if r['replicate']>=0)
    report['unsupported_baselines']=sum(r['status']!='ok' for r in report['rows'] if r['replicate']==-1)
    if authorization is not None:
        E.F.unchanged_since(authorization)  # refits ran lmplz and loaded code from disk
    save()
    return report


@_boundary
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('jobs',type=Path); parser.add_argument('named',type=Path); parser.add_argument('out',type=Path)
    parser.add_argument('--budget',type=int,required=True)
    parser.add_argument('--test-budget',type=int)
    parser.add_argument('--n-refits',type=int,default=100)
    parser.add_argument('--seed',type=int,default=2026101011)
    parser.add_argument('--work',type=Path,default=Path('results/refit-sensitivity-work'))
    parser.add_argument('--rungs',nargs='+',choices=RUNGS,default=RUNGS)
    parser.add_argument('--freeze-archive',type=Path); parser.add_argument('--freeze-proof',type=Path)
    parser.add_argument('--block-headers',type=Path)
    args=parser.parse_args()
    jobs=json.loads(R.local(args.jobs).read_text()); named=json.loads(R.local(args.named).read_text())
    result=run(jobs,named,args.work,args.budget,args.n_refits,args.seed,args.test_budget,args.rungs,
               checkpoint=args.out,freeze_archive=args.freeze_archive,freeze_proof=args.freeze_proof,block_headers=args.block_headers)
    print(R.canonical(dict(run_id=result['run_id'],requested_refits=result['n_refits'],distinct_universes=len(result['universes']),
                           failed_job_refits=result['failed_job_refits'],unsupported_baselines=result['unsupported_baselines'])))

if __name__=='__main__':
    main()
