"""Rules module — rule CRUD + the engine that evaluates events.

Implements PRD Module 9 (Pay-PRD-0530 to 0624). Phase C implements only
the `first_time` and `milestone` rule types. The full 7-type schema is in
place so adding more types is a code-only change.
"""
from app.modules.rules.router import router

__all__ = ["router"]
