"""Aleph REST client.

project_y talks to OpenAleph over REST only — never imports its AGPL packages.
This module exposes a typed client plus a `DocumentSource` protocol that the
substring quote verifier (workspace C) depends on.
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
from aleph.document_source import AlephDocumentSource, DocumentSource

__all__ = [
    "AlephClient",
    "AlephDocumentSource",
    "AlephError",
    "AlephHTTPError",
    "AlephResponseError",
    "AlephTransportError",
    "AuthenticationError",
    "Collection",
    "DocumentSource",
    "DocumentText",
    "Entity",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
    "SearchResults",
    "ServerError",
]
