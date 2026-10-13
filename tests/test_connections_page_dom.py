"""Browser-DOM and reader tests for the Connections page (Recently added)."""

from datetime import date
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from linkedin_mcp_server.linkedin.connections_page import (
    CONNECTION_CARDS_JS,
    CONNECTIONS_URL,
    ConnectionsPageReader,
    parse_connected_on,
)
from linkedin_mcp_server.linkedin.session import PageSession
from test_message_recipient_dom import dom_page  # noqa: F401

DOM = [pytest.mark.browser_dom, pytest.mark.xdist_group("browser_runtime")]


def card(i, slug, name, headline, connected, urn="ACoAATEST"):
    profile = f"https://www.linkedin.com/in/{slug}/" if slug else None
    anchor = (
        f'<a href="{profile}"><div><p>{name}</p><div><p><span>{headline}</span></p></div></div></a>'
        if profile
        else f"<div><p>{name}</p><div><p><span>{headline}</span></p></div></div>"
    )
    return (
        f'<div class="x1 x2" componentkey="ConnectionCard_{i}-{slug or "none"}">'
        f"{f'<a href={chr(34)}{profile}{chr(34)}><figure></figure></a>' if profile else ''}"
        f"<div><div>{anchor}<p>{connected}</p></div></div>"
        f'<div><a aria-label="Send a message to {name}" '
        f'href="/messaging/compose/?profileUrn=urn%3Ali%3Afsd_profile%3A{urn}&amp;recipient={urn}">Message</a></div>'
        f"</div>"
    )


def page(sort_label, cards):
    return f"<main><div><button>Sort by: {sort_label}</button></div>{''.join(cards)}</main>"


def test_parse_connected_on():
    assert parse_connected_on("Connected on October 13, 2026") == date(2026, 10, 13)
    assert parse_connected_on("Connected on Sept 3, 2026") is None
    assert parse_connected_on("") is None


@pytest.mark.browser_dom
@pytest.mark.xdist_group("browser_runtime")
async def test_reads_every_card(dom_page):  # noqa: F811
    await dom_page.set_content(
        page(
            "Recently added",
            [
                card(
                    0,
                    "ada-lovelace-123",
                    "Ada Lovelace",
                    "Office Manager at Bright Smiles",
                    "Connected on October 13, 2026",
                    "ACoAAAda",
                ),
                card(
                    1,
                    "grace-hopper",
                    "Grace Hopper",
                    "DDS",
                    "Connected on October 12, 2026",
                    "ACoAAGrace",
                ),
            ],
        )
    )
    result = await dom_page.evaluate(CONNECTION_CARDS_JS)
    assert result["sort"] == "Recently added"
    assert result["cards"] == [
        {
            "name": "Ada Lovelace",
            "headline": "Office Manager at Bright Smiles",
            "slug": "ada-lovelace-123",
            "profile_urn": "ACoAAAda",
            "connected_text": "Connected on October 13, 2026",
        },
        {
            "name": "Grace Hopper",
            "headline": "DDS",
            "slug": "grace-hopper",
            "profile_urn": "ACoAAGrace",
            "connected_text": "Connected on October 12, 2026",
        },
    ]


@pytest.mark.browser_dom
@pytest.mark.xdist_group("browser_runtime")
async def test_wrong_sort_returns_error(dom_page):  # noqa: F811
    await dom_page.set_content(
        page(
            "Last name",
            [
                card(
                    0,
                    "ada-lovelace-123",
                    "Ada Lovelace",
                    "x",
                    "Connected on October 13, 2026",
                )
            ],
        )
    )
    result = await dom_page.evaluate(CONNECTION_CARDS_JS)
    assert result["sort"] == "Last name"


@pytest.mark.browser_dom
@pytest.mark.xdist_group("browser_runtime")
async def test_card_without_slug_or_date_is_kept_and_counted(dom_page):  # noqa: F811
    await dom_page.set_content(
        page(
            "Recently added",
            [
                card(0, None, "No Link", "x", "Connected on October 13, 2026"),
                card(1, "bad-date", "Bad Date", "y", "Connected recently"),
            ],
        )
    )
    result = await dom_page.evaluate(CONNECTION_CARDS_JS)
    assert [c["slug"] for c in result["cards"]] == [None, "bad-date"]


class FakePage:
    def __init__(self, snapshots):
        self.snapshots, self.scrolls, self.url = list(snapshots), 0, CONNECTIONS_URL

    async def evaluate(self, script, *args):
        if script is CONNECTION_CARDS_JS:
            return self.snapshots[min(self.scrolls, len(self.snapshots) - 1)]
        self.scrolls += 1  # the scroll/"Load more" step
        return None


class FakeSession:
    def __init__(self, page):
        self.page = page
        self.delay = AsyncMock()
        self.check_rate_limit = AsyncMock()


def raw(slug, connected):
    return {
        "name": slug.title(),
        "headline": "h",
        "slug": slug,
        "profile_urn": "ACoAA" + slug,
        "connected_text": connected,
    }


def reader_for(snapshots):
    page = FakePage(snapshots)
    navigator = MagicMock()
    navigator._navigate_to_page = AsyncMock()
    session = cast(PageSession, FakeSession(page))
    return ConnectionsPageReader(session, navigator), page, navigator


async def test_reader_stops_once_since_is_reached():
    first = {
        "sort": "Recently added",
        "cards": [raw("ada", "Connected on October 13, 2026")],
    }
    second = {
        "sort": "Recently added",
        "cards": first["cards"] + [raw("bob", "Connected on October 10, 2026")],
    }
    reader, page, navigator = reader_for([first, second])

    result = await reader.read(date(2026, 10, 11), max_scrolls=5)

    navigator._navigate_to_page.assert_awaited_once_with(CONNECTIONS_URL)
    assert page.scrolls == 1
    assert result["reached_since"] is True
    assert [c["slug"] for c in result["connections"]] == ["ada", "bob"]
    assert result["connections"][1]["connected_on"] == "2026-10-10"
    assert result["unparsed"] == 0


async def test_reader_respects_scroll_cap_and_reports_not_reached():
    only_new = {
        "sort": "Recently added",
        "cards": [raw("ada", "Connected on October 13, 2026")],
    }
    reader, page, _ = reader_for([only_new])

    result = await reader.read(date(2026, 10, 1), max_scrolls=2)

    assert page.scrolls == 2
    assert result["reached_since"] is False
    assert len(result["connections"]) == 1


async def test_reader_returns_unexpected_sort_without_scrolling():
    wrong = {
        "sort": "Last name",
        "cards": [raw("ada", "Connected on October 13, 2026")],
    }
    reader, page, _ = reader_for([wrong])

    result = await reader.read(date(2026, 10, 11))

    assert page.scrolls == 0
    assert result["error"] == "unexpected_sort"
    assert result["connections"] == []


async def test_reader_counts_unparsed_cards():
    snap = {
        "sort": "Recently added",
        "cards": [
            {
                "name": "No Link",
                "headline": "x",
                "slug": None,
                "profile_urn": None,
                "connected_text": "Connected on October 13, 2026",
            },
            raw("bad", "Connected recently"),
            raw("old", "Connected on October 1, 2026"),
        ],
    }
    reader, _, _ = reader_for([snap])

    result = await reader.read(date(2026, 10, 11))

    assert result["unparsed"] == 2
    assert [c["connected_on"] for c in result["connections"]] == [
        "2026-10-13",
        None,
        "2026-10-01",
    ]
