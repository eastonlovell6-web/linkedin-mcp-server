# tests/test_connect_button_layout_dom.py
"""Browser-DOM tests for the 2026-10 top-card layout.

LinkedIn now renders Connect as an ``<a>`` that links back to the profile,
carries an ``aria-label`` and a ``componentkey`` like
``ConnectButtonstate:invitation:urn:li:member:<id>_connect``; there is no
``/preload/custom-invite/`` anchor. A "<Name> is a mutual connection" line
above the buttons is an ``<a aria-label="Open http://…/search/results/…">``.
Under the old rules both read as Pending. Fixtures mirror a live dump of that
layout (2026-10-12), with the words replaced where they don't matter.
"""

from __future__ import annotations

import pytest
from patchright.async_api import async_playwright

from linkedin_mcp_server.linkedin.connection import (
    ActionSignals,
    detect_connection_state,
)
from linkedin_mcp_server.linkedin.connection_actions import (
    ACTION_SIGNALS_JS,
    ConnectionActions,
)
from linkedin_mcp_server.linkedin.navigation import PageNavigator
from linkedin_mcp_server.linkedin.session import PageSession

pytestmark = [pytest.mark.browser_dom, pytest.mark.xdist_group("browser_runtime")]

USER = "testuser"
MUTUAL = (
    '<a href="https://www.linkedin.com/search/results/people/?network=%5B%22F%22%5D&connectionOf=x">'
    '<p><span><a aria-label="Open http://www.linkedin.com/search/results/people/?connectionOf=x" '
    'href="https://www.linkedin.com/search/results/people/?connectionOf=x" target="_blank">'
    "<strong>Mason</strong> is a mutual connection</a></span></p></a>"
)


def _connect_anchor(user: str, state: str, member: str = "23887902") -> str:
    return (
        f'<a aria-disabled="false" href="https://www.linkedin.com/in/{user}/" '
        f'componentkey="ConnectButtonstate:invitation:urn:li:member:{member}_{state}" '
        f'aria-label="Invite {user} to connect"><span>Connect</span></a>'
    )


MESSAGE = (
    '<a aria-disabled="false" href="/messaging/compose/?profileUrn=urn%3Ali%3Afsd_profile%3AX'
    '&recipient=X&screenContext=NON_SELF_PROFILE_VIEW&interop=msgOverlay"><span>Message</span></a>'
)
MORE = '<button type="button" aria-label="More"><span></span></button>'


def _top_card(*buttons: str, mutual: bool = True) -> str:
    row = "".join(f"<div>{b}</div>" for b in buttons)
    return (
        "<section><div><h2>Test User</h2>"
        + (MUTUAL if mutual else "")
        + f"<div><div><div>{row}</div></div></div></div></section>"
    )


def _sidebar_connect(user: str) -> str:
    return f"<section><div><p>{user}</p><div>{_connect_anchor(user, 'connect', '999')}</div></div></section>"


def _rail(viewed: str, *members: str) -> str:
    """The live "People you may know" rail: an <aside> inside <main> whose
    Connect anchors carry other members' ids but link to the VIEWED profile
    (observed 2026-10-12 on every profile probed)."""
    cards = "".join(
        f"<section><div><p>Member {m}</p>{_connect_anchor(viewed, 'connect', m)}</div></section>"
        for m in members
    )
    return f"<aside>{cards}</aside>"


def _page_with_header(header: str, *sections: str) -> str:
    """The sticky header copy of the Connect control sits outside <main>."""
    return f"<html><body><header>{header}</header><main>{''.join(sections)}</main></body></html>"


def _page(*sections: str) -> str:
    return f"<html><body><main>{''.join(sections)}</main></body></html>"


@pytest.fixture
async def dom_page():
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(channel="chromium", headless=True)
            page = await browser.new_page()
        except Exception as exc:  # browser binary missing
            pytest.skip(f"chromium unavailable: {exc}")
        try:
            yield page
        finally:
            await browser.close()


