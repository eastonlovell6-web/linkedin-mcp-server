"""Browser-DOM and reader tests for the Connections page (Recently added)."""

from datetime import date
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from patchright.async_api import TimeoutError as PlaywrightTimeoutError

from linkedin_mcp_server.linkedin.connections_page import (
    CONNECTION_CARD_SELECTOR,
    CONNECTION_CARDS_JS,
    CONNECTIONS_URL,
    CARD_COUNT_ABOVE_JS,
    LOAD_MORE_JS,
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
    def __init__(self, snapshots, wait_error=None):
        self.snapshots, self.scrolls, self.url = list(snapshots), 0, CONNECTIONS_URL
        self.calls, self.wait_error = [], wait_error

    async def wait_for_selector(self, selector, **kwargs):
        self.calls.append(("wait_for_selector", selector, kwargs))
        if self.wait_error is not None:
            raise self.wait_error

    async def wait_for_function(self, script, **kwargs):
        self.calls.append(("wait_for_function", script, kwargs))

    async def evaluate(self, script, *args):
        self.calls.append(("evaluate", script))
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


def reader_for(snapshots, wait_error=None):
    page = FakePage(snapshots, wait_error)
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


async def test_reader_accepts_no_sort_control_when_dates_run_newest_first():
    # 2026-10-27 redesign: no "Sort by" control; the list is still newest first.
    first = {
        "sort": None,
        "cards": [
            raw("ada", "Connected on October 27, 2026"),
            raw("cy", "Connected recently"),
            raw("bob", "Connected on October 26, 2026"),
            raw("dee", "Connected on October 26, 2026"),
        ],
    }
    second = {
        "sort": None,
        "cards": first["cards"] + [raw("eve", "Connected on October 20, 2026")],
    }
    reader, page, _ = reader_for([first, second])

    result = await reader.read(date(2026, 10, 25))

    assert "error" not in result
    assert page.scrolls == 1
    assert result["reached_since"] is True
    assert [c["slug"] for c in result["connections"]] == [
        "ada",
        "cy",
        "bob",
        "dee",
        "eve",
    ]


async def test_reader_rejects_no_sort_control_when_dates_are_out_of_order():
    snap = {
        "sort": None,
        "cards": [
            raw("ada", "Connected on October 20, 2026"),
            raw("bob", "Connected on October 26, 2026"),
        ],
    }
    reader, page, _ = reader_for([snap])

    result = await reader.read(date(2026, 10, 25))

    assert page.scrolls == 0
    assert result["error"] == "unexpected_sort"
    assert result["connections"] == []


async def test_reader_rejects_no_sort_control_with_fewer_than_two_dated_cards():
    snap = {"sort": None, "cards": [raw("ada", "Connected on October 27, 2026")]}
    reader, page, _ = reader_for([snap])

    result = await reader.read(date(2026, 10, 25))

    assert page.scrolls == 0
    assert result["error"] == "unexpected_sort"


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


async def test_reader_waits_for_cards_before_the_first_snapshot():
    snap = {
        "sort": "Recently added",
        "cards": [raw("old", "Connected on October 1, 2026")],
    }
    reader, page, _ = reader_for([snap])

    await reader.read(date(2026, 10, 11))

    assert page.calls[0] == (
        "wait_for_selector",
        CONNECTION_CARD_SELECTOR,
        {"state": "attached", "timeout": 10000},
    )
    assert CONNECTION_CARD_SELECTOR == 'div[componentkey^="ConnectionCard_"]'


async def test_reader_reads_anyway_when_cards_never_render():
    snap = {"sort": "Recently added", "cards": []}
    reader, page, _ = reader_for([snap], PlaywrightTimeoutError("no cards"))

    result = await reader.read(date(2026, 10, 11), max_scrolls=0)

    assert result["connections"] == []
    assert result["reached_since"] is False


async def test_reader_merges_snapshots_when_the_list_virtualizes():
    first = {
        "sort": "Recently added",
        "cards": [
            raw("ada", "Connected on October 13, 2026"),
            raw("bob", "Connected on October 12, 2026"),
        ],
    }
    # The list dropped "ada" from the DOM while rendering older cards.
    second = {
        "sort": "Recently added",
        "cards": [
            raw("bob", "Connected on October 12, 2026"),
            raw("cy", "Connected on October 9, 2026"),
        ],
    }
    reader, page, _ = reader_for([first, second])

    result = await reader.read(date(2026, 10, 11), max_scrolls=5)

    assert page.scrolls == 1
    assert [c["slug"] for c in result["connections"]] == ["ada", "bob", "cy"]
    assert result["reached_since"] is True


async def test_reader_dedupes_slugless_cards_by_name_and_date():
    slugless = {
        "name": "No Link",
        "headline": "x",
        "slug": None,
        "profile_urn": None,
        "connected_text": "Connected on October 13, 2026",
    }
    first = {"sort": "Recently added", "cards": [slugless]}
    second = {
        "sort": "Recently added",
        "cards": [slugless, raw("old", "Connected on October 1, 2026")],
    }
    reader, _, _ = reader_for([first, second])

    result = await reader.read(date(2026, 10, 11), max_scrolls=5)

    assert [c["name"] for c in result["connections"]] == ["No Link", "Old"]
    assert result["unparsed"] == 1


@pytest.mark.browser_dom
@pytest.mark.xdist_group("browser_runtime")
async def test_malformed_percent_encoding_nulls_only_that_card(dom_page):  # noqa: F811
    bad_profile = card(0, "ok", "Bad Href", "x", "Connected on October 13, 2026")
    bad_profile = bad_profile.replace(
        "https://www.linkedin.com/in/ok/", "https://www.linkedin.com/in/bad%E0%A4%A/"
    )
    bad_urn = card(
        1, "bad-urn", "Bad Urn", "y", "Connected on October 12, 2026"
    ).replace("urn%3Ali%3Afsd_profile%3A", "urn%3Ali%E0%A4%A%3Afsd_profile%3A")
    good = card(2, "good", "Good", "z", "Connected on October 11, 2026", "ACoAAGood")
    await dom_page.set_content(page("Recently added", [bad_profile, bad_urn, good]))

    result = await dom_page.evaluate(CONNECTION_CARDS_JS)

    assert [c["slug"] for c in result["cards"]] == [None, "bad-urn", "good"]
    assert [c["profile_urn"] for c in result["cards"]] == [
        "ACoAATEST",
        None,
        "ACoAAGood",
    ]


@pytest.mark.browser_dom
@pytest.mark.xdist_group("browser_runtime")
async def test_load_more_scrolls_the_list_inside_main(dom_page):  # noqa: F811
    # LinkedIn (2026-10-14 capture) scrolls the list inside <main overflow-y:
    # scroll> and loads the next page when the last card comes into view; the
    # window itself never scrolls.
    cards = "".join(
        card(i, f"p{i}", f"P {i}", "x", "Connected on October 13, 2026")
        for i in range(10)
    )
    await dom_page.set_viewport_size({"width": 800, "height": 600})
    await dom_page.set_content(
        "<style>html,body{height:100%;margin:0;overflow:hidden}"
        "main{height:100%;overflow-y:scroll}"
        "[componentkey]{height:120px}</style>"
        f"<main><div><button>Sort by: Recently added</button></div>{cards}</main>"
    )
    await dom_page.evaluate(LOAD_MORE_JS)
    await dom_page.wait_for_timeout(100)
    assert await dom_page.evaluate("document.querySelector('main').scrollTop") > 0


async def test_reader_waits_for_the_next_page_after_each_scroll():
    first = {
        "sort": "Recently added",
        "cards": [raw("ada", "Connected on October 13, 2026")],
    }
    second = {
        "sort": "Recently added",
        "cards": first["cards"] + [raw("bob", "Connected on October 10, 2026")],
    }
    reader, page, _ = reader_for([first, second])

    await reader.read(date(2026, 10, 11), max_scrolls=5)

    waits = [c for c in page.calls if c[0] == "wait_for_function"]
    assert waits == [
        ("wait_for_function", CARD_COUNT_ABOVE_JS, {"arg": 1, "timeout": 8000})
    ]


@pytest.mark.browser_dom
@pytest.mark.xdist_group("browser_runtime")
async def test_card_count_predicate(dom_page):  # noqa: F811
    await dom_page.set_content(
        page(
            "Recently added", [card(0, "a", "A", "x", "Connected on October 13, 2026")]
        )
    )
    assert await dom_page.evaluate(CARD_COUNT_ABOVE_JS, 0) is True
    assert await dom_page.evaluate(CARD_COUNT_ABOVE_JS, 1) is False
