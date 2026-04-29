"""Typed REST client for OpenAleph.

project_y talks to Aleph over REST only. The AGPL Python packages
(``ftm-analyze``, ``ingest-file``, ``openaleph-procrastinate``,
``ftm-translate``, ``ftm-lakehouse``) MUST NOT be imported — see CLAUDE.md.

Only a thin slice of the Aleph API is wrapped here: the surface the v2
investigator needs (search, get one entity, get document text, list
collections). Models are FtM-shaped but use ``extra="allow"`` so unknown
fields from future Aleph versions don't break decoding.

Auth: ``Authorization: ApiKey <key>``. No JWT, no query-string fallback.
Errors are mapped to named exceptions per HTTP status; no ``except Exception:``.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

# ---------------------------------------------------------------------------
# Hashing — must match Brief.compute_hash's NFC convention (src/schema/brief.py).
# Without NFC, copy-paste / OCR / IME drift produces visually-identical strings
# that hash differently and silently orphan notes from documents.
# ---------------------------------------------------------------------------


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _sha256_nfc(s: str) -> str:
    return hashlib.sha256(_nfc(s).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AlephError(Exception):
    """Base class for every Aleph client error."""


class AlephTransportError(AlephError):
    """Network / TLS / DNS failure — request never reached Aleph or response was lost."""


class AlephResponseError(AlephError):
    """Aleph returned a response that wasn't decodable JSON or didn't match the expected shape."""


class AlephHTTPError(AlephError):
    """Aleph returned a non-2xx HTTP status without a more specific mapping below."""

    def __init__(self, status_code: int, message: str, *, body: Any = None) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.body = body


class AuthenticationError(AlephHTTPError):
    """HTTP 401 — invalid or missing API key."""


class PermissionDeniedError(AlephHTTPError):
    """HTTP 403 — caller lacks permission for the requested resource."""


class NotFoundError(AlephHTTPError):
    """HTTP 404 — entity / collection / document does not exist or is not visible."""


class RateLimitError(AlephHTTPError):
    """HTTP 429 — rate limit exceeded."""


class ServerError(AlephHTTPError):
    """HTTP 5xx — Aleph backend failure."""


# ---------------------------------------------------------------------------
# Response models (FtM-shaped where applicable). extra="allow" because Aleph
# adds fields across versions; we don't want a new field to break decoding.
# ---------------------------------------------------------------------------


class Collection(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    label: str
    foreign_id: str | None = None
    category: str | None = None
    countries: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)


class Entity(BaseModel):
    """A FollowTheMoney entity as returned by Aleph.

    ``properties`` keys vary per FtM schema. Document entities expose
    ``bodyText`` (raw text) and/or ``bodyHtml`` once OCR/extraction has
    completed — but Aleph excludes ``bodyText`` from the default detail
    response, so callers who need text should use
    :py:meth:`AlephClient.get_document_text`.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    schema_: str = Field(alias="schema")
    collection_id: str | None = None
    properties: dict[str, list[Any]] = Field(default_factory=dict)


class SearchResults(BaseModel):
    """Paginated entity search results."""

    model_config = ConfigDict(extra="allow")

    results: list[Entity]
    total: int
    limit: int
    offset: int = 0
    page: int = 1
    pages: int = 0
    next: str | None = None
    previous: str | None = None
    facets: dict[str, Any] = Field(default_factory=dict)


