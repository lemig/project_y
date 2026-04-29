"""DocumentSource — re-export from the canonical location at ``aleph.document_source``.

When this module first landed it carried an inline stub Protocol with the same
shape, waiting for workspace B's Aleph client to merge. That has now landed;
the canonical Protocol + exception hierarchy live at ``aleph.document_source``.

This file is a re-export so existing imports in ``verifier.substring``,
``verifier.__init__``, and the verifier's tests keep working without churn.
The exception classes here ARE the same Python objects raised by
``aleph.AlephDocumentSource`` — the verifier's ``except DocumentNotFound:``
clauses match cleanly without any conversion layer.
"""

from __future__ import annotations

from aleph.document_source import (
    AlephDocumentSource,
    DocumentNotFound,
    DocumentSource,
    PageNotFound,
    TransientSourceError,
)

__all__ = [
    "AlephDocumentSource",
    "DocumentNotFound",
    "DocumentSource",
    "PageNotFound",
    "TransientSourceError",
]
