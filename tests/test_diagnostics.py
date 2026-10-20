"""VCD parsing for diagnostic traces: pre-rise sampling and identifier handling."""

import unittest

from rift.diagnostics import parse_vcd
from rift.pipeline import contention

VCD = """$timescale 1ps $end
$scope module TOP $end
$var wire 1 ! clk_i $end
$scope module i_bfly_net $end
$var wire 4 b router_req_in [3:0] $end
$var wire 4 bb router_gnt_out [3:0] $end
$upscope $end
$scope module lfsr_i $end
$var wire 8 # out_q [7:0] $end
$upscope $end
$upscope $end
$enddefinitions $end
#0
0!
b0000 b
b0 bb
b101 #
#5
1!
#10
0!
b0011 b
b1x bb
#15
1!
#20
0!
"""


class ParseVcdTest(unittest.TestCase):
    def test_snapshots_hold_state_just_before_each_rising_edge(self):
        sig, snaps = parse_vcd(VCD)
        self.assertEqual(set(sig), {"clk", "router_req_in", "router_gnt_out", "lfsr_out_q"})
        self.assertEqual([c for c, _ in snaps], [0, 1])
        self.assertEqual(snaps[0][1]["router_req_in"], 0)
        self.assertEqual(snaps[1][1]["router_req_in"], 0b0011)
        self.assertEqual(snaps[1][1]["router_gnt_out"], 0b10)  # x/z read as 0
        self.assertEqual(snaps[1][1]["lfsr_out_q"], 0b101)

    def test_identifiers_that_look_like_values(self):
        _, snaps = parse_vcd(VCD)
        self.assertNotEqual(snaps[1][1]["router_req_in"], snaps[1][1]["router_gnt_out"])


class ContentionTest(unittest.TestCase):
    def test_counts_cycles_with_two_or_more_requesters_once(self):
        view = {"mapping_check": {"cycles_checked": 10},
                "first_stage_outputs": [{"cycles": [{"c": 4, "requesters": [0, 1]}, {"c": 5, "requesters": [0]}]},
                                        {"cycles": [{"c": 4, "requesters": [2, 3]}, {"c": 6, "requesters": [2, 3]}]}]}
        self.assertEqual(contention(view), (2, 10))


if __name__ == "__main__":
    unittest.main()
