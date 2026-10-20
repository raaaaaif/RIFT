// RIFT baseline B3: bounded SMT search on the pinned BFLY4 8x16 RTL.
//
// Every initiator holds one symbolic constant bank index (row 0) and requests
// continuously after reset with always-granting banks. The cover asks for a
// post-reset cycle in which the RTL accepts fewer requests than the number of
// distinct requested banks, i.e. a request vector on which a bank-only model's
// acceptance count is wrong. Previously found vectors are excluded through the
// generated include file rift_b3_exclusions.svh.

module rift_bfly_conflict_search (
  input logic clk_i,
  input logic rst_ni
);
  localparam int N = 8;
  localparam int B = 16;

  (* anyconst *) logic [3:0] bank_c [N];

  logic        req_i [N];
  logic [31:0] add_i [N];
  logic        wen_i [N];
  logic [31:0] wdata_i [N];
  logic [3:0]  be_i [N];
  logic        gnt_o [N];
  logic        vld_o [N];
  logic [31:0] rdata_o [N];
  logic        req_o [B];
  logic        gnt_i [B];
  logic [7:0]  add_o [B];
  logic        wen_o [B];
  logic [3:0]  be_o [B];
  logic [31:0] rdata_i [B];
  logic [7:0]  mon;

  always_comb begin
    for (int i = 0; i < N; i++) begin
      req_i[i]   = rst_ni;
      add_i[i]   = {26'd0, bank_c[i], 2'b00};
      wen_i[i]   = 1'b0;
      wdata_i[i] = '0;
      be_i[i]    = 4'hf;
    end
    for (int b = 0; b < B; b++) begin
      gnt_i[b]   = 1'b1;
      rdata_i[b] = '0;
    end
  end

  rift_tcdm_top #(.TOPOLOGY(2), .NUM_IN(N), .NUM_OUT(B), .ADDR_MEM_WIDTH(8)) dut (
    .clk_i, .rst_ni, .req_i, .add_i, .wen_i, .wdata_i, .be_i,
    .gnt_o, .vld_o, .rdata_o, .req_o, .gnt_i, .add_o, .wen_o, .be_o, .rdata_i,
    .mon_inject_i(8'h00), .mon_fail_o(mon)
  );

  logic init = 1'b1;
  always_ff @(posedge clk_i) init <= 1'b0;

  logic [4:0] n_acc, n_banks;
  logic [B-1:0] requested;
  always_comb begin
    n_acc = '0;
    requested = '0;
    for (int i = 0; i < N; i++) begin
      n_acc = n_acc + {4'd0, req_i[i] & gnt_o[i]};
      requested[bank_c[i]] = 1'b1;
    end
    n_banks = '0;
    for (int b = 0; b < B; b++) n_banks = n_banks + {4'd0, requested[b]};
  end

  always_comb begin
    if (init) assume (!rst_ni);
    else assume (rst_ni);
`include "rift_b3_exclusions.svh"
    if (rst_ni) begin
      assert (mon == 8'h00);
      cover (n_acc < n_banks);
    end
  end
endmodule
