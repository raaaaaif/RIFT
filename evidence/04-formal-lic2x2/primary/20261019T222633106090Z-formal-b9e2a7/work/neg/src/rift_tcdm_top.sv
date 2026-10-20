// RIFT Phase 0 wrapper around the pinned pulp-platform tcdm_interconnect.
//
// The upstream sources are compiled unmodified. This wrapper only fixes the
// audited parameter set (32-bit data/address, ByteOffWidth=2, RespLat=1,
// WriteRespOn=1, NumPar=1), converts packed buses to unpacked ports for the C++
// driver, and adds RIFT's own explicitly counted boundary monitors.
//
// Monitor outputs are combinational and are sampled by the driver immediately
// before each rising edge, together with the acceptance sample A_t.
// mon_inject_i corrupts only the monitor's *view* of one signal so that each
// monitor's detection path can be shown active; it never alters the DUT.

module rift_tcdm_top #(
  parameter int unsigned TOPOLOGY       = 0,   // 0=LIC, 1=BFLY2, 2=BFLY4 (tcdm_interconnect_pkg::topo_e)
  parameter int unsigned NUM_IN         = 2,
  parameter int unsigned NUM_OUT        = 2,
  parameter int unsigned ADDR_MEM_WIDTH = 11
) (
  input  logic                      clk_i,
  input  logic                      rst_ni,
  // initiator side
  input  logic                      req_i   [NUM_IN],
  input  logic [31:0]               add_i   [NUM_IN],
  input  logic                      wen_i   [NUM_IN],
  input  logic [31:0]               wdata_i [NUM_IN],
  input  logic [3:0]                be_i    [NUM_IN],
  output logic                      gnt_o   [NUM_IN],
  output logic                      vld_o   [NUM_IN],
  output logic [31:0]               rdata_o [NUM_IN],
  // bank side
  output logic                      req_o   [NUM_OUT],
  input  logic                      gnt_i   [NUM_OUT],
  output logic [ADDR_MEM_WIDTH-1:0] add_o   [NUM_OUT],
  output logic                      wen_o   [NUM_OUT],
  output logic [3:0]                be_o    [NUM_OUT],
  input  logic [31:0]               rdata_i [NUM_OUT],
  // RIFT local monitors
  input  logic [7:0]                mon_inject_i,
  output logic [7:0]                mon_fail_o
);

  localparam int unsigned AddrWidth    = 32;
  localparam int unsigned DataWidth    = 32;
  localparam int unsigned BeWidth      = 4;
  localparam int unsigned ByteOffWidth = 2;
  localparam int unsigned BankBits     = $clog2(NUM_OUT);

  // ------------------------------------------------------------------
  // Packed views for the upstream module
  // ------------------------------------------------------------------
  logic [NUM_IN-1:0]                          req_p, gnt_p, vld_p, wen_p;
  logic [NUM_IN-1:0][AddrWidth-1:0]           add_p;
  logic [NUM_IN-1:0][DataWidth-1:0]           wdata_p, rdata_p;
  logic [NUM_IN-1:0][BeWidth-1:0]             be_p;
  logic [NUM_OUT-1:0]                         breq_p, bgnt_p, bwen_p;
  logic [NUM_OUT-1:0][ADDR_MEM_WIDTH-1:0]     badd_p;
  logic [NUM_OUT-1:0][DataWidth-1:0]          bwdata_p, brdata_p;
  logic [NUM_OUT-1:0][BeWidth-1:0]            bbe_p;

  for (genvar i = 0; i < NUM_IN; i++) begin : gen_in
    assign req_p[i]   = req_i[i];
    assign add_p[i]   = add_i[i];
    assign wen_p[i]   = wen_i[i];
    assign wdata_p[i] = wdata_i[i];
    assign be_p[i]    = be_i[i];
    assign gnt_o[i]   = gnt_p[i];
    assign vld_o[i]   = vld_p[i];
    assign rdata_o[i] = rdata_p[i];
  end

  for (genvar b = 0; b < NUM_OUT; b++) begin : gen_out
    assign req_o[b]    = breq_p[b];
    assign bgnt_p[b]   = gnt_i[b];
    assign add_o[b]    = badd_p[b];
    assign wen_o[b]    = bwen_p[b];
    assign be_o[b]     = bbe_p[b];
    assign brdata_p[b] = rdata_i[b];
  end

  tcdm_interconnect #(
    .NumIn        ( NUM_IN                                    ),
    .NumOut       ( NUM_OUT                                   ),
    .AddrWidth    ( AddrWidth                                 ),
    .DataWidth    ( DataWidth                                 ),
    .BeWidth      ( BeWidth                                   ),
    .AddrMemWidth ( ADDR_MEM_WIDTH                            ),
    .WriteRespOn  ( 1'b1                                      ),
    .RespLat      ( 1                                         ),
    .ByteOffWidth ( ByteOffWidth                              ),
    .Topology     ( tcdm_interconnect_pkg::topo_e'(TOPOLOGY)  ),
    .NumPar       ( 1                                         )
  ) i_tcdm (
    .clk_i   ( clk_i    ),
    .rst_ni  ( rst_ni   ),
    .req_i   ( req_p    ),
    .add_i   ( add_p    ),
    .wen_i   ( wen_p    ),
    .wdata_i ( wdata_p  ),
    .be_i    ( be_p     ),
    .gnt_o   ( gnt_p    ),
    .vld_o   ( vld_p    ),
    .rdata_o ( rdata_p  ),
    .req_o   ( breq_p   ),
    .gnt_i   ( bgnt_p   ),
    .add_o   ( badd_p   ),
    .wen_o   ( bwen_p   ),
    .wdata_o ( bwdata_p ),
    .be_o    ( bbe_p    ),
    .rdata_i ( brdata_p )
  );

  // ------------------------------------------------------------------
  // RIFT boundary monitors (see docs/monitor_inventory.md for the register)
  //   0 GNT_IMPLIES_REQ      gnt_o[i] only when req_i[i]
  //   1 BANK_SINGLE_ACCEPT   at most one accepted initiator per bank per cycle
  //   2 ACCEPT_CONSERVATION  #initiator acceptances == #bank acceptances
  //   3 PAYLOAD_ROUTING      each bank acceptance carries an accepted initiator's row/wen/be
  //   4 RESP_CORRESPONDENCE  vld_o[i] at t+1 iff initiator i was accepted at t (RespLat=1)
  //   5 LIC_WORK_CONSERVING  (LIC only) a requested, granting bank is never left idle
  //   6 NO_SPURIOUS_BANK_REQ req_o[b] only when some initiator requests bank b
  // ------------------------------------------------------------------
  // Each monitor reads its own view; injection bit k corrupts only monitor k's view.
  logic [NUM_IN-1:0][BankBits-1:0]        bank_sel, bank_sel_v1;
  logic [NUM_IN-1:0][ADDR_MEM_WIDTH-1:0]  row_sel;
  logic [NUM_IN-1:0]                      acc, gnt_v0, gnt_v5, vld_v4, req_v6;
  logic [NUM_IN-1:0]                      acc_q;
  logic [NUM_OUT-1:0]                     breq_v2;
  logic [NUM_OUT-1:0][ADDR_MEM_WIDTH-1:0] badd_v3;

  for (genvar i = 0; i < NUM_IN; i++) begin : gen_mon_in
    assign bank_sel[i]    = add_p[i][ByteOffWidth +: BankBits];
    assign row_sel[i]     = add_p[i][ByteOffWidth + BankBits +: ADDR_MEM_WIDTH];
    assign acc[i]         = req_p[i] & gnt_p[i];
    assign gnt_v0[i]      = (i == 0) ? (gnt_p[i] | mon_inject_i[0]) : gnt_p[i];
    assign bank_sel_v1[i] = (i == 1 && mon_inject_i[1]) ? add_p[0][ByteOffWidth +: BankBits] : bank_sel[i];
    assign vld_v4[i]      = (i == 0) ? (vld_p[i] ^ mon_inject_i[4]) : vld_p[i];
    assign gnt_v5[i]      = (i == 0) ? (gnt_p[i] & ~mon_inject_i[5]) : gnt_p[i];
    assign req_v6[i]      = (i == 0) ? (req_p[i] & ~mon_inject_i[6]) : req_p[i];
  end
  for (genvar b = 0; b < NUM_OUT; b++) begin : gen_mon_out
    assign breq_v2[b] = (b == 0) ? (breq_p[b] & ~mon_inject_i[2]) : breq_p[b];
    assign badd_v3[b] = badd_p[b] ^ {{(ADDR_MEM_WIDTH-1){1'b0}}, mon_inject_i[3]};
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin : p_acc_q
    if (!rst_ni) acc_q <= '0;
    else         acc_q <= acc & ~wen_p;
  end

  logic m_gnt_req, m_single, m_conserve, m_payload, m_resp, m_work, m_spur;
  int unsigned n_acc_in, n_acc_bank, n_hits1, n_hits5, n_match;
  logic requested, requested_v6;

  always_comb begin : p_monitors
    m_gnt_req  = 1'b0;
    m_single   = 1'b0;
    m_conserve = 1'b0;
    m_payload  = 1'b0;
    m_resp     = 1'b0;
    m_work     = 1'b0;
    m_spur     = 1'b0;
    n_acc_in   = 0;
    n_acc_bank = 0;

    for (int unsigned i = 0; i < NUM_IN; i++) begin
      if (gnt_v0[i] && !req_p[i]) m_gnt_req = 1'b1;
      if (acc[i]) n_acc_in++;
      if (vld_v4[i] != acc_q[i]) m_resp = 1'b1;
    end

    for (int unsigned b = 0; b < NUM_OUT; b++) begin
      n_hits1 = 0;
      n_hits5 = 0;
      n_match = 0;
      requested = 1'b0;
      requested_v6 = 1'b0;
      for (int unsigned i = 0; i < NUM_IN; i++) begin
        if (acc[i] && bank_sel_v1[i] == BankBits'(b)) n_hits1++;
        if (acc[i] && bank_sel[i] == BankBits'(b) &&
            badd_v3[b] == row_sel[i] && bwen_p[b] == wen_p[i] && bbe_p[b] == be_p[i]) n_match++;
        if (req_p[i] && gnt_v5[i] && bank_sel[i] == BankBits'(b)) n_hits5++;
        if (req_p[i] && bank_sel[i] == BankBits'(b)) requested = 1'b1;
        if (req_v6[i] && bank_sel[i] == BankBits'(b)) requested_v6 = 1'b1;
      end
      if (n_hits1 > 1) m_single = 1'b1;
      if (breq_v2[b] && bgnt_p[b]) n_acc_bank++;
      if (breq_p[b] && bgnt_p[b] && n_match != 1) m_payload = 1'b1;
      if (breq_p[b] && !requested_v6) m_spur = 1'b1;
      if (TOPOLOGY == 0 && bgnt_p[b] && requested && n_hits5 == 0) m_work = 1'b1;
    end

    if (n_acc_in != n_acc_bank) m_conserve = 1'b1;
  end

  assign mon_fail_o = rst_ni ? {1'b0, m_spur, m_work, m_resp, m_payload, m_conserve, m_single, m_gnt_req}
                             : 8'h00;

endmodule
