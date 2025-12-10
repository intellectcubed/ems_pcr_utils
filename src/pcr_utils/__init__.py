"""
PCR Utils - Utilities for creating and processing EMS Patient Care Reports
"""

__version__ = "0.1.0"

from .pcr_parser import PCRParser, PCRPollingService
from .yahoo_mail_poller import YahooMailPoller

__all__ = ["PCRParser", "PCRPollingService", "YahooMailPoller"]

# Optional imports
try:
    from .supabase_gateway import SupabaseGateway
    __all__.append("SupabaseGateway")
except ImportError:
    pass
