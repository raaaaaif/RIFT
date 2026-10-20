// RIFT local formal harness: LIC 2x2 transport properties.
//
// Scope: the pinned tcdm_interconnect (via rift_tcdm_top) with RespLat=1,
// read-only requests (wen=0, be=4'hf), legal aligned addresses, environment
// request stability, and free (symbolic) bank grants and bank read data.
// Properties concern transport and response correspondence only; no memory
// contents, no progress/fairness, and nothing about the Python fast models.
// Define RIFT_FORMAL_NEGATIVE to add a deliberately false property (control).

module rift_lic2x2_formal (
  input  logic        clk_i,
  input  logic        rst_ni,
  input  logic        req_i   [2],
  input  logic [31:0] add_i   [2],
  input  logic        wen_i   [2],
  input  logic [31:0] wdata_i [2],
  input  logic [3:0]  be_i    [2],
  input  logic        gnt_i   [2],
  input  logic [31:0] rdata_i [2]
);
  logic        gnt_o [2];
  logic        vld_o [2];
  logic [31:0] rdata_o [2];
  logic        req_o [2];
  logic [10:0] add_o [2];
  logic        wen_o [2];
  logic [3:0]  be_o  [2];
  logic [7:0]  mon;

  rift_tcdm_top #(.TOPOLOGY(0), .NUM_IN(2), .NUM_OUT(2), .ADDR_MEM_WIDTH(11)) dut (
    .clk_i, .rst_ni, .req_i, .add_i, .wen_i, .wdata_i, .be_i,
    .gnt_o, .vld_o, .rdata_o, .req_o, .gnt_i, .add_o, .wen_o, .be_o, .rdata_i,
    .mon_inject_i(8'h00), .mon_fail_o(mon)
  );

  // ---------------- environment ----------------
  logic       init = 1'b1;
  logic       rst_q;
  logic       req_q [2];
  logic       gnt_q [2];
  logic [31:0] add_q [2];
  logic       acc_q [2];
  logic       bank_q [2];

  always_ff @(posedge clk_i) begin
    init  <= 1'b0;
    rst_q <= rst_ni;
    for (int i = 0; i < 2; i++) begin
      req_q[i] <= req_i[i];
      gnt_q[i] <= gnt_o[i];
      add_q[i] <= add_i[i];
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      for (int i = 0; i < 2; i++) begin acc_q[i] <= 1'b0; bank_q[i] <= 1'b0; end
    end else begin
      for (int i = 0; i < 2; i++) begin
        acc_q[i]  <= req_i[i] & gnt_o[i] & ~wen_i[i];
        bank_q[i] <= add_i[i][2];
      end
    end
  end

  logic acc [2];
  logic bank_sel [2];
  logic [10:0] row_sel [2];
  always_comb begin
    for (int i = 0; i < 2; i++) begin
      acc[i]      = req_i[i] & gnt_o[i];
      bank_sel[i] = add_i[i][2];
      row_sel[i]  = add_i[i][13:3];
    end
  end

