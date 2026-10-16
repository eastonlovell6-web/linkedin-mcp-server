# ruff: noqa: F811  (the imported dom_page fixture is "redefined" as a test argument)
"""Browser-DOM tests for ``get_inbox_threads``.

The fixture follows the conversation list LinkedIn rendered on bare
``/messaging/`` on 2026-10-16 (three read-only ``inbox-dom`` live checks, text
masked; names and previews here are invented):

* the list is ``ul.msg-conversations-container__conversations-list``
  (``aria-label="Conversation List"``); each conversation is a direct child
  ``li.msg-conversation-listitem`` (Ember ``id``), newest first. The list also
  holds two non-conversation ``<li>`` (a loader and a ``p3`` footer);
* only rows near the viewport are rendered. The rest are the same ``li`` with
  ``msg-conversation-card--occluded`` and no content. A row renders once it is
  scrolled into view and stays rendered; scrolling the list to its end loads
  20 more rows. 10 of 20 rows were rendered on load;
* a rendered row holds the participant name in
  ``h3.msg-conversation-listitem__participant-names`` (one ``span.truncate``)
  and the preview in one ``p`` whose class is
  ``msg-conversation-card__message-snippet``, with ``--unread`` added on an
  unread row, or ``msg-conversation-card__message-snippet--v2`` on a row with
  a "Reply?" nudge (whose nudge text is a separate ``p``);
* the preview of our own last message starts with ``You:``. Theirs starts with
  their first name and a colon, or with no prefix at all; sponsored and InMail
  rows start with a ``span.msg-conversation-card__pill`` ("InMail •");
* an unread row has ``.msg-conversation-card__unread-count``
  (``aria-label="1 unread message"``);
* bare ``/messaging/`` opens the newest thread by itself (its row's link has
  ``--active``); no row needs a click to be read.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from linkedin_mcp_server.linkedin.content import PageContentReader
from linkedin_mcp_server.linkedin.conversations import ConversationReader
from linkedin_mcp_server.linkedin.navigation import PageNavigator
from linkedin_mcp_server.linkedin.profile_page import ProfilePageReader
from linkedin_mcp_server.linkedin.session import PageSession
from test_message_recipient_dom import dom_page  # noqa: F401

pytestmark = [pytest.mark.browser_dom, pytest.mark.xdist_group("browser_runtime")]

INBOX_URL = "https://www.linkedin.com/messaging/"


def row(
    name: str,
    snippet_html: str,
    *,
    unread: bool = False,
    snippet_class: str = "msg-conversation-card__message-snippet",
    nudge: str = "",
) -> str:
    """The inner markup of one rendered conversation row."""
    if unread:
        snippet_class += " msg-conversation-card__message-snippet--unread"
    badge = (
        '<div class="artdeco-notification-badge msg-conversation-card__unread-count"'
        ' aria-label="1 unread message"><span class="notification-badge__count"'
        ' aria-hidden="true">1</span></div>'
        if unread
        else ""
    )
    nudge_html = (
        f'<p class="msg-conversation-card__nudge-text">{nudge}</p>' if nudge else ""
    )
    return (
        '<div class="msg-conversation-card msg-conversations-container__pillar">'
        '<div class="msg-conversation-listitem__link'
        ' msg-conversations-container__convo-item-link pl3"'
        " onclick=\"document.getElementById('clicks').insertAdjacentHTML("
        "'beforeend', '<li>row</li>')\">"
        '<div class="msg-selectable-entity">'
        '<label class="msg-selectable-entity__checkbox-label ml2"'
        f' aria-label="Select conversation with {name}"></label></div>'
        '<div class="msg-conversation-card__rows">'
        '<div class="msg-conversation-card__row msg-conversation-card__title-row">'
        '<h3 class="msg-conversation-listitem__participant-names'
        ' msg-conversation-card__participant-names truncate pr1 t-16 t-black">'
        '<div class="display-flex justify-left align-items-center truncate">'
        f'<span class="truncate"> {name} </span></div></h3>'
        '<time class="msg-conversation-listitem__time-stamp t-14"> Oct 15 '
        '<span class="visually-hidden">Oct 15</span></time></div>'
        '<div class="msg-conversation-card__row msg-conversation-card__body-row">'
        '<div class="msg-conversation-card__message-snippet-container flex-grow-1">'
        f'<p class="{snippet_class} m0 t-14">  {snippet_html}  </p>'
        f"{nudge_html}</div>{badge}</div></div></div></div>"
    )


def inbox_html(rows: list[str], *, occluded: set[int] | None = None) -> str:
    """The inbox list; rows in ``occluded`` render only once scrolled into view.

    An occluded row is an empty ``li`` whose markup an IntersectionObserver on
    the list's scroll container fills in, as LinkedIn's renders on scroll.
    A click anywhere is logged in ``#clicks``, which the page's isolated world
    can read.
    """
    occluded = occluded or set()
    items = []
    for index, inner in enumerate(rows):
        if index in occluded:
            items.append(
                f'<li id="ember{index}" class="ember-view'
                " msg-conversation-card--occluded scaffold-layout__list-item"
                ' msg-conversation-listitem msg-conversations-container__convo-item"'
                f' style="height:90px" data-template="{_attr(inner)}"></li>'
            )
        else:
            items.append(
                f'<li id="ember{index}" class="ember-view scaffold-layout__list-item'
                ' msg-conversation-listitem msg-conversations-container__convo-item"'
                f' style="height:90px">{inner}</li>'
            )
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
      <main>
        <div id="scroller" style="height:300px;overflow-y:auto">
          <ul class="list-style-none msg-conversations-container__conversations-list"
              aria-label="Conversation List">
            {"".join(items)}
            <li class="p3"></li>
          </ul>
        </div>
        <ul id="clicks"></ul>
      </main>
      <script>
        document.addEventListener('click', () => {{
          document.getElementById('clicks').insertAdjacentHTML('beforeend', '<li>any</li>');
        }}, true);
        const observer = new IntersectionObserver(entries => {{
          for (const entry of entries) {{
            const li = entry.target;
            if (!entry.isIntersecting || !li.dataset.template) continue;
            setTimeout(() => {{
              li.innerHTML = li.dataset.template;
              delete li.dataset.template;
              li.classList.remove('msg-conversation-card--occluded');
            }}, 150);
          }}
        }}, {{root: document.getElementById('scroller')}});
        document.querySelectorAll('li[data-template]').forEach(li => observer.observe(li));
      </script>
    </body></html>"""