async def _state(page, html: str) -> tuple[str, dict]:
    await page.set_content(html)
    raw = await page.evaluate(ACTION_SIGNALS_JS, USER)
    signals = ActionSignals(
        has_invite_anchor=bool(raw.get("hasInvite")),
        has_compose_anchor_in_action_root=bool(raw.get("hasComposeInActionRoot")),
        has_edit_intro_anchor=bool(raw.get("hasEditIntro")),
        has_labeled_action_button=bool(raw.get("hasLabeledActionButton")),
        has_labeled_action_anchor=bool(raw.get("hasLabeledActionAnchor")),
        has_incoming_action_row=bool(raw.get("hasIncomingActionRow")),
        has_connect_button=bool(raw.get("hasConnectButton")),
        has_connect_state_anchor=bool(raw.get("hasConnectStateAnchor")),
    )
    return detect_connection_state(signals), raw


class TestConnectButtonLayout:
    async def test_live_connect_layout_is_connectable(self, dom_page):
        state, raw = await _state(
            dom_page, _page(_top_card(_connect_anchor(USER, "connect"), MESSAGE, MORE))
        )
        assert raw["hasConnectButton"] is True
        assert raw["hasConnectStateAnchor"] is False
        assert state == "connectable"

    async def test_mutual_connection_link_is_not_a_pending_signal(self, dom_page):
        # Before Connect hydrates the row holds only Message and More.
        state, raw = await _state(dom_page, _page(_top_card(MESSAGE, MORE)))
        assert raw["hasLabeledActionAnchor"] is False
        assert state != "pending"
        assert state != "connectable"

    async def test_connect_state_other_than_connect_is_pending(self, dom_page):
        state, raw = await _state(
            dom_page, _page(_top_card(_connect_anchor(USER, "withdraw"), MESSAGE, MORE))
        )
        assert raw["hasConnectButton"] is False
        assert raw["hasConnectStateAnchor"] is True
        assert state == "pending"

    async def test_sidebar_connect_for_another_profile_is_not_connectable(
        self, dom_page
    ):
        state, raw = await _state(
            dom_page, _page(_top_card(MESSAGE, MORE), _sidebar_connect("someoneelse"))
        )
        assert raw["hasConnectButton"] is False
        assert raw["hasConnectStateAnchor"] is False
        assert state != "connectable"

    async def test_live_pending_profile_with_rail_is_pending(self, dom_page):
        # Farid Pakravan, 2026-10-12: invitation confirmed in the Sent list; the
        # old href scoping read the rail's _connect anchors as his and reported
        # send_failed for a delivered invite.
        pending = _connect_anchor(USER, "pending", "91424629")
        html = _page_with_header(
            pending,
            _top_card(pending, MESSAGE, MORE),
            _rail(USER, "263534462", "573658256", "103174284"),
        )
        state, raw = await _state(dom_page, html)
        assert raw["hasConnectButton"] is False
        assert raw["hasConnectStateAnchor"] is True
        assert state == "pending"

    async def test_live_connectable_profile_with_rail_is_connectable(self, dom_page):
        connect = _connect_anchor(USER, "connect", "201307698")
        html = _page_with_header(
            connect, _top_card(connect, MESSAGE, MORE), _rail(USER, "13489154")
        )
        state, raw = await _state(dom_page, html)
        assert raw["hasConnectButton"] is True
        assert raw["hasConnectStateAnchor"] is False
        assert state == "connectable"

    async def test_rail_connect_alone_is_not_connectable(self, dom_page):
        # A top card without a Connect control (e.g. 1st-degree) must not
        # borrow one from the rail, even though the rail links to this profile.
        state, raw = await _state(
            dom_page, _page(_top_card(MESSAGE, MORE), _rail(USER, "1", "2"))
        )
        assert raw["hasConnectButton"] is False
        assert state != "connectable"

    async def test_pending_outranks_connect_in_the_top_card(self, dom_page):
        html = _page(
            _top_card(
                _connect_anchor(USER, "pending"),
                _connect_anchor(USER, "connect"),
                MESSAGE,
                MORE,
            )
        )
        state, _ = await _state(dom_page, html)
        assert state == "pending"


FOLLOW = (
    '<button type="button" aria-label="Follow Test User"><span>Follow</span></button>'
)
MORE_OPEN = '<button type="button" aria-expanded="true"><span></span></button>'


def _more_menu(*items: str) -> str:
    """The open profile More menu. Live 2026-10-19 (wes-hinson): LinkedIn
    renders it in a portal OUTSIDE <main>; Connect is an
    <a role="menuitem"> with the same ConnectButtonstate componentkey."""
    return '<div role="menu">' + "".join(items) + "</div>"


