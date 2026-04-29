"""Aleph REST client.

project_y talks to OpenAleph over REST only — never imports its AGPL packages.
This module exposes a typed client plus the canonical ``DocumentSource``
Protocol that the substring quote verifier (``src/verifier/substring.py``)
reads through.
"""

from aleph.client import (
    AlephClient,
    AlephError,
    AlephHTTPError,
    AlephResponseError,
    AlephTransportError,
    AuthenticationError,
    Collection,
    DocumentText,
    Entity,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    SearchResults,
    ServerError,
)
from aleph.document_source import (
    AlephDocumentSource,
    DocumentNotFound,
    DocumentSource,
    PageNotFound,
    TransientSourceError,
)

__all__ = [
    "AlephClient",
    "AlephDocumentSource",
    "AlephError",
    "AlephHTTPError",
    "AlephResponseError",
    "AlephTransportError",
    "AuthenticationError",
    "Collection",
    "DocumentNotFound",
    "DocumentSource",
    "DocumentText",
    "Entity",
    "NotFoundError",
    "PageNotFound",
    "PermissionDeniedError",
    "RateLimitError",
    "SearchResults",
    "ServerError",
    "TransientSourceError",
]
