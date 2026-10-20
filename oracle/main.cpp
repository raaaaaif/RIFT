// RIFT Phase 0 Verilator driver, memory oracle, scoreboard and event exporter.
//
// Sampling convention (docs/interface_contract.md):
//   For every cycle c the driver (1) drives inputs with clk low and evaluates,
//   (2) samples A_c = req_i & gnt_o, bank acceptances, V_c = vld_o/rdata_o and
//   monitor outputs immediately before rising edge c, (3) applies rising edge c.
//   Banks capture the accepted row at edge c and expose registered read data for
//   the V_{c+1} sample. The memory image is distributed by bank = q mod NumOut,
//   row = q / NumOut; the scoreboard derives expected data directly from the
//   operation's logical byte address and never from the bank arrays.

#include "Vrift_tcdm_top.h"
#include "verilated.h"
#ifdef RIFT_TRACE
#include "verilated_fst_c.h"
#endif

#include <sys/resource.h>

#include <chrono>
#include <cinttypes>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

#ifndef RIFT_NUM_IN
#error "RIFT_NUM_IN must be defined"
#endif
#ifndef RIFT_NUM_OUT
#error "RIFT_NUM_OUT must be defined"
#endif
#ifndef RIFT_ADDR_MEM_WIDTH
#error "RIFT_ADDR_MEM_WIDTH must be defined"
#endif
#ifndef RIFT_TOPOLOGY
#error "RIFT_TOPOLOGY must be defined"
#endif

static constexpr int kNumIn = RIFT_NUM_IN;
static constexpr int kNumOut = RIFT_NUM_OUT;
static constexpr int kAddrMemWidth = RIFT_ADDR_MEM_WIDTH;
static constexpr int kTopology = RIFT_TOPOLOGY;
static constexpr uint32_t kCapacityWords = 4096;
static constexpr uint32_t kBankDepth = 1u << kAddrMemWidth;
static_assert(kBankDepth * kNumOut == kCapacityWords, "configuration must hold exactly 4096 logical words");

static constexpr int kResetCycles = 4;
static constexpr int kDrainCycles = 3;

static uint32_t oracle_word(uint32_t q) { return (uint32_t)((q * 0x9E3779B1u) ^ 0xA5A55A5Au); }

enum class Release { AfterAccept, AfterResponse };

struct Op {
  int master;
  int index;
  uint32_t byte_address;
  Release release;
  uint32_t gap;
};

struct Workload {
  std::string digest;
  int masters = 0;
  std::vector<std::vector<Op>> per_master;
  size_t total_ops = 0;
};

struct Stall {
  int bank;
  uint64_t start;  // absolute cycle
  uint64_t length;
};

struct Options {
  std::string workload_path;
  std::string events_path;
  std::string summary_path;
  std::string run_id = "unnamed";
  std::string batch_path;
  std::string fst_path;
  std::string inject;  // C++ fault injection
  uint32_t sv_inject = 0;
  uint64_t timeout = 4096;
  std::vector<Stall> stalls;
};

static bool parse_workload(const std::string& path, Workload& wl, std::string& err) {
  std::ifstream in(path);
  if (!in) {
    err = "cannot open workload file";
    return false;
  }
  std::string line;
  if (!std::getline(in, line) || line != "RIFT_COMPILED_WORKLOAD 1") {
    err = "bad workload header";
    return false;
  }
  wl.per_master.assign(kNumIn, {});
  bool ended = false;
  while (std::getline(in, line)) {
    if (line.empty()) continue;
    std::istringstream ss(line);
    std::string tag;
    ss >> tag;
    if (tag == "digest") {
      ss >> wl.digest;
    } else if (tag == "masters") {
      ss >> wl.masters;
      if (wl.masters != kNumIn) {
        err = "workload initiator count does not match configuration";
        return false;
      }
    } else if (tag == "op") {
      Op op{};
      std::string rel;
      ss >> op.master >> op.index >> op.byte_address >> rel >> op.gap;
      if (ss.fail()) {
        err = "malformed op line";
        return false;
      }
      if (op.master < 0 || op.master >= kNumIn) {
        err = "op initiator out of range";
        return false;
      }
      if (op.byte_address % 4 != 0 || op.byte_address >= kCapacityWords * 4) {
        err = "op address unaligned or outside logical capacity";
        return false;
      }
      if (rel == "A") op.release = Release::AfterAccept;
      else if (rel == "R") op.release = Release::AfterResponse;
      else {
        err = "unknown release kind";
        return false;
      }
      if (op.gap > 4096) {
        err = "release gap exceeds bound";
        return false;
      }
      if ((size_t)op.index != wl.per_master[op.master].size()) {
        err = "operation indices must be dense and ordered per initiator";
        return false;
      }
      wl.per_master[op.master].push_back(op);
      wl.total_ops++;
    } else if (tag == "end") {
      ended = true;
      break;
    } else {
      err = "unknown workload line tag";
      return false;
    }
  }
  if (!ended) {
    err = "workload missing end marker";
    return false;
  }
  if (wl.total_ops == 0) {
    err = "workload has no operations";
    return false;
  }
  return true;
}

