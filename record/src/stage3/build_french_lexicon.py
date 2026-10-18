"""Rebuild a frozen French lexicon from the supplied public Lexique table only."""
import csv, hashlib, importlib.util, io, json, sys, unicodedata
from collections import Counter, defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('frozen_french_helpers', ROOT/'src/stage3/french_lexicon.py')
F=sys.modules.get(spec.name)
if F is None:
    F=importlib.util.module_from_spec(spec);sys.modules[spec.name]=F;spec.loader.exec_module(F)
select_entries=F.select_entries

def main():
    source=ROOT/'resources/lexique/Lexique4.1.tsv'
    rows=[]; inventory=defaultdict(Counter); disagreements=Counter(); mismatches=[]; anomalies=[]
    legacy=dict(F.LEXIQUE_IPA, **{'3':'ə'})
    with source.open(encoding='utf-8',newline='') as stream:
        for raw in csv.DictReader(stream,delimiter='\t'):
            row=dict(zip(F.FIELDS,(raw[k] for k in ('1_Mot','2_Phono','3_Phono_IPA','5_Cgram','4_Lemme','10_FreqMot','25_SyllPhono','26_SyllNb'))))
            rows.append(row)
            phones=[]
            for c in unicodedata.normalize('NFD',row['ipa']):
                if unicodedata.combining(c) and phones: phones[-1]+=c
                else: phones.append(c)
            if len(phones)!=len(row['phon']):
                raise ValueError('Lexique character alignment failed')
            for a,b in zip(row['phon'],phones):
                b=unicodedata.normalize('NFC',b);inventory[a][b]+=1
                if legacy.get(a,a)!=b: disagreements[a]+=1
            if F.decode_lexique(row['phon'])!=unicodedata.normalize('NFC',row['ipa']):
                mismatches.append(row)
            if any(c in '3JHAMK\\' for c in row['phon']): anomalies.append(row)
    grouped=F.group_entries(rows);selected=F.select_entries(rows)
    ordered=[r for rs in grouped.values() for r in rs]
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,F.FIELDS,delimiter='\t',lineterminator='\n');writer.writeheader();writer.writerows(ordered)
    data=stream.getvalue().encode('utf-8')
    (ROOT/'resources/fra_lexique.tsv').write_bytes(data)
    meta=dict(source='Lexique 4.1, supplied public Lexique4.1.tsv',release='4.1',license='CC BY-SA 4.0',
        citation='New, Pallier, Schalchli, Bourgin & Gimenes (2026). Lexique 4. Behavior Research Methods 58(5): 140.',
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),sha256=hashlib.sha256(data).hexdigest(),
        builder_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),helpers_sha256=hashlib.sha256(Path(F.__file__).read_bytes()).hexdigest(),
        entries=len(rows),spellings=len(grouped),multiple_entry_spellings=sum(len(rs)>1 for rs in grouped.values()),
        maximum_frequency_ties=sum(sum(F.key(r)[0]==F.key(rs[0])[0] for r in rs)>1 for rs in grouped.values()),
        selection_policy=F.TIE_RULE,schwa_policy='A keeps every vowel; B deletes only °, keeps 2 (/ø/, including nonelidable schwa); remove ° from supplied syllables only if every remaining segment has one nucleus and concatenation matches; otherwise segmentation unset',
        nonstandard_3_policy='Official decoding preserves source literal 3; counting retains it as schwa in A/B for compatibility. relish is a declared source anomaly, not a corrected IPA claim.',
        elidable_schwa_entries=sum('°' in r['phon'] for r in rows),elidable_schwa_symbols=sum(r['phon'].count('°') for r in rows),
        legacy_mapping_disagreements=dict(disagreements),symbol_inventory=inventory,post_fix_ipa_mismatch_entries=mismatches,
        source_anomalies=anomalies)
    (ROOT/'resources/fra-lexique-provenance.json').write_text(json.dumps(meta,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    print(json.dumps({k:v for k,v in meta.items() if k in {'entries','spellings','multiple_entry_spellings','maximum_frequency_ties','elidable_schwa_entries','elidable_schwa_symbols','legacy_mapping_disagreements'}},sort_keys=True))
    print('Post-fix IPA mismatches:',len(mismatches),'source anomalies:',len(anomalies))
if __name__=='__main__': main()
