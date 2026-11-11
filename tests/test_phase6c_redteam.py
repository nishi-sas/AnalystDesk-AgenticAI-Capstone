"""Phase 6C: exploit-oriented deterministic checks, not mocked always-pass verdicts."""
from pathlib import Path
import json
import pytest
from analyst_desk.phase6c_redteam import (load_jsonl, validate_fixtures, evaluate_attack,
                                            run_suite, RedTeamFixtureError, _bundle)
from analyst_desk.phase6b_output import run_output_guardrails

ROOT=Path(__file__).resolve().parents[1]
ATTACKS=load_jsonl(ROOT/'security/red_team/attacks.jsonl')
BENIGN=load_jsonl(ROOT/'security/red_team/benign.jsonl')

def test_fixture_contract_and_category_counts():
    validate_fixtures(ATTACKS)
    assert len(ATTACKS)==35 and len(BENIGN)==8
    assert len({x['attack_id'] for x in ATTACKS})==35

@pytest.mark.parametrize('case',ATTACKS,ids=lambda x:x['attack_id'])
def test_each_attack_is_blocked_by_real_guardrail(case):
    decision=evaluate_attack(case)
    assert decision['met_expectation'],decision
    assert case['expected_code'] in decision['block_codes']

@pytest.mark.parametrize('case',BENIGN,ids=lambda x:x['benign_id'])
def test_legitimate_requests_not_false_blocked(case):
    from analyst_desk.phase6c_redteam import evaluate_benign
    assert not evaluate_benign(case)['blocked']

def test_suite_measures_rates_and_exposes_limitations():
    result=run_suite(ATTACKS,BENIGN)
    assert result['status']=='PASS'
    assert result['defences_on']['blocked']==35
    assert result['defences_on']['expected_codes_met']==35
    assert result['benign']['false_blocked']==0
    assert result['defences_off']['executed'] is False
    assert result['defences_off']['not_an_attack_success_measure']
    assert len(result['known_gaps'])>=4

def test_injection_payload_is_never_copied_into_policy_receipt():
    case=ATTACKS[9]
    result=evaluate_attack(case)
    assert result['blocked']
    assert case['input'] not in json.dumps(result)

def test_numeric_fact_presence_is_not_numeric_accuracy_proof():
    # This is an EXPECTED GAP, not a security acceptance success.
    # The deterministic output gate can accept fabricated percentages when
    # a valid company fact *identifier* exists; audited operand values and
    # source period verification must remain enforced upstream.
    fake='| MSFT | FY2026 | 99.99% | 99.99% |'
    decision=run_output_guardrails(_bundle(fake,{}))
    assert decision.passed, 'If fixed upstream or in 6B, update this gap test and the report'

def test_malformed_duplicate_attack_is_not_scored():
    with pytest.raises(RedTeamFixtureError):validate_fixtures(ATTACKS+[ATTACKS[0]])
