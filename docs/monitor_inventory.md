# Monitor inventory

Every RTL run reports each monitor's evaluation count and failures in `runner_summary.json`. Any
monitor failure makes the run HARNESS_INVALID. Each monitor's detection path was shown active by an
injected fault in Gate 0A.

| ID | Location | Property | Injection used in Gate 0A |
|---|---|---|---|
| SV0_GNT_IMPLIES_REQ | wrapper | `gnt_o[i]` only while `req_i[i]` | master-0 grant view forced high |
| SV1_BANK_SINGLE_ACCEPT | wrapper | at most one accepted initiator per bank per cycle | master-1 bank view copied from master 0 |
| SV2_ACCEPT_CONSERVATION | wrapper | initiator acceptances = bank acceptances | bank-0 request view masked |
| SV3_PAYLOAD_ROUTING | wrapper | each bank acceptance carries an accepted initiator's row/wen/be | `add_o` view LSB flipped |
| SV4_RESP_CORRESPONDENCE | wrapper | `vld_o[i]` at t+1 iff a read of i was accepted at t | master-0 `vld` view inverted |
| SV5_LIC_WORK_CONSERVING | wrapper (LIC only) | a requested, granting bank always accepts someone | master-0 grant view masked |
| SV6_NO_SPURIOUS_BANK_REQ | wrapper | `req_o[b]` only while some initiator requests bank b | master-0 request view masked |
| C0_RESET_QUIET | driver | no grant/response during reset | (covered by reset check) |
| C1_REQUEST_STABILITY | driver | an unaccepted request stays stable | driver changes a held address |
| C2_RESPONSE_TIMING | driver | response exactly one cycle after acceptance; no unmatched response | (tampered-trace check) |
| C3_RESPONSE_DATA | driver | read data = f(q) for the operation's word | scoreboard expects f(q+1) |
| C4_DRAIN_QUIET | driver | no activity during 3 post-completion cycles | — |
| C5_COMPLETION | driver | each operation accepted once and completed once | (tampered-trace check) |
| C6_TIMEOUT | driver | all responses within the active-cycle limit | stalled bank + 32-cycle limit |

Injections corrupt only the monitor's **view** of a signal, never the DUT. For the butterfly
configurations, SV5 is not evaluated and the inventory has 13 monitors.

Formal properties P1–P9 (see `docs/results.md`) restate SV0–SV6 plus reset and response-data routing.
They are proved under the listed assumptions for LIC 2×2.