def _attr(html: str) -> str:
    return html.replace("&", "&amp;").replace('"', "&quot;")


def _reader(page) -> ConversationReader:
    session = PageSession(page)

    async def _no_profile_read():
        raise AssertionError("the inbox read never reads a profile")

    return ConversationReader(
        session,
        PageNavigator(session),
        PageContentReader(session),
        ProfilePageReader(session, _no_profile_read),
    )


async def _read(page, html: str, *, limit: int = 20) -> dict:
    await page.goto(INBOX_URL)
    await page.set_content(html)
    page.set_default_timeout(600)
    reader = _reader(page)
    with (
        patch.object(PageNavigator, "_navigate_to_page", new_callable=AsyncMock),
        patch.object(PageSession, "check_rate_limit", new_callable=AsyncMock),
        patch(
            "linkedin_mcp_server.linkedin.conversations._INBOX_LIST_TIMEOUT_MS",
            300,
        ),
    ):
        return await reader.get_inbox_threads(limit=limit)


async def _clicks(page) -> int:
    return await page.locator("#clicks li").count()


async def test_reads_rows_with_direction(dom_page):
    result = await _read(
        dom_page,
        inbox_html([row("Mason White", "You: Hi Mason"), row("Sarah Lee", "A")]),
    )

    assert result["unparsed"] == 0
    assert result["threads"] == [
        {
            "name": "Mason White",
            "preview": "You: Hi Mason",
            "last_from_me": True,
            "unread": False,
        },
        {"name": "Sarah Lee", "preview": "A", "last_from_me": False, "unread": False},
    ]
    assert result["url"]