class DocumentText(BaseModel):
    """Text extracted from one document (or one page of a document).

    ``text`` is NFC-normalized so substring offsets line up with whatever the
    quote verifier sees. ``normalized_text_sha256`` is the sha256 of those
    NFC-normalized bytes — same convention as ``Brief.compute_hash``.

    ``extractor_version`` identifies the OCR + Aleph toolchain that produced
    the text (e.g. ``"tesseract-5.3.1@aleph-3.18"``). Aleph itself does not
    expose this in API responses, so the operator pins it on the client at
    construction time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str
    page: int | None
    text: str
    extractor_version: str
    normalized_text_sha256: str


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


def _extract_message(body: Any) -> str:
    if isinstance(body, dict):
        msg = body.get("message")
        if isinstance(msg, str) and msg:
            return msg
    return "Aleph returned an error response"


def _raise_for_status(response: httpx.Response) -> None:
    if 200 <= response.status_code < 300:
        return

    try:
        body: Any = response.json()
    except json.JSONDecodeError:
        body = response.text

    status = response.status_code
    message = _extract_message(body) if isinstance(body, dict) else (body or "")

    if status == 401:
        raise AuthenticationError(status, message, body=body)
    if status == 403:
        raise PermissionDeniedError(status, message, body=body)
    if status == 404:
        raise NotFoundError(status, message, body=body)
    if status == 429:
        raise RateLimitError(status, message, body=body)
    if status >= 500:
        raise ServerError(status, message, body=body)
    raise AlephHTTPError(status, message, body=body)


def _decode_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise AlephResponseError(
            f"Aleph response was not valid JSON: {exc.msg} (status={response.status_code})"
        ) from exc


def _join_body_text(values: list[Any]) -> str:
    """Aleph stores text properties as lists of strings; join with newlines.

    The ``\\n`` between chunks is synthesized by this client — it does not
    appear in the original extractor output. Workspace C's substring quote
    verifier MUST treat the join boundaries as untrustable: a quote that
    straddles a synthetic newline points at offsets the OCR layer never
    produced. Until we surface chunk boundaries explicitly, the verifier
    should reject any quote whose ``[start, end)`` window crosses a ``\\n``
    that lies between two source chunks.
    """
    return "\n".join(str(v) for v in values if v is not None)


class AlephClient:
    """Synchronous Aleph REST client.

    Parameters
    ----------
    base_url:
        Aleph API root including the version prefix, e.g.
        ``"http://localhost:55151/api/2"``. Trailing slashes are tolerated.
    api_key:
        API key sent as ``Authorization: ApiKey <key>``.
    timeout:
        Per-request timeout in seconds.
    extractor_version:
        Pinned identifier of the OCR + Aleph toolchain producing document
        text (e.g. ``"tesseract-5.3.1@aleph-3.18"``). Stamped on every
        :class:`DocumentText` returned by :py:meth:`get_document_text`.
    transport:
        Optional ``httpx`` transport. Provided for tests
        (``httpx.MockTransport``); production code leaves this ``None``.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        extractor_version: str = "openaleph@unknown",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url must be a non-empty URL")
        if not api_key:
            raise ValueError("api_key must be a non-empty string")
        if not extractor_version:
            raise ValueError("extractor_version must be a non-empty string")

        self._extractor_version = extractor_version
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={
                "Authorization": f"ApiKey {api_key}",
                "Accept": "application/json",
                "User-Agent": "project_y-aleph-client/0.1",
            },
            transport=transport,
        )

    # -- context manager / lifecycle ---------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "AlephClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- low-level ---------------------------------------------------------

    def _get(
        self,
        path: str,
        *,
        params: dict[str, Any] | list[tuple[str, Any]] | None = None,
    ) -> Any:
        try:
            response = self._http.get(path, params=params)
        except httpx.RequestError as exc:
            raise AlephTransportError(f"GET {path} failed: {exc}") from exc
        _raise_for_status(response)
        return _decode_json(response)

    # -- public API --------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        collection_id: str | None = None,
        schemata: list[str] | None = None,
        filters: dict[str, str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> SearchResults:
        """Full-text entity search.

        Wraps ``GET /entities``. Collection scoping uses the documented
        ``filter:collection_id`` query param. Aleph caps ``limit`` at 10_000;
        we do not enforce that here so future quota changes don't require a
        client release.

        ``schemata`` adds ``filter:schemata=<name>`` for each entry — Aleph
        expands to descendants, so ``["Document"]`` matches every file-shaped
        entity (Pages, Image, PlainText, …). ``filters`` lets the caller add
        any other ``filter:*`` param (e.g. ``{"properties.document": doc_id}``
        becomes ``filter:properties.document=<doc_id>``). Reserved ``filter:``
        keys (``collection_id``, ``schemata``) are rejected — use the dedicated
        kwargs instead so the call site is greppable.
        """
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if offset < 0:
            raise ValueError("offset must be >= 0")

        params: list[tuple[str, Any]] = [
            ("q", query),
            ("limit", limit),
            ("offset", offset),
        ]
        if collection_id is not None:
            params.append(("filter:collection_id", collection_id))
        if schemata:
            for schema in schemata:
                params.append(("filter:schemata", schema))
        if filters:
            for key, value in filters.items():
                if key in {"collection_id", "schemata"}:
                    raise ValueError(
                        f"filter key '{key}' is reserved — use the dedicated "
                        "search() kwarg instead"
                    )
                params.append((f"filter:{key}", value))

        payload = self._get("/entities", params=params)
        return _parse_model(SearchResults, payload, context="search")

    def get_entity(self, entity_id: str) -> Entity:
        """Fetch one FtM entity by id (``GET /entities/{id}``).

        ``entity_id`` is URL-quoted before being inserted into the path so an
        LLM-chosen id like ``"../collections/1"`` cannot rewrite the request
        path. Audit-grade tools cannot afford SSRF / authorization-bypass
        primitives sitting in the substrate adapter.
        """
        if not entity_id:
            raise ValueError("entity_id must be a non-empty string")
        payload = self._get(f"/entities/{quote(entity_id, safe='')}")
        return _parse_model(Entity, payload, context=f"entity {entity_id}")

    def list_collections(self, *, limit: int = 50, offset: int = 0) -> list[Collection]:
        """List collections visible to the API key."""
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if offset < 0:
            raise ValueError("offset must be >= 0")

        payload = self._get(
            "/collections", params={"limit": limit, "offset": offset}
        )
        if not isinstance(payload, dict) or "results" not in payload:
            raise AlephResponseError(
                "Aleph /collections response missing 'results' field"
            )
        results = payload["results"]
        if not isinstance(results, list):
            raise AlephResponseError(
                "Aleph /collections 'results' was not a list"
            )
        return [_parse_model(Collection, item, context="collection") for item in results]

    def get_document_text(
        self, doc_id: str, *, page: int | None = None
    ) -> DocumentText:
        """Fetch extracted text for a document (or one page of it).

        ``page=None`` returns the full document's ``properties.bodyText``.
        ``page=N`` (1-based) finds the matching ``Page`` child entity and
        returns its ``bodyText``.

        Raises :class:`NotFoundError` when:

        * no entity exists at ``doc_id``,
        * the entity has no ``bodyText`` property at all (extraction not run,
          or Aleph excluded the field — pass ``excludes=`` to the entity
          endpoint at the deployment layer to include it),
        * ``page=N`` is requested but no matching ``Page`` child exists, or
        * the page result Aleph returns does not actually belong to ``doc_id``
          / does not match ``index=N`` (defensive — Aleph's
          ``filter:properties.*`` is best-effort).

        Silent loss is unacceptable per CLAUDE.md. An empty extraction
        (``bodyText=[""]``) is allowed through and surfaces as an empty
        ``text``; missing extraction is not.

        The returned ``text`` is NFC-normalized and ``normalized_text_sha256``
        is the sha256 of those NFC-normalized bytes — the convention the
        downstream substring quote verifier reads against.
        """
        if not doc_id:
            raise ValueError("doc_id must be a non-empty string")
        if page is not None and page < 1:
            raise ValueError("page must be >= 1 (1-based) or None")

        if page is None:
            entity = self.get_entity(doc_id)
            if "bodyText" not in entity.properties:
                raise NotFoundError(
                    404,
                    f"Document {doc_id} has no bodyText property — extraction "
                    "may not have run, or Aleph excluded the field from this "
                    "response. Configure the deployment to include bodyText.",
                    body=None,
                )
            body_values = entity.properties["bodyText"]
            text = _nfc(_join_body_text(body_values))
            return DocumentText(
                doc_id=doc_id,
                page=None,
                text=text,
                extractor_version=self._extractor_version,
                normalized_text_sha256=_sha256_nfc(text),
            )

        # Page entities live as children of the parent Document. We search
        # for a Page with matching parent doc_id and 1-based index.
        params: dict[str, Any] = {
            "q": "",
            "filter:schemata": "Page",
            "filter:properties.document": doc_id,
            "filter:properties.index": str(page),
            "limit": 1,
        }
        payload = self._get("/entities", params=params)
        results = _parse_model(SearchResults, payload, context="page-lookup")
        if not results.results:
            raise NotFoundError(
                404,
                f"No Page entity with index {page} for document {doc_id}",
                body=None,
            )
        page_entity = results.results[0]

        # Aleph's filter:properties.* is best-effort (tokenized in some
        # versions); verify the result actually belongs to this doc/page
        # before trusting it. Otherwise an unrelated Page could be surfaced
        # and its text would substring-match while pointing at the wrong
        # document — a court-defensibility break.
        doc_refs = page_entity.properties.get("document", [])
        index_refs = page_entity.properties.get("index", [])
        if doc_id not in doc_refs or str(page) not in index_refs:
            raise NotFoundError(
                404,
                f"Aleph returned Page entity {page_entity.id} for "
                f"doc={doc_id} page={page}, but its properties don't match "
                f"(document={doc_refs!r}, index={index_refs!r})",
                body=None,
            )

        if "bodyText" not in page_entity.properties:
            raise NotFoundError(
                404,
                f"Page entity {page_entity.id} (doc={doc_id} page={page}) "
                "has no bodyText property",
                body=None,
            )
        body_values = page_entity.properties["bodyText"]
        text = _nfc(_join_body_text(body_values))
        return DocumentText(
            doc_id=doc_id,
            page=page,
            text=text,
            extractor_version=self._extractor_version,
            normalized_text_sha256=_sha256_nfc(text),
        )


def _parse_model(model: type, payload: Any, *, context: str) -> Any:
    """Parse a JSON payload into a pydantic model, mapping errors cleanly."""
    if not isinstance(payload, dict):
        raise AlephResponseError(
            f"Expected JSON object for {context}, got {type(payload).__name__}"
        )
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        # Catch ValidationError specifically (not its ValueError parent) so
        # bugs in custom validators surface as themselves rather than being
        # reformatted as response errors.
        raise AlephResponseError(
            f"Aleph {context} response failed validation: {exc}"
        ) from exc
