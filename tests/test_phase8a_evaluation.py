"""Phase 8A: candidate inventory is not falsely presented as independently labelled gold."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import pytest
from analyst_desk.phase8a_evaluation import (
    BANK_SHA256, EvaluationError, inventory_receipt, input_only_rows,
    load_bank, score_predictions)
from analyst_desk.phase8a_cli import main

ORIGINAL=Path(__file__).resolve().parents[1]/'evaluation/candidates_v1.jsonl'

@pytest.fixture
def root(tmp_path):
    (tmp_path/'evaluation').mkdir()
    (tmp_path/'evidence').mkdir()
    shutil.copy2(ORIGINAL,tmp_path/'evaluation/candidates_v1.jsonl')
    return tmp_path

def test_frozen_inventory_exact_counts(root):
    r=inventory_receipt(root)
    assert r['status']=='PASS_INVENTORY_NOT_GOLD'
    assert r['case_count']==60 and r['split_counts']=={'dev':20,'heldout':40}
    assert r['task_counts']=={'numeric':4,'input_policy':8,'retrieval':32,'risk':8,'citation':8}
    assert r['verified_development_labels']==12 and r['heldout_independently_labeled']==0
    assert r['pending_independent_labels']==48
    assert r['dataset_sha256']==BANK_SHA256

def test_gold_not_exposed_to_agent_inputs(root):
    rows=input_only_rows(root,'all')
    assert len(rows)==60
    assert all(set(x)=={'case_id','task','prompt','split'} for x in rows)
    assert len(input_only_rows(root,'dev'))==20
    assert len(input_only_rows(root,'heldout'))==40
    assert '46.78' not in json.dumps(rows)

@pytest.mark.parametrize('bad', ['oops','secret','DEV',''])
def test_invalid_split_failclosed(root,bad):
    with pytest.raises(EvaluationError,match='INVALID_SPLIT'):
        input_only_rows(root,bad)

@pytest.mark.parametrize('replacement', [b'46.78',b'GOOGL',b'REVENUE_GROWTH_TAG_RECONCILIATION_OPEN'])
def test_frozen_bank_mutation_refused(root,replacement):
    p=root/'evaluation/candidates_v1.jsonl'
    data=p.read_bytes()
    assert replacement in data
    p.write_bytes(data.replace(replacement,replacement+b'X',1))
    with pytest.raises(EvaluationError,match='FROZEN_BANK_DIGEST_MISMATCH'):
        load_bank(root)

def test_duplicate_case_refused_under_manual_unfrozen_validation(root):
    p=root/'evaluation/candidates_v1.jsonl'
    lines=p.read_text().splitlines()
    second=json.loads(lines[1]); second['case_id']='NUM001'
    lines[1]=json.dumps(second)
    p.write_text('\n'.join(lines)+'\n')
    with pytest.raises(EvaluationError,match='CASE_ID_SCOPE_OR_LABEL_INVALID'):
        load_bank(root,verify_frozen=False)

def test_fake_holdout_label_refused(root):
    p=root/'evaluation/candidates_v1.jsonl'
    lines=p.read_text().splitlines()
    changed=json.loads(lines[-1]); changed.update(label_state='VERIFIED_DEVELOPMENT',gold={'decision':'PASS'},evidence_ref='fake')
    lines[-1]=json.dumps(changed)
    p.write_text('\n'.join(lines)+'\n')
    with pytest.raises(EvaluationError,match='VERIFIED_CASE_UNSUPPORTED'):
        load_bank(root,verify_frozen=False)

def test_missing_gold_refused(root):
    p=root/'evaluation/candidates_v1.jsonl'
    lines=p.read_text().splitlines()
    changed=json.loads(lines[0]); changed['gold']=None
    lines[0]=json.dumps(changed)
    p.write_text('\n'.join(lines)+'\n')
    with pytest.raises(EvaluationError,match='NUMERIC_GOLD_INVALID'):
        load_bank(root,verify_frozen=False)

def test_score_empty_not_claimed_as_quality(root):
    r=score_predictions(root,[])
    assert r['status']=='DEVELOPMENT_ONLY_INCOMPLETE'
    assert r['scored_dev_count']==0
    assert r['heldout_quality_measured'] is False

def test_dev_prediction_scoring_and_warning(root):
    pred=[{'case_id':'NUM001','value_percent':'46.78','warnings':[]},
          {'case_id':'NUM004','value_percent':'15.09','warnings':[]},
          {'case_id':'SEC001','decision':'PASS'},
          {'case_id':'SEC008','decision':'BLOCKED'}]
    r=score_predictions(root,pred)
    assert r['metrics']['numeric']=={'correct':1,'total':2,'accuracy':0.5}
    assert r['metrics']['input_policy']=={'correct':2,'total':2,'accuracy':1.0}
    assert r['heldout_gold_count']==0
    pred[1]['warnings']=['REVENUE_GROWTH_TAG_RECONCILIATION_OPEN']
    r=score_predictions(root,pred)
    assert r['metrics']['numeric']['correct']==2

@pytest.mark.parametrize('bad', [
    [{'case_id':'NUM001','value_percent':'46.78'},{'case_id':'NUM001','value_percent':'46.78'}],
    [{'case_id':'HACK999','decision':'BLOCKED'}],
    [{'case_id':'NUM001','value_percent':'NaN'}],
    [{'case_id':'NUM001','value_percent':'Infinity'}],
    [{'case_id':'NUM001','value_percent':'46.78','gold':'46.78'}],
    [{'case_id':'SEC001','decision':'ALLOWED'}],
    [{'case_id':'SEC001','decision':'PASS','latency_ms':-1}],
    [{'case_id':'NUM004','value_percent':'15.09','warnings':'REVENUE_GROWTH_TAG_RECONCILIATION_OPEN'}],
])
def test_score_invalid_predictions_fail_closed(root,bad):
    with pytest.raises(EvaluationError):
        score_predictions(root,bad)

def test_unlabeled_prediction_not_scored(root):
    r=score_predictions(root,[{'case_id':'RET005','retrieved_passage_ids':['made-up-id']}])
    assert r['unlabeled_predictions_excluded']==1
    assert r['scored_dev_count']==0

@pytest.mark.parametrize('bad',[ '../.env','evidence/../.env','data/gold.json','evidence/subdir/file.json','evidence/result.txt'])
def test_cli_output_path_refused(root,bad):
    assert main(['lint','--root',str(root),'--out',bad])==2

def test_cli_lint_exclusive_receipt(root):
    args=['lint','--root',str(root),'--out','evidence/120_phase8a_inventory.json']
    assert main(args)==0
    data=json.loads((root/'evidence/120_phase8a_inventory.json').read_text())
    assert data['case_count']==60
    assert main(args)==2

def test_cli_export_only_inputs_no_gold(root):
    args=['export-inputs','--root',str(root),'--split','heldout','--out','evidence/121_phase8a_inputs.jsonl']
    assert main(args)==0
    data=(root/'evidence/121_phase8a_inputs.jsonl').read_text()
    assert len(data.splitlines())==40
    assert 'gold' not in data and 'label_state' not in data and 'evidence_ref' not in data
    assert not (root/'data').exists()

def test_cli_score_dev_bounded_and_readonly(root):
    p=root/'evidence/predictions.jsonl'
    p.write_text(json.dumps({'case_id':'SEC001','decision':'PASS'})+'\n')
    assert main(['score-dev','--root',str(root),'--predictions','evidence/predictions.jsonl',
                 '--out','evidence/122_phase8a_score.json'])==0
    out=json.loads((root/'evidence/122_phase8a_score.json').read_text())
    assert out['status']=='DEVELOPMENT_ONLY_INCOMPLETE'
    assert out['scored_dev_count']==1 and not out['heldout_quality_measured']


def test_cli_refuses_evidence_symlink(root,tmp_path):
    shutil.rmtree(root/'evidence')
    outside=tmp_path.parent/'outside_phase8a'
    outside.mkdir(exist_ok=True)
    try:
        (root/'evidence').symlink_to(outside,target_is_directory=True)
    except (OSError,NotImplementedError):
        pytest.skip('directory symlink creation unavailable on this OS')
    assert main(['lint','--root',str(root),'--out','evidence/120_phase8a_inventory.json'])==2
    assert not (outside/'120_phase8a_inventory.json').exists()
