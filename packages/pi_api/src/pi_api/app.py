"""The HTTP layer (design §3-§6): FastAPI routes inside three pure-ASGI guards.

Outermost first:

1. ``NoStore`` sets ``Cache-Control: private, no-store`` on every response, errors included.
2. ``ServerErrors`` turns any exception that escapes the layers below into a JSON 500, so even
   an unexpected failure goes out through ``NoStore``.
3. ``Authenticate`` verifies the Firebase ID token (``Authorization: Bearer``) on every path,
   including unknown ones, and fails closed. Cookies are never read. Verification runs in a
   worker thread because a certificate refresh is blocking I/O.
4. ``RateLimit`` is a per-uid token bucket per instance; over it answers 429 with Retry-After.

There are no unauthenticated routes: no health endpoints (Cloud Run uses a TCP startup probe)
and no docs or OpenAPI routes (the spec is exported to ``docs/contracts`` instead).
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from pi_api import export
from pi_api.analytics import (
    AssortmentQuery,
    AvailabilityQuery,
    CompareQuery,
    CompareRowsQuery,
    IndexQuery,
    LaunchesRowsQuery,
    MatchesQuery,
    MatchPage,
    PromotionsQuery,
    PromotionsRowsQuery,
    ReviewsQuery,
    StatesForbiddenError,
    capped_comparison,
    capped_launches,
    capped_promotions,
    matches,
)
from pi_api.auth import AuthError, HttpCertSource, Principal, Role, TokenVerifier
from pi_api.catalog import (
    AdminProductDetail,
    CoverageQuery,
    EvidenceHosts,
    History,
    HistoryQuery,
    InvalidQueryError,
    MetaView,
    ProductDetail,
    ProductFilters,
    ProductNotFoundError,
    ProductPage,
    ProductQuery,
    ScopeQuery,
    ScopeRef,
    StaleCursorError,
    admin_product_detail,
    find,
    history,
    meta_view,
    product_cards,
    product_detail,
    product_page,
)
from pi_api.config import Settings
from pi_api.source import (
    AmbiguousDatasetError,
    DataUnavailableError,
    GcsStore,
    Loaded,
    LocalStore,
    NotFoundError,
    ObjectStore,
    SnapshotSource,
)
from pi_api.wire import API_VERSION, ApiMeta, Envelope, ErrorBody, envelope, error_body
from pi_dataset import ContractModel
from pi_metrics import (
    AssortmentGaps,
    Availability,
    Comparison,
    Launches,
    Metric,
    PriceIndex,
    Promotions,
    ReviewsSummary,
    assortment_gaps,
    availability,
    compare,
    launches,
    price_index,
    promotions,
    reviews_summary,
)
from pi_metrics.coverage import Coverage, coverage
from pi_metrics.view import AmbiguousContext, UnknownInput

log = logging.getLogger(__name__)

CACHE_CONTROL = b"private, no-store"
PREFIX = "/api/v1"
#: Seconds a client should wait before retrying when no dataset is loaded.
UNAVAILABLE_RETRY = 30
#: Seconds a client should wait before retrying when tokens can't be verified (no signing keys).
AUTH_RETRY = 5
#: Documented on every route; all use the ``ErrorBody`` shape (FastAPI's 422 shape is replaced).
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorBody, "description": text}
    for status, text in {
        401: "missing, malformed or invalid Bearer token (WWW-Authenticate: Bearer)",
        403: "no role, or admins only",
        404: "no such route, product, market or scope",
        409: "stale_cursor: the data changed; restart from the first page",
        422: (
            "invalid_request / invalid_query / ambiguous_dataset / ambiguous_context"
            " / export_too_large"
        ),
        429: "rate_limited (Retry-After)",
        500: "internal_error: an unexpected failure; nothing about it is echoed",
        503: "data_unavailable / auth_unavailable: retry later (Retry-After)",
    }.items()
}
ProductId = Annotated[str, Path(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$")]


# ---------------------------------------------------------------- ASGI guards


async def _send_json(send: Send, status: int, body: dict[str, Any], **headers: str) -> None:
    raw = json.dumps(body, separators=(",", ":")).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(raw)).encode()),
                *((k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": raw})


class NoStore:
    """Forces ``Cache-Control: private, no-store`` and ``nosniff`` on every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def guarded(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in {b"cache-control", b"x-content-type-options"}
                ]
                headers += [
                    (b"cache-control", CACHE_CONTROL),
                    (b"x-content-type-options", b"nosniff"),
                ]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, guarded)


