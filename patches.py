"""SSL patch for mattermostdriver.

``mattermostdriver`` calls ``ssl.create_default_context()`` without the
``purpose`` keyword argument on Python 3.10+, which triggers a deprecation
warning and may fail in strict environments.  This module monkey-patches the
standard library function to always pass ``purpose=ssl.Purpose.SERVER_AUTH``.

Call :func:`apply_ssl_patch` once, early in the startup sequence (before the
driver connects), to activate the patch for the lifetime of the process.
"""

from __future__ import annotations

import logging
import ssl

logger = logging.getLogger(__name__)


def apply_ssl_patch() -> None:
    """Monkey-patch ``ssl.create_default_context`` to force ``SERVER_AUTH``.

    Intercepts every call to the standard library function and injects
    ``purpose=ssl.Purpose.SERVER_AUTH`` into the keyword arguments.  The
    original function is still called — only the missing argument is supplied.
    """
    original = ssl.create_default_context

    def _patched(*args, **kwargs):
        logger.debug("SSL patch: forcing purpose=SERVER_AUTH.")
        kwargs["purpose"] = ssl.Purpose.SERVER_AUTH
        return original(*args, **kwargs)

    ssl.create_default_context = _patched
    logger.info("Applied SSL patch for mattermostdriver.")