async def test_never_clicks_a_row(dom_page):
    await _read(
        dom_page,
        inbox_html(
            [row("Mason White", "You: Hi Mason"), row("Sarah Lee", "A")]
            + [row(f"Person {i}", "Sarah: hello") for i in range(6)],
            occluded={4, 5, 6, 7},
        ),
    )

    assert await _clicks(dom_page) == 0


async def test_unrecognised_row_counts_as_unparsed(dom_page):
    no_snippet = row("Ann Fox", "x").replace(
        "msg-conversation-card__message-snippet", "something-else"
    )
    no_name = row("", "Bo: hi")
    result = await _read(
        dom_page,
        inbox_html([row("Mason White", "You: Hi Mason"), no_snippet, no_name]),
    )

    assert result["unparsed"] == 2
    assert [thread["name"] for thread in result["threads"]] == ["Mason White"]


async def test_theirs_unread_and_nudged_rows(dom_page):
    result = await _read(
        dom_page,
        inbox_html(
            [
                row("Sarah Lee", "Sarah: Sounds good", unread=True),
                row(
                    "Tom Hill",
                    "Tom: Thanks for connecting",
                    snippet_class="msg-conversation-card__message-snippet--v2",
                    nudge="Received 9 days ago. Reply?",
                ),
                row(
                    "Ann Fox",
                    '<span class="msg-conversation-card__pill">InMail</span>'
                    '<span class="msg-conversation-card__message-label-dot"> • </span>'
                    "Quick question",
                ),
                row("Youssef Amar", "Youssef: You: is how it starts"),
            ]
        ),
    )

    assert result["unparsed"] == 0
    assert result["threads"] == [
        {
            "name": "Sarah Lee",
            "preview": "Sarah: Sounds good",
            "last_from_me": False,
            "unread": True,
        },
        {
            "name": "Tom Hill",
            "preview": "Tom: Thanks for connecting",
            "last_from_me": False,
            "unread": False,
        },
        {
            "name": "Ann Fox",
            "preview": "InMail • Quick question",
            "last_from_me": False,
            "unread": False,
        },
        {
            "name": "Youssef Amar",
            "preview": "Youssef: You: is how it starts",
            "last_from_me": False,
            "unread": False,
        },
    ]


async def test_occluded_rows_are_scrolled_into_view_and_read(dom_page):
    rows = [row(f"Person {i}", f"Person: message {i}") for i in range(8)]
    rows[6] = row("Mason White", "Mason: A")
    result = await _read(dom_page, inbox_html(rows, occluded={3, 4, 5, 6, 7}))

    assert result["unparsed"] == 0
    assert [thread["name"] for thread in result["threads"]] == [
        "Person 0",
        "Person 1",
        "Person 2",
        "Person 3",
        "Person 4",
        "Person 5",
        "Mason White",
        "Person 7",
    ]
    assert result["threads"][6]["last_from_me"] is False


async def test_row_that_never_renders_counts_as_unparsed(dom_page):
    html = inbox_html(
        [row("Mason White", "You: Hi Mason"), row("Sarah Lee", "A")], occluded={1}
    ).replace("li.dataset.template", "li.dataset.never")
    with patch(
        "linkedin_mcp_server.linkedin.conversations._INBOX_ROW_RENDER_TIMEOUT_MS",
        400,
    ):
        result = await _read(dom_page, html)

    assert result["unparsed"] == 1
    assert [thread["name"] for thread in result["threads"]] == ["Mason White"]


async def test_limit_reads_only_the_newest_rows(dom_page):
    rows = [row(f"Person {i}", "You: hi") for i in range(5)]
    result = await _read(dom_page, inbox_html(rows, occluded={4}), limit=3)

    assert [thread["name"] for thread in result["threads"]] == [
        "Person 0",
        "Person 1",
        "Person 2",
    ]
    assert result["unparsed"] == 0


async def test_missing_list_is_an_error(dom_page):
    result = await _read(dom_page, "<html><body><main></main></body></html>")

    assert result["error"] == "inbox_unavailable"
    assert result["threads"] == []
