"""Ground the planner in real, parsed facts.

The LLM only ever sees a compact summary derived from the compiled dossier: which sources
parsed, which controls are available, and the catalogs of entity ids that actually exist.
Hypotheses and tool arguments are validated against these catalogs, so the model can never
reference a vendor, user, or account that is not in the data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from audit_compiler.agent.context import AgentContext
from audit_compiler.ir.roles import resolve_column


@dataclass
class EntityCatalog:
    vendors: set[str] = field(default_factory=set)
    users: set[str] = field(default_factory=set)
    accounts: set[str] = field(default_factory=set)

    def known(self, entity_id: str) -> bool:
        return entity_id in self.vendors or entity_id in self.users or entity_id in self.accounts


def build_entity_catalog(ctx: AgentContext) -> EntityCatalog:
    catalog = EntityCatalog()
    for table in ctx.dossier.tables:
        vendor_col = resolve_column(table, "vendor")
        user_col = resolve_column(table, "permission_user") or resolve_column(table, "changed_by")
        account_col = resolve_column(table, "account")
        approver_col = resolve_column(table, "approved_by")
        for row in table.rows:
            if vendor_col and row.get(vendor_col):
                catalog.vendors.add(row[vendor_col].strip())
            if account_col and row.get(account_col):
                catalog.accounts.add(row[account_col].strip())
            for col in (user_col, approver_col):
                if col and row.get(col) and str(row[col]).strip():
                    catalog.users.add(row[col].strip())
    # Users tend to look like MV-U05; keep entries that are short codes, drop long free text.
    catalog.users = {u for u in catalog.users if len(u) <= 12}
    return catalog


def build_dossier_summary(ctx: AgentContext, *, control_ids: list[str]) -> dict:
    """A compact, token-bounded description of the engagement for the planner."""

    catalog = build_entity_catalog(ctx)
    sources = [
        {
            "name": t.name,
            "source_type": t.source_type.value,
            "columns": list(t.columns),
            "rows": len(t.rows),
        }
        for t in ctx.dossier.tables
    ]
    return {
        "source_count": len(ctx.dossier.tables),
        "sources": sources[:40],
        "available_controls": control_ids,
        "entity_counts": {
            "vendors": len(catalog.vendors),
            "users": len(catalog.users),
            "accounts": len(catalog.accounts),
        },
        # Bounded id samples so the planner can target a concrete entity without huge prompts.
        "vendor_ids_sample": sorted(catalog.vendors)[:60],
        "user_ids": sorted(catalog.users)[:40],
        "warnings": [f"{p}: {m}" for p, m in ctx.dossier.warnings],
    }
