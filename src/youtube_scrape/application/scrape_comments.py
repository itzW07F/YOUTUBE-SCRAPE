"""Application service: comments + replies with optional Innertube continuation."""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

from youtube_scrape.application.envelope import make_envelope
from youtube_scrape.domain.comments_extract import (
    extract_comment_records_from_response,
    extract_continuation_tokens,
    response_has_comment_entities,
)
from youtube_scrape.domain.innertube import (
    extract_innertube_api_key,
    extract_innertube_context,
    next_endpoint,
)
from youtube_scrape.domain.models import ResultEnvelope
from youtube_scrape.domain.ports import BrowserSession, HttpClient
from youtube_scrape.domain.youtube_url import parse_video_id, watch_url
from youtube_scrape.exceptions import ContinuationError, ExtractionError
from youtube_scrape.settings import Settings

log = logging.getLogger(__name__)


class ScrapeCommentsService:
    """Collect comments from the initial renderer tree and ``youtubei/v1/next``."""

    def __init__(self, *, browser: BrowserSession, http: HttpClient, settings: Settings) -> None:
        self._browser = browser
        self._http = http
        self._settings = settings

    async def scrape(
        self,
        url_or_id: str,
        *,
        max_comments: int | None,
        fetch_all: bool,
        max_replies_per_thread: int | None,
        include_replies: bool,
    ) -> ResultEnvelope:
        url = watch_url(url_or_id)
        video_id = parse_video_id(url_or_id)
        log.info(
            "scrape_comments_start",
            extra={
                "url": url,
                "max_comments": max_comments,
                "fetch_all": fetch_all,
                "include_replies": include_replies,
            },
        )
        player, initial, html = await self._browser.extract_watch_payload(url)
        _ = player  # reserved for future alternate extraction paths
        if not include_replies:
            reply_cap: int | None = 0
        else:
            reply_cap = max_replies_per_thread
        comments = extract_comment_records_from_response(
            initial,
            max_replies_per_thread=reply_cap,
            include_replies=include_replies,
        )
        seen_ids: set[str] = {c.comment_id for c in comments if c.comment_id}

        try:
            api_key = extract_innertube_api_key(html)
            innertube_ctx = extract_innertube_context(html)
        except ExtractionError as exc:
            log.warning("innertube_context_unavailable", extra={"error": str(exc)})
            innertube_ctx = {}
            api_key = ""

        token_queue: deque[str] = deque(extract_continuation_tokens(initial))
        seen_tokens: set[str] = set()
        want_continuation = fetch_all or (max_comments is not None)

        def should_stop() -> bool:
            return len(comments) >= self._settings.comments_safety_ceiling or (
                max_comments is not None and len(comments) >= max_comments
            )

        while token_queue and want_continuation and not should_stop() and api_key and innertube_ctx:
            token = token_queue.popleft()
            if token in seen_tokens:
                continue
            seen_tokens.add(token)
            body: dict[str, Any] = {"context": innertube_ctx, "continuation": token}
            endpoint = next_endpoint(api_key)
            try:
                resp = await self._http.post_json(endpoint, json_body=body)
            except Exception as exc:
                msg = "Continuation POST failed"
                raise ContinuationError(msg, details=str(exc)) from exc
            fresh = extract_comment_records_from_response(
                resp,
                max_replies_per_thread=reply_cap,
                include_replies=include_replies,
            )
            for c in fresh:
                if c.comment_id and c.comment_id not in seen_ids:
                    seen_ids.add(c.comment_id)
                    comments.append(c)
                    if should_stop():
                        break
            new_tokens = extract_continuation_tokens(resp)
            if not fresh and not response_has_comment_entities(resp):
                pass
            elif include_replies and any(c.is_reply for c in fresh):
                for t in reversed(new_tokens):
                    if t not in seen_tokens:
                        token_queue.appendleft(t)
            else:
                for t in new_tokens:
                    if t not in seen_tokens:
                        token_queue.append(t)

        if fetch_all and len(comments) >= self._settings.comments_safety_ceiling:
            log.warning(
                "comments_safety_ceiling_hit",
                extra={"video_id": video_id, "ceiling": self._settings.comments_safety_ceiling},
            )

        # Organize comments hierarchically: parent comments with nested replies
        organized_comments = self._organize_comments_hierarchical(comments)

        data = {
            "video_id": video_id,
            "comments": organized_comments,
            "total_count": len(comments),
            "top_level_count": len(organized_comments),
        }
        return make_envelope(settings=self._settings, kind="comments", data=data)

    def _organize_comments_hierarchical(
        self,
        comments: list[Any],
    ) -> list[dict[str, Any]]:
        """Organize flat comment list into hierarchical structure.

        Parent comments contain a "replies" list with their reply comments.
        This makes it clear which replies belong to which parent comment.
        """
        # First pass: separate parents and replies
        parents: dict[str, dict[str, Any]] = {}
        replies: list[dict[str, Any]] = []

        for comment in comments:
            comment_dict = comment.model_dump(mode="json")
            if comment.is_reply:
                replies.append(comment_dict)
            else:
                comment_dict["replies"] = []
                parents[comment.comment_id] = comment_dict

        # Second pass: attach replies to their parents
        orphan_replies: list[dict[str, Any]] = []
        for reply in replies:
            parent_id = reply.get("parent_comment_id")
            if parent_id and parent_id in parents:
                parents[parent_id]["replies"].append(reply)
            else:
                # Parent not found (may not have been scraped), keep as orphan
                orphan_replies.append(reply)

        # Build result: parents in order, with their replies attached
        result: list[dict[str, Any]] = []
        seen_reply_ids = set()

        for comment in comments:
            if not comment.is_reply:
                parent_dict = parents.get(comment.comment_id)
                if parent_dict:
                    result.append(parent_dict)

        # Add any orphan replies at the end with a special marker
        if orphan_replies:
            result.append({
                "_note": "Replies whose parent comments were not found",
                "orphan_replies": orphan_replies,
            })

        return result
