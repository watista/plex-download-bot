#!/usr/bin/python3

import unittest

from src.faults import Fault, FaultKind


class FaultTest(unittest.TestCase):
    """ A Fout in the code: an exception with its kind, made by the constructor of that kind """

    def test_each_constructor_makes_its_kind(self):
        bug = Fault.bug(what="Radarr refused the movie request", service="radarr",
                        reason="This movie has already been added", http_status=400)
        disruption = Fault.disruption(service="telegram", what="Telegram is not responding", reason="Timed out")
        setup = Fault.setup(service="sonarr", what="Carrie has no path in Sonarr", check="series_path", item=1418)

        self.assertEqual([fault.kind for fault in (bug, disruption, setup)],
                         [FaultKind.BUG, FaultKind.DISRUPTION, FaultKind.SETUP])
        self.assertEqual((setup.check, setup.item), ("series_path", 1418))
        self.assertEqual((bug.check, bug.item), (None, None))
        self.assertEqual(str(bug), "Radarr refused the movie request: This movie has already been added")

    def test_the_kind_is_written_as_in_the_field_fault(self):
        self.assertEqual([str(kind) for kind in FaultKind], ["bug", "disruption", "setup"])

    def test_a_setup_fault_needs_a_check(self):
        with self.assertRaises(TypeError):
            Fault.setup(service="sonarr", what="Carrie has no path in Sonarr", item=1418)

    def test_only_a_setup_fault_has_a_check_and_an_item(self):
        with self.assertRaises(TypeError):
            Fault.bug(what="Radarr refused the movie request", check="tmdb_lookup")
        with self.assertRaises(TypeError):
            Fault.disruption(service="radarr", what="Radarr is not responding", item=1418)

    def test_a_disruption_is_always_of_a_service(self):
        with self.assertRaises(TypeError):
            Fault.disruption(what="Radarr is not responding")


if __name__ == "__main__":
    unittest.main()
