"""No provider network calls and no model downloads during unit tests."""
from __future__ import annotations
import json
from types import SimpleNamespace
import pytest
from analyst_desk.phase6a_models import (
    scope_verdict, llama_guard_verdict, PromptGuard2CPU, GuardModelError,
    load_model_classifiers, _label_score,
)
from analyst_desk.input_guardrails import run_input_guardrails

CLEAN = 'Compare MSFT and GOOGL annual SEC filings and revenue risks.'


class DummyClient:
    def __init__(self, content):
        self.content = content
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.content, Exception):
            raise self.content
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])


@pytest.mark.parametrize('content,result', [('{"in_scope":true}',True),('{"in_scope":false}',False)])
def test_scope_json_true_false(content, result):
    client = DummyClient(content)
    assert scope_verdict(CLEAN, client=client)['in_scope'] is result
    assert client.calls[0]['messages'][1]['role'] == 'user'
    assert 'untrusted_research_request' in client.calls[0]['messages'][1]['content']


@pytest.mark.parametrize('content', ['```json\n{"in_scope":true}\n```', '{"in_scope":1}',
                                     '{"in_scope":true,"approve":true}', '{}', 'yes', 'null'])
def test_scope_strict_schema_rejects(content):
    with pytest.raises(GuardModelError):
        scope_verdict(CLEAN, client=DummyClient(content))


@pytest.mark.parametrize('content,expected', [('safe',True),('unsafe\nS6',False),('unsafe\nS7,S14',False)])
def test_llama_guard_exact_labels(content,expected):
    client = DummyClient(content)
    assert llama_guard_verdict(CLEAN,client=client)['safe'] is expected
    assert client.calls[0]['model'] == 'meta/llama-guard-4-12b'
    assert client.calls[0]['max_tokens'] <= 30


@pytest.mark.parametrize('content', ['Safe','safe\nS6','unsafe\nUNKNOWN','unsafe\nS15','absolutely safe',
                                     'safe because this is fine','unsafe\nS1\nanything'])
def test_llama_guard_fails_closed_on_unrecognized_text(content):
    with pytest.raises(GuardModelError):
        llama_guard_verdict(CLEAN,client=DummyClient(content))


def test_prompt_guard_labels_and_probabilities():
    assert _label_score([{'label':'benign','score':0.75},{'label':'malicious','score':0.25}]) == .25
    assert _label_score([{'label':'LABEL_0','score':0.75},{'label':'LABEL_1','score':0.25}]) == .25
    with pytest.raises(GuardModelError):
        _label_score([{'label':'benign','score':0.3},{'label':'malicious','score':0.1}])
    with pytest.raises(GuardModelError):
        _label_score([{'label':'benign','score':0.75}])


class FakeTokenizer:
    def encode(self,s,add_special_tokens=False):
        return list(range(len(s)))
    def decode(self,ids,skip_special_tokens=True):
        return 'X'*len(ids)


class FakePipeline:
    tokenizer = FakeTokenizer()
    def __init__(self):
        self.calls = []
    def __call__(self,text,**kwargs):
        self.calls.append((text,kwargs))
        i = len(self.calls)
        score = [.1,.8,.2][min(i-1,2)]
        return [{'label':'BENIGN','score':1-score},{'label':'MALICIOUS','score':score}]


def test_prompt_guard_cpu_chunking_no_truncation_or_undetected_final_chunk():
    pipe = FakePipeline()
    pg = PromptGuard2CPU(pipeline_factory=lambda *args,**kwargs:pipe)
    assert pg('A'*960) == .8
    assert [len(x[0]) for x in pipe.calls] == [480,480,64]
    assert all(v['max_length'] == 512 for _,v in pipe.calls)


