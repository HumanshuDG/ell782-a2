#!/usr/bin/env python3
"""
design.py - WM-8 five-stage pipelined washing-machine microcontroller.

Builds every sub-circuit from basic gates / registers (see logisim_gen.py)
and writes:
    washing_pipeline.circ            (deliverable, main = interactive top level)
    tests/tN_*.circ                  (self-checking test benches for Logisim -tty)

Run:  python3 tools/design.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from logisim_gen import Circuit, project_xml   # noqa: E402
import asm                                       # noqa: E402

# Control-word bit positions (ID/EX "CW" field)
CW_BITS = ["RW", "MR", "MW", "UA", "UB", "YI", "AOP0", "AOP1", "SB", "BZ", "BNZ", "JP", "HT"]
CWW = len(CW_BITS)
OPNAMES = ["NOP", "LDI", "MOV", "ADD", "SUB", "AND", "LD", "ST",
           "ADDI", "BEQZ", "BNEZ", "JMP", "SGEU", "RSV_D", "RSV_E", "HALT"]


# =====================================================================
#  Gate-level building blocks
# =====================================================================
def build_library():
    L = {}

    # ---- 1-bit full adder / half adder --------------------------------
    c = Circuit("fa1")
    for p in ("A", "B", "CI"):
        c.inp(p)
    c.newcol()
    c.gate("XOR", ["A", "B"], "P")
    c.gate("XOR", ["P", "CI"], "S")
    c.gate("AND", ["A", "B"], "G")
    c.gate("AND", ["P", "CI"], "T")
    c.gate("OR", ["G", "T"], "CO")
    c.newcol()
    c.outp("S"); c.outp("CO")
    L["fa1"] = c.finish()

    c = Circuit("ha1")
    c.inp("A"); c.inp("CI")
    c.newcol()
    c.gate("XOR", ["A", "CI"], "S")
    c.gate("AND", ["A", "CI"], "CO")
    c.newcol()
    c.outp("S"); c.outp("CO")
    L["ha1"] = c.finish()

    # ---- 8-bit ripple-carry adder -------------------------------------
    c = Circuit("add8", maxh=1300)
    c.inp("A", 8); c.inp("B", 8); c.inp("CI")
    c.newcol()
    c.split("A", 8, [(f"a{i}", i) for i in range(8)])
    c.split("B", 8, [(f"b{i}", i) for i in range(8)])
    c.newcol()
    for i in range(8):
        cin = "CI" if i == 0 else f"c{i}"
        cout = "CO" if i == 7 else f"c{i + 1}"
        c.sub(L["fa1"], {"A": f"a{i}", "B": f"b{i}", "CI": cin, "S": f"s{i}", "CO": cout},
              label=f"FA{i}")
    c.newcol()
    c.join("S", 8, [(f"s{i}", i) for i in range(8)])
    c.newcol()
    c.outp("S", 8); c.outp("CO")
    L["add8"] = c.finish()

    # ---- 8-bit incrementer (PC+1, timer, cycle counters) ----------------
    c = Circuit("inc8", maxh=1300)
    c.inp("A", 8); c.inp("CI")
    c.newcol()
    c.split("A", 8, [(f"a{i}", i) for i in range(8)])
    c.newcol()
    for i in range(8):
        cin = "CI" if i == 0 else f"c{i}"
        cout = "CO" if i == 7 else f"c{i + 1}"
        c.sub(L["ha1"], {"A": f"a{i}", "CI": cin, "S": f"s{i}", "CO": cout}, label=f"HA{i}")
    c.newcol()
    c.join("S", 8, [(f"s{i}", i) for i in range(8)])
    c.newcol()
    c.outp("S", 8); c.outp("CO")
    L["inc8"] = c.finish()

    # ---- 8-bit 2:1 multiplexer: Y = S ? D1 : D0 ------------------------
    c = Circuit("mux2_8")
    c.inp("D0", 8); c.inp("D1", 8); c.inp("S")
    c.newcol()
    c.rep("S", "S8", 8)
    c.inv("S8", "NS8", 8)
    c.newcol()
    c.gate("AND", ["D1", "S8"], "T1", 8)
    c.gate("AND", ["D0", "NS8"], "T0", 8)
    c.gate("OR", ["T0", "T1"], "Y", 8)
    c.newcol()
    c.outp("Y", 8)
    L["mux2_8"] = c.finish()

    # ---- 8-bit 4:1 multiplexer (tree of mux2_8) ------------------------
    c = Circuit("mux4_8")
    for i in range(4):
        c.inp(f"D{i}", 8)
    c.inp("S", 2)
    c.newcol()
    c.split("S", 2, [("s0", 0), ("s1", 1)])
    c.newcol()
    c.sub(L["mux2_8"], {"D0": "D0", "D1": "D1", "S": "s0", "Y": "L0"}, label="M0")
    c.sub(L["mux2_8"], {"D0": "D2", "D1": "D3", "S": "s0", "Y": "L1"}, label="M1")
    c.sub(L["mux2_8"], {"D0": "L0", "D1": "L1", "S": "s1", "Y": "Y"}, label="M2")
    c.newcol()
    c.outp("Y", 8)
    L["mux4_8"] = c.finish()

    # ---- 8-bit 8:1 multiplexer (register-file read port) ---------------
    c = Circuit("mux8_8", maxh=1300)
    for i in range(8):
        c.inp(f"D{i}", 8)
    c.inp("S", 3)
    c.newcol()
    c.split("S", 3, [("s0", 0), ("s1", 1), ("s2", 2)])
    c.newcol()
    for k in range(4):
        c.sub(L["mux2_8"], {"D0": f"D{2 * k}", "D1": f"D{2 * k + 1}", "S": "s0", "Y": f"L{k}"},
              label=f"A{k}")
    c.newcol()
    c.sub(L["mux2_8"], {"D0": "L0", "D1": "L1", "S": "s1", "Y": "M0"}, label="B0")
    c.sub(L["mux2_8"], {"D0": "L2", "D1": "L3", "S": "s1", "Y": "M1"}, label="B1")
    c.sub(L["mux2_8"], {"D0": "M0", "D1": "M1", "S": "s2", "Y": "Y"}, label="C0")
    c.newcol()
    c.outp("Y", 8)
    L["mux8_8"] = c.finish()

    # ---- AND an 8-bit bus with a 1-bit enable --------------------------
    c = Circuit("and8en")
    c.inp("D", 8); c.inp("E")
    c.newcol()
    c.rep("E", "E8", 8)
    c.newcol()
    c.gate("AND", ["D", "E8"], "Y", 8)
    c.newcol()
    c.outp("Y", 8)
    L["and8en"] = c.finish()

    # ---- zero detect / equality comparators ----------------------------
    c = Circuit("zero8")
    c.inp("A", 8)
    c.newcol()
    c.split("A", 8, [(f"a{i}", i) for i in range(8)])
    c.newcol()
    c.gate("NOR", [f"a{i}" for i in range(8)], "Z")
    c.newcol()
    c.outp("Z")
    L["zero8"] = c.finish()

    c = Circuit("eq8")
    c.inp("A", 8); c.inp("B", 8)
    c.newcol()
    c.gate("XOR", ["A", "B"], "X", 8)
    c.split("X", 8, [(f"x{i}", i) for i in range(8)])
    c.newcol()
    c.gate("NOR", [f"x{i}" for i in range(8)], "EQ")
    c.newcol()
    c.outp("EQ")
    L["eq8"] = c.finish()

    c = Circuit("eq3")
    c.inp("A", 3); c.inp("B", 3)
    c.newcol()
    c.gate("XOR", ["A", "B"], "X", 3)
    c.split("X", 3, [("x0", 0), ("x1", 1), ("x2", 2)])
    c.newcol()
    c.gate("NOR", ["x0", "x1", "x2"], "EQ")
    c.newcol()
    c.outp("EQ")
    L["eq3"] = c.finish()

    # ---- decoders --------------------------------------------------------
    c = Circuit("dec3to8", maxh=1300)
    c.inp("A", 3)
    c.newcol()
    c.split("A", 3, [("a0", 0), ("a1", 1), ("a2", 2)])
    for i in range(3):
        c.inv(f"a{i}", f"n{i}")
    c.newcol()
    for k in range(8):
        lits = [f"a{i}" if (k >> i) & 1 else f"n{i}" for i in range(3)]
        c.gate("AND", lits, f"y{k}")
    c.newcol()
    c.join("Y", 8, [(f"y{k}", k) for k in range(8)])
    c.newcol()
    c.outp("Y", 8)
    L["dec3to8"] = c.finish()

    c = Circuit("dec4to16", maxh=1500)
    c.inp("A", 4)
    c.newcol()
    c.split("A", 4, [(f"a{i}", i) for i in range(4)])
    for i in range(4):
        c.inv(f"a{i}", f"n{i}")
    c.newcol()
    for k in range(16):
        lits = [f"a{i}" if (k >> i) & 1 else f"n{i}" for i in range(4)]
        c.gate("AND", lits, f"y{k}")
    c.newcol()
    c.join("Y", 16, [(f"y{k}", k) for k in range(16)])
    c.newcol()
    c.outp("Y", 16)
    L["dec4to16"] = c.finish()

    # ---- ALU -------------------------------------------------------------
    # OP=00 X+Y / X-Y (SUB=1) ; 01 X AND Y ; 10 pass Y ; 11 SGEU = carry(X-Y)
    c = Circuit("alu8")
    c.inp("X", 8); c.inp("Y", 8); c.inp("OP", 2); c.inp("SUB")
    c.newcol()
    c.rep("SUB", "SUB8", 8)
    c.gate("XOR", ["Y", "SUB8"], "YX", 8)
    c.newcol()
    c.sub(L["add8"], {"A": "X", "B": "YX", "CI": "SUB", "S": "SUM", "CO": "CO"}, label="ADDER")
    c.gate("AND", ["X", "Y"], "ANDV", 8)
    c.const("Z7", 7, 0)
    c.join("SGE", 8, [("CO", 0, 0), ("Z7", 1, 7)])
    c.newcol()
    c.sub(L["mux4_8"], {"D0": "SUM", "D1": "ANDV", "D2": "Y", "D3": "SGE", "S": "OP", "Y": "R"},
          label="RESULT_MUX")
    c.newcol()
    c.outp("R", 8); c.outp("CO")
    L["alu8"] = c.finish()

    # ---- Register file: 8 x 8, 2 read ports, 1 write port, WB->ID bypass --
    c = Circuit("regfile", maxh=1700)
    c.inp("RA", 3); c.inp("RB", 3); c.inp("WA", 3); c.inp("WD", 8); c.inp("WE"); c.inp("CLK")
    c.newcol()
    c.text("write decode")
    c.sub(L["dec3to8"], {"A": "WA", "Y": "WSEL"}, label="WDEC")
    c.split("WSEL", 8, [(f"ws{i}", i) for i in range(8)])
    for i in range(8):
        c.gate("AND", ["WE", f"ws{i}"], f"we{i}")
    c.newcol()
    c.text("R0..R7")
    for i in range(8):
        c.reg("WD", f"R{i}", 8, en=f"we{i}", clr=None, label=f"R{i}")
    c.newcol()
    c.text("read ports")
    c.sub(L["mux8_8"], dict({f"D{i}": f"R{i}" for i in range(8)}, S="RA", Y="RDA"), label="READ_A")
    c.sub(L["mux8_8"], dict({f"D{i}": f"R{i}" for i in range(8)}, S="RB", Y="RDB"), label="READ_B")
    c.newcol()
    c.text("WB->ID bypass")
    c.sub(L["eq3"], {"A": "WA", "B": "RA", "EQ": "EQA"})
    c.gate("AND", ["WE", "EQA"], "BPA")
    c.sub(L["mux2_8"], {"D0": "RDA", "D1": "WD", "S": "BPA", "Y": "DA"}, label="BYP_A")
    c.sub(L["eq3"], {"A": "WA", "B": "RB", "EQ": "EQB"})
    c.gate("AND", ["WE", "EQB"], "BPB")
    c.sub(L["mux2_8"], {"D0": "RDB", "D1": "WD", "S": "BPB", "Y": "DB"}, label="BYP_B")
    c.newcol()
    c.outp("DA", 8); c.outp("DB", 8)
    L["regfile"] = c.finish()

    # ---- main control decoder: opcode -> control word -----------------------
    c = Circuit("control", maxh=1400)
    c.inp("OP", 4)
    c.newcol()
    c.sub(L["dec4to16"], {"A": "OP", "Y": "OH"}, label="OPDEC")
    c.split("OH", 16, [(f"is_{n}", i) for i, n in enumerate(OPNAMES)])
    c.newcol()
    c.gate("OR", ["is_LDI", "is_MOV", "is_ADD", "is_SUB", "is_AND", "is_LD", "is_ADDI", "is_SGEU"], "RW")
    c.gate("OR", ["is_ADD", "is_SUB", "is_AND", "is_ST", "is_ADDI", "is_BEQZ", "is_BNEZ", "is_SGEU"], "UA")
    c.gate("OR", ["is_MOV", "is_ADD", "is_SUB", "is_AND", "is_LD", "is_ST", "is_SGEU"], "UB")
    c.gate("OR", ["is_LDI", "is_ADDI"], "YI")
    c.gate("OR", ["is_AND", "is_SGEU"], "AOP0")
    c.gate("OR", ["is_LDI", "is_MOV", "is_LD", "is_ST", "is_SGEU"], "AOP1")
    c.gate("OR", ["is_SUB", "is_SGEU"], "SB")
    c.newcol()
    src = {"RW": "RW", "MR": "is_LD", "MW": "is_ST", "UA": "UA", "UB": "UB", "YI": "YI",
           "AOP0": "AOP0", "AOP1": "AOP1", "SB": "SB", "BZ": "is_BEQZ", "BNZ": "is_BNEZ",
           "JP": "is_JMP", "HT": "is_HALT"}
    c.join("CW", CWW, [(src[b], i) for i, b in enumerate(CW_BITS)])
    c.newcol()
    c.outp("CW", CWW)
    L["control"] = c.finish()

    # ---- load-use hazard detection -----------------------------------------
    c = Circuit("hazard")
    for p, w in [("IFID_V", 1), ("UA", 1), ("UB", 1), ("RA", 3), ("RB", 3),
                 ("IDEX_V", 1), ("IDEX_MR", 1), ("IDEX_RD", 3)]:
        c.inp(p, w)
    c.newcol()
    c.sub(L["eq3"], {"A": "RA", "B": "IDEX_RD", "EQ": "EA"})
    c.sub(L["eq3"], {"A": "RB", "B": "IDEX_RD", "EQ": "EB"})
    c.gate("AND", ["UA", "EA"], "HA")
    c.gate("AND", ["UB", "EB"], "HB")
    c.gate("OR", ["HA", "HB"], "HAB")
    c.gate("AND", ["IFID_V", "IDEX_V", "IDEX_MR", "HAB"], "STALL")
    c.newcol()
    c.outp("STALL")
    L["hazard"] = c.finish()

    # ---- forwarding unit (one EX operand) ---------------------------------
    c = Circuit("fwd")
    for p, w in [("SRC", 3), ("USE", 1), ("EXMEM_V", 1), ("EXMEM_RW", 1), ("EXMEM_MR", 1),
                 ("EXMEM_RD", 3), ("MEMWB_V", 1), ("MEMWB_RW", 1), ("MEMWB_RD", 3)]:
        c.inp(p, w)
    c.newcol()
    c.sub(L["eq3"], {"A": "EXMEM_RD", "B": "SRC", "EQ": "E1"})
    c.gate("AND", ["USE", "EXMEM_V", "EXMEM_RW", "E1"], "EXM")   # youngest writer matches
    c.inv("EXMEM_MR", "NMR")
    c.gate("AND", ["EXM", "NMR"], "F_EXMEM")                      # ...and is not a load
    c.sub(L["eq3"], {"A": "MEMWB_RD", "B": "SRC", "EQ": "E2"})
    c.gate("AND", ["USE", "MEMWB_V", "MEMWB_RW", "E2"], "M2")
    c.inv("EXM", "NEXM")
    c.gate("AND", ["M2", "NEXM"], "F_MEMWB")                      # only if no younger writer
    c.newcol()
    c.outp("F_EXMEM"); c.outp("F_MEMWB")
    L["fwd"] = c.finish()

    # ---- 8-bit timer -------------------------------------------------------
    c = Circuit("timer8", maxh=1300)
    for p, w in [("CLK", 1), ("RST", 1), ("WD", 8), ("WE_LIMIT", 1), ("WE_CTRL", 1)]:
        c.inp(p, w)
    c.newcol()
    c.text("CTRL: bit0 EN, bit1 CLR")
    c.split("WD", 8, [("wd0", 0), ("wd1", 1)])
    c.reg("wd0", "EN", 1, en="WE_CTRL", label="EN")
    c.gate("AND", ["WE_CTRL", "wd1"], "CLRCMD")
    c.inv("CLRCMD", "NCLR")
    c.const("ONE", 1, 1)
    c.newcol()
    c.text("COUNT")
    c.sub(L["inc8"], {"A": "COUNT", "CI": "ONE", "S": "INC"}, label="INC")
    c.sub(L["and8en"], {"D": "INC", "E": "NCLR", "Y": "CNT_D"})
    c.gate("OR", ["CLRCMD", "EN"], "CNT_EN")
    c.reg("CNT_D", "COUNT", 8, en="CNT_EN", label="COUNT")
    c.newcol()
    c.text("LIMIT / sticky MATCH")
    c.reg("WD", "LIMIT", 8, en="WE_LIMIT", label="LIMIT")
    c.sub(L["eq8"], {"A": "INC", "B": "LIMIT", "EQ": "EQL"})
    c.sub(L["zero8"], {"A": "LIMIT", "Z": "LZ"})
    c.inv("LZ", "LNZ")
    c.gate("AND", ["EN", "EQL", "LNZ"], "HIT")
    c.gate("OR", ["MATCH", "HIT"], "MH")
    c.gate("AND", ["MH", "NCLR"], "M_D")
    c.reg("M_D", "MATCH", 1, label="MATCH")
    c.newcol()
    c.outp("COUNT", 8); c.outp("LIMIT", 8); c.outp("EN"); c.outp("MATCH")
    L["timer8"] = c.finish()

    # ---- motor safety interlock ------------------------------------------
    c = Circuit("safety")
    for p in ("CLK", "RST", "REQ", "DOOR", "START"):
        c.inp(p)
    c.newcol()
    c.text("START edge detector")
    c.reg("START", "SPREV", 1, label="START_PREV")
    c.inv("SPREV", "NSPREV")
    c.gate("AND", ["START", "NSPREV"], "RISE")
    c.newcol()
    c.text("TRIP latch")
    c.inv("DOOR", "NDOOR")
    c.gate("AND", ["REQ", "NDOOR"], "SET_TRIP")
    c.inv("REQ", "NREQ")
    c.gate("AND", ["NREQ", "DOOR", "RISE"], "REARM")
    c.inv("REARM", "NREARM")
    c.gate("AND", ["TRIP", "NREARM"], "HOLD")
    c.gate("OR", ["SET_TRIP", "HOLD"], "TRIP_D")
    c.reg("TRIP_D", "TRIP", 1, label="TRIP")
    c.newcol()
    c.text("combinational gate")
    c.inv("TRIP", "NTRIP")
    c.gate("AND", ["REQ", "DOOR", "NTRIP"], "ACTUAL")
    c.newcol()
    c.outp("ACTUAL"); c.outp("TRIP"); c.outp("RISE")
    L["safety"] = c.finish()

    # ---- memory-mapped I/O, address decode, read mux ------------------------
    c = Circuit("mmio", maxh=1900)
    for p, w in [("CLK", 1), ("RST", 1), ("ADDR", 8), ("WDATA", 8), ("WE", 1), ("RAM_DO", 8),
                 ("START", 1), ("DOOR", 1), ("MODE", 2), ("WL", 8), ("TEMP", 8), ("RPM", 8)]:
        c.inp(p, w)
    c.newcol()
    c.text("address decode")
    c.split("ADDR", 8, [("RAM_A", 0, 6), ("A7", 7)])
    c.split("ADDR", 8, [("LO", 0, 3), ("A4", 4), ("A5", 5), ("A6", 6), ("A7b", 7)])
    c.inv("A7", "IS_RAM")
    c.gate("AND", ["A4", "A5", "A6", "A7b"], "IS_PER")
    c.sub(L["dec4to16"], {"A": "LO", "Y": "PSEL"}, label="PDEC")
    used = [0, 1, 2, 3, 4, 5, 8, 9, 10, 11]
    c.split("PSEL", 16, [(f"p{k}" if k in used else None, k) for k in range(16)])
    c.newcol()
    c.text("selects / write enables")
    for k in used:
        c.gate("AND", ["IS_PER", f"p{k}"], f"SEL_F{k:X}")
    c.gate("AND", ["WE", "IS_RAM"], "RAM_WE")
    c.gate("AND", ["WE", "SEL_F4"], "WE_ACT")
    c.gate("AND", ["WE", "SEL_F5"], "WE_DISP")
    c.gate("AND", ["WE", "SEL_F9"], "WE_LIMIT")
    c.gate("AND", ["WE", "SEL_FA"], "WE_CTRL")
    c.newcol()
    c.text("output latches")
    c.const("M7F", 8, 0x7F)
    c.gate("AND", ["WDATA", "M7F"], "WACT", 8)
    c.reg("WACT", "ACT", 8, en="WE_ACT", label="ACT_LATCH")
    c.reg("WDATA", "DISP", 8, en="WE_DISP", label="DISPLAY")
    c.text("timer / safety")
    c.sub(L["timer8"], {"CLK": "CLK", "RST": "RST", "WD": "WDATA", "WE_LIMIT": "WE_LIMIT",
                        "WE_CTRL": "WE_CTRL", "COUNT": "T_COUNT", "LIMIT": "T_LIMIT",
                        "EN": "T_EN", "MATCH": "T_MATCH"}, label="TIMER")
    c.split("ACT", 8, [("MOTOR_REQ", 2)])
    c.sub(L["safety"], {"CLK": "CLK", "RST": "RST", "REQ": "MOTOR_REQ", "DOOR": "DOOR",
                        "START": "START", "ACTUAL": "MOTOR_ACT", "TRIP": "TRIP"}, label="SAFETY")
    c.newcol()
    c.text("read-back words")
    c.const("Z2", 2, 0)
    c.const("Z7", 7, 0)
    c.join("STATUS", 8, [("START", 0, 0), ("DOOR", 1, 1), ("MODE", 2, 3), ("TRIP", 4, 4),
                         ("MOTOR_ACT", 5, 5), ("Z2", 6, 7)])
    c.join("CTRL_RB", 8, [("T_EN", 0, 0), ("Z7", 1, 7)])
    c.join("TSTAT", 8, [("T_MATCH", 0, 0), ("Z7", 1, 7)])
    c.newcol()
    c.text("read mux (AND-OR)")
    srcs = [("RAM_DO", "IS_RAM"), ("STATUS", "SEL_F0"), ("WL", "SEL_F1"), ("TEMP", "SEL_F2"),
            ("RPM", "SEL_F3"), ("ACT", "SEL_F4"), ("DISP", "SEL_F5"), ("T_COUNT", "SEL_F8"),
            ("T_LIMIT", "SEL_F9"), ("CTRL_RB", "SEL_FA"), ("TSTAT", "SEL_FB")]
    for i, (d, e) in enumerate(srcs):
        c.sub(L["and8en"], {"D": d, "E": e, "Y": f"RD{i}"})
    c.newcol()
    c.gate("OR", [f"RD{i}" for i in range(len(srcs))], "RDATA", 8, size=70)
    c.newcol()
    for p, w in [("RDATA", 8), ("RAM_WE", 1), ("RAM_A", 7), ("ACT", 8), ("DISP", 8),
                 ("MOTOR_ACT", 1), ("TRIP", 1), ("T_COUNT", 8), ("T_MATCH", 1), ("T_EN", 1),
                 ("T_LIMIT", 8)]:
        c.outp(p, w)
    L["mmio"] = c.finish()

    L["cpu"] = build_cpu(L)
    return L


# =====================================================================
#  Five-stage pipelined CPU
# =====================================================================
def build_cpu(L):
    c = Circuit("cpu", maxh=2000, gapx=50)
    for p, w in [("CLK", 1), ("RST", 1), ("I_DATA", 16), ("D_RDATA", 8)]:
        c.inp(p, w)
    c.const("ONE", 1, 1)

    # ------------------------------------------------------------------ IF
    c.newcol()
    c.text("IF: PC / next-PC / IF-ID")
    c.reg("NPC", "PC", 8, en="PC_EN", label="PC")
    c.sub(L["inc8"], {"A": "PC", "CI": "ONE", "S": "PCP1"}, label="PC+1")
    c.sub(L["mux2_8"], {"D0": "PCP1", "D1": "IDEX_IMM", "S": "REDIRECT", "Y": "NPC"}, label="NPC_MUX")
    c.gate("OR", ["STALL_RAW", "HALT_EX", "HALTED"], "HOLD")
    c.inv("HOLD", "NHOLD")
    c.gate("OR", ["REDIRECT", "NHOLD"], "PC_EN")
    c.gate("OR", ["REDIRECT", "HALT_EX"], "FLUSH")
    c.inv("STALL_RAW", "NSTALL")
    c.gate("OR", ["NSTALL", "FLUSH"], "IFID_EN")
    c.gate("NOR", ["FLUSH", "HALTED"], "IFV_D")
    c.reg("I_DATA", "IFID_IR", 16, en="IFID_EN", label="IFID.IR")
    c.reg("PC", "IFID_PC", 8, en="IFID_EN", label="IFID.PC")
    c.reg("IFV_D", "IFID_V", 1, en="IFID_EN", label="IFID.V")
    c.reg("ONE", "HALTED", 1, en="HALT_EX", label="HALTED")

    # ------------------------------------------------------------------ ID
    c.newcol()
    c.text("ID: decode / register read / hazard")
    c.split("IFID_IR", 16, [("RB", 6, 8), ("RA", 9, 11), ("OPC", 12, 15)])
    c.split("IFID_IR", 16, [("IMM", 0, 7)])
    c.sub(L["control"], {"OP": "OPC", "CW": "CW"}, label="CONTROL")
    c.split("CW", CWW, [("ID_UA", 3), ("ID_UB", 4)])
    c.sub(L["regfile"], {"RA": "RA", "RB": "RB", "WA": "MEMWB_RD", "WD": "MEMWB_RES",
                         "WE": "WB_WE", "CLK": "CLK", "DA": "DA", "DB": "DB"}, label="REGFILE")
    c.sub(L["hazard"], {"IFID_V": "IFID_V", "UA": "ID_UA", "UB": "ID_UB", "RA": "RA", "RB": "RB",
                        "IDEX_V": "IDEX_V", "IDEX_MR": "X_MR", "IDEX_RD": "IDEX_RA",
                        "STALL": "STALL_RAW"}, label="HAZARD")
    c.inv("FLUSH", "NFLUSH")
    c.gate("AND", ["IFID_V", "NSTALL", "NFLUSH"], "IDV_D")
    c.gate("AND", ["STALL_RAW", "NFLUSH"], "STALL")

    c.newcol()
    c.text("ID/EX pipeline register")
    c.reg("IDV_D", "IDEX_V", 1, label="IDEX.V")
    c.reg("CW", "IDEX_CW", CWW, label="IDEX.CW")
    c.reg("RA", "IDEX_RA", 3, label="IDEX.RA")
    c.reg("RB", "IDEX_RB", 3, label="IDEX.RB")
    c.reg("DA", "IDEX_DA", 8, label="IDEX.DA")
    c.reg("DB", "IDEX_DB", 8, label="IDEX.DB")
    c.reg("IMM", "IDEX_IMM", 8, label="IDEX.IMM")
    c.reg("IFID_PC", "IDEX_PC", 8, label="IDEX.PC")

    # ------------------------------------------------------------------ EX
    c.newcol()
    c.text("EX: forwarding / ALU / branch")
    c.split("IDEX_CW", CWW, [("X_RW", 0), ("X_MR", 1), ("X_MW", 2), ("X_UA", 3), ("X_UB", 4),
                              ("X_YI", 5), ("X_AOP", 6, 7), ("X_SB", 8), ("X_BZ", 9),
                              ("X_BNZ", 10), ("X_JP", 11), ("X_HT", 12)])
    fw = dict(EXMEM_V="EXMEM_V", EXMEM_RW="EXMEM_RW", EXMEM_MR="EXMEM_MR", EXMEM_RD="EXMEM_RD",
              MEMWB_V="MEMWB_V", MEMWB_RW="MEMWB_RW", MEMWB_RD="MEMWB_RD")
    c.gate("AND", ["IDEX_V", "X_UA"], "USE_A")     # forward only for a valid EX consumer
    c.gate("AND", ["IDEX_V", "X_UB"], "USE_B")
    c.sub(L["fwd"], dict(fw, SRC="IDEX_RA", USE="USE_A", F_EXMEM="FA_EXMEM", F_MEMWB="FA_MEMWB"),
          label="FWD_A")
    c.sub(L["fwd"], dict(fw, SRC="IDEX_RB", USE="USE_B", F_EXMEM="FB_EXMEM", F_MEMWB="FB_MEMWB"),
          label="FWD_B")
    c.sub(L["mux2_8"], {"D0": "IDEX_DA", "D1": "MEMWB_RES", "S": "FA_MEMWB", "Y": "OA0"}, label="FA_M1")
    c.sub(L["mux2_8"], {"D0": "OA0", "D1": "EXMEM_ALU", "S": "FA_EXMEM", "Y": "OPA"}, label="FA_M2")
    c.sub(L["mux2_8"], {"D0": "IDEX_DB", "D1": "MEMWB_RES", "S": "FB_MEMWB", "Y": "OB0"}, label="FB_M1")
    c.sub(L["mux2_8"], {"D0": "OB0", "D1": "EXMEM_ALU", "S": "FB_EXMEM", "Y": "OPB"}, label="FB_M2")
    c.newcol()
    c.sub(L["mux2_8"], {"D0": "OPB", "D1": "IDEX_IMM", "S": "X_YI", "Y": "ALUY"}, label="YSEL")
    c.sub(L["alu8"], {"X": "OPA", "Y": "ALUY", "OP": "X_AOP", "SUB": "X_SB", "R": "ALUR"}, label="ALU")
    c.sub(L["zero8"], {"A": "OPA", "Z": "ZA"}, label="ZERO")
    c.inv("ZA", "NZA")
    c.gate("AND", ["X_BZ", "ZA"], "TBZ")
    c.gate("AND", ["X_BNZ", "NZA"], "TBNZ")
    c.gate("OR", ["X_JP", "TBZ", "TBNZ"], "TAKE")
    c.gate("AND", ["IDEX_V", "TAKE"], "REDIRECT")
    c.gate("AND", ["IDEX_V", "X_HT"], "HALT_EX")
    c.join("FWDA", 2, [("FA_MEMWB", 0), ("FA_EXMEM", 1)])
    c.join("FWDB", 2, [("FB_MEMWB", 0), ("FB_EXMEM", 1)])
    c.join("XC3", 3, [("X_RW", 0), ("X_MR", 1), ("X_MW", 2)])

    c.newcol()
    c.text("EX/MEM pipeline register")
    c.reg("IDEX_V", "EXMEM_V", 1, label="EXMEM.V")
    c.reg("XC3", "EXMEM_C", 3, label="EXMEM.CTRL")
    c.split("EXMEM_C", 3, [("EXMEM_RW", 0), ("EXMEM_MR", 1), ("EXMEM_MW", 2)])
    c.reg("IDEX_RA", "EXMEM_RD", 3, label="EXMEM.RD")
    c.reg("ALUR", "EXMEM_ALU", 8, label="EXMEM.ALU")
    c.reg("OPA", "EXMEM_SD", 8, label="EXMEM.SDATA")
    c.reg("IDEX_PC", "EXMEM_PC", 8, label="EXMEM.PC")

    # ------------------------------------------------------------------ MEM
    c.newcol()
    c.text("MEM: data port / MEM-WB")
    c.gate("AND", ["EXMEM_V", "EXMEM_MW"], "D_WE")
    c.gate("AND", ["EXMEM_V", "EXMEM_MR"], "D_RE")
    c.sub(L["mux2_8"], {"D0": "EXMEM_ALU", "D1": "D_RDATA", "S": "EXMEM_MR", "Y": "MRES"},
          label="LOAD_MUX")
    c.reg("EXMEM_V", "MEMWB_V", 1, label="MEMWB.V")
    c.reg("EXMEM_RW", "MEMWB_RW", 1, label="MEMWB.RW")
    c.reg("EXMEM_RD", "MEMWB_RD", 3, label="MEMWB.RD")
    c.reg("MRES", "MEMWB_RES", 8, label="MEMWB.RES")
    c.reg("EXMEM_PC", "MEMWB_PC", 8, label="MEMWB.PC")
    c.text("WB")
    c.gate("AND", ["MEMWB_V", "MEMWB_RW"], "WB_WE")

    # ------------------------------------------------------------------ ports
    c.newcol()
    for name, w, net in [("I_ADDR", 8, "PC"), ("D_ADDR", 8, "EXMEM_ALU"), ("D_WDATA", 8, "EXMEM_SD"),
                         ("D_WE", 1, "D_WE"), ("D_RE", 1, "D_RE"),
                         ("IFID_PC", 8, "IFID_PC"), ("IFID_V", 1, "IFID_V"), ("IFID_IR", 16, "IFID_IR"),
                         ("IDEX_PC", 8, "IDEX_PC"), ("IDEX_V", 1, "IDEX_V"),
                         ("EXMEM_PC", 8, "EXMEM_PC"), ("EXMEM_V", 1, "EXMEM_V"),
                         ("MEMWB_PC", 8, "MEMWB_PC"), ("MEMWB_V", 1, "MEMWB_V"),
                         ("STALL", 1, "STALL"), ("FLUSH", 1, "FLUSH"), ("HALTED", 1, "HALTED"),
                         ("FWD_A", 2, "FWDA"), ("FWD_B", 2, "FWDB"),
                         ("WB_WE", 1, "WB_WE"), ("WB_RD", 3, "MEMWB_RD"), ("WB_DATA", 8, "MEMWB_RES")]:
        c.outp(name, w, net=net)
    return c.finish()


# =====================================================================
#  Top levels
# =====================================================================
CPU_DBG = ["IFID_PC", "IFID_V", "IFID_IR", "IDEX_PC", "IDEX_V", "EXMEM_PC", "EXMEM_V",
           "MEMWB_PC", "MEMWB_V", "STALL", "FLUSH", "HALTED", "FWD_A", "FWD_B",
           "WB_WE", "WB_RD", "WB_DATA"]


def core_system(c, L, rom_words, clk="CLK", rst="RST"):
    """CPU + instruction ROM + data RAM + MMIO; sensor nets START, DOOR, MODE, WL, TEMP, RPM."""
    c.newcol()
    c.text("Processor (5-stage pipeline)")
    conn = {"CLK": clk, "RST": rst, "I_DATA": "I_DATA", "D_RDATA": "D_RDATA",
            "I_ADDR": "PC", "D_ADDR": "D_ADDR", "D_WDATA": "D_WDATA", "D_WE": "D_WE", "D_RE": "D_RE"}
    for d in CPU_DBG:
        conn[d] = d
    c.sub(L["cpu"], conn, label="CPU")
    c.newcol()
    c.text("Instruction ROM 256x16")
    c.rom("PC", "I_DATA", 8, 16, rom_words)
    c.text("Data RAM 128x8 (0x00-0x7F)")
    c.ram("RAM_A", "D_WDATA", "RAM_DO", "RAM_WE", clk, 7, 8)
    c.text("Memory-mapped I/O, timer, safety")
    c.sub(L["mmio"], {"CLK": clk, "RST": rst, "ADDR": "D_ADDR", "WDATA": "D_WDATA", "WE": "D_WE",
                      "RAM_DO": "RAM_DO", "START": "START", "DOOR": "DOOR", "MODE": "MODE",
                      "WL": "WL", "TEMP": "TEMP", "RPM": "RPM", "RDATA": "D_RDATA",
                      "RAM_WE": "RAM_WE", "RAM_A": "RAM_A", "ACT": "ACT", "DISP": "DISP",
                      "MOTOR_ACT": "MOTOR_ACT", "TRIP": "TRIP", "T_COUNT": "T_COUNT",
                      "T_MATCH": "T_MATCH", "T_EN": "T_EN", "T_LIMIT": "T_LIMIT"}, label="MMIO")
    c.split("ACT", 8, [("VALVE_IN", 0), ("HEATER", 1), ("MOTOR_EN", 2), ("PUMP_OUT", 3),
                       ("MOTOR_DIR", 4), ("DOOR_LOCK", 5), ("BUZZER", 6)])


def build_main(L, rom_words):
    c = Circuit("main", maxh=1500, gapx=60)
    c.text("WM-8 washing-machine controller  (ELL7282 A2)", size=18)
    c.text("Clock / reset", size=14)
    c.clock("CLK")
    c.inp("RESET", 1, net="RST")
    c.text("Sensor inputs (poke to change)", size=14)
    c.inp("START", 1)
    c.inp("DOOR_CLOSED", 1, net="DOOR")
    c.inp("MODE", 2)
    c.inp("WATER_LEVEL", 8, net="WL")
    c.inp("TEMP", 8)
    c.inp("DRUM_RPM", 8, net="RPM")
    core_system(c, L, rom_words)
    c.newcol()
    c.text("Actuator requests (CPU latch 0xF4)", size=14)
    for n in ["VALVE_IN", "HEATER", "MOTOR_EN", "MOTOR_DIR", "PUMP_OUT", "DOOR_LOCK", "BUZZER"]:
        c.outp(n, 1)
    c.text("Safety-gated physical output", size=14)
    c.outp("MOTOR_EN_ACTUAL", 1, net="MOTOR_ACT")
    c.outp("TRIP", 1)
    c.text("Display / timer", size=14)
    c.outp("DISPLAY", 8, net="DISP")
    c.outp("TIMER_COUNT", 8, net="T_COUNT")
    c.outp("TIMER_MATCH", 1, net="T_MATCH")
    c.newcol()
    c.text("Pipeline monitor", size=14)
    c.outp("PC", 8)
    for d in CPU_DBG:
        w = {"IFID_IR": 16, "FWD_A": 2, "FWD_B": 2, "WB_RD": 3}.get(d, 8 if d.endswith("PC") or d == "WB_DATA" else 1)
        c.outp(d, w)
    c.outp("D_WE", 1); c.outp("D_ADDR", 8); c.outp("D_WDATA", 8)
    return c.finish_top()


# ---------------------------------------------------------------------
#  Test-bench top level (for Logisim -tty table)
# ---------------------------------------------------------------------
TB_COLS = [("CYC", 16), ("PC", 8), ("IFID_PC", 8), ("IFID_V", 1), ("IDEX_PC", 8), ("IDEX_V", 1),
           ("EXMEM_PC", 8), ("EXMEM_V", 1), ("MEMWB_PC", 8), ("MEMWB_V", 1),
           ("STALL", 1), ("FLUSH", 1), ("HALTED", 1), ("FWD_A", 2), ("FWD_B", 2),
           ("WB_WE", 1), ("WB_RD", 3), ("WB_DATA", 8), ("D_WE", 1), ("D_ADDR", 8), ("D_WDATA", 8),
           ("RAM_WE", 1), ("ACT", 8), ("DISP", 8), ("MOTOR_ACT", 1), ("TRIP", 1), ("T_COUNT", 8), ("T_MATCH", 1),
           ("T_EN", 1), ("T_LIMIT", 8), ("START", 1), ("DOOR", 1), ("MODE", 2), ("WL", 8), ("RPM", 8),
           ("IFID_IR", 16)]


def build_tb(L, rom_words, stim_words, stim_shift, stop_cycle, plant=True):
    """stim_words[k] (k = cycle >> stim_shift): bit0 START, bit1 DOOR, bit3:2 MODE."""
    c = Circuit("tb_main", maxh=2200, gapx=60)
    c.text("Test bench (auto power-on reset, scripted inputs, plant model)", size=16)
    c.clock("CLK")
    c.const("ONE", 1, 1)
    c.reg("ONE", "POR", 1, clr=None, label="POR")
    c.inv("POR", "RST")
    c.text("cycle counter")
    c.sub(L["inc8"], {"A": "CYC_LO", "CI": "ONE", "S": "CYC_LO_N", "CO": "CYC_C"}, label="CNT_LO")
    c.sub(L["inc8"], {"A": "CYC_HI", "CI": "CYC_C", "S": "CYC_HI_N"}, label="CNT_HI")
    c.reg("CYC_LO_N", "CYC_LO", 8, clr=None, label="CYC_LO")
    c.reg("CYC_HI_N", "CYC_HI", 8, clr=None, label="CYC_HI")
    c.join("CYC", 16, [("CYC_LO", 0, 7), ("CYC_HI", 8, 15)])
    c.text("stimulus ROM")
    c.split("CYC", 16, [("SADDR", stim_shift, stim_shift + 7)])
    c.rom("SADDR", "STIM", 8, 16, stim_words)
    c.split("STIM", 16, [("START", 0), ("DOOR", 1), ("MODE", 2, 3)])
    c.const("TEMP", 8, 0x19)
    c.text("halt after N cycles")
    c.const("STOP_LO", 8, stop_cycle & 0xFF)
    c.const("STOP_HI", 8, stop_cycle >> 8)
    c.sub(L["eq8"], {"A": "CYC_LO", "B": "STOP_LO", "EQ": "EQLO"})
    c.sub(L["eq8"], {"A": "CYC_HI", "B": "STOP_HI", "EQ": "EQHI"})
    c.gate("AND", ["EQLO", "EQHI"], "HALT_TB")
    c.newcol()
    c.text("plant model")
    if plant:
        # water: +3/cycle when VALVE_IN, -7/cycle (saturating at 0) when PUMP_OUT
        c.const("K3", 8, 3)
        c.const("KM7", 8, 0xF9)
        c.const("ZERO", 1, 0)
        c.sub(L["add8"], {"A": "WL", "B": "K3", "CI": "ZERO", "S": "WL_UP"}, label="WL+3")
        c.sub(L["add8"], {"A": "WL", "B": "KM7", "CI": "ZERO", "S": "WL_DN", "CO": "WL_NB"}, label="WL-7")
        c.sub(L["and8en"], {"D": "WL_DN", "E": "WL_NB", "Y": "WL_DNS"})
        c.sub(L["mux2_8"], {"D0": "WL", "D1": "WL_DNS", "S": "PUMP_OUT", "Y": "WL_M1"})
        c.sub(L["mux2_8"], {"D0": "WL_M1", "D1": "WL_UP", "S": "VALVE_IN", "Y": "WL_N"})
        c.split("CYC_LO", 8, [("cy0", 0), ("cy1", 1), ("cy2", 2), ("cy3", 3)])
        c.gate("AND", ["cy0", "cy1", "cy2", "cy3"], "PLANT_TICK")   # water changes every 16 cycles
        c.reg("WL_N", "WL", 8, en="PLANT_TICK", clr=None, label="WATER")
        # drum: 200 rpm when the gated motor is on, otherwise -40/cycle down to 0
        c.const("KM40", 8, 0xD8)
        c.const("K200", 8, 0xC8)
        c.sub(L["add8"], {"A": "RPM", "B": "KM40", "CI": "ZERO", "S": "RPM_DN", "CO": "RPM_NB"}, label="RPM-40")
        c.sub(L["and8en"], {"D": "RPM_DN", "E": "RPM_NB", "Y": "RPM_DNS"})
        c.sub(L["mux2_8"], {"D0": "RPM_DNS", "D1": "K200", "S": "MOTOR_ACT", "Y": "RPM_N"})
        c.reg("RPM_N", "RPM", 8, clr=None, label="DRUM")
    else:
        c.const("WL", 8, 0)
        c.const("RPM", 8, 0)
    core_system(c, L, rom_words)
    c.newcol()
    c.text("monitored outputs (tty column order)")
    for name, w in TB_COLS:
        c.outp(name, w)
    c.outp("halt", 1, net="HALT_TB")
    return c.finish_top()


def all_defs(L):
    order = ["cpu", "mmio", "regfile", "control", "hazard", "fwd", "alu8", "timer8", "safety",
             "add8", "inc8", "fa1", "ha1", "mux2_8", "mux4_8", "mux8_8", "and8en",
             "zero8", "eq8", "eq3", "dec3to8", "dec4to16"]
    return [L[k] for k in order]


def stim_from_events(events, nwords=256):
    """events: list of (start_word_index, dict(START=,DOOR=,MODE=)) applied cumulatively."""
    state = dict(START=0, DOOR=1, MODE=0)
    ev = sorted(events, key=lambda e: e[0])
    words = []
    j = 0
    for k in range(nwords):
        while j < len(ev) and ev[j][0] <= k:
            state.update(ev[j][1])
            j += 1
        words.append((state["START"] & 1) | ((state["DOOR"] & 1) << 1) | ((state["MODE"] & 3) << 2))
    return words


TESTS = {
    # name: (asm file, stim events (cycle based), shift, stop cycle)
    "t1_hazards": ("tests/t1_hazards.asm", [], 2, 60),
    "t2_branch_halt": ("tests/t2_branch_halt.asm", [], 2, 60),
    "t3_ram_reserved": ("tests/t3_ram_reserved.asm", [], 2, 70),
    "t4_timer": ("tests/t4_timer.asm", [], 2, 420),
    "t5_safety": ("tests/t5_safety.asm",
                  [(0, dict(DOOR=1, START=0)), (40, dict(DOOR=0)), (52, dict(DOOR=1)),
                   (64, dict(START=1)), (76, dict(START=0)), (88, dict(DOOR=0)),
                   (92, dict(START=1)), (100, dict(START=0)), (108, dict(DOOR=1)),
                   (120, dict(START=1)), (140, dict(START=0))], 2, 180),
    "t6_wash_e2e": ("program.asm",
                    [(0, dict(DOOR=1, START=0, MODE=0)), (32, dict(START=1)), (128, dict(START=0)),
                     (480, dict(MODE=1)),
                     (1600, dict(START=1, MODE=1)), (1696, dict(START=0)),
                     (2400, dict(MODE=0))], 4, 3600),
}


def read_prog(path):
    with open(os.path.join(ROOT, path)) as f:
        rows, _ = asm.assemble(f.read())
    return asm.words_of(rows)


def main():
    L = build_library()
    prog = read_prog("program.asm")
    top = build_main(L, prog)
    with open(os.path.join(ROOT, "washing_pipeline.circ"), "w") as f:
        f.write(project_xml([top] + all_defs(L), "main"))
    with open(os.path.join(ROOT, "program.hex"), "w") as f:
        with open(os.path.join(ROOT, "program.asm")) as g:
            f.write(asm.to_logisim_hex(asm.assemble(g.read())[0]))
    for name, (src, events, shift, stop) in TESTS.items():
        words = read_prog(src)
        ev = [(cyc >> shift, d) for cyc, d in events]
        stim = stim_from_events(ev)
        L2 = build_library()          # fresh instances (layout state is per circuit)
        tb = build_tb(L2, words, stim, shift, stop)
        with open(os.path.join(ROOT, "tests", name + ".circ"), "w") as f:
            f.write(project_xml([tb] + all_defs(L2), "tb_main"))
        if src.startswith("tests/"):
            with open(os.path.join(ROOT, src)) as g:
                hexs = asm.to_logisim_hex(asm.assemble(g.read())[0])
            with open(os.path.join(ROOT, src.replace(".asm", ".hex")), "w") as f:
                f.write(hexs)
    print("generated washing_pipeline.circ, program.hex and", len(TESTS), "test benches")


if __name__ == "__main__":
    main()
