from __future__ import annotations

import unittest

from backend.app.demo_runner.validator import DemoActionValidationError, parse_action_events


class DemoActionValidatorTests(unittest.TestCase):
    def test_parse_valid_actions(self) -> None:
        timeline = {
            "action_events": [
                {"id": "a1", "at_ms": 0, "action": "goto", "target": "https://example.com"},
                {"id": "a2", "at_ms": 500, "action": "click", "target": "#btn"},
                {"id": "a3", "at_ms": 1200, "action": "fill", "target": "#name", "args": {"value": "Tanner"}},
                {"id": "a4", "at_ms": 1800, "action": "press", "target": "body", "args": {"key": "Enter"}},
                {"id": "a5", "at_ms": 2500, "action": "wait", "args": {"ms": 250}},
            ]
        }
        parsed = parse_action_events(timeline)
        self.assertEqual(5, len(parsed))
        self.assertEqual("goto", parsed[0].action)
        self.assertEqual("a5", parsed[-1].id)
        self.assertEqual(10000, parsed[0].timeout_ms)
        self.assertEqual(1, parsed[0].retries)

    def test_unsupported_action_fails(self) -> None:
        timeline = {"action_events": [{"id": "a1", "at_ms": 0, "action": "drag", "target": "#x"}]}
        with self.assertRaises(DemoActionValidationError):
            parse_action_events(timeline)

    def test_missing_required_args_fails(self) -> None:
        timeline = {"action_events": [{"id": "a1", "at_ms": 0, "action": "fill", "target": "#x", "args": {}}]}
        with self.assertRaises(DemoActionValidationError):
            parse_action_events(timeline)

    def test_invalid_timeout_has_stable_error_context(self) -> None:
        timeline = {
            "action_events": [
                {"id": "click_1", "at_ms": 0, "action": "click", "target": "#x", "timeout_ms": 50}
            ]
        }
        with self.assertRaises(DemoActionValidationError) as ctx:
            parse_action_events(timeline)
        msg = str(ctx.exception)
        self.assertIn("action timeout_ms", msg)
        self.assertIn("action_index=0", msg)
        self.assertIn("action_id=click_1", msg)

    def test_invalid_retries_has_stable_error_context(self) -> None:
        timeline = {
            "action_events": [
                {"id": "click_1", "at_ms": 0, "action": "click", "target": "#x", "retries": 999}
            ]
        }
        with self.assertRaises(DemoActionValidationError) as ctx:
            parse_action_events(timeline)
        msg = str(ctx.exception)
        self.assertIn("action retries", msg)
        self.assertIn("action_index=0", msg)
        self.assertIn("action_id=click_1", msg)

    def test_duplicate_action_id_fails(self) -> None:
        timeline = {
            "action_events": [
                {"id": "dup", "at_ms": 0, "action": "click", "target": "#x"},
                {"id": "dup", "at_ms": 10, "action": "wait", "args": {"ms": 0}},
            ]
        }
        with self.assertRaises(DemoActionValidationError) as ctx:
            parse_action_events(timeline)
        self.assertIn("duplicate action id", str(ctx.exception))

    def test_invalid_goto_target_fails(self) -> None:
        timeline = {"action_events": [{"id": "a1", "at_ms": 0, "action": "goto", "target": "example.com"}]}
        with self.assertRaises(DemoActionValidationError) as ctx:
            parse_action_events(timeline)
        self.assertIn("http:// or https://", str(ctx.exception))

    def test_wait_ms_upper_bound_fails(self) -> None:
        timeline = {
            "action_events": [
                {"id": "wait_1", "at_ms": 0, "action": "wait", "args": {"ms": 999999}}
            ]
        }
        with self.assertRaises(DemoActionValidationError) as ctx:
            parse_action_events(timeline)
        self.assertIn("wait action args.ms", str(ctx.exception))

    def test_equal_timestamp_order_is_source_deterministic(self) -> None:
        timeline = {
            "action_events": [
                {"id": "z_action", "at_ms": 100, "action": "wait", "args": {"ms": 0}},
                {"id": "a_action", "at_ms": 100, "action": "wait", "args": {"ms": 0}},
            ]
        }
        parsed = parse_action_events(timeline)
        self.assertEqual(["z_action", "a_action"], [item.id for item in parsed])


if __name__ == "__main__":
    unittest.main()
