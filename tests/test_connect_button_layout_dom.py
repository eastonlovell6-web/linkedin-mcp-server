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

from linkedin_mcp_server.linkedin.connection import ActionSignals, detect_connection_state
from linkedin_mcp_server.linkedin.connection_actions import ACTION_SIGNALS_JS

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
        state, raw = await _state(dom_page, _page(_top_card(_connect_anchor(USER, "connect"), MESSAGE, MORE)))
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
        state, raw = await _state(dom_page, _page(_top_card(_connect_anchor(USER, "withdraw"), MESSAGE, MORE)))
        assert raw["hasConnectButton"] is False
        assert raw["hasConnectStateAnchor"] is True
        assert state == "pending"

    async def test_sidebar_connect_for_another_profile_is_not_connectable(self, dom_page):
        state, raw = await _state(dom_page, _page(_top_card(MESSAGE, MORE), _sidebar_connect("someoneelse")))
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
        html = _page_with_header(connect, _top_card(connect, MESSAGE, MORE), _rail(USER, "13489154"))
        state, raw = await _state(dom_page, html)
        assert raw["hasConnectButton"] is True
        assert raw["hasConnectStateAnchor"] is False
        assert state == "connectable"

    async def test_rail_connect_alone_is_not_connectable(self, dom_page):
        # A top card without a Connect control (e.g. 1st-degree) must not
        # borrow one from the rail, even though the rail links to this profile.
        state, raw = await _state(dom_page, _page(_top_card(MESSAGE, MORE), _rail(USER, "1", "2")))
        assert raw["hasConnectButton"] is False
        assert state != "connectable"

    async def test_pending_outranks_connect_in_the_top_card(self, dom_page):
        html = _page(_top_card(_connect_anchor(USER, "pending"), _connect_anchor(USER, "connect"), MESSAGE, MORE))
        state, _ = await _state(dom_page, html)
        assert state == "pending"


FOLLOW = '<button type="button" aria-label="Follow Test User"><span>Follow</span></button>'
MORE_OPEN = '<button type="button" aria-expanded="true"><span></span></button>'


def _more_menu(*items: str) -> str:
    """The open profile More menu. Live 2026-10-19 (wes-hinson): LinkedIn
    renders it in a portal OUTSIDE <main>; Connect is an
    <a role="menuitem"> with the same ConnectButtonstate componentkey."""
    return '<div role="menu">' + "".join(items) + "</div>"


def _menu_item(user: str, key_suffix: str | None, text: str) -> str:
    key = f' componentkey="ConnectButtonstate:invitation:urn:li:member:5_{key_suffix}"' if key_suffix else ""
    return f'<a role="menuitem" href="https://www.linkedin.com/in/{user}/"{key}><span>{text}</span></a>'


def _page_with_portal(portal: str, *sections: str) -> str:
    return f"<html><body><main>{''.join(sections)}</main>{portal}</body></html>"


class TestMoreMenuConnect:
    async def test_follow_only_with_connect_in_open_more_menu_is_connectable(self, dom_page):
        menu = _more_menu(
            '<div role="menuitem"><span>Save to PDF</span></div>',
            _menu_item(USER, "connect", "Connect"),
            _menu_item(USER, None, "Report"),
        )
        html = _page_with_portal(menu, _top_card(MESSAGE, FOLLOW, MORE_OPEN), _rail(USER, "7", "8"))
        state, raw = await _state(dom_page, html)
        assert raw["hasConnectButton"] is True
        assert state == "connectable"

    async def test_open_more_menu_without_connect_is_not_connectable(self, dom_page):
        menu = _more_menu(_menu_item(USER, None, "Report"), _menu_item(USER, None, "Block"))
        html = _page_with_portal(menu, _top_card(MESSAGE, FOLLOW, MORE_OPEN), _rail(USER, "7", "8"))
        state, raw = await _state(dom_page, html)
        assert raw["hasConnectButton"] is False
        assert state != "connectable"

    async def test_pending_in_open_more_menu_is_pending(self, dom_page):
        menu = _more_menu(_menu_item(USER, "pending", "Pending"))
        html = _page_with_portal(menu, _top_card(MESSAGE, FOLLOW, MORE_OPEN))
        state, raw = await _state(dom_page, html)
        assert raw["hasConnectStateAnchor"] is True
        assert state == "pending"
