#!/usr/bin/env python3
"""
make_reports.py - runs every test bench, checks the required properties,
stores the expected Logisim `-tty table` output for each bench and emits
LaTeX fragments used by the documents in latex/.

    python3 tools/design.py         # (re)generate the .circ files
    python3 tools/make_reports.py   # simulate, check, write tests/expected + latex/generated
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import asm        # noqa: E402
import circsim    # noqa: E402
import isa_ref    # noqa: E402

GEN = os.path.join(ROOT, "latex", "generated")
EXP = os.path.join(ROOT, "tests", "expected")
os.makedirs(GEN, exist_ok=True)
os.makedirs(EXP, exist_ok=True)

IO_NAMES = {0xF0: "IN_STATUS", 0xF1: "WATER_LEVEL", 0xF2: "TEMP", 0xF3: "DRUM_RPM",
            0xF4: "ACT", 0xF5: "DISPLAY", 0xF8: "T_COUNT", 0xF9: "T_LIMIT",
            0xFA: "T_CTRL", 0xFB: "T_STATUS"}
RESULTS = []      # (group, id, ok)


def tex(s):
    return asm.tex_escape(str(s))


def val(s):
    s = s.replace(" ", "")
    return None if ("x" in s or "E" in s) else int(s, 2)


def simulate(name):
    path = os.path.join(ROOT, "tests", name + ".circ")
    buf = io.StringIO()
    circsim.run(path, header=True, stream=buf)
    lines = buf.getvalue().splitlines()
    with open(os.path.join(EXP, name + ".txt"), "w") as f:
        f.write("\n".join(lines[1:]) + "\n")
    hdr = lines[0].split("\t")
    rows = [{h: val(x) for h, x in zip(hdr, ln.split("\t"))} for ln in lines[1:]]
    # rows are printed only on change; expand to one row per cycle
    full, last = [], None
    for r in rows:
        if last is not None:
            for c in range(last["CYC"] + 1, r["CYC"]):
                full.append(dict(last, CYC=c))
        full.append(r)
        last = r
    return full


def program(path):
    with open(os.path.join(ROOT, path)) as f:
        rows, _ = asm.assemble(f.read())
    src = {r["addr"]: " ".join(r["src"].split()) for r in rows}
    return rows, src


def at(rows, cyc):
    return rows[cyc]


def first(rows, pred, start=0):
    for r in rows[start:]:
        if pred(r):
            return r
    return None


def ok_cell(ok):
    return r"\pass" if ok else r"\fail"


# ---------------------------------------------------------------- traces
def inst(src, pc, v):
    s = tex(f"{pc:02X} {src.get(pc, '?')}")
    return r"\texttt{" + s + "}" if v else r"\bub{" + s + "}"


def fwd(x, use=True):
    return {2: "EX/MEM", 1: "MEM/WB"}.get(x, "--")


def writes(r):
    w = []
    if r["WB_WE"]:
        w.append(f"R{r['WB_RD']}$\\leftarrow${r['WB_DATA']:02X}")
    if r["D_WE"]:
        a = r["D_ADDR"]
        nm = f"RAM[{a:02X}]" if a < 0x80 else IO_NAMES.get(a, f"[{a:02X}] (ignored)")
        if 0x80 <= a < 0xF0:
            nm = f"[{a:02X}] reserved, ignored"
        w.append(tex(nm) + f"$\\leftarrow${r['D_WDATA']:02X}")
    return "; ".join(w) if w else "--"


def trace_table(rows, src, lo, hi, label):
    out = []
    for c in range(lo, hi + 1):
        r = rows[c]
        ifc = r"\textit{halted}" if r["HALTED"] else r"\texttt{" + tex(f"{r['PC']:02X} {src.get(r['PC'], '?')}") + "}"
        out.append(" & ".join([
            str(c), ifc,
            inst(src, r["IFID_PC"], r["IFID_V"]),
            inst(src, r["IDEX_PC"], r["IDEX_V"]),
            inst(src, r["EXMEM_PC"], r["EXMEM_V"]),
            inst(src, r["MEMWB_PC"], r["MEMWB_V"]),
            r"\textbf{1}" if r["STALL"] else "0",
            r"\textbf{1}" if r["FLUSH"] else "0",
            fwd(r["FWD_A"]), fwd(r["FWD_B"]), writes(r)]) + r" \\")
    with open(os.path.join(GEN, label + ".tex"), "w") as f:
        f.write("\n".join(out) + "\n")


# ---------------------------------------------------------------- validation helpers
def vrow(group, tid, stim, exp, obs, ok):
    RESULTS.append((group, tid, ok))
    return f"{tid} & {stim} & {exp} & {obs} & {ok_cell(ok)} \\\\ \\hline"


def write_rows(name, rows):
    with open(os.path.join(GEN, name + ".tex"), "w") as f:
        f.write("\n".join(rows) + "\n")


def events(rows):
    ev = []
    for r in rows:
        if r["WB_WE"]:
            ev.append(("R", r["WB_RD"], r["WB_DATA"]))
        if r["D_WE"]:
            ev.append(("M", r["D_ADDR"], r["D_WDATA"]))
    return ev


def isa_equiv(name, rows):
    prows, _ = program(f"tests/{name}.asm")
    ref, _, _ = isa_ref.run(asm.words_of(prows), strict=True)
    return events(rows) == ref, len(ref)


def stage_cyc(rows, stage, pc, v=1):
    """first cycle in which instruction pc occupies stage with given valid bit"""
    key = {"ID": ("IFID_PC", "IFID_V"), "EX": ("IDEX_PC", "IDEX_V"),
           "MEM": ("EXMEM_PC", "EXMEM_V"), "WB": ("MEMWB_PC", "MEMWB_V")}[stage]
    r = first(rows, lambda r: r[key[0]] == pc and r[key[1]] == v)
    return r["CYC"] if r else None


# ================================================================= G1
def group1():
    rows = simulate("t1_hazards")
    _, src = program("tests/t1_hazards.asm")
    trace_table(rows, src, 8, 15, "trace82")
    trace_table(rows, src, 12, 18, "trace83")
    trace_table(rows, src, 0, 24, "trace_t1_full")
    out = []
    c = stage_cyc(rows, "EX", 0x07)
    r = rows[c]
    wb = first(rows, lambda q: q["WB_WE"] and q["MEMWB_PC"] == 0x07)
    ok = r["STALL"] == 0 and r["FWD_B"] == 2 and wb["WB_DATA"] == 0xF2
    out.append(vrow(1, "1a", r"\S8.1 \texttt{ADD R1,R2; SUB R3,R1}; R1=01, R2=10, R3=03",
                    "no stall; SUB takes R1 from EX/MEM; R3=F2",
                    f"cyc {c}: stall={r['STALL']}, FwdB={fwd(r['FWD_B'])}; R3={wb['WB_DATA']:02X} (cyc {wb['CYC']})", ok))
    stalls = [q["CYC"] for q in rows if q["STALL"] and q["IFID_PC"] == 0x09]
    cex = stage_cyc(rows, "EX", 0x09)
    r = rows[cex]
    bub = rows[stalls[0] + 1] if stalls else None
    wb = first(rows, lambda q: q["WB_WE"] and q["MEMWB_PC"] == 0x09)
    ok = (len(stalls) == 1 and bub["IDEX_V"] == 0 and bub["PC"] == rows[stalls[0]]["PC"]
          and bub["IFID_PC"] == 0x09 and r["FWD_B"] == 1 and wb["WB_DATA"] == 0xF5)
    out.append(vrow(1, "1b", r"\S8.2 \texttt{LD R1,[R2]; ADD R3,R1}; RAM[10]=03",
                    "exactly 1 stall cycle; PC and IF/ID hold; bubble (V=0) in EX; R1 from MEM/WB; R3=F5",
                    f"stall cycles {stalls}; cyc {stalls[0]+1}: IDEX.V={bub['IDEX_V']}, PC held at {bub['PC']:02X}; "
                    f"cyc {cex}: FwdB={fwd(r['FWD_B'])}; R3={wb['WB_DATA']:02X}", ok))
    c = stage_cyc(rows, "EX", 0x0C)
    r = rows[c]
    st = first(rows, lambda q: q["D_WE"] and q["EXMEM_PC"] == 0x0C)
    ok = r["FWD_A"] == 2 and st["D_WDATA"] == 0x1E and st["D_ADDR"] == 0x20 and rows[c]["MEMWB_PC"] == 0x0A
    out.append(vrow(1, "1c", r"\S8.3 \texttt{ADD R1,R2; SUB R1,R3; ST R1,[R4]}",
                    "store data from youngest writer (SUB, EX/MEM) = 1E, not older ADD (MEM/WB) = 13",
                    f"cyc {c}: FwdA={fwd(r['FWD_A'])} while MEM/WB holds pc {r['MEMWB_PC']:02X}; "
                    f"RAM[{st['D_ADDR']:02X}]$\\leftarrow${st['D_WDATA']:02X} (cyc {st['CYC']})", ok))
    last = rows[-1]
    r6 = [q for q in rows if q["WB_WE"] and q["WB_RD"] == 6]
    ok = last["DISP"] == 0x1E and last["HALTED"] == 1 and not r6
    out.append(vrow(1, "1d", r"read-back \texttt{LD R5,[R4]; ST R5,[DISPLAY]; HALT; LDI R6,FF}",
                    "DISPLAY=1E; HALT stops machine; younger LDI R6 never writes",
                    f"DISPLAY={last['DISP']:02X}; HALTED={last['HALTED']}; writes to R6: {len(r6)}", ok))
    eq, n = isa_equiv("t1_hazards", rows)
    out.append(vrow(1, "1e", "whole program vs. ISA reference model",
                    "identical ordered list of register/memory writes",
                    f"{n} writes, {'identical' if eq else 'MISMATCH'}", eq))
    write_rows("val_g1", out)


# ================================================================= G2
def group2():
    rows = simulate("t2_branch_halt")
    _, src = program("tests/t2_branch_halt.asm")
    trace_table(rows, src, 5, 14, "trace84")
    trace_table(rows, src, 0, 26, "trace_t2_full")
    out = []
    c = stage_cyc(rows, "EX", 0x06)
    r = rows[c]
    nxt = rows[c + 1]
    stv = first(rows, lambda q: q["EXMEM_PC"] == 0x07 and q["CYC"] > c)
    act_writes = [q["CYC"] for q in rows if q["D_WE"] and q["D_ADDR"] == 0xF4]
    ok = (r["FLUSH"] == 1 and r["FWD_A"] == 2 and nxt["IFID_V"] == 0 and nxt["IDEX_V"] == 0
          and stv["EXMEM_V"] == 0 and not act_writes and all(q["ACT"] == 0 for q in rows))
    out.append(vrow(2, "2a", r"\S8.4 \texttt{SUB R1,R1; BEQZ R1,T; ST R2,[Rvalve]; ADD R3,R4}; R2=21, Rvalve=F4",
                    "branch taken in EX (R1 via EX/MEM); IF/ID and ID/EX invalidated; wrong-path store reaches MEM with V=0; VALVE/ACT never written",
                    f"cyc {c}: flush={r['FLUSH']}, FwdA={fwd(r['FWD_A'])}; cyc {c+1}: IFID.V={nxt['IFID_V']}, IDEX.V={nxt['IDEX_V']}; "
                    f"cyc {stv['CYC']}: ST in MEM V={stv['EXMEM_V']}; valid stores to F4: {len(act_writes)}; ACT=00 throughout", ok))
    r3 = [q["WB_DATA"] for q in rows if q["WB_WE"] and q["WB_RD"] == 3]
    d7 = first(rows, lambda q: q["DISP"] == 0x07)
    ok = r3 == [0x07] and d7 is not None
    out.append(vrow(2, "2b", r"wrong-path \texttt{ADD R3,R4}", "R3 keeps 07 (DISPLAY shows 07)",
                    f"writes to R3: {', '.join('%02X' % x for x in r3)} (only the LDI); DISPLAY=07 at cyc {d7['CYC']}", ok))
    c9 = stage_cyc(rows, "EX", 0x09)
    ok = rows[c9]["FLUSH"] == 0
    out.append(vrow(2, "2c", r"\texttt{BNEZ R1,bad} with R1=0", "not taken, no flush",
                    f"cyc {c9}: flush={rows[c9]['FLUSH']}", ok))
    h_wrong = [pc for pc in (0x0B, 0x0F, 0x10) if stage_cyc(rows, "EX", pc, 1) is not None]
    first_halt = first(rows, lambda q: q["HALTED"] == 1)
    daa = first(rows, lambda q: q["DISP"] == 0xAA)
    ok = not h_wrong and daa is not None and first_halt["CYC"] > daa["CYC"] - 1 and \
        rows[first_halt["CYC"] - 1]["IDEX_PC"] == 0x13
    out.append(vrow(2, "2d", r"wrong-path \texttt{HALT} at 0B (after taken BNEZ) and 0F/10 (after JMP)",
                    "flushed before EX; execution continues to DISPLAY=AA",
                    f"wrong-path HALTs valid in EX: {len(h_wrong)}; DISPLAY=AA at cyc {daa['CYC']}; "
                    f"HALTED first at cyc {first_halt['CYC']} by HALT @13", ok))
    killed = stage_cyc(rows, "MEM", 0x14, 1) is None
    last = rows[-1]
    ok = killed and last["ACT"] == 0 and last["HALTED"] == 1 and last["PC"] == rows[first_halt["CYC"]]["PC"]
    out.append(vrow(2, "2e", r"real \texttt{HALT} followed by \texttt{ST R2,[R4]}",
                    "younger store killed; fetch stops; remains halted",
                    f"store @14 valid in MEM: {not killed}; ACT={last['ACT']:02X}; PC frozen at {last['PC']:02X}", ok))
    eq, n = isa_equiv("t2_branch_halt", rows)
    out.append(vrow(2, "2f", "whole program vs. ISA reference model", "identical write sequence",
                    f"{n} writes, {'identical' if eq else 'MISMATCH'}", eq))
    write_rows("val_g2", out)


# ================================================================= G3
def group3():
    rows = simulate("t3_ram_reserved")
    out = []
    ramw = [(q["CYC"], q["D_ADDR"], q["D_WDATA"]) for q in rows if q["RAM_WE"]]
    ok = [(a, d) for _, a, d in ramw] == [(0x00, 0x5A), (0x6F, 0x33), (0x7F, 0xA5)]
    out.append(vrow(3, "3a", r"\texttt{ST} to RAM 00, 6F, 7F", "RAM write-enable exactly 3 times",
                    "RAM\\_WE at " + ", ".join(f"cyc {c} [{a:02X}]$\\leftarrow${d:02X}" for c, a, d in ramw), ok))
    bad = [q for q in rows if q["D_WE"] and q["D_ADDR"] in (0x80, 0xEF, 0xFF, 0xF0)]
    side = [q["CYC"] for q in bad if q["RAM_WE"]]
    acts = {q["ACT"] for q in rows}
    disp_before = {q["DISP"] for q in rows if q["CYC"] <= bad[-1]["CYC"] + 1}
    ok = len(bad) == 4 and not side and acts == {0} and disp_before == {0}
    out.append(vrow(3, "3b", r"\texttt{ST 77} to 80, EF (reserved), FF (unimpl.), F0 (read-only)",
                    "no RAM write (no aliasing), no latch change",
                    f"{len(bad)} stores seen on the bus, RAM\\_WE during them: {len(side)}; ACT/DISPLAY unchanged", ok))
    regs = {}
    for q in rows:
        if q["WB_WE"]:
            regs[q["WB_RD"]] = q["WB_DATA"]
    exp = {6: 0xA5, 7: 0x5A, 1: 0x33}
    ok = all(regs.get(k) == v for k, v in exp.items())
    out.append(vrow(3, "3c", "loads from 7F, 00, 6F after the reserved stores",
                    "R6=A5, R7=5A, R1=33 (unchanged)",
                    f"R6={regs[6]:02X}, R7={regs[7]:02X}, R1={regs[1]:02X}", ok))
    exp = {0: 0, 3: 0, 5: 0}
    ok = all(regs.get(k) == v for k, v in exp.items())
    out.append(vrow(3, "3d", "loads from 80, EF (reserved) and F7 (unimplemented)", "read as 00",
                    f"R0={regs[0]:02X}, R3={regs[3]:02X}, R5={regs[5]:02X}", ok))
    eq, n = isa_equiv("t3_ram_reserved", rows)
    out.append(vrow(3, "3e", "whole program vs. ISA reference model", "identical write sequence",
                    f"{n} writes, {'identical' if eq else 'MISMATCH'}", eq))
    write_rows("val_g3", out)


# ================================================================= G4
def group4():
    rows = simulate("t4_timer")
    out = []
    ctrl = [q["CYC"] for q in rows if q["D_WE"] and q["D_ADDR"] == 0xFA]
    c1 = ctrl[0]
    m1 = first(rows, lambda q: q["T_MATCH"] == 1)
    ok = rows[c1 + 1]["T_COUNT"] == 0 and rows[c1 + 1]["T_EN"] == 1 and m1["T_COUNT"] == 6 \
        and rows[m1["CYC"] - 1]["T_MATCH"] == 0 and m1["CYC"] == c1 + 7
    out.append(vrow(4, "4a", "LIMIT=6, CTRL=03 (clear+enable)",
                    "COUNT=0 after the CTRL edge, +1 per clock; MATCH set on the edge where COUNT becomes 6",
                    f"CTRL write cyc {c1}; COUNT=00 at cyc {c1+1}; MATCH=1 at cyc {m1['CYC']} with COUNT={m1['T_COUNT']:02X}", ok))
    st = [q["CYC"] for q in rows if q["STALL"] and q["T_EN"]]
    inc_ok = all((rows[c + 1]["T_COUNT"] - rows[c]["T_COUNT"]) % 256 == 1 for c in st
                 if rows[c + 1]["T_EN"] and not (rows[c]["D_WE"] and rows[c]["D_ADDR"] == 0xFA))
    out.append(vrow(4, "4b", "polling loops \\texttt{LD R2,[T\\_STATUS]; BEQZ R2} (load-use stall)",
                    "COUNT increments during every stall cycle", f"stall cycles {st[:6]}{'...' if len(st) > 6 else ''}: COUNT +1 each", inc_ok and len(st) > 0))
    c2 = ctrl[1]
    sticky = all(q["T_MATCH"] == 1 for q in rows[m1["CYC"]:c2 + 1])
    over = rows[c2]["T_COUNT"]
    ok = sticky and over > 6
    out.append(vrow(4, "4c", "keep running after MATCH", "MATCH stays 1 (sticky) while COUNT passes LIMIT",
                    f"MATCH=1 from cyc {m1['CYC']} to {c2}, COUNT reached {over:02X}", ok))
    m2 = first(rows, lambda q: q["T_MATCH"] == 1, c2 + 1)
    ok = rows[c2 + 1]["T_COUNT"] == 0 and rows[c2 + 1]["T_MATCH"] == 0 and m2["T_COUNT"] == 10 \
        and rows[c2]["T_LIMIT"] == 10
    out.append(vrow(4, "4d", "re-arm: LIMIT=0A, CTRL=03",
                    "clear wins: COUNT=0, MATCH=0 on the CTRL edge; MATCH again at COUNT=0A",
                    f"cyc {c2+1}: COUNT={rows[c2+1]['T_COUNT']:02X}, MATCH={rows[c2+1]['T_MATCH']}; MATCH at cyc {m2['CYC']} (COUNT={m2['T_COUNT']:02X})", ok))
    lw = [q for q in rows if q["D_WE"] and q["D_ADDR"] == 0xF9]
    lw3 = lw[3]
    r_after = rows[lw3["CYC"] + 1]
    ok = (r_after["T_LIMIT"] == r_after["T_COUNT"] and r_after["T_MATCH"] == 0 and r_after["T_EN"] == 0
          and rows[-1]["DISP"] == 0)
    out.append(vrow(4, "4e", "timer stopped (CTRL=00), then LIMIT := current COUNT",
                    "no retroactive MATCH", f"cyc {r_after['CYC']}: COUNT={r_after['T_COUNT']:02X}, "
                    f"LIMIT={r_after['T_LIMIT']:02X}, MATCH={r_after['T_MATCH']}; DISPLAY(MATCH)={rows[-1]['DISP']:02X}", ok))
    wrap = first(rows, lambda q: q["T_COUNT"] == 0 and rows[q["CYC"] - 1]["T_COUNT"] == 0xFF, 1)
    m3 = first(rows, lambda q: q["T_MATCH"] == 1, lw3["CYC"] + 2)
    ok = wrap is not None and wrap["HALTED"] == 1 and m3 is not None and m3["T_COUNT"] == 3 and m3["CYC"] > wrap["CYC"]
    out.append(vrow(4, "4f", "LIMIT=03, CTRL=01 (enable, no clear), then \\texttt{HALT}",
                    "timer keeps ticking while halted; COUNT wraps FF$\\rightarrow$00; MATCH at COUNT=03",
                    f"wrap at cyc {wrap['CYC']} (HALTED={wrap['HALTED']}); MATCH at cyc {m3['CYC']} (COUNT={m3['T_COUNT']:02X})", ok))
    write_rows("val_g4", out)
    # small timer trace
    lines = [r"\begin{tabular}{rcccccl}\toprule Cyc & STALL & HALTED & EN & COUNT & LIMIT & MATCH \\ \midrule"]
    for c in list(range(c1 - 1, c1 + 9)):
        q = rows[c]
        lines.append(f"{c} & {q['STALL']} & {q['HALTED']} & {q['T_EN']} & {q['T_COUNT']:02X} & {q['T_LIMIT']:02X} & {q['T_MATCH']} \\\\")
    lines.append(r"\midrule \multicolumn{7}{c}{\dots} \\ \midrule")
    for c in range(wrap["CYC"] - 2, m3["CYC"] + 2):
        q = rows[c]
        lines.append(f"{c} & {q['STALL']} & {q['HALTED']} & {q['T_EN']} & {q['T_COUNT']:02X} & {q['T_LIMIT']:02X} & {q['T_MATCH']} \\\\")
    lines.append(r"\bottomrule\end{tabular}")
    write_rows("timer_trace", lines)


# ================================================================= G5
def group5():
    rows = simulate("t5_safety")
    out = []
    on = first(rows, lambda q: q["MOTOR_ACT"] == 1)
    out.append(vrow(5, "5a", "DOOR=1, software writes ACT=24 (LOCK+MOTOR\\_EN)", "ActualMotorEnable=1",
                    f"cyc {on['CYC']}: ACT={on['ACT']:02X}, actual={on['MOTOR_ACT']}", True))
    op = first(rows, lambda q: q["DOOR"] == 0)
    nxt = rows[op["CYC"] + 1]
    ok = op["MOTOR_ACT"] == 0 and op["TRIP"] == 0 and (op["ACT"] >> 2) & 1 == 1 and nxt["TRIP"] == 1
    out.append(vrow(5, "5b", f"open door at cyc {op['CYC']} (request still 1)",
                    "actual motor drops in the same cycle (combinational); TRIP latched at next edge",
                    f"cyc {op['CYC']}: MOTOR\\_EN req={(op['ACT']>>2)&1}, actual={op['MOTOR_ACT']}, TRIP={op['TRIP']}; cyc {nxt['CYC']}: TRIP={nxt['TRIP']}", ok))
    cl = first(rows, lambda q: q["DOOR"] == 1, op["CYC"])
    seg = [q for q in rows if cl["CYC"] <= q["CYC"] < cl["CYC"] + 10]
    ok = all(q["MOTOR_ACT"] == 0 and q["TRIP"] == 1 and (q["ACT"] >> 2) & 1 for q in seg)
    out.append(vrow(5, "5c", f"re-close door at cyc {cl['CYC']}, request still 1",
                    "no automatic restart", f"cyc {cl['CYC']}-{cl['CYC']+9}: actual=0, TRIP=1, request=1", ok))
    s1 = first(rows, lambda q: q["START"] == 1)
    ok = s1["TRIP"] == 1 and rows[s1["CYC"] + 1]["TRIP"] == 1 and (s1["ACT"] >> 2) & 1 == 1
    out.append(vrow(5, "5d", f"START 0$\\rightarrow$1 at cyc {s1['CYC']} while MOTOR\\_EN request still active",
                    "not a valid re-arm: TRIP stays 1", f"cyc {s1['CYC']+1}: TRIP={rows[s1['CYC']+1]['TRIP']}", ok))
    s2 = first(rows, lambda q: q["START"] == 1 and q["DOOR"] == 0)
    clr = first(rows, lambda q: (q["ACT"] >> 2) & 1 == 0, s1["CYC"])
    ok = s2 is not None and rows[s2["CYC"] + 1]["TRIP"] == 1 and (s2["ACT"] >> 2) & 1 == 0
    out.append(vrow(5, "5e", f"software clears request (cyc {clr['CYC']}); START edge with door open (cyc {s2['CYC']})",
                    "not a valid re-arm: TRIP stays 1", f"cyc {s2['CYC']+1}: TRIP={rows[s2['CYC']+1]['TRIP']}", ok))
    s3 = first(rows, lambda q: q["START"] == 1 and q["DOOR"] == 1 and q["CYC"] > s2["CYC"] and rows[q["CYC"] - 1]["START"] == 0)
    rearm = rows[s3["CYC"] + 1]
    run2 = first(rows, lambda q: q["MOTOR_ACT"] == 1, s3["CYC"])
    ok = rearm["TRIP"] == 0 and run2 is not None and all(q["MOTOR_ACT"] == 0 for q in rows[op["CYC"]:run2["CYC"]])
    out.append(vrow(5, "5f", f"door closed, request off, new START edge at cyc {s3['CYC']}",
                    "TRIP cleared; motor runs only after software requests it again",
                    f"cyc {rearm['CYC']}: TRIP={rearm['TRIP']}; actual=1 again at cyc {run2['CYC']} (ACT={run2['ACT']:02X}); "
                    f"DISPLAY={rows[-1]['DISP']:02X}", ok))
    write_rows("val_g5", out)
    # compact event table
    lines = [r"\begin{tabular}{rccccccl}\toprule Cyc & DOOR & START & ACT & MOTOR\_EN req & Actual & TRIP & note \\ \midrule"]
    prev = None
    for q in rows:
        key = (q["DOOR"], q["START"], q["ACT"], q["MOTOR_ACT"], q["TRIP"])
        if key != prev:
            lines.append(f"{q['CYC']} & {q['DOOR']} & {q['START']} & {q['ACT']:02X} & {(q['ACT']>>2)&1} & {q['MOTOR_ACT']} & {q['TRIP']} & \\\\")
            prev = key
    lines.append(r"\bottomrule\end{tabular}")
    write_rows("safety_trace", lines)


# ================================================================= G6
def group6():
    rows = simulate("t6_wash_e2e")
    global PSRC
    PSRC = program("program.asm")[1]
    out = []

    def run_info(start_cyc, end_cyc):
        seg = rows[start_cyc:end_cyc]
        lock = first(seg, lambda q: q["ACT"] == 0x20)
        fill_on = first(seg, lambda q: q["ACT"] == 0x21)
        fill_off = first(seg, lambda q: q["ACT"] == 0x20 and q["CYC"] > fill_on["CYC"])
        samples = []
        for i in range(fill_on["CYC"], fill_off["CYC"]):
            q, p = rows[i], rows[i - 1]
            if q["WB_WE"] and p["EXMEM_V"] and p["D_ADDR"] == 0xF1 and p["EXMEM_PC"] == q["MEMWB_PC"] \
                    and PSRC[q["MEMWB_PC"]].startswith("LD "):
                samples.append(q["WB_DATA"])
        wash = [q for q in seg if q["ACT"] in (0x24, 0x34)]
        dirs = sum(1 for i in range(1, len(wash)) if wash[i]["ACT"] != wash[i - 1]["ACT"])
        wash_lim = wash[0]["T_LIMIT"]
        wash_end = first(seg, lambda q: q["ACT"] == 0x20 and q["CYC"] > wash[-1]["CYC"])
        m_at_end = rows[wash[-1]["CYC"]]
        drain = [q for q in seg if q["ACT"] == 0x28]
        dsamples = []
        for i in range(drain[0]["CYC"], drain[-1]["CYC"] + 1):
            q, p = rows[i], rows[i - 1]
            if q["WB_WE"] and p["EXMEM_V"] and p["D_ADDR"] == 0xF1 and p["EXMEM_PC"] == q["MEMWB_PC"] \
                    and PSRC[q["MEMWB_PC"]].startswith("LD "):
                dsamples.append(q["WB_DATA"])
        spin = [q for q in seg if q["ACT"] == 0x2C]
        spin_lim = spin[0]["T_LIMIT"]
        spin_start_count = spin[0]["T_COUNT"]
        spin_match = first(seg, lambda q: q["T_MATCH"] == 1 and q["CYC"] >= spin[0]["CYC"])
        stop = first(seg, lambda q: q["ACT"] == 0x20 and q["CYC"] > spin[-1]["CYC"])
        done = first(seg, lambda q: q["ACT"] == 0x40 and q["CYC"] > stop["CYC"])
        rpm_zero = first(seg, lambda q: q["RPM"] == 0 and q["CYC"] > stop["CYC"])
        disp_done = first(seg, lambda q: (q["DISP"] & 0x0F) == 8 and q["CYC"] >= done["CYC"])
        return dict(lock=lock, fill_on=fill_on, fill_off=fill_off, samples=samples, dirs=dirs,
                    wash_lim=wash_lim, wash_end=wash_end, wash_match=m_at_end, drain=drain,
                    dsamples=dsamples, spin_lim=spin_lim, spin=spin, spin_match=spin_match,
                    spin_start_count=spin_start_count, stop=stop, done=done, rpm_zero=rpm_zero,
                    disp_done=disp_done, wl_close=fill_off["WL"])

    s2 = first(rows, lambda q: q["START"] == 1 and q["MODE"] == 1)
    runs = [("NORMAL (MODE=00)", 0, s2["CYC"], 100, 64, 32, 0x08),
            ("HEAVY (MODE=01)", s2["CYC"], len(rows), 160, 96, 48, 0x18)]
    timeline = []
    for (title, a, b, tgt, wl, sl, dcode) in runs:
        I = run_info(a, b)
        n = "6a" if a == 0 else "6g"
        crossed = [x for x in I["samples"] if x >= tgt]
        below = [x for x in I["samples"] if x < tgt]
        ok = crossed == [I["samples"][-1]] and I["samples"][-1] != tgt and below and I["wl_close"] == I["samples"][-1]
        out.append(vrow(6, n, f"{title}: START=1, DOOR=1; plant +3 per 16 cycles",
                        f"fill until WATER\\_LEVEL $\\geq$ {tgt} (unsigned) although reading jumps past {tgt}",
                        f"last samples {', '.join(str(x) for x in I['samples'][-4:])}; valve closed at cyc {I['fill_off']['CYC']} "
                        f"with WATER\\_LEVEL={I['wl_close']}", ok))
        ok = I["wash_lim"] == wl and I["dirs"] >= 3 and I["wash_match"]["T_MATCH"] == 1
        out.append(vrow(6, n[:1] + chr(ord(n[1]) + 1),
                        "wash phase", f"LIMIT={wl}; motor direction alternates; motor off at MATCH",
                        f"LIMIT={I['wash_lim']}; DIR changed {I['dirs']} times; motor off at cyc {I['wash_end']['CYC']} "
                        f"(COUNT={I['wash_match']['T_COUNT']}, MATCH={I['wash_match']['T_MATCH']})", ok))
        ok = I["dsamples"][-1] <= 10 and all(x > 10 for x in I["dsamples"][:-1])
        out.append(vrow(6, n[:1] + chr(ord(n[1]) + 2), "drain phase (plant $-7$ per 16 cycles)",
                        "pump until WATER\\_LEVEL $\\leq$ 10 (unsigned)",
                        f"samples \\dots {', '.join(str(x) for x in I['dsamples'][-3:])}; spin starts cyc {I['spin'][0]['CYC']}", ok))
        ok = I["spin_lim"] == sl and I["spin_start_count"] <= 2 and I["spin_match"]["T_COUNT"] == sl
        out.append(vrow(6, n[:1] + chr(ord(n[1]) + 3), "spin phase", f"timer cleared/re-armed, LIMIT={sl}, MATCH at {sl}",
                        f"LIMIT={I['spin_lim']}, COUNT={I['spin_start_count']} at spin start, MATCH at cyc {I['spin_match']['CYC']} (COUNT={I['spin_match']['T_COUNT']})", ok))
        ok = (I["done"]["CYC"] > I["rpm_zero"]["CYC"] and I["disp_done"]["DISP"] == dcode
              and I["done"]["ACT"] == 0x40)
        out.append(vrow(6, n[:1] + chr(ord(n[1]) + 4), "completion",
                        f"all actuators off; unlock only after drum RPM=0; BUZZER=1; DISPLAY={dcode:02X}",
                        f"motor/pump off cyc {I['stop']['CYC']}; RPM=0 cyc {I['rpm_zero']['CYC']}; ACT=40 (unlock+buzzer) cyc {I['done']['CYC']}; "
                        f"DISPLAY={I['disp_done']['DISP']:02X}", ok))
        timeline.append((title, I))
    # MODE change during a run
    mchg = [q["CYC"] for q in rows[1:] if q["MODE"] != rows[q["CYC"] - 1]["MODE"]]
    r1_end, r2_start = timeline[0][1]["done"]["CYC"], timeline[1][1]["lock"]["CYC"]
    in_run1 = any(timeline[0][1]["lock"]["CYC"] < c < r1_end for c in mchg)
    in_run2 = any(r2_start < c < timeline[1][1]["done"]["CYC"] for c in mchg)
    ok = in_run1 and in_run2 and all(r[2] for r in RESULTS if r[0] == 6)
    out.append(vrow(6, "6m", f"MODE changed during run 1 (cyc {mchg[0]}) and run 2 (cyc {mchg[-1]})",
                    "parameters of the running cycle unchanged",
                    "run 1 still used target 100 / LIMIT 64 / 32; run 2 still used 160 / 96 / 48 (rows 6a--6k)", ok))
    write_rows("val_g6", out)
    lines = [r"\begin{tabular}{lrr}\toprule Event & NORMAL & HEAVY \\ \midrule"]
    A, B = timeline[0][1], timeline[1][1]
    for lab, key in [("DOOR\\_LOCK commanded (START accepted)", "lock"), ("VALVE\\_IN on", "fill_on"),
                     ("VALVE\\_IN off", "fill_off"), ("wash motor off (MATCH)", "wash_end"),
                     ("spin start", None), ("spin MATCH", "spin_match"), ("motor/pump off", "stop"),
                     ("drum stopped (RPM=0)", "rpm_zero"), ("unlock + BUZZER", "done")]:
        if key is None:
            lines.append(f"{lab} & {A['spin'][0]['CYC']} & {B['spin'][0]['CYC']} \\\\")
        else:
            lines.append(f"{lab} & {A[key]['CYC']} & {B[key]['CYC']} \\\\")
    lines.append(f"water level at valve close & {A['wl_close']} & {B['wl_close']} \\\\")
    lines.append(f"last drain sample & {A['dsamples'][-1]} & {B['dsamples'][-1]} \\\\")
    lines.append(r"\bottomrule\end{tabular}")
    write_rows("wash_timeline", lines)


# ================================================================= listing
def listings():
    for name, path in [("listing_program", "program.asm"), ("listing_t1", "tests/t1_hazards.asm"),
                       ("listing_t2", "tests/t2_branch_halt.asm"), ("listing_t3", "tests/t3_ram_reserved.asm"),
                       ("listing_t4", "tests/t4_timer.asm"), ("listing_t5", "tests/t5_safety.asm")]:
        rows, syms = program(path)[0], None
        with open(os.path.join(GEN, name + ".tex"), "w") as f:
            f.write(asm.listing_tex(rows))
    rows, _ = program("program.asm")
    with open(os.path.join(ROOT, "program_listing.txt"), "w") as f:
        f.write(asm.listing_text(rows))


def uninit_check():
    rows, _ = program("program.asm")
    words = asm.words_of(rows)
    ok_all = True
    for trip in (False, True):
        st = {"act": 0, "n": 0}

        def rd(a):
            st["n"] += 1
            if a == 0xF0:
                s = 0x03 if st["n"] < 400 else 0x02
                if trip and st["act"] & 0x04:
                    s |= 0x10
                return s
            if a == 0xF1:
                return 200 if st["act"] & 1 else 0
            if a == 0xFB:
                return 1
            return 0

        def wr(a, v):
            if a == 0xF4:
                st["act"] = v
        try:
            isa_ref.run(words, max_steps=6000, io_read=rd, io_write=wr, strict=True)
        except isa_ref.Uninit as e:
            print("UNINITIALISED READ:", e)
            ok_all = False
    return ok_all


def main():
    group1(); group2(); group3(); group4(); group5(); group6()
    listings()
    un = uninit_check()
    with open(os.path.join(GEN, "summary.tex"), "w") as f:
        npass = sum(1 for _, _, ok in RESULTS if ok)
        f.write(f"{npass} of {len(RESULTS)} checks passed")
    print(f"checks: {sum(1 for r in RESULTS if r[2])}/{len(RESULTS)} passed; uninitialised-state check: {'OK' if un else 'FAIL'}")
    for g, t, ok in RESULTS:
        if not ok:
            print("  FAILED:", t)


if __name__ == "__main__":
    main()
