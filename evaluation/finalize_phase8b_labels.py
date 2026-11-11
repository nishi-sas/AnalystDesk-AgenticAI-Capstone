"""Finalise explicitly human-reviewed SEC passage labels (Phase 8B dev only).

WARNING: This helper cannot independently verify that a reviewer actually read the sources.
Only run after examining and, if necessary, editing the proposed labels.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

CORPUS_SHA = "ac3259063a7cfee9160d0f4a6e8a118335db6bca60d6fd8113dc2367dc5bade7"

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--reviewer', required=True, help='Human reviewer identifier (3–80 characters)')
    p.add_argument('--attest-reviewed', action='store_true', help='I manually reviewed relevant passages against the SEC corpus')
    args=p.parse_args()
    if not args.attest_reviewed:
        p.error('Human source review is required: use --attest-reviewed only after checking all cases')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,80}',args.reviewer):
        p.error('Reviewer identifier must be 3-80 letters/digits/underscore/dot/hyphen')
    if args.reviewer.upper().startswith(('AI','CHATGPT','AUTO','PENDING','LLM')):
        p.error('Human reviewer required; use an identifier that refers to an actual reviewer')
    root=Path.cwd().resolve(); ev=root/'evaluation'; src=ev/'retrieval_labels_dev_v1.PROPOSED.jsonl';dest=ev/'retrieval_labels_dev_v1.jsonl'; corpus=root/'data'/'parsed'/'10k_passages.jsonl'; bank=ev/'candidates_v1.jsonl'
    if any(x.is_symlink() for x in (ev,src,dest,corpus,bank)):
        p.error('Symlinked evaluation inputs or outputs are not permitted')
    if not all(x.is_file() for x in (src,corpus,bank)) or dest.exists():
        p.error('Required input is missing or final label file already exists')
    if hashlib.sha256(corpus.read_bytes()).hexdigest()!=CORPUS_SHA:
        p.error('Original SEC corpus checksum changed')
    cases={x['case_id']:x for x in (json.loads(s) for s in bank.read_text(encoding='utf8').splitlines()) if x['split']=='dev' and x['task']=='retrieval'}
    docs={x['passage_id']:x for x in (json.loads(s) for s in corpus.read_text(encoding='utf8').splitlines())}
    entries=[json.loads(s) for s in src.read_text(encoding='utf8').splitlines() if s.strip()]
    if len(entries)!=8 or {x.get('case_id') for x in entries}!=set(cases):
        p.error('Proposed labels do not match all eight development cases')
    for x in entries:
        c=cases[x['case_id']]; ids=x.get('relevant_passage_ids')
        if not isinstance(ids,list) or not ids or len(ids)>30 or len(set(ids))!=len(ids):
            p.error('Invalid reference list in '+x['case_id'])
        if any(pid not in docs or docs[pid]['ticker'] not in c['companies'] or docs[pid]['item']!=c['item'] or docs[pid]['report_date']!=c['reported_period'] for pid in ids):
            p.error('Reference not found in correct canonical SEC scope for '+x['case_id'])
        if x.get('unanswerable') is not False or not isinstance(x.get('reason'),str) or len(x['reason'])<15:
            p.error('Invalid or missing label explanation for '+x['case_id'])
        x['reviewer']=args.reviewer
        x['reviewed_against_corpus']=True
    with dest.open('x',encoding='utf8') as f:
        for x in entries:f.write(json.dumps(x,ensure_ascii=False,sort_keys=True)+'\n')
    print('Human-attested relevance file created:',dest)
    print('Cases:',len(entries),'  Reference passages:',sum(len(x['relevant_passage_ids']) for x in entries))
    print('Reminder: This is a reviewed DEVELOPMENT reference set, not held-out or exhaustive corpus gold.')

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError) as e:
        print('PHASE8B_LABEL_FINALIZE_ERROR:',type(e).__name__,str(e)[:140],file=sys.stderr)
        sys.exit(2)
