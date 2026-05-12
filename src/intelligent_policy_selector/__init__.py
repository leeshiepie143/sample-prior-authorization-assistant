"""
Intelligent Policy Selector module.

This module replaces the separate SearchPolicies and SelectBestPolicy steps
with a single KB-powered intelligent selection.
"""

from .handler import lambda_handler, health_check

__all__ = ['lambda_handler', 'health_check']