// ---------------------------------------------------------------------------
// Monitor register
// ---------------------------------------------------------------------------
struct Monitor {
  const char* id;
  const char* source;
  const char* description;
  uint64_t evaluations = 0;
  uint64_t failures = 0;
  int64_t first_failure_cycle = -1;
};

static const char* kSvMonitorIds[7] = {
    "SV0_GNT_IMPLIES_REQ",     "SV1_BANK_SINGLE_ACCEPT", "SV2_ACCEPT_CONSERVATION", "SV3_PAYLOAD_ROUTING",
    "SV4_RESP_CORRESPONDENCE", "SV5_LIC_WORK_CONSERVING", "SV6_NO_SPURIOUS_BANK_REQ"};
static const char* kSvMonitorDesc[7] = {
    "gnt_o[i] asserted only while req_i[i] is asserted",
    "at most one accepted initiator per bank per cycle",
    "number of initiator acceptances equals number of bank acceptances",
    "each bank acceptance carries the row/wen/be of exactly one accepted initiator",
    "vld_o[i] at t+1 iff initiator i had a read accepted at t (RespLat=1)",
    "LIC only: a requested bank with gnt_i=1 always accepts some initiator",
    "req_o[b] only while some initiator requests bank b"};

enum CppMon {
  C_RESET_QUIET = 0,
  C_REQUEST_STABILITY,
  C_RESPONSE_TIMING,
  C_RESPONSE_DATA,
  C_DRAIN_QUIET,
  C_COMPLETION,
  C_TIMEOUT,
  C_COUNT
};
static const char* kCppMonitorIds[C_COUNT] = {"C0_RESET_QUIET",    "C1_REQUEST_STABILITY", "C2_RESPONSE_TIMING",
                                              "C3_RESPONSE_DATA",  "C4_DRAIN_QUIET",       "C5_COMPLETION",
                                              "C6_TIMEOUT"};
static const char* kCppMonitorDesc[C_COUNT] = {
    "no gnt_o or vld_o while reset is asserted",
    "an unaccepted request keeps req/add/wen/be/wdata stable in the next cycle",
    "each response arrives exactly one cycle after its acceptance; no unmatched response",
    "read data equals f(q) for the operation's logical word q (independent oracle)",
    "no grants or responses during post-completion drain cycles",
    "every operation accepted exactly once and completed exactly once",
    "all responses arrive within the declared active-cycle limit"};