def _menu_item(user: str, key_suffix: str | None, text: str) -> str:
    key = (
        f' componentkey="ConnectButtonstate:invitation:urn:li:member:5_{key_suffix}"'
        if key_suffix
        else ""
    )
    return f'<a role="menuitem" href="https://www.linkedin.com/in/{user}/"{key}><span>{text}</span></a>'


def _page_with_portal(portal: str, *sections: str) -> str:
    return f"<html><body><main>{''.join(sections)}</main>{portal}</body></html>"


class TestMoreMenuConnect:
    async def test_follow_only_with_connect_in_open_more_menu_is_connectable(
        self, dom_page
    ):
        menu = _more_menu(
            '<div role="menuitem"><span>Save to PDF</span></div>',
            _menu_item(USER, "connect", "Connect"),
            _menu_item(USER, None, "Report"),
        )
        html = _page_with_portal(
            menu, _top_card(MESSAGE, FOLLOW, MORE_OPEN), _rail(USER, "7", "8")
        )
        state, raw = await _state(dom_page, html)
        assert raw["hasConnectButton"] is True
        assert state == "connectable"

    async def test_open_more_menu_without_connect_is_not_connectable(self, dom_page):
        menu = _more_menu(
            _menu_item(USER, None, "Report"), _menu_item(USER, None, "Block")
        )
        html = _page_with_portal(
            menu, _top_card(MESSAGE, FOLLOW, MORE_OPEN), _rail(USER, "7", "8")
        )
        state, raw = await _state(dom_page, html)
        assert raw["hasConnectButton"] is False
        assert state != "connectable"

    async def test_pending_in_open_more_menu_is_pending(self, dom_page):
        menu = _more_menu(_menu_item(USER, "pending", "Pending"))
        html = _page_with_portal(menu, _top_card(MESSAGE, FOLLOW, MORE_OPEN))
        state, raw = await _state(dom_page, html)
        assert raw["hasConnectStateAnchor"] is True
        assert state == "pending"


MORE_UNHYDRATED = (
    '<button type="button" id="more" aria-label="More"><span></span></button>'
)


def _hydrate_more_after(ms: int) -> str:
    """Live 2026-11-02 (cedric-lewis-830211b1, 2 of 6 loads): the More button
    paints with aria-label but no aria-expanded, and gains aria-expanded
    seconds later; the menu opens only after that."""
    return (
        "<script>setTimeout(() => {"
        "const b = document.getElementById('more'); b.setAttribute('aria-expanded', 'false');"
        "b.addEventListener('click', () => { b.setAttribute('aria-expanded', 'true');"
        "const m = document.createElement('div'); m.setAttribute('role', 'menu');"
        'm.innerHTML = \'<a role="menuitem" href="https://www.linkedin.com/in/testuser/" '
        'componentkey="ConnectButtonstate:invitation:urn:li:member:5_connect"><span>Connect</span></a>\';'
        "document.body.appendChild(m); });"
        f"}}, {ms});</script>"
    )


def _connection_actions(page) -> ConnectionActions:
    session = PageSession(page)

    async def unread(_username: str):
        raise AssertionError("not used")

    return ConnectionActions(session, PageNavigator(session), unread)


class TestMoreButtonHydration:
    async def test_waits_for_more_button_to_hydrate_then_opens_menu(self, dom_page):
        html = _page(_top_card(MESSAGE, FOLLOW, MORE_UNHYDRATED)).replace(
            "</body>", _hydrate_more_after(1500) + "</body>"
        )
        await dom_page.set_content(html)
        opened = await _connection_actions(dom_page)._open_more_menu()
        assert opened is True
        raw = await dom_page.evaluate(ACTION_SIGNALS_JS, USER)
        assert raw["hasConnectButton"] is True

    async def test_more_button_that_never_hydrates_reports_not_opened(self, dom_page):
        await dom_page.set_content(_page(_top_card(MESSAGE, FOLLOW, MORE_UNHYDRATED)))
        actions = _connection_actions(dom_page)
        opened = await actions._open_more_menu(ready_timeout=500)
        assert opened is False


HIDDEN_PLAYER_MENU = (
    '<div class="video-player" style="display:none"><div role="menu">'
    '<div role="menuitem">subtitles settings</div></div></div>'
)


