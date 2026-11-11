"""Least-privilege policy for tools. Stage 4A defines the contract; Stage 4B enforces it at MCP dispatch."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolPolicy:
    access: str  # 'read' | 'write'
    roles: frozenset[str]


_READERS = frozenset({'filing_researcher', 'risk_diff', 'quant', 'compliance_critic', 'writer'})
_TOOL_POLICIES: dict[str, ToolPolicy] = {
    'search_passages': ToolPolicy('read', _READERS),
    'get_passage': ToolPolicy('read', _READERS),
    'get_item_sections': ToolPolicy('read', _READERS),
    'kb_status': ToolPolicy('read', _READERS),
    'list_annual_filings': ToolPolicy('read', _READERS),
    'get_annual_facts': ToolPolicy('read', frozenset({'quant', 'compliance_critic'})),
    'get_annual_fact': ToolPolicy('read', frozenset({'quant', 'compliance_critic'})),
    'edgar_status': ToolPolicy('read', _READERS),
    'calculate_operating_margin': ToolPolicy('read', frozenset({'quant', 'compliance_critic'})),
    'calculate_revenue_growth': ToolPolicy('read', frozenset({'quant', 'compliance_critic'})),
    'calc_status': ToolPolicy('read', frozenset({'quant'})),
    'get_report': ToolPolicy('read', frozenset({'writer', 'publisher', 'compliance_critic'})),
    'list_reports': ToolPolicy('read', frozenset({'writer', 'publisher'})),
    'portal_status': ToolPolicy('read', frozenset({'publisher'})),
    'create_report_draft': ToolPolicy('write', frozenset({'writer'})),
    'revise_report_draft': ToolPolicy('write', frozenset({'writer'})),
    'submit_for_review': ToolPolicy('write', frozenset({'writer'})),
    'publish_report': ToolPolicy('write', frozenset({'publisher'})),
}


class ToolPermissionError(PermissionError):
    pass


def allowed_tools(role: str) -> tuple[str, ...]:
    return tuple(sorted(name for name, policy in _TOOL_POLICIES.items() if role in policy.roles))


def assert_tool_permission(role: str, tool_name: str) -> None:
    policy = _TOOL_POLICIES.get(tool_name)
    if policy is None or role not in policy.roles:
        raise ToolPermissionError(f'{role!r} is not authorized to call {tool_name!r}')


def tool_manifest() -> list[dict[str, object]]:
    return [{'name': name, 'access': spec.access, 'roles': sorted(spec.roles)} for name, spec in sorted(_TOOL_POLICIES.items())]
