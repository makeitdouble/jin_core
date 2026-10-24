import unittest
from types import SimpleNamespace
from utils.assets_utils import parse_telegram_send_payload
from utils.python_skill_asset_utils import _parse_payload
from runtime.stream import project_telegram_asset_action_marker


class TelegramQuoteRepairTests(unittest.TestCase):
    def test_unescaped_quotes_and_newlines(self):
        raw = '{"action":"telegram_send","text":"Он сказал "бро в чатике".\\nПока."}'
        expected = 'Он сказал "бро в чатике".\nПока.'
        self.assertEqual(parse_telegram_send_payload(raw)['text'], expected)
        self.assertEqual(_parse_payload(raw)['text'], expected)
        marker = project_telegram_asset_action_marker('', SimpleNamespace(name='ASSET_ACTION', payload=raw))
        self.assertIn(expected, marker)

    def test_valid_json_and_escaped_quotes(self):
        raw = '{"action":"telegram_send","text":"Текст \\"кавычки\\""}'
        self.assertEqual(_parse_payload(raw)['text'], 'Текст "кавычки"')

    def test_other_actions_not_repaired(self):
        raw = '{"action":"delete_file","text":"Some "bad" text"}'
        self.assertEqual(parse_telegram_send_payload(raw), {})
        self.assertIsNone(project_telegram_asset_action_marker('', SimpleNamespace(name='ASSET_ACTION', payload=raw)))

    def test_malformed_telegram_does_not_guess_arbitrary_fields(self):
        raw = '{"action":"telegram_send","text":"hi "quoted"","chat_id":"abc"}'
        self.assertEqual(parse_telegram_send_payload(raw), {})


if __name__ == '__main__':
    unittest.main()