class TestMoreMenuBehindHiddenPlayerMenu:
    async def test_opens_when_a_hidden_video_menu_comes_first(self, dom_page):
        """Live 2026-11-02 (cedric-lewis-830211b1, 3 of 6 loads): a profile video
        renders hidden caption menus with role="menu" before the More menu, so
        waiting for the first [role=menu] to be visible timed out while the
        real menu was open with Connect in it."""
        html = (
            "<html><body>"
            + HIDDEN_PLAYER_MENU
            + f"<main>{_top_card(MESSAGE, FOLLOW, MORE_UNHYDRATED)}</main>"
            + _hydrate_more_after(0)
            + "</body></html>"
        )
        await dom_page.set_content(html)
        opened = await _connection_actions(dom_page)._open_more_menu()
        assert opened is True
        raw = await dom_page.evaluate(ACTION_SIGNALS_JS, USER)
        assert raw["hasConnectButton"] is True


# Live 2026-11-02 (Cedric Lewis, Blake Ballenger, Mark Schenkman): a
# Message-first row, Message + Follow + "…", where "…" first paints as a bare
# <button aria-label="More"> with no aria-expanded and no handler, and gains
# both a second or more later. Connect is only in the menu it opens. The page
# also keeps the video player's hidden [role="menu"] (subtitles).
PROFILE_URL = f"https://www.linkedin.com/in/{USER}/"
SUBTITLES_MENU = (
    '<div role="menu" style="display:none"><li>subtitles settings</li></div>'
)


def _late_more(menu: str, delay_ms: int) -> str:
    """A More button that only hydrates (aria-expanded + click handler)
    after ``delay_ms``; its click mounts ``menu`` in a portal."""
    return (
        '<button type="button" id="more" aria-label="More"><svg></svg></button>'
        "<script>setTimeout(() => {"
        "const b = document.getElementById('more');"
        "b.setAttribute('aria-expanded', 'false');"
        "b.addEventListener('click', () => {"
        "b.setAttribute('aria-expanded', 'true');"
        f"document.body.insertAdjacentHTML('beforeend', {menu!r});"
        "});"
        f"}}, {delay_ms});</script>"
    )


async def _serve(page, html: str) -> None:
    async def fulfill(route):
        await route.fulfill(body=html, content_type="text/html")

    await page.route(PROFILE_URL, fulfill)
    await page.goto(PROFILE_URL)


def _live_actions(page):
    from typing import Any, cast

    from patchright.async_api import Page

    from linkedin_mcp_server.linkedin.connection_actions import ConnectionActions
    from linkedin_mcp_server.linkedin.navigation import PageNavigator
    from linkedin_mcp_server.linkedin.session import PageSession

    async def unreachable(_username: str) -> dict[str, Any]:
        raise AssertionError("these cases never read a profile")

    session = PageSession(cast(Page, page))
    return ConnectionActions(session, PageNavigator(session), unreachable)


