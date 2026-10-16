# ruff: noqa: F811  (the imported dom_page fixture is "redefined" as a test argument)
from unittest.mock import AsyncMock, patch

import pytest

from linkedin_mcp_server.linkedin.message_sender import (
    _MESSAGE_COMPOSER_INSPECT_JS,
    _MESSAGE_COMPOSER_PINNED_JS,
    MessageSender,
    _ProfileMessageTargetResolution,
)
from linkedin_mcp_server.linkedin.navigation import PageNavigator
from test_message_recipient_dom import (  # noqa: F401
    _message_target,
    _sender,
    _set_composer_content,
    dom_page,
)

pytestmark = [pytest.mark.browser_dom, pytest.mark.xdist_group("browser_runtime")]

PITCH = (
    "Hi Ada, quick one.\n\n"
    "Only about 1 in 5 callers leaves a voicemail.\n\n"
    "Just reply with a letter:\n\n"
    "A Yes, I'm interested. Let's move forward\n"
    "B I'm interested, but not right now\n"
    "D Go to hell, leave me alone 😄"
)


def composer_html(prefill: str = "") -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
      <section role="dialog" data-recipient-urn="ACoAAB">
        <form>
          <a href="https://www.linkedin.com/in/testuser/">Test</a>
          <div role="textbox" contenteditable="true"
               style="display:block;width:400px;min-height:30px">{prefill}</div>
          <button type="submit" onclick="event.preventDefault();
            this.setAttribute('data-clicked','yes')">Send</button>
        </form>
      </section>
    </body></html>"""


async def _owner(page):
    sender = _sender(page)
    owner = await sender._resolve_message_owner(
        _message_target(), expected_route=page.url
    )
    assert owner is not None
    return sender, owner


async def test_canonical_helpers_are_defined_in_both_fragments(dom_page):
    for fragment in (_MESSAGE_COMPOSER_INSPECT_JS, _MESSAGE_COMPOSER_PINNED_JS):
        result = await dom_page.evaluate(
            "() => {" + fragment + " return [canonicalMessage(' a \\n\\n b \\n'), "
            "sameMessage('a\\n\\nb', 'a\\nb'), sameMessage('a b', 'a\\nb')]; }"
        )
        assert result == ["a\nb", True, False]


async def test_blank_line_paragraphs_compare_equal(dom_page):
    same = await dom_page.evaluate(
        "(arg) => {"
        + _MESSAGE_COMPOSER_PINNED_JS
        + " return sameMessage(arg.a, arg.b); }",
        {"a": PITCH, "b": PITCH.replace("\n\n", "\n \n\n").replace("😄", "😄 ")},
    )
    assert same is True


async def test_multiline_write_inserts_paragraphs(dom_page):
    await _set_composer_content(dom_page, composer_html())
    sender, owner = await _owner(dom_page)
    await dom_page.evaluate(
        "() => { window.__keyEvents = 0; "
        "document.addEventListener('keydown', () => window.__keyEvents++, true); }"
    )
    written = await sender._write_verified_message(
        PITCH, target=_message_target(), owner=owner
    )
    text = await dom_page.evaluate(
        "() => document.querySelector('[contenteditable=true]').innerText"
    )
    key_events = await dom_page.evaluate("() => window.__keyEvents")
    clicked = await dom_page.locator("form button").get_attribute("data-clicked")
    await sender._dispose_message_owner(owner)

    assert written == "written"
    assert [x.strip() for x in text.split("\n") if x.strip()] == [
        x for x in PITCH.split("\n") if x.strip()
    ]
    assert key_events == 0
    assert clicked is None  # writing never submits


async def test_multiline_write_refuses_occupied_editor(dom_page):
    await _set_composer_content(dom_page, composer_html(prefill="draft"))
    sender, owner = await _owner(dom_page)
    written = await sender._write_verified_message(
        PITCH, target=_message_target(), owner=owner
    )
    text = await dom_page.evaluate(
        "() => document.querySelector('[contenteditable=true]').innerText"
    )
    await sender._dispose_message_owner(owner)

    assert written == "occupied"
    assert text.strip() == "draft"


async def test_multiline_write_then_submit_clicks_once(dom_page):
    await _set_composer_content(dom_page, composer_html())
    sender, owner = await _owner(dom_page)
    written = await sender._write_verified_message(
        PITCH, target=_message_target(), owner=owner
    )
    submitted = await sender._submit_verified_message(
        PITCH, target=_message_target(), owner=owner
    )
    await sender._dispose_message_owner(owner)

    assert written == "written"
    assert submitted == "clicked"


async def _text_and_clicked(page):
    text = await page.evaluate(
        "() => document.querySelector('[contenteditable=true]').innerText"
    )
    clicked = await page.locator("form button").get_attribute("data-clicked")
    return text, clicked


# Reverses what an insertText put in: every character stays, the order breaks.
REVERSE_SINGLE_LINE_JS = """<script>
  document.querySelector('[contenteditable=true]').addEventListener(
    'input', e => {
      if (document.documentElement.dataset.garble && e.inputType === 'insertText') {
        e.target.textContent = Array.from(e.target.textContent).reverse().join('');
      }
    });
  document.documentElement.dataset.garble = 'yes';
