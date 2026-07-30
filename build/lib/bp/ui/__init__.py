"""The web interface — the intended daily surface.

The CLI is a testing scaffold; this is the product. Two rules shape everything
in this package:

**The UI contains no logic of its own.** Every endpoint calls an existing
function in :mod:`bp.ops` or :mod:`bp.roles`. Nothing here decides a status,
computes a support set, ranks a frontier or interprets a diagnostic. If the
interface needs a derived fact, the derivation goes in the core and the endpoint
returns it. That is what keeps the browser and the terminal from disagreeing
about the same graph.

**Nothing blocks.** A decomposition takes minutes on a subscription backend. Role
calls run on a background thread, the request returns a job id, and the page
polls. The interface never freezes and always says which agent is working.
"""

from .app import create_app

__all__ = ["create_app"]
