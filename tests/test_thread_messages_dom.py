# ruff: noqa: F811  (the imported dom_page fixture is "redefined" as a test argument)
"""Browser-DOM tests for ``get_thread_messages``.

The fixture follows the conversation LinkedIn rendered for the profile-URN
compose route on 2026-10-16 (read-only ``thread-dom`` live check on the test
recipient's thread, 11 message items):

* every message is a ``[data-view-name="message-list-item"]`` carrying a
  ``data-event-urn`` of the form ``urn:li:msg_message:(<sender fsd_profile>,
  <id>)``;
* a headed item links its sender twice, by profile URN:
  ``a.msg-s-event-listitem__link[href="https://www.linkedin.com/in/<URN>"]``
  around the avatar, and a name link inside ``.msg-s-message-group__meta``.
  The recipient's items link the recipient's URN (the one in the compose
  route); ours link the signed-in member's URN. A follow-up from the same
  sender is assumed to be unheaded, so it takes the nearest headed item's
  sender (the send-confirmation reader's rule);
* the text is ``p.msg-s-event-listitem__body`` inside
  ``.msg-s-event__content``, with ``<br>`` line breaks (``<br><br>`` between
  paragraphs);
* the composer ``form.msg-form`` and the message list share a
  ``div.display-flex.flex-column.flex-grow-1`` ancestor, which ``threadScope``
  finds by climbing from the form.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from linkedin_mcp_server.linkedin.content import PageContentReader
from linkedin_mcp_server.linkedin.conversations import ConversationReader
from linkedin_mcp_server.linkedin.message_sender import (
    _ProfileMessageTarget,
    _ProfileMessageTargetResolution,
)
from linkedin_mcp_server.linkedin.navigation import PageNavigator
from linkedin_mcp_server.linkedin.profile_page import ProfilePageReader
from linkedin_mcp_server.linkedin.session import PageSession
from test_message_recipient_dom import dom_page  # noqa: F401

pytestmark = [pytest.mark.browser_dom, pytest.mark.xdist_group("browser_runtime")]

RECIPIENT_URN = "ACoAAB"
SELF_URN = "ACoAAS"
COMPOSE_URL = f"https://www.linkedin.com/messaging/compose/?recipient={RECIPIENT_URN}"
TARGET = _ProfileMessageTarget(
    profile_path="/in/testuser/",
    profile_urn=RECIPIENT_URN,
    compose_url=COMPOSE_URL,
    display_name="Test User",
)


def item(
    body_html: str,
    *,
    sender: str | None,
    event_id: str,
    urn_sender: str | None = None,
    named_by_urn: bool = True,
) -> str:
    """One message item; ``sender=None`` renders an unheaded follow-up.

    The event URN names ``urn_sender`` (default: the header's sender, or us),
    as LinkedIn's server URNs do; ``named_by_urn=False`` gives it a client URN
    that names nobody, leaving the header links as the only evidence.
    """
    head = ""
    if sender is not None:
        profile = f"https://www.linkedin.com/in/{sender}"
        head = (
            f'<a class="msg-s-event-listitem__link" href="{profile}">'
            f'<span class="a11y-text">View profile</span><img alt="Name"></a>'
            f'<div class="msg-s-message-group__meta"><span><a href="{profile}">'
            f'<span class="msg-s-message-group__name">Name</span></a></span>'
            f'<time class="msg-s-message-group__timestamp">3:21 PM</time></div>'
        )
    urn = (
        "urn:li:msg_message:(urn:li:fsd_profile:"
        f"{urn_sender or sender or SELF_URN},{event_id})"
        if named_by_urn
        else f"client-{event_id}"
    )
    return (
        f'<div class="msg-s-event-listitem" data-view-name="message-list-item" '
        f'data-event-urn="{urn}">{head}'
        f'<div class="msg-s-event-listitem__message-bubble">'
        f'<div class="msg-s-event__content">'
        f'<p class="msg-s-event-listitem__body">{body_html}</p>'
        f"</div></div></div>"
    )


def thread_html(items: list[str], script: str = "", header: str = "") -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
      <main><div class="display-flex flex-column flex-grow-1">
        <ul id="thread">{"".join(f"<li>{i}</li>" for i in items)}</ul>
        <form class="msg-form">
          {header}
          <div role="textbox" contenteditable="true"
               style="display:block;width:400px;min-height:30px"></div>
          <button type="submit">Send</button>
        </form>
      </div></main>
      <script>{script}</script>
    </body></html>"""


def _reader(page) -> ConversationReader:
    session = PageSession(page)

    async def _no_profile_read():
        raise AssertionError("the thread read resolves its target itself")

    return ConversationReader(
        session,
        PageNavigator(session),
        PageContentReader(session),
        ProfilePageReader(session, _no_profile_read),
    )


async def _read(
    page, html: str, *, limit: int = 20, settle_cap_ms: int | None = None
) -> dict:
    await page.goto(COMPOSE_URL)
    await page.set_content(html)
    page.set_default_timeout(600)
    reader = _reader(page)
    with (
        patch.object(PageNavigator, "_navigate_to_page", new_callable=AsyncMock),
        patch.object(PageSession, "check_rate_limit", new_callable=AsyncMock),
        patch.object(
            type(reader._message_sender),
            "_read_profile_message_target",
            new_callable=AsyncMock,
            return_value=_ProfileMessageTargetResolution("resolved", TARGET),
        ),
        patch(
            "linkedin_mcp_server.linkedin.message_sender._message_page_url_is_safe",
            return_value=True,
        ),
        patch(
            "linkedin_mcp_server.linkedin.conversations._THREAD_FIRST_MESSAGE_TIMEOUT_MS",
            300,
        ),
        patch(
            "linkedin_mcp_server.linkedin.message_sender._THREAD_SETTLE_TIMEOUT_MS",
            settle_cap_ms or 6000,
        ),
    ):
        return await reader.get_thread_messages("testuser", limit=limit)


async def test_reads_messages_with_direction(dom_page):
    result = await _read(
        dom_page,
        thread_html(
            [
                item("Hi, quick one.", sender=SELF_URN, event_id="1"),
                item("Just reply with a letter.", sender=None, event_id="2"),
                item("A", sender=RECIPIENT_URN, event_id="3"),
            ]
        ),
    )

    assert result["recipient_selected"] is True
    assert result["loaded"] is True
    assert result["their_count"] == 1
    assert result["my_count"] == 2
    assert result["messages"] == [
        {"from_me": True, "text": "Hi, quick one."},
        {"from_me": True, "text": "Just reply with a letter."},
        {"from_me": False, "text": "A"},
    ]
    assert result["messages"][-1] == {"from_me": False, "text": "A"}


async def test_multiline_text_keeps_line_breaks(dom_page):
    result = await _read(
        dom_page,
        thread_html([item("A<br>thanks", sender=RECIPIENT_URN, event_id="1")]),
    )

    assert result["messages"] == [{"from_me": False, "text": "A\nthanks"}]


async def test_empty_thread_returns_no_messages(dom_page):
    result = await _read(dom_page, thread_html([]))

    assert "error" not in result
    assert result["loaded"] is False
    assert result["messages"] == []
    assert result["their_count"] == 0
    assert result["my_count"] == 0


async def test_waits_for_late_history(dom_page):
    # Measured 2026-10-14: the newest message renders first and older history
    # is inserted above it about 0.4 s later.
    older = [
        item("Hi, quick one.", sender=SELF_URN, event_id="1"),
        item("Ya I like it.", sender=RECIPIENT_URN, event_id="2"),
    ]
    script = f"""
      setTimeout(() => {{
        const thread = document.getElementById('thread');
        thread.insertAdjacentHTML('afterbegin', {"".join(f"<li>{i}</li>" for i in older)!r});
      }}, 400);
    """
    result = await _read(
        dom_page,
        thread_html([item("Following up.", sender=SELF_URN, event_id="3")], script),
    )

    assert result["my_count"] == 2
    assert result["their_count"] == 1
    assert [m["text"] for m in result["messages"]] == [
        "Hi, quick one.",
        "Ya I like it.",
        "Following up.",
    ]


async def test_limit_keeps_the_newest_messages(dom_page):
    result = await _read(
        dom_page,
        thread_html(
            [
                item("one", sender=SELF_URN, event_id="1"),
                item("two", sender=RECIPIENT_URN, event_id="2"),
                item("three", sender=SELF_URN, event_id="3"),
            ]
        ),
        limit=2,
    )

    assert [m["text"] for m in result["messages"]] == ["two", "three"]
    assert (result["their_count"], result["my_count"]) == (1, 2)


async def test_contradicting_recipient_returns_mismatch(dom_page):
    result = await _read(
        dom_page,
        thread_html(
            [item("A", sender=RECIPIENT_URN, event_id="1")],
            header='<a href="https://www.linkedin.com/in/someone-else/">Other</a>',
        ),
    )

    assert result["error"] == "recipient_mismatch"
    assert result["messages"] == []


async def test_unknown_sender_fails_closed(dom_page):
    # The oldest loaded item is a follow-up whose headed predecessor never
    # rendered, so its sender cannot be told.
    result = await _read(
        dom_page,
        thread_html(
            [
                item("orphan", sender=None, event_id="1", named_by_urn=False),
                item("A", sender=RECIPIENT_URN, event_id="2"),
            ]
        ),
    )

    assert result["error"] == "sender_unknown"
    assert result["messages"] == []


@pytest.mark.parametrize("named_by_urn", [True, False], ids=["event-urn", "header"])
async def test_profile_link_in_a_reply_body_does_not_make_it_ours(
    dom_page, named_by_urn
):
    # The recipient's unheaded follow-up linkifies another member. Only the
    # event URN or the header links name a sender, never a link in the body.
    body = '<a href="https://www.linkedin.com/in/someone-else">Someone</a> can help'
    result = await _read(
        dom_page,
        thread_html(
            [
                item("Hi, quick one.", sender=SELF_URN, event_id="1"),
                item(
                    "A",
                    sender=RECIPIENT_URN,
                    event_id="2",
                    named_by_urn=named_by_urn,
                ),
                item(
                    body,
                    sender=None,
                    event_id="3",
                    urn_sender=RECIPIENT_URN,
                    named_by_urn=named_by_urn,
                ),
            ]
        ),
    )

    assert result["their_count"] == 2
    assert result["my_count"] == 1
    assert result["messages"][-1] == {"from_me": False, "text": "Someone can help"}


async def test_event_urn_outranks_the_preceding_header(dom_page):
    # An unheaded item whose server URN names the recipient is theirs even
    # right after one of ours.
    result = await _read(
        dom_page,
        thread_html(
            [
                item("Hi, quick one.", sender=SELF_URN, event_id="1"),
                item("A", sender=None, event_id="2", urn_sender=RECIPIENT_URN),
            ]
        ),
    )

    assert (result["their_count"], result["my_count"]) == (1, 1)


async def test_thread_still_changing_at_the_cap_is_an_error(dom_page):
    # Messages keep arriving faster than the quiet period, so the list never
    # settles; whatever rendered so far must not read as the whole thread.
    script = f"""
      let next = 10;
      setInterval(() => {{
        document.getElementById('thread').insertAdjacentHTML(
          'afterbegin',
          '<li><div data-view-name="message-list-item" '
            + 'data-event-urn="urn:li:msg_message:(urn:li:fsd_profile:{RECIPIENT_URN},'
            + (next++) + ')"></div></li>');
      }}, 200);
    """
    result = await _read(
        dom_page,
        thread_html([item("Following up.", sender=SELF_URN, event_id="1")], script),
        settle_cap_ms=1500,
    )

    assert result["error"] == "thread_unsettled"
    assert result["messages"] == []
