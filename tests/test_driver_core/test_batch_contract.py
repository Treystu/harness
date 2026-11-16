"""#300 — the batch rule ``check_batch``'s docstring promises, over the whole vocabulary.

The 2026-11-04 cure (``832a059``) made the refusal real; its tests exercise
``delete_file`` only. ``submit_irreversible`` is the vocabulary's second
irreversible action, so an enforcement that narrowed to one sample could regress
behind ``delete_file`` with every existing test still green. These cases take the
docstring as the contract and hold it over every declared action, in both orders.

There is no production caller, on purpose and on record: ``Driver.step`` takes one
decision per step, so ``check_batch`` guards a batch/plan path that does not exist
yet (#270-#273). A guard nobody calls still has to be the guard it claims to be —
which is the whole finding in #300.
"""
import unittest

from driver_core.actions import (
    DEFAULT_VOCABULARY,
    MAX_IRREVERSIBLE_PER_STEP,
    VocabularyError,
    check_batch,
)


class BatchContractTest(unittest.TestCase):
    """The docstring's rule, checked exhaustively rather than by example."""

    def setUp(self):
        self.irreversible = [a.name for a in DEFAULT_VOCABULARY.actions()
                             if a.requires_human_confirmation]
        self.reversible = [a.name for a in DEFAULT_VOCABULARY.actions()
                           if not a.requires_human_confirmation]

    def test_the_vocabulary_still_declares_two_irreversible_actions(self):
        # Without this, a rename later could empty the loops below and leave a
        # green test that checks nothing.
        self.assertEqual(self.irreversible,
                         ["delete_file", "submit_irreversible"])
        self.assertGreaterEqual(len(self.reversible), 2)

    def test_every_irreversible_action_is_refused_beside_every_other_action(self):
        for risk in self.irreversible:
            others = self.reversible + [n for n in self.irreversible if n != risk]
            for other in others:
                for batch in ([risk, other], [other, risk]):
                    with self.subTest(batch=batch):
                        with self.assertRaises(VocabularyError):
                            check_batch(batch, DEFAULT_VOCABULARY)

    def test_every_lone_irreversible_action_is_accepted(self):
        for risk in self.irreversible:
            with self.subTest(irreversible=risk):
                self.assertEqual(check_batch([risk], DEFAULT_VOCABULARY), [risk])

    def test_every_all_reversible_batch_is_accepted_whole(self):
        self.assertEqual(check_batch(self.reversible, DEFAULT_VOCABULARY),
                         self.reversible)
        self.assertEqual(check_batch(list(reversed(self.reversible)),
                                     DEFAULT_VOCABULARY),
                         list(reversed(self.reversible)))
        for name in self.reversible:
            with self.subTest(action=name):
                self.assertEqual(check_batch([name], DEFAULT_VOCABULARY), [name])

    def test_the_limit_is_what_the_docstring_describes(self):
        # "A lone irreversible action is allowed" is only true while the limit
        # is 1; the mixed-batch refusal above leans on the same constant.
        self.assertEqual(MAX_IRREVERSIBLE_PER_STEP, 1)

    def test_the_docstring_still_states_the_rule_the_code_enforces(self):
        doc = check_batch.__doc__ or ""
        self.assertIn("mixes an irreversible action with anything else", doc)
        self.assertIn("A lone irreversible action is", doc)


if __name__ == "__main__":
    unittest.main()
