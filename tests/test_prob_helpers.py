import unittest

from tests.prob_helpers import BehaviorProbeHelpers


class BehaviorProbeHelperTests(unittest.TestCase):
    def setUp(self):
        self.helpers = BehaviorProbeHelpers({})

    def test_check_description_describes_positive_and_negative_fragment_checks(self):
        self.assertEqual(
            self.helpers.check_description(
                {
                    "name": "turn_1.answer_not_contains",
                    "target": "answer",
                    "fragment": "<",
                }
            ),
            "answer does not contain: <",
        )
        self.assertEqual(
            self.helpers.check_description(
                {
                    "name": "turn_1.answer_contains",
                    "target": "answer",
                    "fragment": "hello",
                }
            ),
            "answer contains: hello",
        )


if __name__ == "__main__":
    unittest.main()