class ServerErrors:
    """Answers an escaped exception with a JSON 500 (inside ``NoStore``) and logs it.

    If the response had already started, it can't be replaced: the exception is logged and the
    connection ends with what was sent.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracked(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked)
        except Exception:
            log.exception("unhandled error on %s %s", scope.get("method"), scope.get("path"))
            if not started:
                await _send_json(send, 500, error_body("internal_error", "internal error"))


class Authenticate:
    """Verifies the bearer token before anything else runs; any other scope type is refused."""

    def __init__(self, app: ASGIApp, verifier: TokenVerifier) -> None:
        self.app = app
        self.verifier = verifier

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":  # websockets: none are served
            return
        values = [v for k, v in scope["headers"] if k == b"authorization"]
        try:
            if len(values) > 1:
                raise AuthError(401, "unauthenticated", "more than one Authorization header")
            header = values[0].decode("latin-1") if values else None
            principal = await run_in_threadpool(self.verifier.verify, header)
        except AuthError as error:
            extra = {
                401: {"www_authenticate": 'Bearer realm="pi-api"'},
                503: {"retry_after": str(AUTH_RETRY)},
            }.get(error.status, {})
            await _send_json(send, error.status, error_body(error.code, error.message), **extra)
            return
        scope.setdefault("state", {})["principal"] = principal
        await self.app(scope, receive, send)


class TokenBuckets:
    """Per-uid buckets, least recently used evicted beyond ``capacity`` uids."""

    def __init__(
        self,
        rate: float,
        burst: int,
        clock: Callable[[], float] = time.monotonic,
        capacity: int = 10_000,
    ) -> None:
        self.rate, self.burst, self.clock, self.capacity = rate, burst, clock, capacity
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()
        self._lock = threading.Lock()

    def take(self, uid: str) -> float:
        """0 if the request may proceed, else the seconds until a token is available."""
        now = self.clock()
        with self._lock:
            tokens, last = self._buckets.pop(uid, (float(self.burst), now))
            tokens = min(float(self.burst), tokens + (now - last) * self.rate)
            wait = 0.0 if tokens >= 1 else (1 - tokens) / self.rate
            self._buckets[uid] = (tokens - 1 if wait == 0 else tokens, now)
            while len(self._buckets) > self.capacity:
                self._buckets.popitem(last=False)
        return wait


class RateLimit:
    def __init__(self, app: ASGIApp, buckets: TokenBuckets) -> None:
        self.app = app
        self.buckets = buckets

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            principal: Principal = scope["state"]["principal"]
            wait = self.buckets.take(principal.uid)
            if wait > 0:
                body = error_body("rate_limited", "too many requests; retry later")
                await _send_json(send, 429, body, retry_after=str(max(1, math.ceil(wait))))
                return
        await self.app(scope, receive, send)


# ---------------------------------------------------------------- queries and helpers


def principal(request: Request) -> Principal:
    value: Principal = request.state.principal
    return value


#: Any signed-in role; the route only needs the guard to have run.
Viewer = Annotated[Principal, Depends(principal)]


def admin(request: Request) -> Principal:
    who = principal(request)
    if who.role is not Role.ADMIN:
        raise ForbiddenError
    return who


class ForbiddenError(Exception):
    pass


def _api_meta(loaded: Loaded, endpoint: str, filters: Mapping[str, Any]) -> ApiMeta:
    markets = loaded.dataset.meta.markets
    return ApiMeta(
        endpoint=endpoint,
        generation=loaded.generation,
        cutoff=loaded.dataset.meta.cutoff,
        market=",".join(m.country for m in markets),
        currency=",".join(sorted({m.currency for m in markets})),
        scope=loaded.scope,
        filters={k: v for k, v in filters.items() if v not in (None, (), [])},
    )


def _filters(query: ContractModel) -> dict[str, Any]:
    return query.model_dump(mode="json", by_alias=True, exclude={"cursor", "format"})


def _error(status: int, code: str, message: str, **headers: str) -> JSONResponse:
    return JSONResponse(
        error_body(code, message),
        status_code=status,
        headers={k.replace("_", "-"): v for k, v in headers.items()},
    )


def _install_handlers(api: FastAPI) -> None:
    def handle(
        kind: type[Exception], status: int, code: str, message: str | None = None, **headers: str
    ) -> None:
        async def handler(_: Request, error: Exception) -> JSONResponse:
            return _error(status, code, message or str(error) or code, **headers)

        api.add_exception_handler(kind, handler)

    handle(
        DataUnavailableError,
        503,
        "data_unavailable",
        "no dataset is loaded yet",
        retry_after=str(UNAVAILABLE_RETRY),
    )
    handle(NotFoundError, 404, "not_found", "no dataset for that market and scope")
    handle(ProductNotFoundError, 404, "not_found", "no such product")
    handle(AmbiguousDatasetError, 422, "ambiguous_dataset")
    handle(InvalidQueryError, 422, "invalid_query")
    handle(export.ExportTooLargeError, 422, "export_too_large")
    handle(
        export.ExportBusyError,
        429,
        "rate_limited",
        "too many exports running; retry later",
        retry_after=str(export.BUSY_RETRY),
    )
    handle(UnknownInput, 422, "invalid_query")
    # A retailer id with several contexts where one context is needed (ADR-0008 §2).
    handle(AmbiguousContext, 422, "ambiguous_context")
    handle(StaleCursorError, 409, "stale_cursor", "the data changed; restart from the first page")
    handle(ForbiddenError, 403, "forbidden", "admins only")
    handle(StatesForbiddenError, 403, "forbidden", "only admins may list unreviewed or rejected")

    async def invalid(_: Request, error: Exception) -> JSONResponse:
        errors = error.errors() if isinstance(error, RequestValidationError) else []
        first = errors[0] if errors else {}
        where = ".".join(str(p) for p in first.get("loc", ()))
        # The input is never echoed back.
        return _error(422, "invalid_request", f"{where}: {first.get('msg', 'invalid')}")

    async def http(_: Request, error: Exception) -> JSONResponse:
        status = error.status_code if isinstance(error, StarletteHTTPException) else 500
        code = {404: "not_found", 405: "method_not_allowed"}.get(status, "http_error")
        return _error(status, code, code.replace("_", " "))

    async def internal(_: Request, __: Exception) -> JSONResponse:
        # Starlette re-raises after this response; ServerErrors logs it then.
        return _error(500, "internal_error", "internal error")

    api.add_exception_handler(RequestValidationError, invalid)
    api.add_exception_handler(Exception, internal)
    api.add_exception_handler(StarletteHTTPException, http)


# ---------------------------------------------------------------- the app


def respond[T](
    loaded: Loaded, endpoint: str, query: ContractModel, metric: Metric[T]
) -> Envelope[T]:
    return envelope(metric, _api_meta(loaded, endpoint, _filters(query)))


def build_api(
    source: SnapshotSource,
    evidence_hosts: EvidenceHosts | None = None,
    image_hosts: EvidenceHosts | None = None,
) -> FastAPI:
    """Routes only; ``create_app`` wraps them in the guards. Exposed for the OpenAPI export."""
    api = FastAPI(
        title="Product Intelligence API",
        version=API_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        servers=[{"url": "/"}],
        responses=ERROR_RESPONSES,
    )
    _install_handlers(api)
    hosts: EvidenceHosts = {} if evidence_hosts is None else evidence_hosts
    images: EvidenceHosts = {} if image_hosts is None else image_hosts

    @api.get(f"{PREFIX}/meta", response_model=Envelope[MetaView], response_model_by_alias=True)
    def get_meta(
        query: Annotated[ScopeQuery, Query()], _: Annotated[Principal, Depends(principal)]
    ) -> Envelope[MetaView]:
        loaded = source.select(query.market, query.scope)
        refs = tuple(
            ScopeRef(
                markets=d.markets,
                scope=d.scope,
                cutoff=d.dataset.meta.cutoff,
                generation=d.generation,
            )
            for d in source.datasets()
        )
        return respond(loaded, "meta", query, meta_view(loaded.dataset, refs))

    @api.get(f"{PREFIX}/products", response_model=Envelope[ProductPage])
    def get_products(
        query: Annotated[ProductQuery, Query()], _: Annotated[Principal, Depends(principal)]
    ) -> Envelope[ProductPage]:
        loaded = source.select(query.market, query.scope)
        page = product_page(loaded.dataset, loaded.generation, query, images)
        return respond(loaded, "products", query, page)

    @api.get(f"{PREFIX}/products/{{product_id}}", response_model=Envelope[ProductDetail])
    def get_product(
        product_id: ProductId,
        query: Annotated[ScopeQuery, Query()],
        _: Annotated[Principal, Depends(principal)],
    ) -> Envelope[ProductDetail]:
        loaded = source.select(query.market, query.scope)
        detail = product_detail(loaded.dataset, find(loaded.dataset, product_id), hosts, images)
        return respond(loaded, "product", query, detail)

    @api.get(f"{PREFIX}/admin/products/{{product_id}}", response_model=Envelope[AdminProductDetail])
    def get_admin_product(
        product_id: ProductId,
        query: Annotated[ScopeQuery, Query()],
        _: Annotated[Principal, Depends(admin)],
    ) -> Envelope[AdminProductDetail]:
        loaded = source.select(query.market, query.scope)
        detail = admin_product_detail(
            loaded.dataset, find(loaded.dataset, product_id), hosts, images
        )
        return respond(loaded, "admin_product", query, detail)

    @api.get(f"{PREFIX}/products/{{product_id}}/history", response_model=Envelope[History])
    def get_history(
        product_id: ProductId,
        query: Annotated[HistoryQuery, Query()],
        _: Annotated[Principal, Depends(principal)],
    ) -> Envelope[History]:
        loaded = source.select(query.market, query.scope)
        series = history(loaded.dataset, find(loaded.dataset, product_id), query)
        return respond(loaded, "history", query, series)

    @api.get(f"{PREFIX}/coverage", response_model=Envelope[Coverage])
    def get_coverage(
        query: Annotated[CoverageQuery, Query()], _: Annotated[Principal, Depends(principal)]
    ) -> Envelope[Coverage]:
        loaded = source.select(query.market, query.scope)
        return respond(loaded, "coverage", query, coverage(loaded.dataset, query.retailer))

    _metric_routes(api, source)
    _export_routes(api, source, images)
    return api


def _metric_routes(api: FastAPI, source: SnapshotSource) -> None:
    """S3: one route per ``pi_metrics`` call (design §6); every number comes from there."""

    @api.get(f"{PREFIX}/compare", response_model=Envelope[Comparison])
    def get_compare(query: Annotated[CompareRowsQuery, Query()], _: Viewer) -> Envelope[Comparison]:
        loaded = source.select(query.market, query.scope)
        base, other = query.pair()
        metric = compare(
            loaded.dataset, base, other, query.where(), on=query.on, group_by=query.group_by
        )
        return respond(loaded, "compare", query, capped_comparison(metric, query.limit))

    @api.get(f"{PREFIX}/index", response_model=Envelope[PriceIndex])
    def get_index(query: Annotated[IndexQuery, Query()], _: Viewer) -> Envelope[PriceIndex]:
        loaded = source.select(query.market, query.scope)
        base, other = query.pair()
        metric = price_index(
            loaded.dataset, base, other, query.where(), start=query.start, end=query.end
        )
        return respond(loaded, "index", query, metric)

    @api.get(f"{PREFIX}/promotions", response_model=Envelope[Promotions])
    def get_promotions(
        query: Annotated[PromotionsRowsQuery, Query()], _: Viewer
    ) -> Envelope[Promotions]:
        loaded = source.select(query.market, query.scope)
        metric = promotions(
            loaded.dataset, query.retailer, query.where(), query.min_depth(), query.on
        )
        return respond(loaded, "promotions", query, capped_promotions(metric, query.limit))

    @api.get(f"{PREFIX}/assortment-gaps", response_model=Envelope[AssortmentGaps])
    def get_assortment_gaps(
        query: Annotated[AssortmentQuery, Query()], _: Viewer
    ) -> Envelope[AssortmentGaps]:
        loaded = source.select(query.market, query.scope)
        metric = assortment_gaps(
            loaded.dataset, query.missing_at, query.present_at, query.where(), query.on
        )
        return respond(loaded, "assortment_gaps", query, metric)

    @api.get(f"{PREFIX}/availability", response_model=Envelope[Availability])
    def get_availability(
        query: Annotated[AvailabilityQuery, Query()], _: Viewer
    ) -> Envelope[Availability]:
        loaded = source.select(query.market, query.scope)
        metric = availability(loaded.dataset, query.retailer, query.where(), query.on)
        return respond(loaded, "availability", query, metric)

    @api.get(f"{PREFIX}/launches", response_model=Envelope[Launches])
    def get_launches(query: Annotated[LaunchesRowsQuery, Query()], _: Viewer) -> Envelope[Launches]:
        loaded = source.select(query.market, query.scope)
        metric = launches(loaded.dataset, query.retailer, query.where(), query.since)
        return respond(loaded, "launches", query, capped_launches(metric, query.limit))

    @api.get(f"{PREFIX}/reviews-summary", response_model=Envelope[ReviewsSummary])
    def get_reviews_summary(
        query: Annotated[ReviewsQuery, Query()], _: Viewer
    ) -> Envelope[ReviewsSummary]:
        loaded = source.select(query.market, query.scope)
        metric = reviews_summary(loaded.dataset, query.retailer, query.where())
        return respond(loaded, "reviews_summary", query, metric)

    @api.get(f"{PREFIX}/matches", response_model=Envelope[MatchPage])
    def get_matches(query: Annotated[MatchesQuery, Query()], who: Viewer) -> Envelope[MatchPage]:
        loaded = source.select(query.market, query.scope)
        page = matches(loaded.dataset, loaded.generation, query, admin=who.role is Role.ADMIN)
        return respond(loaded, "matches", query, page)


# ---------------------------------------------------------------- exports


class ProductsExport(ProductFilters, export.FormatQuery):
    pass


class CompareExport(CompareQuery, export.FormatQuery):
    pass


class IndexExport(IndexQuery, export.FormatQuery):
    pass


class PromotionsExport(PromotionsQuery, export.FormatQuery):
    pass


class AssortmentExport(AssortmentQuery, export.FormatQuery):
    pass


class CoverageExport(CoverageQuery, export.FormatQuery):
    pass


EXPORT_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": (
            "Line 1 is the manifest (CSV: `# <JSON>` after a UTF-8 BOM; JSONL: "
            '`{"manifest": ...}`), then the rows. At most 50 000 rows, else 422 export_too_large.'
        ),
        "content": {"text/csv": {}, "application/x-ndjson": {}},
    }
}


def _download(  # noqa: PLR0913 -- the view's answer plus who asked, all keyword-only
    loaded: Loaded,
    *,
    view: export.ExportView,
    query: ContractModel,
    metric: Metric[Any],
    rows: tuple[ContractModel, ...],
    who: Principal,
    slots: export.ExportSlots,
) -> StreamingResponse:
    """Refuses over the cap or with no free slot, audits either way, then streams."""
    fmt = export.ExportFormat(query.model_dump()["format"])
    endpoint = f"export_{view}".replace("-", "_")
    head = export.manifest(view, fmt, len(rows), respond(loaded, endpoint, query, metric))
    refused = export.too_large(len(rows))
    if refused is not None:
        export.audit(who, head, export.Outcome.TOO_LARGE)
        raise refused
    if not slots.acquire():
        export.audit(who, head, export.Outcome.BUSY)
        raise export.ExportBusyError
    stream = slots.hold(export.encode(head, rows))
    try:
        export.audit(who, head)
        name = export.filename(view, fmt, loaded.dataset.meta.cutoff)
        return StreamingResponse(
            stream,
            media_type=export.MEDIA_TYPES[fmt],
            headers={"content-disposition": f'attachment; filename="{name}"'},
        )
    except BaseException:  # pragma: no cover - no response, so free the slot now
        stream.close()
        raise


def _export_routes(api: FastAPI, source: SnapshotSource, images: EvidenceHosts) -> None:
    """One route per exportable view, each taking that view's filters plus ``format``."""
    route = {
        "response_class": StreamingResponse,
        "responses": EXPORT_RESPONSES,
    }
    view = export.ExportView
    slots = export.ExportSlots(export.MAX_CONCURRENT_EXPORTS)

    @api.get(f"{PREFIX}/export/products", **route)  # type: ignore[arg-type]
    def export_products(
        query: Annotated[ProductsExport, Query()], who: Viewer
    ) -> StreamingResponse:
        loaded = source.select(query.market, query.scope)
        metric = product_cards(loaded.dataset, query, images)
        return _download(
            loaded,
            view=view.PRODUCTS,
            query=query,
            metric=metric,
            rows=metric.data,
            who=who,
            slots=slots,
        )

    @api.get(f"{PREFIX}/export/compare", **route)  # type: ignore[arg-type]
    def export_compare(query: Annotated[CompareExport, Query()], who: Viewer) -> StreamingResponse:
        loaded = source.select(query.market, query.scope)
        base, other = query.pair()
        metric = compare(
            loaded.dataset, base, other, query.where(), on=query.on, group_by=query.group_by
        )
        return _download(
            loaded,
            view=view.COMPARE,
            query=query,
            metric=metric,
            rows=metric.data.rows,
            who=who,
            slots=slots,
        )

    @api.get(f"{PREFIX}/export/index", **route)  # type: ignore[arg-type]
    def export_index(query: Annotated[IndexExport, Query()], who: Viewer) -> StreamingResponse:
        loaded = source.select(query.market, query.scope)
        base, other = query.pair()
        metric = price_index(
            loaded.dataset, base, other, query.where(), start=query.start, end=query.end
        )
        return _download(
            loaded,
            view=view.INDEX,
            query=query,
            metric=metric,
            rows=metric.data.points,
            who=who,
            slots=slots,
        )

    @api.get(f"{PREFIX}/export/promotions", **route)  # type: ignore[arg-type]
    def export_promotions(
        query: Annotated[PromotionsExport, Query()], who: Viewer
    ) -> StreamingResponse:
        loaded = source.select(query.market, query.scope)
        metric = promotions(
            loaded.dataset, query.retailer, query.where(), query.min_depth(), query.on
        )
        return _download(
            loaded,
            view=view.PROMOTIONS,
            query=query,
            metric=metric,
            rows=metric.data.items,
            who=who,
            slots=slots,
        )

    @api.get(f"{PREFIX}/export/assortment-gaps", **route)  # type: ignore[arg-type]
    def export_assortment_gaps(
        query: Annotated[AssortmentExport, Query()], who: Viewer
    ) -> StreamingResponse:
        loaded = source.select(query.market, query.scope)
        metric = assortment_gaps(
            loaded.dataset, query.missing_at, query.present_at, query.where(), query.on
        )
        return _download(
            loaded,
            view=view.ASSORTMENT_GAPS,
            query=query,
            metric=metric,
            rows=metric.data.items,
            who=who,
            slots=slots,
        )

    @api.get(f"{PREFIX}/export/coverage", **route)  # type: ignore[arg-type]
    def export_coverage(
        query: Annotated[CoverageExport, Query()], who: Viewer
    ) -> StreamingResponse:
        loaded = source.select(query.market, query.scope)
        metric = coverage(loaded.dataset, query.retailer)
        return _download(
            loaded,
            view=view.COVERAGE,
            query=query,
            metric=metric,
            rows=metric.data.retailers,
            who=who,
            slots=slots,
        )