// ---------------------------------------------------------------------------
// Event writer
// ---------------------------------------------------------------------------
struct EventWriter {
  FILE* f = nullptr;
  std::string run_id;
  uint64_t count = 0;
  void open(const std::string& path, const std::string& rid) {
    run_id = rid;
    if (path.empty()) return;
    f = (path == "-") ? stdout : std::fopen(path.c_str(), "w");
  }
  void close() {
    if (f && f != stdout) std::fclose(f);
    f = nullptr;
  }
  void base(uint64_t cycle, const char* kind) {
    std::fprintf(f, "{\"schema_version\":1,\"run_id\":\"%s\",\"cycle\":%" PRIu64 ",\"sample_phase\":\"pre_rise\",",
                 run_id.c_str(), cycle);
    std::fprintf(f, "\"event_kind\":\"%s\"", kind);
  }
  void reset(uint64_t cycle) {
    count++;
    if (!f) return;
    base(cycle, "reset");
    std::fprintf(f, ",\"master\":null,\"operation_index\":null,\"byte_address\":null}\n");
  }
  void op_event(uint64_t cycle, const char* kind, const Op& op, int bank, uint32_t row, bool with_data,
                uint32_t data) {
    count++;
    if (!f) return;
    base(cycle, kind);
    std::fprintf(f, ",\"master\":%d,\"operation_index\":%d,\"byte_address\":%u,\"bank\":%d,\"row\":%u", op.master,
                 op.index, op.byte_address, bank, row);
    if (with_data) std::fprintf(f, ",\"read_data\":%u", data);
    std::fprintf(f, "}\n");
  }
  void monitor_failure(uint64_t cycle, const char* monitor_id, int master, const char* detail) {
    count++;
    if (!f) return;
    base(cycle, "monitor_failure");
    if (master >= 0) std::fprintf(f, ",\"master\":%d", master);
    else std::fprintf(f, ",\"master\":null");
    std::fprintf(f, ",\"operation_index\":null,\"byte_address\":null,\"monitor_id\":\"%s\",\"detail\":\"%s\"}\n",
                 monitor_id, detail);
  }
};

// ---------------------------------------------------------------------------
// One complete run from reset
// ---------------------------------------------------------------------------
struct RunResult {
  std::string exit_status = "COMPLETED";
  std::string functional_verdict = "PASS";
  uint64_t accepted = 0;
  uint64_t completed = 0;
  uint64_t first_release_cycle = 0;
  int64_t first_offer_cycle = -1;
  int64_t last_response_cycle = -1;
  int64_t makespan = -1;
  uint64_t active_cycles = 0;
  uint64_t total_cycles = 0;
  uint64_t bank_accepts = 0;
  uint64_t events = 0;
  double elapsed_s = 0;
  Monitor sv[7];
  Monitor cpp[C_COUNT];
};

enum class MState { Waiting, Offering, Outstanding, Done };

struct MasterState {
  size_t next = 0;           // index of the op being offered or waiting
  MState state = MState::Waiting;
  int64_t earliest = 0;      // earliest offer cycle for ops[next]
  bool release_known = true; // false while waiting for a predecessor's response
  int64_t offer_cycle = -1;
  // outstanding read (accepted, awaiting response)
  bool outstanding = false;
  size_t outstanding_idx = 0;
  int64_t outstanding_accept_cycle = -1;
  // last driven payload (for stability checks)
  bool prev_req = false;
  bool prev_gnt = false;
  uint32_t prev_add = 0;
};