class TestHalfLoadedTopCard:
    async def test_message_and_labelled_more_is_connected_not_follow_only(
        self, dom_page
    ):
        # The 2026-10 More carries aria-label; it is the menu opener, not an action.
        state, raw = await _state(dom_page, _page(_top_card(MESSAGE, MORE)))
        assert raw["hasLabeledActionButton"] is False
        assert state == "already_connected"

    async def test_message_follow_more_is_still_follow_only(self, dom_page):
        state, _ = await _state(dom_page, _page(_top_card(MESSAGE, FOLLOW, MORE)))
        assert state == "follow_only"

    async def test_top_card_is_not_ready_until_more_hydrates(self, dom_page):
        from linkedin_mcp_server.linkedin.connection_actions import TOP_CARD_READY_JS

        await dom_page.set_content(
            _page(_top_card(MESSAGE, FOLLOW, MORE), _rail(USER, "7"))
        )
        assert (
            await dom_page.evaluate(TOP_CARD_READY_JS) is False
        )  # rail Connect doesn't count
        await dom_page.evaluate(
            "document.querySelector('main section button[aria-label=More]')"
            ".setAttribute('aria-expanded', 'false')"
        )
        assert await dom_page.evaluate(TOP_CARD_READY_JS) is True

    async def test_hidden_player_menu_is_not_the_more_menu(self, dom_page):
        from linkedin_mcp_server.linkedin.connection_actions import MORE_MENU_OPEN_JS

        await _serve(
            dom_page,
            _page_with_portal(SUBTITLES_MENU, _top_card(MESSAGE, FOLLOW, MORE)),
        )
        assert await dom_page.evaluate(MORE_MENU_OPEN_JS) is False

    @pytest.mark.parametrize(
        "requested", [USER, "old-vanity-name-123"], ids=["slug", "redirected-slug"]
    )
    async def test_connect_under_a_late_hydrating_more_is_found(
        self, dom_page, requested
    ):
        menu = _more_menu(
            '<div role="menuitem"><span>Save to PDF</span></div>',
            _menu_item(USER, "connect", "Connect"),
            _menu_item(USER, None, "Report"),
        )
        html = _page_with_portal(
            SUBTITLES_MENU,
            _top_card(MESSAGE, FOLLOW, _late_more(menu, 1500)),
            _rail(USER, "7", "8"),
        )
        await _serve(dom_page, html)

        signals, state, menu_failed = await _live_actions(
            dom_page
        )._read_signals_through_more_menu(requested)

        assert menu_failed is False
        assert signals.has_connect_button is True
        assert state == "connectable"

    async def test_message_only_row_with_connect_in_menu_is_connectable(self, dom_page):
        menu = _more_menu(
            _menu_item(USER, "connect", "Connect"), _menu_item(USER, None, "Report")
        )
        await _serve(dom_page, _page(_top_card(MESSAGE, _late_more(menu, 300))))

        _, state, menu_failed = await _live_actions(
            dom_page
        )._read_signals_through_more_menu(USER)

        assert state == "connectable"

    async def test_first_degree_menu_without_connect_stays_connected(self, dom_page):
        menu = _more_menu(
            _menu_item(USER, None, "Remove connection"),
            _menu_item(USER, None, "Report"),
        )
        await _serve(dom_page, _page(_top_card(MESSAGE, _late_more(menu, 300))))

        _, state, menu_failed = await _live_actions(
            dom_page
        )._read_signals_through_more_menu(USER)

        assert state == "already_connected"


# Live 2026-11-02 (Abby Smith-Nieves, viewed by a Sales Navigator account):
# Follow + "Save in Sales Navigator" + More, no Message anchor in the row;
# Message and Connect are both inside the More menu.
SAVE_IN_SALES_NAV = (
    '<button type="button" aria-label="Save as a lead in Sales Navigator">'
    "<span>Save in Sales Navigator</span></button>"
)
VIDEO_PLAYER = (
    "<div><video></video>"
    '<button type="button" aria-label="Play"><svg></svg></button>'
    '<button type="button" aria-label="Settings" aria-expanded="false"><svg></svg></button></div>'
)


class TestRowWithoutMessage:
    async def test_follow_first_row_without_message_opens_more_and_finds_connect(
        self, dom_page
    ):
        menu = _more_menu(
            _menu_item(USER, None, "Message"),
            _menu_item(USER, "connect", "Connect"),
            _menu_item(USER, None, "Report"),
        )
        html = _page_with_portal(
            SUBTITLES_MENU,
            _top_card(FOLLOW, SAVE_IN_SALES_NAV, _late_more(menu, 800), mutual=True),
            _rail(USER, "7"),
        )
        await _serve(dom_page, html)

        signals, state, menu_failed = await _live_actions(
            dom_page
        )._read_signals_through_more_menu(USER, rowless_too=True)

        assert menu_failed is False
        assert signals.has_connect_button is True
        assert state == "connectable"

    async def test_row_without_message_and_no_connect_stays_unavailable(self, dom_page):
        menu = _more_menu(_menu_item(USER, None, "Report"))
        await _serve(
            dom_page, _page(_top_card(FOLLOW, SAVE_IN_SALES_NAV, _late_more(menu, 200)))
        )

        _, state, menu_failed = await _live_actions(
            dom_page
        )._read_signals_through_more_menu(USER, rowless_too=True)

        assert (state, menu_failed) == ("unavailable", False)

    async def test_video_player_controls_are_not_the_action_row(self, dom_page):
        from linkedin_mcp_server.linkedin.connection_actions import OPEN_MORE_BUTTON_JS

        await dom_page.set_content(
            _page(f"<section>{VIDEO_PLAYER}<h2>Test User</h2></section>")
        )
        assert await dom_page.evaluate(OPEN_MORE_BUTTON_JS) is False
