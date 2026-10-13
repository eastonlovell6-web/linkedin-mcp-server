"""Read the Connections page (Sort by: Recently added) as structured records."""

from __future__ import annotations

import random
import re
from datetime import date, datetime
from typing import Any

from linkedin_mcp_server.linkedin.navigation import PageNavigator
from linkedin_mcp_server.linkedin.session import PageSession

CONNECTIONS_URL = "https://www.linkedin.com/mynetwork/invite-connect/connections/"
EXPECTED_SORT = "Recently added"
DEFAULT_MAX_SCROLLS = 5
MAX_SCROLLS_CEILING = 10

# Cards are found by LinkedIn's componentkey (ConnectionCard_<n>-<slug>), not by
# layout classes, which are hashed and change between deploys (DOM capture 2026-10-13).
CONNECTION_CARDS_JS = r"""() => {
    const main = document.querySelector('main') || document.body;
    const sortNode = Array.from(main.querySelectorAll('button, [role="button"]'))
        .find(node => /Sort by:/.test(node.innerText || ''));
    const sortMatch = sortNode && (sortNode.innerText || '').match(/Sort by:\s*([^\n]+)/);
    const slugOf = href => {
        const match = (href || '').match(/^(?:https:\/\/www\.linkedin\.com)?\/in\/([^/?#]+)\/?/);
        return match ? decodeURIComponent(match[1]) : null;
    };
    const cards = Array.from(main.querySelectorAll('div[componentkey^="ConnectionCard_"]')).map(card => {
        const profileAnchor = Array.from(card.querySelectorAll('a[href*="/in/"]'))
            .find(a => (a.innerText || '').trim().length > 0)
            || card.querySelector('a[href*="/in/"]');
        const textBlock = profileAnchor || card;
        const paragraphs = Array.from(textBlock.querySelectorAll('p'))
            .map(p => (p.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean);
        const connected = Array.from(card.querySelectorAll('p'))
            .map(p => (p.innerText || '').replace(/\s+/g, ' ').trim())
            .find(text => /^Connected on /.test(text)) || null;
        const message = card.querySelector('a[href*="/messaging/compose/"]');
        const urnMatch = message && decodeURIComponent(message.getAttribute('href') || '')
            .match(/fsd_profile:([A-Za-z0-9_-]+)/);
        return {
            name: paragraphs[0] || null,
            headline: paragraphs.find((text, i) => i > 0 && !/^Connected on /.test(text)) || null,
            slug: slugOf(profileAnchor && profileAnchor.getAttribute('href')),
            profile_urn: urnMatch ? urnMatch[1] : null,
            connected_text: connected,
        };
    });
    return {sort: sortMatch ? sortMatch[1].trim() : null, cards};
}"""

LOAD_MORE_JS = r"""() => {
    const main = document.querySelector('main') || document.body;
    const button = Array.from(main.querySelectorAll('button'))
        .find(b => /^(Load more|Show more results)$/i.test((b.innerText || '').trim()));
    if (button) { button.click(); return 'clicked'; }
    window.scrollTo(0, document.body.scrollHeight);
    return 'scrolled';
}"""

_CONNECTED_RE = re.compile(r"^Connected on ([A-Z][a-z]+ \d{1,2}, \d{4})$")


def parse_connected_on(text: str | None) -> date | None:
    match = _CONNECTED_RE.match((text or "").strip())
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%B %d, %Y").date()
    except ValueError:
        return None


class ConnectionsPageReader:
    def __init__(self, session: PageSession, navigator: PageNavigator):
        self._session = session
        self._navigator = navigator

    async def read(
        self, since: date, max_scrolls: int = DEFAULT_MAX_SCROLLS
    ) -> dict[str, Any]:
        max_scrolls = max(0, min(int(max_scrolls), MAX_SCROLLS_CEILING))
        await self._navigator._navigate_to_page(CONNECTIONS_URL)
        await self._session.check_rate_limit()
        page = self._session.page
        snapshot = await page.evaluate(CONNECTION_CARDS_JS)
        if snapshot.get("sort") != EXPECTED_SORT:
            return {
                "url": page.url,
                "sort": snapshot.get("sort"),
                "connections": [],
                "reached_since": False,
                "unparsed": 0,
                "error": "unexpected_sort",
            }
        scrolls = 0
        while not self._reached(snapshot, since) and scrolls < max_scrolls:
            await page.evaluate(LOAD_MORE_JS)
            scrolls += 1
            await self._session.delay(random.uniform(1.5, 3.0))
            snapshot = await page.evaluate(CONNECTION_CARDS_JS)
        connections, unparsed = [], 0
        for card in snapshot.get("cards", []):
            connected_on = parse_connected_on(card.get("connected_text"))
            if connected_on is None or card.get("slug") is None:
                unparsed += 1
            connections.append(
                {
                    "name": card.get("name") or "",
                    "headline": card.get("headline") or "",
                    "slug": card.get("slug"),
                    "profile_urn": card.get("profile_urn"),
                    "connected_on": connected_on.isoformat() if connected_on else None,
                }
            )
        return {
            "url": page.url,
            "sort": EXPECTED_SORT,
            "connections": connections,
            "reached_since": self._reached(snapshot, since),
            "unparsed": unparsed,
        }

    @staticmethod
    def _reached(snapshot: dict[str, Any], since: date) -> bool:
        dates = [
            parse_connected_on(c.get("connected_text"))
            for c in snapshot.get("cards", [])
        ]
        known = [d for d in dates if d is not None]
        return bool(known) and min(known) < since