def create_app(
    source: SnapshotSource,
    verifier: TokenVerifier,
    buckets: TokenBuckets,
    evidence_hosts: EvidenceHosts | None = None,
    image_hosts: EvidenceHosts | None = None,
) -> ASGIApp:
    api = build_api(source, evidence_hosts, image_hosts)
    return NoStore(ServerErrors(Authenticate(RateLimit(api, buckets), verifier)))


def store_for(settings: Settings) -> ObjectStore:
    if settings.local_dir is not None:
        return LocalStore(settings.local_dir)
    return GcsStore(str(settings.bucket))  # pragma: no cover - needs GCS credentials


def app_from_env(env: Mapping[str, str] | None = None) -> ASGIApp:
    """``uvicorn --factory pi_api.app:app_from_env``: loads the datasets before serving."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    export.configure_audit()
    settings = Settings.from_env(os.environ if env is None else env)
    source = SnapshotSource(
        store_for(settings),
        settings.datasets,
        settings.refresh_seconds,
        allow_test=settings.allow_test,
    )
    source.load_all()
    verifier = TokenVerifier(settings.project_id, HttpCertSource())
    buckets = TokenBuckets(settings.rate_per_second, settings.rate_burst)
    return create_app(source, verifier, buckets, settings.evidence_hosts, settings.image_hosts)
