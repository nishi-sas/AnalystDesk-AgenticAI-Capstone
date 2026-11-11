"""Phase 8C2 independent human review of frozen Stage 4C architecture pilot.

No LLM-as-a-judge, portal writes, author approvals, or retrospective fabrication of
missing draft text. A prior summary-only 8C1 receipt cannot be quality-scored.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from .phase8c_architecture import financial_digest, BLOCKER
from .stage4c1_writer import _THEME_TITLES

class QualityReviewError(ValueError):
    pass

def fail(code):
    raise QualityReviewError(code)

def canonical(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')

def digest(obj: Any) -> str:
    return sha256(canonical(obj)).hexdigest()

def read_json(path: Path, *, max_bytes: int = 1800000) -> dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > max_bytes:
        fail('INPUT_MISSING_OR_UNSAFE')
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError):
        fail('INPUT_INVALID_JSON')
    if not isinstance(value,dict):
        fail('INPUT_NOT_OBJECT')
    return value

def check_receipt(receipt: dict, *, require_materials: bool = False) -> dict:
    if (receipt.get('phase') != 'PHASE8C_DOWNSTREAM_ARCHITECTURE_PILOT' or
        receipt.get('status') != 'PASS_PAIRED_PILOT' or
        receipt.get('publication_performed') is not False or
        receipt.get('portal_publication_performed') is not False or
        receipt.get('human_approval_performed') is not False):
        fail('RECEIPT_NOT_VALID_UNPUBLISHED_PILOT')
    arms = receipt.get('results')
    if not isinstance(arms,list) or len(arms)!=3 or {a.get('configuration') for a in arms if isinstance(a,dict)}!={'C0','C1','C2'}:
        fail('RECEIPT_ARMS_MISSING')
    finance_hash = receipt.get('financial_section_sha256')
    if not isinstance(finance_hash,str) or not re.fullmatch('[0-9a-f]{64}', finance_hash):
        fail('RECEIPT_FINANCIAL_HASH_MISSING')
    for a in arms:
        if (a.get('human_report_approved') is not False or a.get('publication_performed') is not False
            or BLOCKER not in a.get('hard_blockers',[]) or
            a.get('financial_section_sha256') != finance_hash or
            a.get('input_evidence_sha256') != receipt.get('input_evidence_sha256')):
            fail('RECEIPT_ARM_INTEGRITY_FAILED')
    materials = receipt.get('review_materials')
    if materials is None:
        if require_materials:
            fail('REPORT_TEXT_NOT_CAPTURED_REQUIRES_EXPLICIT_NEW_RUN')
        return {'status':'REPORT_TEXT_NOT_CAPTURED','quality_measured':False,
                'has_original_reports':False, 'model_calls_performed':0,
                'case_count':1,'arm_count':3,
                'next_step':'Optional opt-in live capture; existing receipt alone cannot provide independent claim assessment'}
    if (not isinstance(materials,list) or len(materials)!=3 or
            {m.get('configuration') for m in materials if isinstance(m,dict)}!={'C0','C1','C2'}):
        fail('REPORT_MATERIALS_INVALID')
    arm_map = {a['configuration']:a for a in arms}
    for m in materials:
        a = arm_map[m['configuration']]
        raw = m.get('draft_markdown')
        if (not isinstance(raw,str) or len(raw) > 180000 or not raw.startswith('# AnalystDesk') or
                sha256(raw.encode('utf-8')).hexdigest()!=a.get('final_draft_sha256') or
                m.get('draft_sha256')!=a.get('final_draft_sha256') or
                financial_digest(raw)!=finance_hash or
                m.get('human_report_approved') is not False or
                m.get('publication_performed') is not False or
                'GOOGL:REVENUE_TAG_RECONCILIATION_REQUIRED' not in raw):
            fail('CAPTURED_REPORT_INTEGRITY_FAILED')
        findings=m.get('critic_findings')
        if (not isinstance(findings,list) or len(findings)!=a.get('critic_claim_count') or
                len({f.get('claim_id') for f in findings if isinstance(f,dict)})!=len(findings)):
            fail('CAPTURED_CRITIC_METADATA_INVALID')
    return {'status':'CAPTURE_READY_FOR_INDEPENDENT_REVIEW','quality_measured':False,
            'has_original_reports':True,'model_calls_performed':0,'case_count':1,'arm_count':3}

_RISK = re.compile(r'\*\*(?P<title>[^*\n]{4,110})\*\* — (?P<text>.*?)\n\nEvidence: (?P<cites>.*?)\. \*Provisional; semantic support not yet checked\.\*', re.S)
_CITE = re.compile(r'`((?:MSFT|GOOGL)_\d{4}-\d{2}-\d{2}_Item1A_\d{5})`')
_SUMMARY = re.compile(r'### Executive summary\n\n(.*?)\n\n### Selected comparative risk evidence', re.S)
_REVERSE = {v:k for k,v in _THEME_TITLES.items()}

def claims_from_report(md: str) -> list[dict]:
    found = []
    risks = list(_RISK.finditer(md))
    if len(risks)!=4 or set(x.group('title') for x in risks)!=set(_REVERSE):
        fail('RISK_CLAIM_PARSE_FAILED')
    for m in risks:
        cites = _CITE.findall(m.group('cites'))
        if len(cites)!=len(set(cites)) or not m.group('text').strip():
            fail('RISK_CLAIM_CITATIONS_INVALID')
        found.append({'claim_id':_REVERSE[m.group('title')],
                      'text':m.group('text').strip(),'citations':cites})
    match=_SUMMARY.search(md)
    if not match:
        fail('EXECUTIVE_SUMMARY_SECTION_MISSING')
    section=match.group(1).strip()
    if 'Summary citations: ' in section:
        text, _, cite_section = section.partition('\n\nSummary citations: ')
        cites=_CITE.findall(cite_section)
        if not text or not cites or len(cites)!=len(set(cites)):
            fail('EXECUTIVE_SUMMARY_CITATIONS_INVALID')
        found.append({'claim_id':'executive_summary','text':text,'citations':cites})
    elif 'No additional narrative has been generated by the writer model.' not in section:
        fail('EXECUTIVE_SUMMARY_UNKNOWN_FORMAT')
    return found

def load_corpus(root:Path) -> tuple[dict,str]:
    path=root/'data'/'parsed'/'10k_passages.jsonl'
    if (not path.is_file() or path.is_symlink() or
            not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size>40_000_000):
        fail('CORPUS_NOT_VERIFIABLE')
    raw=path.read_bytes(); corpus_sha=sha256(raw).hexdigest()
    index={}
    try:
        for line in raw.decode('utf-8').splitlines():
            if not line.strip():continue
            x=json.loads(line); pid=x['passage_id']
            if pid in index: fail('DUPLICATE_CORPUS_PASSAGE')
            index[pid]=x
    except (ValueError, UnicodeError, KeyError, TypeError):
        fail('CORPUS_INVALID')
    return index, corpus_sha

def build_queue(root:Path, receipt:dict) -> tuple[dict,list[dict]]:
    check_receipt(receipt, require_materials=True)
    corpus, corpus_sha=load_corpus(root)
    arm_map={a['configuration']:a for a in receipt['results']}
    # Bounded stable pseudonyms, sorted by opaque identifiers rather than configuration.
    entries=sorted(receipt['review_materials'],key=lambda m:sha256((m['configuration']+m['draft_sha256']).encode()).hexdigest())
    units=[]; identity=[]
    for i,m in enumerate(entries,1):
        blind=f'Q{i:02d}'
        claims=claims_from_report(m['draft_markdown'])
        original={f['claim_id']:f for f in m['critic_findings']}
        if len(claims)!=arm_map[m['configuration']]['critic_claim_count'] or set(c['claim_id'] for c in claims)!=set(original):
            fail('CAPTURED_CLAIM_COUNT_OR_IDS_MISMATCH')
        for claim in claims:
            sources=[]
            for pid in claim['citations']:
                passage=corpus.get(pid)
                if (not passage or passage.get('item')!='1A' or
                        passage.get('ticker') not in ('MSFT','GOOGL') or
                        passage.get('report_date') not in ('2026-06-30','2025-12-31') or
                        not isinstance(passage.get('text'),str)):
                    fail('CITATION_NOT_IN_LOCAL_CANONICAL_CORPUS')
                raw=passage['text']
                sources.append({'passage_id':pid,'report_date':passage['report_date'],
                                'source_sha256':passage['source_sha256'],
                                'excerpt':raw[:2200], 'excerpt_truncated':len(raw)>2200})
            units.append({'unit_id':blind+':'+claim['claim_id'],'blind_report_id':blind,
                          'claim_id':claim['claim_id'], 'claim_text':claim['text'],
                          'citation_ids':claim['citations'], 'evidence':sources})
        identity.append({'blind_report_id':blind,'configuration':m['configuration'],
                         'draft_sha256':m['draft_sha256'],
                         'model_critic_findings':original})
    queue={'phase':'PHASE8C2_BLINDED_QUALITY_REVIEW','status':'HUMAN_LABELS_REQUIRED',
           'scope':'ONE_DEV_APPROVED_MSFT_GOOGL_TASK_NOT_HELDOUT',
           'source_receipt_sha256':digest(receipt),'corpus_sha256':corpus_sha,
           'review_units':units, 'model_critic_verdicts_exposed':False,
           'model_calls_performed':0, 'portal_publication_performed':False,
           'instructions':'Read full SEC passage in local corpus where excerpt_truncated is true. Human reviewer must independently judge each claim; citation identity alone is not entailment.'}
    return queue, identity

def label_template(queue:dict) -> list[dict]:
    h=digest(queue)
    return [{'unit_id':x['unit_id'],'queue_sha256':h,'verdict':'',
             'checked_citations':[], 'source_read_in_full':False,
             'reason':'','reviewer_id':'','human_attested':False} for x in queue['review_units']]

def score_review(receipt:dict, queue:dict, labels:list[dict]) -> dict:
    check_receipt(receipt,require_materials=True)
    if queue.get('source_receipt_sha256') != digest(receipt): fail('QUEUE_RECEIPT_BINDING_FAILED')
    if queue.get('status')!='HUMAN_LABELS_REQUIRED' or queue.get('model_critic_verdicts_exposed') is not False:
        fail('QUEUE_INVALID')
    units={u['unit_id']:u for u in queue['review_units']}
    if (not isinstance(labels,list) or len(labels)!=len(units) or
        len({l.get('unit_id') for l in labels if isinstance(l,dict)})!=len(units) or
        {l.get('unit_id') for l in labels}!=set(units)):
        fail('HUMAN_LABEL_COVERAGE_INCOMPLETE')
    qhash=digest(queue)
    for l in labels:
        unit=units[l['unit_id']]
        reviewer=l.get('reviewer_id'); checked=l.get('checked_citations'); reason=l.get('reason')
        if (l.get('queue_sha256')!=qhash or l.get('human_attested') is not True or
            l.get('source_read_in_full') is not True or
            not isinstance(reviewer,str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_-]{3,59}',reviewer) or
            reviewer.casefold() in ('model','openai','assistant','automated') or
            l.get('verdict') not in ('SUPPORTED','UNSUPPORTED','UNCERTAIN') or
            not isinstance(reason,str) or not 20<=len(reason)<=1200 or
            not isinstance(checked,list) or len(checked)!=len(set(checked)) or
            not set(checked).issubset(set(unit['citation_ids'])) or
            (unit['citation_ids'] and set(checked)!=set(unit['citation_ids'])) or
            (l.get('verdict')=='SUPPORTED' and not checked)):
            fail('HUMAN_LABEL_UNATTESTED_OR_INVALID')
    label_map={x['unit_id']:x for x in labels}
    arms={}
    for m in receipt['review_materials']:
        config=m['configuration']
        # Determine pseudonym from visible unit-to-claim coverage, never from a reviewer-supplied arm label.
        blind=next('Q'+str(i).zfill(2) for i,entry in enumerate(sorted(receipt['review_materials'],key=lambda a:sha256((a['configuration']+a['draft_sha256']).encode()).hexdigest()),1) if entry['configuration']==config)
        critiques={x['claim_id']:x['verdict'] for x in m['critic_findings']}
        ls=[l for l in labels if l['unit_id'].startswith(blind+':')]
        ct=Counter(l['verdict'] for l in ls)
        agreement=sum(l['verdict']==critiques[l['unit_id'].split(':',1)[1]] for l in ls)
        arms[config]={'reviewed_claims':len(ls),'human_supported':ct['SUPPORTED'],
                      'human_unsupported':ct['UNSUPPORTED'],'human_uncertain':ct['UNCERTAIN'],
                      'human_support_rate':round(ct['SUPPORTED']/len(ls),4),
                      'critic_human_agreement':round(agreement/len(ls),4),
                      'original_critic_verdicts':{k:ct2 for k,ct2 in sorted(Counter(critiques.values()).items())},
                      'revisions':next(a['revisions'] for a in receipt['results'] if a['configuration']==config)}
    return {'phase':'PHASE8C2_INDEPENDENT_REVIEW','status':'SCORED_HUMAN_ATTESTED_DEVELOPMENT_PILOT',
            'review_unit_count':len(labels),'reviewer_ids':sorted({l['reviewer_id'] for l in labels}),
            'quality_measured_by_human':True,'independent_reviewer_role_verified':False,
            'arms':arms,'receipt_sha256':digest(receipt),'queue_sha256':qhash,
            'publication_performed':False,'real_model_calls_performed':0,
            'limitations':['One development pilot only; no held-out performance or statistical significance',
                           'Human attestation is self-declared; reviewer independence cannot be authenticated offline',
                           'Evidence references were checked for source identity; semantic judgment depends on actual human source reading',
                           'GOOGL revenue-concept comparability remains unresolved; publication blocked',
                           'Extra Critic calls in C0/C1 are posthoc diagnostics, not equal compute budgets']}
