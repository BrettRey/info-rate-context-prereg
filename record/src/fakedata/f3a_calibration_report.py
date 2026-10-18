"""Join all candidate coverage and MC errors without hiding any scenario rows."""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('calibration_report_design',HERE/'f3a_design.py')
D=importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)
KEYS=('n_languages','setting','experiment','scenario','interval','quantity','candidate')


def read_rows(path):
    with Path(path).open() as stream:
        raw=list(csv.DictReader(stream,delimiter='\t'))
    rows=[]
    string_keys=set(KEYS)|{'phase','target','exclusion_interpretation','run_id','code_sha256'}
    for row in raw:
        converted={}
        for key,value in row.items():
            if key in string_keys or value=='':
                converted[key]=value
            else:
                try:
                    converted[key]=float(value)
                except ValueError:
                    converted[key]=value
        rows.append(converted)
    return rows


def coverage_comparison(paths):
    phases={}
    for path in paths:
        rows=read_rows(path)
        for row in rows:
            key=tuple(row[k] for k in KEYS)
            unique=(key,row['phase'])
            if unique in phases:
                raise ValueError('duplicate phase/candidate row')
            n=row['n_rep'];p=row['coverage']
            if not np.isclose(row['coverage_mcse'],np.sqrt(p*(1-p)/n),rtol=1e-10,atol=1e-12):
                raise ValueError('invalid coverage MCSE')
            if row['reference'] != (0 if row['quantity']=='R_4-R_1w' else 1):
                raise ValueError('invalid diagnostic reference')
            phases[unique]=row
    joined=[]
    for key in sorted({key for key,phase in phases}):
        left=phases.get((key,'selection'))
        right=phases.get((key,'validation'))
        row=dict(zip(KEYS,key))
        for label,source in (('selection',left),('validation',right)):
            for metric in ('coverage','coverage_mcse','coverage_gain','coverage_gain_mcse','width','n_rep','run_id'):
                row[f'{label}_{metric}']=source[metric] if source else ''
        joined.append(row)
    return joined, list(phases.values())


def make_report(out, paths):
    comparison,rows=coverage_comparison(paths)
    out=Path(out)
    historical={}
    for size in ('17','15'):
        prior=HERE.parents[1]/f'results/fakedata/f3a_design_settings_{size}.tsv'
        if prior.exists():
            for row in read_rows(prior):
                key=tuple(row[k] for k in KEYS[:-1])
                historical[key]=row
    for row in comparison:
        old=historical.get(tuple(row[k] for k in KEYS[:-1]))
        row['round2_current_coverage']=old['coverage'] if old else ''
        row['round2_current_coverage_mcse']=old['coverage_mcse'] if old else ''
    with out.with_suffix('.tsv').open('w',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=list(comparison[0]),delimiter='\t')
        w.writeheader();w.writerows(comparison)
    lines=['# T7 round 3: complete candidate coverage', '',
           'All values below are coverage ± Monte Carlo standard error. Each row has 500 '
           'replicates. Selection and validation use disjoint simulation and bootstrap seed '
           'namespaces. The 17-language grid chooses the candidate; both language counts '
           'validate that frozen choice. A blank 15-language selection cell means no separate '
           'selection was performed there. Round-2 current is the archived pre-remedy baseline; '
           'its coverage is unchanged by the new diagnostic reference. Within either phase, “gain” compares a candidate '
           'with the current interval on the same replicates.', '',
           'Panel current = basic crossed bootstrap; reverse = percentile; bias_corrected = BC; '
           'studentized = approximate finite-cluster t interval with bias-reflected centre. '
           'Language current = percentile; reverse = basic; bias_corrected = BCa; '
           'studentized = paired bootstrap-t using the delta-method influence SE.', '',
           'known_sr_language uses latent SR, without reading-sample error; it is a mechanism '
           'diagnostic, not an implementable real-data interval. Fixed/language coverage is a '
           'conditional diagnostic, since languages do not vary in that experiment.', '',
           '| Languages | Setting | Experiment | Scenario | Interval | Quantity | Candidate | Round-2 current coverage ± MCSE | Selection coverage ± MCSE | Validation coverage ± MCSE | Validation gain ± paired MCSE |',
           '|---|---|---|---|---|---|---|---:|---:|---:|---:|']
    def fmt(row,phase,metric):
        a=row[f'{phase}_{metric}'];b=row[f'{phase}_{metric}_mcse']
        return '—' if a=='' else f'{a:.3f} ± {b:.3f}'
    for row in comparison:
        lines.append('| '+' | '.join([str(row[key]) for key in KEYS]+
                     [fmt(row,'round2_current','coverage'),fmt(row,'selection','coverage'),fmt(row,'validation','coverage'),
                      fmt(row,'validation','coverage_gain')])+' |')
    lines+=['', 'The TSV beside this report retains full precision, widths, counts and run IDs. '
            'The phase files retain bias/RMSE, exclusion frequencies relative to the stated '
            'reference, unconditional sign errors, Type S, exaggeration and every MCSE. '
            'Zero observed events give a zero plug-in MCSE; this does not establish zero risk.']
    out.write_text('\n'.join(lines)+'\n')
    selection_files=[Path(path).with_suffix('.json') for path in paths
                     if any(row['phase']=='selection' for row in read_rows(path))]
    if selection_files:
        if len(selection_files)!=1:
            raise ValueError('need one frozen selection grid')
        spec=importlib.util.spec_from_file_location('report_calibration', HERE/'f3a_calibration.py')
        C=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(C)
        frozen=json.loads(selection_files[0].read_text())
        validation=[row for row in rows if row['phase']=='validation']
        decision=dict(selection=frozen['selection'],
                      validation=C.validate_choice(frozen['selection'],validation),
                      selection_sha256=hashlib.sha256(selection_files[0].read_bytes()).hexdigest(),
                      validation_language_counts=sorted({row['n_languages'] for row in validation}))
        out.with_name('f3a_calibration_decision.json').write_text(json.dumps(decision,indent=2)+'\n')
    for size in ('17','15'):
        selected=[row for row in rows if row['phase']=='validation' and row['n_languages']==size
                  and row['candidate']=='current' and row['interval'] in ('panel','language')]
        if selected:
            fields=list(selected[0])
            with out.with_name(f'f3a_design_round3_{size}.tsv').open('w',newline='') as stream:
                w=csv.DictWriter(stream,fieldnames=fields,delimiter='\t');w.writeheader();w.writerows(selected)
            summary=[f'# F3a round 3 diagnostics: {size} languages','',
                     'Fresh validation draws; current interval. 500 replicates per setting/scenario/experiment.', '']
            summary+=D.diagnostic_table(selected)+D.diagnostic_notes()
            out.with_name(f'f3a_design_round3_{size}.md').write_text('\n'.join(summary)+'\n')
    print(f'coverage report: rows={len(comparison)} phase_rows={len(rows)} MCSE_and_reference_checks=OK')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('out',type=Path)
    p.add_argument('inputs',nargs='+',type=Path)
    args=p.parse_args()
    make_report(args.out,args.inputs)