def test_model_callbacks_routed_through_existing_policy_and_fail_closed():
    models=load_model_classifiers(scope_client=DummyClient('{"in_scope":true}'),
                                  safety_client=DummyClient('safe'),prompt_guard=lambda _:0.01,safety_provider='nvidia')
    decision=run_input_guardrails(CLEAN,'demo_analyst',**models.guardrail_kwargs())
    assert decision.passed
    assert [c['status'] for c in decision.checks if c['code'] in ('SCOPE_MODEL','INJECTION_MODEL','SAFETY_MODEL')]==['PASS']*3
    assert run_input_guardrails(CLEAN,'demo_analyst',
                **load_model_classifiers(scope_client=DummyClient('{"in_scope":true}'),
                safety_client=DummyClient('unsafe\nS6'),prompt_guard=lambda _:0.01,safety_provider='nvidia').guardrail_kwargs()).block_codes==('SAFETY_MODEL',)


def test_malformed_external_provider_reply_blocks_and_does_not_log_content():
    models = load_model_classifiers(scope_client=DummyClient('secret sk-FAKE'),
                                   safety_client=DummyClient('safe'),prompt_guard=lambda _:0.0,safety_provider='nvidia')
    receipt=run_input_guardrails(CLEAN,'demo_analyst',**models.guardrail_kwargs()).receipt()
    assert 'SCOPE_MODEL_ERROR' in receipt['block_codes']
    assert 'sk-FAKE' not in json.dumps(receipt)


def test_model_loading_does_not_require_secrets_when_mocks_provided(monkeypatch):
    monkeypatch.delenv('OPENROUTER_API_KEY',raising=False)
    monkeypatch.delenv('NVIDIA_API_KEY',raising=False)
    assert load_model_classifiers(scope_client=DummyClient('{"in_scope":true}'),
                                  safety_client=DummyClient('safe'),prompt_guard=lambda _:0.0,safety_provider='nvidia')


def test_strict_graph_gate_blocks_provider_failure_before_planner(tmp_path):
    pytest.importorskip('langgraph')
    from langgraph.checkpoint.sqlite import SqliteSaver
    from analyst_desk.stage4a_graph import build_planning_graph, PlanningError
    from analyst_desk.stage4a_config import PlannerSettings
    settings=PlannerSettings('openai/gpt-5-mini','https://openrouter.ai/api/v1',10000,('MSFT','GOOGL'))
    called=[]
    def planner(*args):called.append(1);raise AssertionError('No planning allowed')
    models=load_model_classifiers(scope_client=DummyClient('invalid'),
                                  safety_client=DummyClient('safe'),prompt_guard=lambda _:0.0,safety_provider='nvidia')
    with SqliteSaver.from_conn_string(str(tmp_path/'model.sqlite3')) as saver:
        graph=build_planning_graph(settings,planner=planner,checkpointer=saver,
                                   model_classifiers=models,require_model_checks=True)
        with pytest.raises(PlanningError,match='Input security guardrail blocked'):
            graph.invoke({'request':CLEAN,'analyst_id':'demo_analyst'},
                         config={'configurable':{'thread_id':'input-model-fail'}})
    assert not called


def test_strict_graph_gate_accepts_all_three_checks(tmp_path):
    pytest.importorskip('langgraph')
    from langgraph.checkpoint.sqlite import SqliteSaver
    from analyst_desk.stage4a_graph import build_planning_graph,offline_planner
    from analyst_desk.stage4a_config import PlannerSettings
    settings=PlannerSettings('openai/gpt-5-mini','https://openrouter.ai/api/v1',10000,('MSFT','GOOGL'))
    models=load_model_classifiers(scope_client=DummyClient('{"in_scope":true}'),
                                  safety_client=DummyClient('safe'),prompt_guard=lambda _:0.0,safety_provider='nvidia')
    with SqliteSaver.from_conn_string(str(tmp_path/'model.sqlite3')) as saver:
        graph=build_planning_graph(settings,planner=offline_planner,checkpointer=saver,
                                   model_classifiers=models,require_model_checks=True)
        thread={'configurable':{'thread_id':'input-model-pass'}}
        graph.invoke({'request':CLEAN,'analyst_id':'demo_analyst'},config=thread)
        checks=graph.get_state(thread).values['input_security_checks']
        assert [c['status'] for c in checks if c['code'] in ('SCOPE_MODEL','INJECTION_MODEL','SAFETY_MODEL')]==['PASS']*3
