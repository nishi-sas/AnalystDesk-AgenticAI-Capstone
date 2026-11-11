"""Phase 8A: frozen evaluation inventory, gold isolation, and conservative scoring.

The 60-case inventory is NOT a 60-case independently adjudicated gold set.
Only 12 previously documented development cases have verified labels. Forty
held-out questions remain UNLABELLED. Until adjudicated by an independent
reviewer, no held-out success rate is valid. No model/MCP/network calls here.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
from typing import Any

BANK_REL = 'evaluation/candidates_v1.jsonl'
BANK_SHA256 = 'dc4a443ea104083e1574e1740862df1996d8b2b45d9001e76469fdca863547e3'
TASKS = {'numeric':4, 'input_policy':8, 'retrieval':32, 'risk':8, 'citation':8}
LABELS = {'VERIFIED_DEVELOPMENT', 'PENDING_INDEPENDENT_LABEL'}
ALLOWED_SPLITS = {'dev','heldout'}
CASE_ID = re.compile(r'(?:NUM|SEC|RET|RISK|CITE)\d{3}\Z')
LABELABLE = {'numeric', 'input_policy', 'retrieval', 'citation'}

class EvaluationError(ValueError):
    """Malformed or unfrozen evaluation data; never silently score it."""


def _fail(code: str):
    raise EvaluationError(code)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_bank(root: Path, *, verify_frozen: bool = True) -> list[dict[str, Any]]:
    root = Path(root).resolve()
    base = root/'evaluation'
    path = base/'candidates_v1.jsonl'
    if (base.is_symlink() or path.is_symlink() or not path.is_file() or
            not path.resolve().is_relative_to(root) or path.stat().st_size > 180_000):
        _fail('BANK_PATH_OR_SIZE_UNSAFE')
    digest = _hash(path)
    if verify_frozen and digest != BANK_SHA256:
        _fail('FROZEN_BANK_DIGEST_MISMATCH')
    try:
        rows = [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]
    except (ValueError, UnicodeError) as exc:
        raise EvaluationError('BANK_INVALID_JSONL') from exc
    if len(rows) != 60:
        _fail('BANK_CASE_COUNT_INVALID')
    ids = set()
    counts, splits = Counter(), Counter()
    verified = 0
    for c in rows:
        if not isinstance(c,dict) or not {'case_id','split','task','prompt','gold','label_state','evidence_ref'}.issubset(c):
            _fail('CASE_SCHEMA_INVALID')
        cid, split, task, prompt, label = (c.get(k) for k in ('case_id','split','task','prompt','label_state'))
        if (not isinstance(cid,str) or not CASE_ID.fullmatch(cid) or cid in ids
                or split not in ALLOWED_SPLITS or task not in TASKS
                or not isinstance(prompt,str) or not 10 <= len(prompt) <= 700
                or label not in LABELS):
            _fail('CASE_ID_SCOPE_OR_LABEL_INVALID')
        ids.add(cid); counts[task]+=1; splits[split]+=1
        if label=='VERIFIED_DEVELOPMENT':
            verified+=1
            if split!='dev' or not isinstance(c['evidence_ref'],str) or not c['evidence_ref']:
                _fail('VERIFIED_CASE_UNSUPPORTED')
            if task=='numeric':
                gold=c['gold']
                if not isinstance(gold,dict) or set(gold)!={'value_percent','required_warning'}:
                    _fail('NUMERIC_GOLD_INVALID')
                try: v=Decimal(gold['value_percent'])
                except (InvalidOperation,TypeError,ValueError): _fail('NUMERIC_GOLD_INVALID')
                if not v.is_finite():_fail('NUMERIC_GOLD_INVALID')
                if gold['required_warning'] not in (None,'REVENUE_GROWTH_TAG_RECONCILIATION_OPEN'):
                    _fail('NUMERIC_WARNING_INVALID')
            elif task=='input_policy':
                if c['gold'] not in ({'decision':'BLOCKED'},{'decision':'PASS'}):
                    _fail('POLICY_GOLD_INVALID')
            else:
                _fail('UNSUPPORTED_VERIFIED_TASK')
        elif c['gold'] is not None or c['evidence_ref'] is not None:
            _fail('PENDING_CASE_CONTAINS_GOLD')
    if counts != TASKS or splits != {'dev':20,'heldout':40} or verified!=12:
        _fail('BANK_DISTRIBUTION_CHANGED')
    return rows


def inventory_receipt(root: Path) -> dict:
    cases = load_bank(root)
    counts=Counter(c['task'] for c in cases)
    return {
        'phase':'PHASE8A_EVALUATION_INVENTORY', 'status':'PASS_INVENTORY_NOT_GOLD',
        'dataset_sha256': BANK_SHA256, 'case_count':len(cases),
        'split_counts': {'dev':20,'heldout':40}, 'task_counts':dict(sorted(counts.items())),
        'verified_development_labels':12, 'heldout_independently_labeled':0,
        'pending_independent_labels':48,
        'measured_model_quality':False,'agent_execution_performed':False,
        'limitations':[
            'The 60 cases are a frozen candidate inventory; NOT 60 independently verified gold answers',
            'Four numerical values rely on the Phase 6D2 SEC arithmetic audit; concept comparability remains blocked for GOOGL revenue growth',
            'Eight input-policy labels reuse Phase 6C development fixtures and MUST NOT be treated as held-out evidence',
            'Retrieval passage IDs and risk/citation judgments require independent labeling before held-out experiments',
            'No prediction, latency, monetary cost, judge reliability, or statistical significance measured',
        ],
    }


def input_only_rows(root: Path, split: str = 'all') -> list[dict]:
    if split not in {'all','dev','heldout'}:
        _fail('INVALID_SPLIT')
    cases=load_bank(root)
    # Agent-facing inputs never contain answer keys, expected values, label
    # state, sources used for adjudication, or reference judgments.
    return [{'case_id':c['case_id'],'task':c['task'],'prompt':c['prompt'],
             'split':c['split']} for c in cases if split=='all' or c['split']==split]


def _safe_decimal(value: Any, code: str) -> Decimal:
    if not isinstance(value, (str, int, float)) or isinstance(value,bool):
        _fail(code)
    try:
        number=Decimal(str(value))
    except (ValueError, InvalidOperation):
        _fail(code)
    if not number.is_finite() or abs(number)>Decimal('1e9'):
        _fail(code)
    return number


def score_predictions(root: Path, predictions: list[dict]) -> dict:
    """Score only frozen VERIFIED_DEVELOPMENT labels; never impute pending truth.

    This is deterministic *development diagnostic scoring*, not a held-out
    evaluation. Caller is responsible for instrumenting latency and API cost.
    """
    cases=load_bank(root)
    lookup={c['case_id']:c for c in cases}
    if not isinstance(predictions,list) or len(predictions)>60:
        _fail('INVALID_PREDICTIONS')
    seen=set(); totals=Counter(); correct=Counter(); missing=set()
    for p in predictions:
        if not isinstance(p,dict) or not isinstance(p.get('case_id'),str):
            _fail('PREDICTION_SCHEMA_INVALID')
        cid=p['case_id']
        if cid not in lookup or cid in seen or set(p)&{'gold','expected','label_state','evidence_ref'}:
            _fail('PREDICTION_UNKNOWN_DUPLICATE_OR_GOLD_LEAK')
        seen.add(cid)
        c=lookup[cid]
        if c['label_state']!='VERIFIED_DEVELOPMENT':
            # Do not score predictions against unknown labels.
            continue
        task=c['task']
        totals[task]+=1
        if task=='input_policy':
            if p.get('decision') not in ('PASS','BLOCKED','ERROR'):
                _fail('POLICY_PREDICTION_INVALID')
            correct[task]+=int(p['decision']==c['gold']['decision'])
        elif task=='numeric':
            result=_safe_decimal(p.get('value_percent'),'NUMERIC_PREDICTION_INVALID')
            warnings=p.get('warnings',[])
            if not isinstance(warnings,list) or any(not isinstance(w,str) or len(w)>128 for w in warnings):
                _fail('NUMERIC_WARNINGS_INVALID')
            gold=c['gold']
            same=abs(result-Decimal(gold['value_percent']))<=Decimal('0.005')
            warned=gold['required_warning'] is None or gold['required_warning'] in warnings
            correct[task]+=int(same and warned)
        for k in ('latency_ms','cost_usd'):
            if k in p and _safe_decimal(p[k], 'MEASUREMENT_INVALID')<0:
                _fail('MEASUREMENT_NEGATIVE')
    eligible={c['case_id'] for c in cases if c['label_state']=='VERIFIED_DEVELOPMENT'}
    missing=eligible-seen
    labeled_total=len(eligible)
    return {
        'phase':'PHASE8A_DEVELOPMENT_SCORING',
        'status':'DEVELOPMENT_ONLY_INCOMPLETE' if missing else 'DEVELOPMENT_ONLY_COMPLETE',
        'frozen_dataset_sha256':BANK_SHA256,
        'verified_dev_labels':labeled_total,'scored_dev_count':sum(totals.values()),
        'missing_verified_dev_predictions':len(missing),
        'heldout_gold_count':0,'heldout_quality_measured':False,
        'unlabeled_predictions_excluded':len(seen)-sum(totals.values()),
        'metrics':{t:{'correct':correct[t],'total':totals[t],
                      'accuracy':round(correct[t]/totals[t],4) if totals[t] else None}
                   for t in sorted({'input_policy','numeric'})},
        'measured_real_system':False,
        'limitations':['Only pre-existing development labels can be scored in Phase 8A',
                       'Numerical equality does not establish citation entailment or SEC provenance',
                       'Predictions must be collected from a separately instrumented runner'],
    }
