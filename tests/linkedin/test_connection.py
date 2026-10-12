"""Locale-independent connection-state classification tests."""

from linkedin_mcp_server.linkedin.connection import (
    ActionSignals,
    detect_connection_state,
)


class TestDetectConnectionState:
    @staticmethod
    def _signals(
        invite: bool = False,
        compose_in_root: bool = False,
        edit: bool = False,
        labeled_action: bool = False,
        labeled_anchor: bool = False,
        incoming_row: bool = False,
        connect_button: bool = False,
        connect_state_anchor: bool = False,
    ) -> ActionSignals:
        return ActionSignals(
            has_invite_anchor=invite,
            has_compose_anchor_in_action_root=compose_in_root,
            has_edit_intro_anchor=edit,
            has_labeled_action_button=labeled_action,
            has_labeled_action_anchor=labeled_anchor,
            has_incoming_action_row=incoming_row,
            has_connect_button=connect_button,
            has_connect_state_anchor=connect_state_anchor,
        )

    def test_self_profile(self):
        assert detect_connection_state(self._signals(edit=True)) == "self_profile"

    def test_connectable(self):
        assert detect_connection_state(self._signals(invite=True)) == "connectable"

    def test_already_connected(self):
        assert (
            detect_connection_state(
                self._signals(compose_in_root=True, labeled_action=False)
            )
            == "already_connected"
        )

    def test_follow_only(self):
        assert (
            detect_connection_state(
                self._signals(compose_in_root=True, labeled_action=True)
            )
            == "follow_only"
        )

    def test_pending_via_labeled_anchor(self):
        assert (
            detect_connection_state(
                self._signals(compose_in_root=True, labeled_anchor=True)
            )
            == "pending"
        )

    def test_pending_takes_priority_over_already_connected(self):
        assert (
            detect_connection_state(
                self._signals(compose_in_root=True, labeled_anchor=True)
            )
            == "pending"
        )

    def test_incoming_request_via_structural_row(self):
        assert (
            detect_connection_state(self._signals(incoming_row=True))
            == "incoming_request"
        )

    def test_incoming_structural_beats_pending_misclassification(self):
        assert (
            detect_connection_state(
                self._signals(
                    incoming_row=True,
                    compose_in_root=True,
                    labeled_action=True,
                    labeled_anchor=True,
                )
            )
            == "incoming_request"
        )

    def test_connectable_takes_priority_over_incoming_row(self):
        assert (
            detect_connection_state(self._signals(invite=True, incoming_row=True))
            == "connectable"
        )

    def test_self_profile_takes_priority_over_incoming_row(self):
        assert (
            detect_connection_state(self._signals(edit=True, incoming_row=True))
            == "self_profile"
        )

    def test_unavailable_when_no_signals(self):
        assert detect_connection_state(self._signals()) == "unavailable"

    def test_unavailable_when_compose_missing(self):
        assert (
            detect_connection_state(self._signals(labeled_action=True)) == "unavailable"
        )

    # 2026-10 top-card layout: Connect is an <a> linking to the profile with a
    # componentkey "ConnectButtonstate:invitation:urn:li:member:<id>_connect"
    # and an aria-label. Without the connect-button signal it reads as Pending.
    def test_connect_button_is_connectable_even_with_a_labeled_anchor(self):
        assert (
            detect_connection_state(
                self._signals(compose_in_root=True, labeled_anchor=True, connect_button=True)
            )
            == "connectable"
        )

    def test_connect_state_anchor_that_is_not_connect_is_pending(self):
        assert (
            detect_connection_state(
                self._signals(compose_in_root=True, labeled_action=True, connect_state_anchor=True)
            )
            == "pending"
        )

    def test_pending_state_anchor_outranks_every_connect_signal(self):
        # Reading an outstanding invitation as connectable would send again.
        assert (
            detect_connection_state(
                self._signals(compose_in_root=True, invite=True, connect_button=True, connect_state_anchor=True)
            )
            == "pending"
        )

    def test_connect_button_takes_priority_over_incoming_row(self):
        assert (
            detect_connection_state(self._signals(connect_button=True, incoming_row=True))
            == "connectable"
        )

    def test_self_profile_beats_connect_button(self):
        assert (
            detect_connection_state(self._signals(edit=True, connect_button=True))
            == "self_profile"
        )