static void run_one(const Options& opt, const Workload& wl, RunResult& res, EventWriter& ev) {
  auto t0 = std::chrono::steady_clock::now();
  for (int k = 0; k < 7; k++) res.sv[k] = Monitor{kSvMonitorIds[k], "sv_wrapper", kSvMonitorDesc[k]};
  for (int k = 0; k < C_COUNT; k++) res.cpp[k] = Monitor{kCppMonitorIds[k], "cpp_driver", kCppMonitorDesc[k]};

  auto ctx = std::make_unique<VerilatedContext>();
  ctx->randReset(0);
  auto top = std::make_unique<Vrift_tcdm_top>(ctx.get());
#ifdef RIFT_TRACE
  std::unique_ptr<VerilatedFstC> tfp;
  if (!opt.fst_path.empty()) {
    ctx->traceEverOn(true);
    tfp = std::make_unique<VerilatedFstC>();
    top->trace(tfp.get(), 99);
    tfp->open(opt.fst_path.c_str());
  }
#endif
  uint64_t trace_time = 0;
  auto eval_and_dump = [&]() {
    top->eval();
#ifdef RIFT_TRACE
    if (tfp) tfp->dump(trace_time);
#endif
    trace_time += 5;
  };

  // Independent memory image distributed into banks.
  std::vector<std::vector<uint32_t>> mem(kNumOut, std::vector<uint32_t>(kBankDepth, 0));
  for (uint32_t q = 0; q < kCapacityWords; q++) mem[q % kNumOut][q / kNumOut] = oracle_word(q);
  std::vector<uint32_t> bank_rdata(kNumOut, 0);
  std::vector<int> bank_capture_row(kNumOut, -1);

  auto bank_stalled = [&](int b, uint64_t c) {
    for (const auto& s : opt.stalls)
      if (s.bank == b && c >= s.start && c < s.start + s.length) return true;
    return false;
  };

  auto fail = [&](Monitor& m, uint64_t cycle, int master, const char* detail) {
    m.failures++;
    if (m.first_failure_cycle < 0) m.first_failure_cycle = (int64_t)cycle;
    ev.monitor_failure(cycle, m.id, master, detail);
  };

  // Idle inputs
  top->clk_i = 0;
  top->rst_ni = 0;
  top->mon_inject_i = (uint8_t)opt.sv_inject;
  for (int i = 0; i < kNumIn; i++) {
    top->req_i[i] = 0;
    top->add_i[i] = 0;
    top->wen_i[i] = 0;
    top->wdata_i[i] = 0;
    top->be_i[i] = 0;
  }
  for (int b = 0; b < kNumOut; b++) {
    top->gnt_i[b] = 1;
    top->rdata_i[b] = 0;
  }
  eval_and_dump();

  uint64_t cycle = 0;
  // ---- reset: four request-free rising edges -------------------------------
  for (int r = 0; r < kResetCycles; r++, cycle++) {
    top->clk_i = 0;
    eval_and_dump();
    ev.reset(cycle);
    res.cpp[C_RESET_QUIET].evaluations++;
    for (int i = 0; i < kNumIn; i++) {
      if (top->gnt_o[i] || top->vld_o[i]) fail(res.cpp[C_RESET_QUIET], cycle, i, "grant or response during reset");
    }
    top->clk_i = 1;
    eval_and_dump();
  }
  // Reset policy: no operation is offered before reset completes, so there are
  // no outstanding responses to cancel; this is asserted by C0.
  top->clk_i = 0;
  top->rst_ni = 1;
  eval_and_dump();

  const uint64_t first_release = cycle;
  res.first_release_cycle = first_release;
  std::vector<MasterState> ms(kNumIn);
  size_t done_masters = 0;
  for (int i = 0; i < kNumIn; i++) {
    if (wl.per_master[i].empty()) {
      ms[i].state = MState::Done;
      done_masters++;
    } else {
      ms[i].earliest = (int64_t)first_release + wl.per_master[i][0].gap;
    }
  }

  std::vector<uint8_t> accepted_flag, completed_flag;
  std::vector<std::vector<uint8_t>> acc_count(kNumIn), cmp_count(kNumIn);
  for (int i = 0; i < kNumIn; i++) {
    acc_count[i].assign(wl.per_master[i].size(), 0);
    cmp_count[i].assign(wl.per_master[i].size(), 0);
  }

  bool unstable_injected = false;
  bool timed_out = false;
  int drain_left = -1;

  while (true) {
    // ------------------------------------------------------------------
    // Drive phase (clock low)
    // ------------------------------------------------------------------
    top->clk_i = 0;
    for (int b = 0; b < kNumOut; b++) {
      top->gnt_i[b] = bank_stalled(b, cycle) ? 0 : 1;
      top->rdata_i[b] = bank_rdata[b];
    }
    for (int i = 0; i < kNumIn; i++) {
      MasterState& m = ms[i];
      bool present = false;
      if (m.state == MState::Waiting && m.release_known && (int64_t)cycle >= m.earliest) {
        m.state = MState::Offering;
        m.offer_cycle = (int64_t)cycle;
        const Op& op = wl.per_master[i][m.next];
        uint32_t q = op.byte_address >> 2;
        ev.op_event(cycle, "offer", op, (int)(q % kNumOut), q / kNumOut, false, 0);
        if (res.first_offer_cycle < 0) res.first_offer_cycle = (int64_t)cycle;
      }
      if (m.state == MState::Offering) present = true;
      if (present) {
        const Op& op = wl.per_master[i][m.next];
        uint32_t addr = op.byte_address;
        // Fault injection: violate request stability while a request is held.
        if (opt.inject == "unstable_request" && m.prev_req && !m.prev_gnt && !unstable_injected) {
          addr = (addr + 4) % (kCapacityWords * 4);
          unstable_injected = true;
        }
        top->req_i[i] = 1;
        top->add_i[i] = addr;
        top->wen_i[i] = 0;
        top->be_i[i] = 0xF;
        top->wdata_i[i] = 0;
      } else {
        top->req_i[i] = 0;
        top->add_i[i] = 0;
        top->wen_i[i] = 0;
        top->be_i[i] = 0;
        top->wdata_i[i] = 0;
      }
    }
    eval_and_dump();

    // ------------------------------------------------------------------
    // Sample phase: immediately before rising edge `cycle`
    // ------------------------------------------------------------------
    uint8_t monf = top->mon_fail_o;
    for (int k = 0; k < 7; k++) {
      if (k == 5 && kTopology != 0) continue;  // LIC-only monitor is not evaluated for BFLY
      res.sv[k].evaluations++;
      if (monf & (1u << k)) fail(res.sv[k], cycle, -1, "wrapper monitor asserted");
    }

    // C1: request stability on the actually driven inputs
    res.cpp[C_REQUEST_STABILITY].evaluations++;
    for (int i = 0; i < kNumIn; i++) {
      MasterState& m = ms[i];
      bool req = top->req_i[i];
      if (m.prev_req && !m.prev_gnt) {
        if (!req || top->add_i[i] != m.prev_add || top->wen_i[i] != 0 || top->be_i[i] != 0xF)
          fail(res.cpp[C_REQUEST_STABILITY], cycle, i, "held request changed before acceptance");
      }
    }

    // Responses V_cycle
    res.cpp[C_RESPONSE_TIMING].evaluations++;
    std::vector<int> responded(kNumIn, 0);
    for (int i = 0; i < kNumIn; i++) {
      MasterState& m = ms[i];
      bool vld = top->vld_o[i];
      if (vld) {
        if (!m.outstanding || m.outstanding_accept_cycle + 1 != (int64_t)cycle) {
          fail(res.cpp[C_RESPONSE_TIMING], cycle, i, "response without a read accepted in the previous cycle");
        } else {
          const Op& op = wl.per_master[i][m.outstanding_idx];
          uint32_t q = op.byte_address >> 2;
          uint32_t data = top->rdata_o[i];
          uint32_t expected = oracle_word(opt.inject == "oracle_offset" ? (q + 1) % kCapacityWords : q);
          res.cpp[C_RESPONSE_DATA].evaluations++;
          if (data != expected) fail(res.cpp[C_RESPONSE_DATA], cycle, i, "read data differs from oracle f(q)");
          ev.op_event(cycle, "complete", op, (int)(q % kNumOut), q / kNumOut, true, data);
          cmp_count[i][m.outstanding_idx]++;
          res.completed++;
          res.last_response_cycle = (int64_t)cycle;
          m.outstanding = false;
          responded[i] = 1;
        }
      } else if (m.outstanding && m.outstanding_accept_cycle + 1 == (int64_t)cycle) {
        fail(res.cpp[C_RESPONSE_TIMING], cycle, i, "missing response one cycle after acceptance");
        m.outstanding = false;  // mark lost so the run can terminate
      }
    }

    if (drain_left >= 0) {
      res.cpp[C_DRAIN_QUIET].evaluations++;
      for (int i = 0; i < kNumIn; i++)
        if (top->gnt_o[i] || top->vld_o[i]) fail(res.cpp[C_DRAIN_QUIET], cycle, i, "activity after completion");
    }

    // Acceptances A_cycle
    std::vector<int> accepted_now(kNumIn, 0);
    for (int i = 0; i < kNumIn; i++) {
      MasterState& m = ms[i];
      bool req = top->req_i[i], gnt = top->gnt_o[i];
      if (req && gnt && m.state == MState::Offering) {
        const Op& op = wl.per_master[i][m.next];
        uint32_t q = op.byte_address >> 2;
        ev.op_event(cycle, "accept", op, (int)(q % kNumOut), q / kNumOut, false, 0);
        acc_count[i][m.next]++;
        res.accepted++;
        accepted_now[i] = 1;
      }
      m.prev_req = req;
      m.prev_gnt = gnt;
      m.prev_add = top->add_i[i];
    }
    for (int b = 0; b < kNumOut; b++) {
      bank_capture_row[b] = -1;
      if (top->req_o[b] && top->gnt_i[b]) {
        bank_capture_row[b] = (int)top->add_o[b];
        res.bank_accepts++;
      }
    }

    // ------------------------------------------------------------------
    // Rising edge `cycle`
    // ------------------------------------------------------------------
    top->clk_i = 1;
    eval_and_dump();
    for (int b = 0; b < kNumOut; b++)
      if (bank_capture_row[b] >= 0) bank_rdata[b] = mem[b][(uint32_t)bank_capture_row[b] % kBankDepth];

    // Advance initiator state after the edge.
    for (int i = 0; i < kNumIn; i++) {
      MasterState& m = ms[i];
      const auto& ops = wl.per_master[i];
      if (responded[i] && m.state == MState::Waiting && !m.release_known) {
        m.release_known = true;
        m.earliest = (int64_t)cycle + 1 + ops[m.next].gap;
      }
      if (accepted_now[i]) {
        m.outstanding = true;
        m.outstanding_idx = m.next;
        m.outstanding_accept_cycle = (int64_t)cycle;
        m.next++;
        if (m.next >= ops.size()) {
          m.state = MState::Done;
          done_masters++;
        } else {
          m.state = MState::Waiting;
          const Op& nxt = ops[m.next];
          if (nxt.release == Release::AfterAccept) {
            m.release_known = true;
            m.earliest = (int64_t)cycle + 1 + nxt.gap;
          } else {
            m.release_known = false;
          }
        }
      }
    }

    uint64_t active = cycle - first_release + 1;
    res.active_cycles = active;
    cycle++;

    bool all_outstanding_clear = true;
    for (int i = 0; i < kNumIn; i++)
      if (ms[i].outstanding) all_outstanding_clear = false;

    if (drain_left > 0) {
      drain_left--;
      if (drain_left == 0) break;
      continue;
    }
    if (done_masters == (size_t)kNumIn && all_outstanding_clear) {
      drain_left = kDrainCycles;
      continue;
    }
    if (active >= opt.timeout) {
      timed_out = true;
      break;
    }
  }
  res.total_cycles = cycle;

  // Completion accounting
  res.cpp[C_COMPLETION].evaluations++;
  for (int i = 0; i < kNumIn; i++) {
    for (size_t k = 0; k < wl.per_master[i].size(); k++) {
      if (acc_count[i][k] != 1 || cmp_count[i][k] != 1) {
        fail(res.cpp[C_COMPLETION], cycle, i, "operation not accepted and completed exactly once");
        break;
      }
    }
  }
  res.cpp[C_TIMEOUT].evaluations++;
  if (timed_out) {
    fail(res.cpp[C_TIMEOUT], cycle, -1, "active-cycle limit reached before drain");
    res.exit_status = "TIMEOUT";
  }

  bool data_fail = res.cpp[C_RESPONSE_DATA].failures > 0;
  bool other_fail = false;
  for (int k = 0; k < 7; k++) other_fail |= res.sv[k].failures > 0;
  for (int k = 0; k < C_COUNT; k++)
    if (k != C_RESPONSE_DATA && k != C_TIMEOUT) other_fail |= res.cpp[k].failures > 0;
  if (data_fail || other_fail || timed_out) res.functional_verdict = "FAIL";
  if (!timed_out) {
    if (other_fail) res.exit_status = "HARNESS_INVALID";
    else if (data_fail) res.exit_status = "FUNCTIONAL_MISMATCH";
  }
  if (res.last_response_cycle >= 0 && res.functional_verdict == "PASS")
    res.makespan = res.last_response_cycle - (int64_t)first_release + 1;

#ifdef RIFT_TRACE
  if (tfp) tfp->close();
#endif
  top->final();
  res.events = ev.count;
  auto t1 = std::chrono::steady_clock::now();
  res.elapsed_s = std::chrono::duration<double>(t1 - t0).count();
}