`ifdef RIFT_FORMAL_STALL_BOUND
  // Scoped variant: every bank stall lasts at most 3 consecutive cycles.
  logic [1:0] stall_cnt [2];
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin stall_cnt[0] <= '0; stall_cnt[1] <= '0; end
    else for (int b = 0; b < 2; b++) stall_cnt[b] <= gnt_i[b] ? 2'd0 : (stall_cnt[b] == 2'd3 ? 2'd3 : stall_cnt[b] + 2'd1);
  end
  always_comb for (int b = 0; b < 2; b++) if (rst_ni && stall_cnt[b] == 2'd3) assume (gnt_i[b]);
`endif

  always_comb begin
    if (init) assume (!rst_ni);
    if (!init && rst_q) assume (rst_ni);                // single reset at start
    for (int i = 0; i < 2; i++) begin
      assume (add_i[i] < 32'd16384 && add_i[i][1:0] == 2'b00);
      assume (wen_i[i] == 1'b0 && be_i[i] == 4'hf);
      if (!rst_ni) assume (!req_i[i]);
      if (!init && rst_q && req_q[i] && !gnt_q[i]) assume (req_i[i] && add_i[i] == add_q[i]);
    end
  end

  // ---------------- properties ----------------
  logic [1:0] n_acc, n_bank_acc;
  always_comb begin
    n_acc = {1'b0, acc[0]} + {1'b0, acc[1]};
    n_bank_acc = {1'b0, req_o[0] & gnt_i[0]} + {1'b0, req_o[1] & gnt_i[1]};
    if (rst_ni) begin
      // P1 grant implies request
      for (int i = 0; i < 2; i++) assert (!gnt_o[i] || req_i[i]);
      // P2 at most one accepted initiator per bank
      for (int b = 0; b < 2; b++) assert (!(acc[0] && acc[1] && bank_sel[0] == b[0] && bank_sel[1] == b[0]));
      // P3 acceptance conservation
      assert (n_acc == n_bank_acc);
      // P4 accepted payload routing
      for (int b = 0; b < 2; b++)
        if (req_o[b] && gnt_i[b])
          assert ((acc[0] && bank_sel[0] == b[0] && add_o[b] == row_sel[0]) ||
                  (acc[1] && bank_sel[1] == b[0] && add_o[b] == row_sel[1]));
      // P5 RespLat=1 response correspondence
      for (int i = 0; i < 2; i++) assert (vld_o[i] == acc_q[i]);
      // P6 response data routed from the accepted bank
      for (int i = 0; i < 2; i++) if (vld_o[i]) assert (rdata_o[i] == rdata_i[bank_q[i]]);
      // P8 LIC work conservation
      for (int b = 0; b < 2; b++)
        if (gnt_i[b] && ((req_i[0] && bank_sel[0] == b[0]) || (req_i[1] && bank_sel[1] == b[0])))
          assert ((acc[0] && bank_sel[0] == b[0]) || (acc[1] && bank_sel[1] == b[0]));
      // P9 RIFT wrapper monitors are consistent with the DUT (never fire)
      assert (mon == 8'h00);
`ifdef RIFT_FORMAL_NEGATIVE
      // deliberately false: parallel acceptance is possible
      assert (n_acc < 2);
`endif
    end else begin
      // P7 reset: no responses while reset is asserted
      for (int i = 0; i < 2; i++) assert (!vld_o[i]);
    end
  end

  // ---------------- strengthening invariant (P10) ----------------
  // A locked bank arbiter (pinned rr_arb_tree, LockIn=1) only holds requests that
  // are still being made. True in every reachable state given request stability;
  // it rules out the unreachable lock states that defeat plain k-induction.
  logic lock0, lock1;
  logic [1:0] lreq0, lreq1, cur0, cur1;
  assign lock0 = dut.i_tcdm.gen_lic.i_xbar.gen_outputs[0].gen_rr_arb_tree.i_rr_arb_tree.gen_arbiter.gen_int_rr.gen_lock.lock_q;
  assign lock1 = dut.i_tcdm.gen_lic.i_xbar.gen_outputs[1].gen_rr_arb_tree.i_rr_arb_tree.gen_arbiter.gen_int_rr.gen_lock.lock_q;
  assign lreq0 = dut.i_tcdm.gen_lic.i_xbar.gen_outputs[0].gen_rr_arb_tree.i_rr_arb_tree.gen_arbiter.gen_int_rr.gen_lock.req_q;
  assign lreq1 = dut.i_tcdm.gen_lic.i_xbar.gen_outputs[1].gen_rr_arb_tree.i_rr_arb_tree.gen_arbiter.gen_int_rr.gen_lock.req_q;
  assign cur0 = {req_i[1] && !bank_sel[1], req_i[0] && !bank_sel[0]};
  assign cur1 = {req_i[1] && bank_sel[1], req_i[0] && bank_sel[0]};
  always_comb begin
    if (rst_ni) begin
      assert (!lock0 || (lreq0 & ~cur0) == 2'b00);
      assert (!lock1 || (lreq1 & ~cur1) == 2'b00);
    end
  end

  // ---------------- reachability covers ----------------
  always_comb begin
    if (rst_ni) begin
      cover (n_acc == 2'd1);                                                       // K1 single transfer
      cover (acc[0] && acc[1]);                                                    // K2 parallel transfer
      cover (req_i[0] && req_i[1] && bank_sel[0] == bank_sel[1] && n_acc == 2'd1); // K3 contention
      cover (!init && rst_q && req_q[0] && !gnt_q[0] && acc[0]);                   // K4 stall then release
      cover (vld_o[0] && vld_o[1]);                                                // K5 simultaneous responses
    end
  end
endmodule