</script>"""


async def test_garbled_paragraph_write_is_left_as_diverged(dom_page):
    # The editor flattens paragraph breaks, so the read-back no longer matches.
    # After a break that may also be LinkedIn sending, so nothing is cleared.
    await _set_composer_content(
        dom_page,
        composer_html()
        + """<script>
        document.querySelector('[contenteditable=true]').addEventListener(
          'input', e => { if (e.inputType === 'insertParagraph') {
            e.target.textContent = e.target.textContent; } });
        </script>""",
    )
    sender, owner = await _owner(dom_page)
    written = await sender._write_verified_message(
        PITCH, target=_message_target(), owner=owner
    )
    text, clicked = await _text_and_clicked(dom_page)
    await sender._dispose_message_owner(owner)

    assert written == "diverged"
    assert text.strip() != ""
    assert clicked is None


async def test_garbled_single_line_insert_is_cleared_and_never_submitted(dom_page):
    await _set_composer_content(dom_page, composer_html() + REVERSE_SINGLE_LINE_JS)
    sender, owner = await _owner(dom_page)
    written = await sender._write_verified_message(
        "One line only", target=_message_target(), owner=owner
    )
    text, clicked = await _text_and_clicked(dom_page)
    await sender._dispose_message_owner(owner)

    assert written == "invalid"
    assert text.strip() == ""
    assert clicked is None


@pytest.mark.parametrize(
    ("working_calls", "expected", "left"),
    [(0, "unsupported", False), (3, "diverged", True)],
    ids=["before_any_break", "after_a_break"],
)
async def test_execcommand_failing_partway(dom_page, working_calls, expected, left):
    # Before any paragraph break a failed write is cleared and retry-safe;
    # after one it may be LinkedIn having taken the break, so it stays put.
    await _set_composer_content(dom_page, composer_html())
    sender, owner = await _owner(dom_page)
    await dom_page.evaluate(
        """working => {
          const real = document.execCommand.bind(document);
          let calls = 0;
          document.execCommand = (...args) =>
            (++calls > working ? false : real(...args));
        }""",
        working_calls,
    )
    written = await sender._write_verified_message(
        PITCH, target=_message_target(), owner=owner
    )
    text, clicked = await _text_and_clicked(dom_page)
    await sender._dispose_message_owner(owner)

    assert written == expected
    assert (text.strip() != "") is left
    assert clicked is None


async def test_retry_after_failed_write_is_not_occupied(dom_page):
    await _set_composer_content(dom_page, composer_html() + REVERSE_SINGLE_LINE_JS)
    sender, owner = await _owner(dom_page)
    first = await sender._write_verified_message(
        "One line only", target=_message_target(), owner=owner
    )
    await sender._dispose_message_owner(owner)
    await dom_page.evaluate("() => { delete document.documentElement.dataset.garble; }")
    sender, owner = await _owner(dom_page)  # a retry is a new tool call
    second = await sender._write_verified_message(
        "One line only", target=_message_target(), owner=owner
    )
    await sender._dispose_message_owner(owner)

    assert first == "invalid"
    assert second == "written"


def thread_composer_html(script: str) -> str:
    """A composer beside a thread list, with a page script for the editor."""
    return (
        composer_html().replace(
            "<form>",
            '<div id="thread"><div data-view-name="message-list-item" '
            'data-event-urn="urn:li:msg_message:old">Earlier</div></div><form>',
        )
        + f"""<script>
      const editor = document.querySelector('[contenteditable=true]');
      editor.addEventListener('input', e => {{
        if (e.inputType === 'deleteContentBackward') {{
          document.documentElement.dataset.cleared = 'yes';
        }}
      }});
      {script}
    </script>"""
    )


async def _cleared(page):
    return await page.evaluate("() => document.documentElement.dataset.cleared")


async def test_editor_emptied_by_a_paragraph_break_diverges_without_clearing(
    dom_page,
):
    # Send without a synchronous message item: only the emptied editor shows it.
    await _set_composer_content(
        dom_page,
        thread_composer_html(
            """editor.addEventListener('input', e => {
                 if (e.inputType === 'insertParagraph') {
                   editor.textContent = '';
                 }
               });"""
        ),
    )
    sender, owner = await _owner(dom_page)
    written = await sender._write_verified_message(
        PITCH, target=_message_target(), owner=owner
    )
    text, clicked = await _text_and_clicked(dom_page)
    cleared = await _cleared(dom_page)
    await sender._dispose_message_owner(owner)

    assert written == "diverged"
    assert text.strip() == ""
    assert cleared is None
    assert clicked is None


async def test_new_thread_item_during_write_diverges_without_clearing(dom_page):
    # Send that leaves the text in place: only the new thread item shows it.
    await _set_composer_content(
        dom_page,
        thread_composer_html(
            """editor.addEventListener('input', e => {
                 if (e.inputType === 'insertParagraph' &&
                     !document.documentElement.dataset.sent) {
                   document.documentElement.dataset.sent = 'yes';
                   const item = document.createElement('div');
                   item.setAttribute('data-view-name', 'message-list-item');
                   item.textContent = editor.innerText;
                   document.getElementById('thread').appendChild(item);
                 }
               });"""
        ),
    )
    sender, owner = await _owner(dom_page)
    written = await sender._write_verified_message(
        PITCH, target=_message_target(), owner=owner
    )
    text, clicked = await _text_and_clicked(dom_page)
    cleared = await _cleared(dom_page)
    await sender._dispose_message_owner(owner)

    assert written == "diverged"
    assert text.strip() != ""
    assert cleared is None
    assert clicked is None


async def test_rerendered_thread_item_with_a_known_urn_is_not_a_send(dom_page):
    # A list re-render replaces the element but keeps its server URN.
    await _set_composer_content(
        dom_page,
        thread_composer_html(
            """editor.addEventListener('input', e => {
                 if (e.inputType === 'insertParagraph') {
                   const old = document.querySelector('[data-view-name="message-list-item"]');
                   old.replaceWith(old.cloneNode(true));
                 }
               });"""
        ),
    )
    sender, owner = await _owner(dom_page)
    written = await sender._write_verified_message(
        PITCH, target=_message_target(), owner=owner
    )
    await sender._dispose_message_owner(owner)

    assert written == "written"


async def test_single_line_does_not_need_insert_paragraph(dom_page):
    await _set_composer_content(dom_page, composer_html())
    await dom_page.evaluate(
        """() => {
          const real = document.queryCommandSupported.bind(document);
          document.queryCommandSupported = command =>
            command === 'insertParagraph' ? false : real(command);
        }"""
    )
    sender, owner = await _owner(dom_page)
    single = await sender._write_verified_message(
        "One line only", target=_message_target(), owner=owner
    )
    await sender._dispose_message_owner(owner)
    await _set_composer_content(dom_page, composer_html())
    await dom_page.evaluate(
        """() => {
          const real = document.queryCommandSupported.bind(document);
          document.queryCommandSupported = command =>
            command === 'insertParagraph' ? false : real(command);
        }"""
    )
    sender, owner = await _owner(dom_page)
    multi = await sender._write_verified_message(
        PITCH, target=_message_target(), owner=owner
    )
    text, _ = await _text_and_clicked(dom_page)
    await sender._dispose_message_owner(owner)

    assert single == "written"
    assert multi == "unsupported"
    assert text.strip() == ""


async def _send(page, message: str = PITCH) -> dict:
    """Run the whole send_message flow against the page as it stands."""
    # The test page has no <main>, so the flow's waits for it must time out
    # quickly rather than at Playwright's 30 s default.
    page.set_default_timeout(600)
    sender = _sender(page)
    with (
        patch.object(PageNavigator, "_navigate_to_page", new_callable=AsyncMock),
        patch.object(
            sender,
            "_read_profile_message_target",
            new_callable=AsyncMock,
            return_value=_ProfileMessageTargetResolution("resolved", _message_target()),
        ),
        patch(
            "linkedin_mcp_server.linkedin.message_sender._message_page_url_is_safe",
            return_value=True,
        ),
        patch(
            "linkedin_mcp_server.linkedin.message_sender._THREAD_SETTLE_QUIET_MS",
            50,
        ),
    ):
        return await sender.send_message("testuser", message, confirm_send=True)


# LinkedIn takes the first paragraph break as Send, but only after the write
# returned: the first line leaves, its bubble lands, and the composer empties.
SEND_FIRST_LINE_JS = """
  const thread = document.getElementById('thread');
  const sendFirstLine = () => {
    const item = document.createElement('div');
    item.setAttribute('data-view-name', 'message-list-item');
    item.textContent = editor.innerText.split('\\n')[0];
    thread.appendChild(item);
    editor.textContent = '';
  };
  // Test code evaluates in an isolated world, so it triggers this by event.
  document.addEventListener('send-first-line', sendFirstLine);