static void json_monitor(FILE* f, const Monitor& m, bool last) {
  std::fprintf(f,
               "    {\"id\":\"%s\",\"source\":\"%s\",\"description\":\"%s\",\"evaluations\":%" PRIu64
               ",\"failures\":%" PRIu64 ",\"first_failure_cycle\":%s}%s\n",
               m.id, m.source, m.description, m.evaluations, m.failures,
               m.first_failure_cycle < 0 ? "null" : std::to_string(m.first_failure_cycle).c_str(), last ? "" : ",");
}

static bool write_summary(const std::string& path, const Options& opt, const Workload& wl, const RunResult& r) {
  FILE* f = std::fopen(path.c_str(), "w");
  if (!f) return false;
  struct rusage ru;
  getrusage(RUSAGE_SELF, &ru);
  std::fprintf(f, "{\n");
  std::fprintf(f, "  \"schema_version\": 1,\n  \"run_id\": \"%s\",\n", opt.run_id.c_str());
  std::fprintf(f, "  \"runner\": \"verilator_rtl\",\n");
  std::fprintf(f,
               "  \"configuration\": {\"topology_code\": %d, \"num_in\": %d, \"num_out\": %d, \"addr_mem_width\": %d, "
               "\"capacity_words\": %u},\n",
               kTopology, kNumIn, kNumOut, kAddrMemWidth, kCapacityWords);
  std::fprintf(f, "  \"workload_digest\": \"%s\",\n", wl.digest.c_str());
  std::fprintf(f, "  \"exit_status\": \"%s\",\n  \"functional_verdict\": \"%s\",\n", r.exit_status.c_str(),
               r.functional_verdict.c_str());
  std::fprintf(f, "  \"expected_operations\": %zu,\n  \"accepted\": %" PRIu64 ",\n  \"completed\": %" PRIu64 ",\n",
               wl.total_ops, r.accepted, r.completed);
  std::fprintf(f, "  \"bank_acceptances\": %" PRIu64 ",\n", r.bank_accepts);
  std::fprintf(f, "  \"reset_cycles\": %d,\n  \"first_release_cycle\": %" PRIu64 ",\n", kResetCycles,
               r.first_release_cycle);
  std::fprintf(f, "  \"first_offer_cycle\": %s,\n",
               r.first_offer_cycle < 0 ? "null" : std::to_string(r.first_offer_cycle).c_str());
  std::fprintf(f, "  \"last_response_cycle\": %s,\n",
               r.last_response_cycle < 0 ? "null" : std::to_string(r.last_response_cycle).c_str());
  std::fprintf(f, "  \"makespan\": %s,\n", r.makespan < 0 ? "null" : std::to_string(r.makespan).c_str());
  std::fprintf(f, "  \"metric_id\": \"inclusive_cycle_makespan_v1\",\n");
  std::fprintf(f, "  \"active_cycles\": %" PRIu64 ",\n  \"total_cycles\": %" PRIu64 ",\n", r.active_cycles,
               r.total_cycles);
  std::fprintf(f, "  \"timeout_cycles\": %" PRIu64 ",\n", opt.timeout);
  std::fprintf(f, "  \"sv_inject_mask\": %u,\n  \"cpp_inject\": \"%s\",\n", opt.sv_inject, opt.inject.c_str());
  std::fprintf(f, "  \"stalls\": [");
  for (size_t k = 0; k < opt.stalls.size(); k++)
    std::fprintf(f, "%s{\"bank\": %d, \"start\": %" PRIu64 ", \"length\": %" PRIu64 "}", k ? ", " : "",
                 opt.stalls[k].bank, opt.stalls[k].start, opt.stalls[k].length);
  std::fprintf(f, "],\n");
  std::fprintf(f, "  \"events_written\": %" PRIu64 ",\n", r.events);
  std::fprintf(f, "  \"elapsed_seconds\": %.9f,\n", r.elapsed_s);
  std::fprintf(f, "  \"max_rss_raw\": %ld,\n", (long)ru.ru_maxrss);
  std::fprintf(f, "  \"monitors\": [\n");
  for (int k = 0; k < 7; k++) {
    if (k == 5 && kTopology != 0) continue;
    json_monitor(f, r.sv[k], false);
  }
  for (int k = 0; k < C_COUNT; k++) json_monitor(f, r.cpp[k], k == C_COUNT - 1);
  std::fprintf(f, "  ]\n}\n");
  std::fclose(f);
  return true;
}

