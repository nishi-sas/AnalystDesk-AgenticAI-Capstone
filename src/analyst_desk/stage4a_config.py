"""Stage 4A: deterministic and secret-safe configuration for the OpenRouter planner."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Stage4AConfigError(ValueError):
    pass


@dataclass(frozen=True)
class PlannerSettings:
    model: str
    base_url: str
    token_budget: int
    allowed_tickers: tuple[str, ...]
    timeout_seconds: int = 40


def load_planner_settings(root: Path | None = None, *, load_env_file: bool = True) -> PlannerSettings:
    root = Path(root) if root is not None else PROJECT_ROOT
    if load_env_file:
        load_dotenv(root / '.env', override=False)
    models_file = root / 'config' / 'models.yaml'
    options_file = root / 'config' / 'settings.yaml'
    if not models_file.is_file() or not options_file.is_file():
        raise Stage4AConfigError('Missing config/models.yaml or config/settings.yaml')
    models = yaml.safe_load(models_file.read_text(encoding='utf-8')) or {}
    options = yaml.safe_load(options_file.read_text(encoding='utf-8')) or {}
    if not isinstance(models, dict) or not isinstance(options, dict):
        raise Stage4AConfigError('Configuration files must contain YAML mappings')
    model = os.getenv('ANALYSTDESK_LLM_MODEL') or models.get('supervisor_model')
    if not isinstance(model, str) or model.count('/') != 1:
        raise Stage4AConfigError('Configure supervisor_model with a provider/model identifier')
    model = model.strip()
    if not model or any(c.isspace() for c in model) or len(model)>120:
        raise Stage4AConfigError('Invalid supervisor model identifier')
    base_url = (os.getenv('OPENROUTER_BASE_URL') or models.get('base_url') or '').rstrip('/')
    parsed = urlsplit(base_url)
    # Restrict credentials to the intended assignment service, never a caller-provided endpoint.
    if parsed.scheme != 'https' or parsed.hostname != 'openrouter.ai' or parsed.path != '/api/v1' or parsed.username or parsed.password or parsed.port is not None or parsed.query or parsed.fragment:
        raise Stage4AConfigError('OpenRouter URL must be https://openrouter.ai/api/v1')
    budget = options.get('token_budget_per_note', 80000)
    if type(budget) is not int or not 1000 <= budget <= 200000:
        raise Stage4AConfigError('token_budget_per_note must be an integer in [1000,200000]')
    tickers = options.get('first_companies', ['MSFT', 'GOOGL'])
    if not isinstance(tickers, list) or not tickers or not all(isinstance(t, str) and t.isupper() and t.isalpha() and 1 < len(t) < 7 for t in tickers):
        raise Stage4AConfigError('first_companies must be a list of uppercase ticker identifiers')
    from .verified_runtime_profile import permitted_company_tickers
    company_allowlist = permitted_company_tickers(root, tuple(dict.fromkeys(tickers)))
    return PlannerSettings(model=model, base_url=base_url, token_budget=budget, allowed_tickers=company_allowlist)


def require_openrouter_key(root: Path | None = None) -> str:
    root = Path(root) if root is not None else PROJECT_ROOT
    load_dotenv(root / '.env', override=False)
    value = os.getenv('OPENROUTER_API_KEY', '').strip()
    if not value or value in {'YOUR_REPLACEMENT_KEY', 'sk-or-...'}:
        raise Stage4AConfigError('Set OPENROUTER_API_KEY in an untracked .env file or environment variable')
    return value
