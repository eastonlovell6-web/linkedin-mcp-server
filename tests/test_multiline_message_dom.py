# ruff: noqa: F811  (the imported dom_page fixture is "redefined" as a test argument)
import pytest

from linkedin_mcp_server.linkedin.message_sender import (
    _MESSAGE_COMPOSER_INSPECT_JS,
    _MESSAGE_COMPOSER_PINNED_JS,
)
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


async def test_garbled_insert_is_cleared_and_never_submitted(dom_page):
    # The editor flattens paragraph breaks, so the read-back no longer matches.
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

    assert written in {"invalid", "unsupported"}
    assert text.strip() == ""
    assert clicked is None


async def test_execcommand_failing_partway_clears_partial_text(dom_page):
    await _set_composer_content(dom_page, composer_html())
    sender, owner = await _owner(dom_page)
    await dom_page.evaluate(
        """() => {
          const real = document.execCommand.bind(document);
          let calls = 0;
          document.execCommand = (...args) => (++calls > 3 ? false : real(...args));
        }"""
    )
    written = await sender._write_verified_message(
        PITCH, target=_message_target(), owner=owner
    )
    text, clicked = await _text_and_clicked(dom_page)
    await sender._dispose_message_owner(owner)

    assert written == "unsupported"
    assert text.strip() == ""
    assert clicked is None


async def test_retry_after_failed_write_is_not_occupied(dom_page):
    await _set_composer_content(
        dom_page,
        composer_html()
        + """<script>
        document.documentElement.dataset.drop = 'yes';
        document.querySelector('[contenteditable=true]').addEventListener(
          'input', e => {
            if (document.documentElement.dataset.drop && e.inputType === 'insertParagraph') {
              e.target.textContent = e.target.textContent;
            }
          });
        </script>""",
    )
    sender, owner = await _owner(dom_page)
    first = await sender._write_verified_message(
        PITCH, target=_message_target(), owner=owner
    )
    await sender._dispose_message_owner(owner)
    await dom_page.evaluate("() => { delete document.documentElement.dataset.drop; }")
    sender, owner = await _owner(dom_page)  # a retry is a new tool call
    second = await sender._write_verified_message(
        PITCH, target=_message_target(), owner=owner
    )
    await sender._dispose_message_owner(owner)

    assert first in {"invalid", "unsupported"}
    assert second == "written"