"""


async def test_async_paragraph_send_is_not_retry_safe(dom_page):
    await _set_composer_content(
        dom_page,
        thread_composer_html(
            SEND_FIRST_LINE_JS
            + """
            // The Send button enables some time after typing starts.
            const button = document.querySelector('form button');
            button.disabled = true;
            editor.addEventListener('input', e => {
              if (e.inputType === 'insertParagraph' &&
                  !document.documentElement.dataset.sent) {
                document.documentElement.dataset.sent = 'yes';
                setTimeout(sendFirstLine, 50);
                setTimeout(() => { button.disabled = false; }, 300);
              }
            });"""
        ),
    )

    result = await _send(dom_page)
    text, clicked = await _text_and_clicked(dom_page)

    assert result["status"] == "send_unconfirmed"
    assert result["sent"] is False
    assert result["retry_safe"] is False
    assert text.strip() == ""
    assert await _cleared(dom_page) is None
    assert clicked is None


@pytest.mark.parametrize(
    "step", ["_prepare_message_confirmation", "_submit_verified_message"]
)
async def test_paragraph_send_seen_before_a_later_step_is_not_retry_safe(
    dom_page, step
):
    await _set_composer_content(dom_page, thread_composer_html(SEND_FIRST_LINE_JS))
    original = getattr(MessageSender, step)

    async def send_first_line_then(self, *args, **kwargs):
        await dom_page.evaluate(
            "() => document.dispatchEvent(new Event('send-first-line'))"
        )
        return await original(self, *args, **kwargs)

    with patch.object(MessageSender, step, send_first_line_then):
        result = await _send(dom_page)
    text, clicked = await _text_and_clicked(dom_page)

    assert result["status"] == "send_unconfirmed"
    assert result["retry_safe"] is False
    assert text.strip() == ""
    assert await _cleared(dom_page) is None
    assert clicked is None


async def test_occupied_after_diverged_is_not_retry_safe(dom_page):
    # The first call's paragraph break sends what was typed so far and leaves
    # it in the composer; a retry then finds that remnant standing there.
    await _set_composer_content(
        dom_page,
        thread_composer_html(
            """editor.addEventListener('input', e => {
                 if (e.inputType === 'insertParagraph' &&
                     !document.documentElement.dataset.sent) {
                   document.documentElement.dataset.sent = 'yes';
                   const item = document.createElement('div');
                   item.setAttribute('data-view-name', 'message-list-item');
                   item.textContent = editor.innerText;
                   document.getElementById('thread').appendChild(item);
                 }
               });"""
        ),
    )

    first = await _send(dom_page)
    retry = await _send(dom_page)
    text, clicked = await _text_and_clicked(dom_page)

    assert first["status"] == "send_unconfirmed"
    assert first["retry_safe"] is False
    assert retry["status"] == "composer_occupied"
    assert retry["sent"] is False
    assert retry["retry_safe"] is False
    assert text.strip() != ""
    assert clicked is None


async def _assert_left_unconfirmed(page, result) -> str:
    text, clicked = await _text_and_clicked(page)
    assert result["status"] == "send_unconfirmed"
    assert result["sent"] is False
    assert result["retry_safe"] is False
    assert await _cleared(page) is None
    assert clicked is None
    return text


async def test_intercepted_paragraph_break_then_async_send_is_not_retry_safe(
    dom_page,
):
    # LinkedIn intercepts the break (execCommand reports failure, nothing is
    # inserted) and sends the first line 50 ms later. Chromium fires no
    # beforeinput for execCommand, so the interception is stubbed in the
    # evaluating world and the page is told by event to send.
    await _set_composer_content(
        dom_page,
        thread_composer_html(
            SEND_FIRST_LINE_JS
            + """document.addEventListener('break-intercepted', () =>
                   setTimeout(sendFirstLine, 50));"""
        ),
    )
    await dom_page.evaluate(
        """() => {
          const real = document.execCommand.bind(document);
          document.execCommand = (command, ...rest) => {
            if (command !== 'insertParagraph') return real(command, ...rest);
            document.dispatchEvent(new Event('break-intercepted'));
            return false;
          };
        }"""
    )

    result = await _send(dom_page)
    await dom_page.wait_for_function(
        "() => document.querySelectorAll('[data-view-name=message-list-item]')"
        ".length === 2"
    )
    text = await _assert_left_unconfirmed(dom_page, result)

    assert text.strip() == ""  # LinkedIn sent it; we never cleared it


@pytest.mark.parametrize("exit_path", ["disabled_timeout", "focus_lost"])
async def test_submit_ready_exits_after_a_break_are_not_retry_safe(dom_page, exit_path):
    # The Send LinkedIn queued from the break may land after the last poll.
    script = "document.querySelector('form button').disabled = true;"
    if exit_path == "focus_lost":
        script += """
          editor.addEventListener('input', () => setTimeout(() => {
            editor.blur();
            document.querySelector('form button').disabled = false;
          }, 20), {once: true});"""
    await _set_composer_content(dom_page, thread_composer_html(script))

    result = await _send(dom_page)
    text = await _assert_left_unconfirmed(dom_page, result)

    assert text.strip() != ""  # the written text is left, not cleared


@pytest.mark.parametrize(
    "step", ["_write_verified_message", "_prepare_message_confirmation"]
)
async def test_errors_after_a_break_are_not_retry_safe(dom_page, step):
    await _set_composer_content(dom_page, thread_composer_html(""))
    original = getattr(MessageSender, step)

    async def run_then_fail(self, *args, **kwargs):
        await original(self, *args, **kwargs)
        raise RuntimeError("evaluate round trip lost")

    with patch.object(MessageSender, step, run_then_fail):
        result = await _send(dom_page)
    text = await _assert_left_unconfirmed(dom_page, result)

    assert text.strip() != ""


async def test_single_line_changed_at_submit_ready_stays_retry_safe(dom_page):
    # No paragraph break went in, so nothing can have been sent.
    await _set_composer_content(
        dom_page,
        thread_composer_html(
            """document.querySelector('form button').disabled = true;
               editor.addEventListener('input', () => setTimeout(() => {
                 editor.textContent = 'Something else';
               }, 20), {once: true});"""
        ),
    )

    result = await _send(dom_page, "One line only")
    _, clicked = await _text_and_clicked(dom_page)

    assert result["status"] == "send_unavailable"
    assert result["retry_safe"] is True
    assert clicked is None
