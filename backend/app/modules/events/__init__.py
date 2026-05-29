"""Events module — external source registration + event ingestion.

Implements PRD Module 8 (Pay-PRD-0480 to 0520).
"""
from app.modules.events.router import router

__all__ = ["router"]