static bool parse_stall(const std::string& s, Stall& st) {
  int b;
  unsigned long long a, l;
  if (std::sscanf(s.c_str(), "%d:%llu:%llu", &b, &a, &l) != 3) return false;
  if (b < 0 || b >= kNumOut) return false;
  st = Stall{b, a, l};
  return true;
}

static int usage() {
  std::fprintf(stderr,
               "usage: rift_sim --workload W --summary S [--events E|-] [--run-id ID] [--timeout N]\n"
               "                [--stall bank:start:len]... [--inject unstable_request|oracle_offset]\n"
               "                [--sv-inject MASK] [--fst FILE]\n"
               "       rift_sim --batch LIST   (each line: workload summary events|-)\n");
  return 2;
}

int main(int argc, char** argv) {
  Options opt;
  for (int i = 1; i < argc; i++) {
    std::string a = argv[i];
    auto need = [&](std::string& dst) {
      if (i + 1 >= argc) return false;
      dst = argv[++i];
      return true;
    };
    std::string v;
    if (a == "--workload") { if (!need(opt.workload_path)) return usage(); }
    else if (a == "--events") { if (!need(opt.events_path)) return usage(); }
    else if (a == "--summary") { if (!need(opt.summary_path)) return usage(); }
    else if (a == "--run-id") { if (!need(opt.run_id)) return usage(); }
    else if (a == "--batch") { if (!need(opt.batch_path)) return usage(); }
    else if (a == "--fst") { if (!need(opt.fst_path)) return usage(); }
    else if (a == "--inject") { if (!need(opt.inject)) return usage(); }
    else if (a == "--sv-inject") { if (!need(v)) return usage(); opt.sv_inject = (uint32_t)std::strtoul(v.c_str(), nullptr, 0); }
    else if (a == "--timeout") { if (!need(v)) return usage(); opt.timeout = std::strtoull(v.c_str(), nullptr, 10); }
    else if (a == "--stall") {
      if (!need(v)) return usage();
      Stall st;
      if (!parse_stall(v, st)) return usage();
      opt.stalls.push_back(st);
    } else if (a == "+verilator+seed" || a.rfind("+verilator", 0) == 0) {
      continue;
    } else {
      return usage();
    }
  }
  if (!opt.inject.empty() && opt.inject != "unstable_request" && opt.inject != "oracle_offset") return usage();
#ifndef RIFT_TRACE
  if (!opt.fst_path.empty()) {
    std::fprintf(stderr, "this build has no FST support; rebuild with tracing enabled\n");
    return 2;
  }
#endif

  if (!opt.batch_path.empty()) {
    std::ifstream in(opt.batch_path);
    if (!in) return usage();
    std::string line;
    int n = 0;
    while (std::getline(in, line)) {
      if (line.empty()) continue;
      std::istringstream ss(line);
      Options o = opt;
      ss >> o.workload_path >> o.summary_path >> o.events_path;
      if (o.events_path == "-") o.events_path.clear();
      o.run_id = "batch-" + std::to_string(n++);
      Workload wl;
      std::string err;
      if (!parse_workload(o.workload_path, wl, err)) {
        std::fprintf(stderr, "INVALID_WORKLOAD %s: %s\n", o.workload_path.c_str(), err.c_str());
        return 3;
      }
      EventWriter ev;
      ev.open(o.events_path, o.run_id);
      RunResult r;
      run_one(o, wl, r, ev);
      ev.close();
      if (!write_summary(o.summary_path, o, wl, r)) return 1;
    }
    return 0;
  }

  if (opt.workload_path.empty() || opt.summary_path.empty()) return usage();
  Workload wl;
  std::string err;
  if (!parse_workload(opt.workload_path, wl, err)) {
    FILE* f = std::fopen(opt.summary_path.c_str(), "w");
    if (f) {
      std::fprintf(f, "{\"schema_version\": 1, \"run_id\": \"%s\", \"runner\": \"verilator_rtl\", "
                      "\"exit_status\": \"INVALID_WORKLOAD\", \"functional_verdict\": \"NOT_EVALUATED\", "
                      "\"detail\": \"%s\"}\n", opt.run_id.c_str(), err.c_str());
      std::fclose(f);
    }
    std::fprintf(stderr, "INVALID_WORKLOAD: %s\n", err.c_str());
    return 3;
  }
  EventWriter ev;
  ev.open(opt.events_path, opt.run_id);
  RunResult r;
  run_one(opt, wl, r, ev);
  ev.close();
  if (!write_summary(opt.summary_path, opt, wl, r)) return 1;
  return 0;
}
