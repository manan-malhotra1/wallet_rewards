"""Taxes module — Pricing v2 Epic 19 (Story 19.4).

Jurisdiction-wide tax rates (`tax_configs`) and the `calculate_tax`
computation of the tax on a fee and on a commission. The inclusive/exclusive
flags travel with the result so the charge assembler (Epic 20) can decide which
leg bears each tax.
"""

from app.modules.taxes.router import router
from app.modules.taxes.service import (
    TaxComputation,
    calculate_tax,
    create_tax_config,
    delete_tax_config_for_scope,
    list_tax_configs,
)

__all__ = [
    "TaxComputation",
    "calculate_tax",
    "create_tax_config",
    "delete_tax_config_for_scope",
    "list_tax_configs",
    "router",
]
