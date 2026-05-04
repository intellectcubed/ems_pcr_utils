"""
PCR Utils - Utilities for creating and processing EMS Patient Care Reports
"""

__version__ = "0.1.0"

__all__ = ["PCRParser", "PCRPollingService", "YahooMailPoller"]


def __getattr__(name):
    if name == "PCRParser":
        from .pcr_parser import PCRParser
        return PCRParser
    if name == "PCRPollingService":
        from .pcr_service import PCRPollingService
        return PCRPollingService
    if name == "YahooMailPoller":
        from .yahoo_mail_poller import YahooMailPoller
        return YahooMailPoller
    if name == "SupabaseGateway":
        from .supabase_gateway import SupabaseGateway
        return SupabaseGateway
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
