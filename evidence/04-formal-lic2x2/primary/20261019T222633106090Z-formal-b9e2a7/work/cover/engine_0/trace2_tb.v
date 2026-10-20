`ifndef VERILATOR
module testbench;
  reg [4095:0] vcdfile;
  reg clock;
`else
module testbench(input clock, output reg genclock);
  initial genclock = 1;
`endif
  reg genclock = 1;
  reg [31:0] cycle = 0;
  reg [63:0] PI_rdata_i;
  reg [0:0] PI_clk_i;
  reg [63:0] PI_add_i;
  reg [1:0] PI_gnt_i;
  reg [0:0] PI_rst_ni;
  reg [1:0] PI_wen_i;
  reg [63:0] PI_wdata_i;
  reg [1:0] PI_req_i;
  reg [7:0] PI_be_i;
  rift_lic2x2_formal UUT (
    .rdata_i(PI_rdata_i),
    .clk_i(PI_clk_i),
    .add_i(PI_add_i),
    .gnt_i(PI_gnt_i),
    .rst_ni(PI_rst_ni),
    .wen_i(PI_wen_i),
    .wdata_i(PI_wdata_i),
    .req_i(PI_req_i),
    .be_i(PI_be_i)
  );
`ifndef VERILATOR
  initial begin
    if ($value$plusargs("vcd=%s", vcdfile)) begin
      $dumpfile(vcdfile);
      $dumpvars(0, testbench);
    end
    #5 clock = 0;
    while (genclock) begin
      #5 clock = 0;
      #5 clock = 1;
    end
  end
`endif
  initial begin
`ifndef VERILATOR
    #1;
`endif
    UUT._witness_.anyinit_driver_dut_i_tcdm_gen_lic_i_xbar_gen_inputs_0__i_addr_dec_resp_mux_vld_q = 1'b0;
    UUT._witness_.anyinit_driver_dut_i_tcdm_gen_lic_i_xbar_gen_inputs_1__i_addr_dec_resp_mux_vld_q = 1'b0;
    UUT._witness_.anyinit_driver_dut_i_tcdm_gen_lic_i_xbar_gen_outputs_0__gen_rr_arb_tree_i_rr_arb_tree_gen_arbiter_gen_int_rr_gen_lock_lock_q = 1'b0;
    UUT._witness_.anyinit_driver_dut_i_tcdm_gen_lic_i_xbar_gen_outputs_0__gen_rr_arb_tree_i_rr_arb_tree_gen_arbiter_gen_int_rr_gen_lock_req_q = 2'b00;
    UUT._witness_.anyinit_driver_dut_i_tcdm_gen_lic_i_xbar_gen_outputs_0__gen_rr_arb_tree_i_rr_arb_tree_gen_arbiter_rr_q = 1'b0;
    UUT._witness_.anyinit_driver_dut_i_tcdm_gen_lic_i_xbar_gen_outputs_1__gen_rr_arb_tree_i_rr_arb_tree_gen_arbiter_gen_int_rr_gen_lock_lock_q = 1'b0;
    UUT._witness_.anyinit_driver_dut_i_tcdm_gen_lic_i_xbar_gen_outputs_1__gen_rr_arb_tree_i_rr_arb_tree_gen_arbiter_gen_int_rr_gen_lock_req_q = 2'b00;
    UUT._witness_.anyinit_driver_dut_i_tcdm_gen_lic_i_xbar_gen_outputs_1__gen_rr_arb_tree_i_rr_arb_tree_gen_arbiter_rr_q = 1'b0;
    UUT.init = 1'b1;
    UUT.rst_q = 1'b0;
    UUT.add_q[1'b0] = 32'b10000000000000000000000000000000;
    UUT.add_q[1'b1] = 32'b10000000000000000000000000000000;
    UUT.gnt_q[1'b1] = 1'b0;
    UUT.gnt_q[1'b0] = 1'b0;
    UUT.req_q[1'b0] = 1'b0;
    UUT.req_q[1'b1] = 1'b0;

    // state 0
    PI_rdata_i = 64'b0000000000000000000000000000000000000000000000000000000000000000;
    PI_clk_i = 1'b0;
    PI_add_i = 64'b0000000000000000000000000000000000000000000000000000000000000000;
    PI_gnt_i = 2'b00;
    PI_rst_ni = 1'b0;
    PI_wen_i = 2'b00;
    PI_wdata_i = 64'b0000000000000000000000000000000000000000000000000000000000000000;
    PI_req_i = 2'b00;
    PI_be_i = 8'b11111111;
  end
  always @(posedge clock) begin
    // state 1
    if (cycle == 0) begin
      PI_rdata_i <= 64'b0000000000000000000000000000000000000000000000000000000000000000;
      PI_clk_i <= 1'b0;
      PI_add_i <= 64'b0000000000000000000000000000010000000000000000000000000000000000;
      PI_gnt_i <= 2'b11;
      PI_rst_ni <= 1'b1;
      PI_wen_i <= 2'b00;
      PI_wdata_i <= 64'b0000000000000000000000000000000000000000000000000000000000000000;
      PI_req_i <= 2'b11;
      PI_be_i <= 8'b11111111;
    end

    genclock <= cycle < 1;
    cycle <= cycle + 1;
  end
endmodule
