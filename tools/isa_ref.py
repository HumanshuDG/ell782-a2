#!/usr/bin/env python3
"""
isa_ref.py - instruction-level (non-pipelined) reference model of the WM-8 ISA.

Used to cross-check that the pipelined circuit produces exactly the same
ordered sequence of architectural writes (register write-backs and data
stores) as the sequential ISA semantics, i.e. that forwarding, stalls and
flushes are transparent to software.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asm


class Uninit(Exception):
    pass


def run(words, max_steps=10000, io_read=lambda a: 0, strict=False, io_write=lambda a, v: None):
    """strict=True: registers/RAM start undefined and any read of an undefined
    value raises Uninit (checks 'program must not use uninitialised state')."""
    R = [None if strict else 0] * 8
    ram = [None if strict else 0] * 128
    pc = 0
    events = []           # ('R', reg, val) / ('M', addr, val)
    USES_A = {0x3, 0x4, 0x5, 0x7, 0x8, 0x9, 0xA, 0xC}
    USES_B = {0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0xC}
    for _ in range(max_steps):
        w = words[pc]
        op, ra, rb, imm = w >> 12, (w >> 9) & 7, (w >> 6) & 7, w & 0xFF
        npc = (pc + 1) & 0xFF
        if (op in USES_A and R[ra] is None) or (op in USES_B and R[rb] is None):
            raise Uninit(f"pc {pc:02X}: read of uninitialised register")
        if op == 0x6 and R[rb] < 0x80 and ram[R[rb]] is None:
            raise Uninit(f"pc {pc:02X}: read of uninitialised RAM[{R[rb]:02X}]")

        def wr(r, v):
            R[r] = v & 0xFF
            events.append(("R", r, v & 0xFF))
        if op == 0x1:
            wr(ra, imm)
        elif op == 0x2:
            wr(ra, R[rb])
        elif op == 0x3:
            wr(ra, R[ra] + R[rb])
        elif op == 0x4:
            wr(ra, R[ra] - R[rb])
        elif op == 0x5:
            wr(ra, R[ra] & R[rb])
        elif op == 0x6:
            a = R[rb]
            v = ram[a] if a < 0x80 else (io_read(a) if a >= 0xF0 else 0)
            wr(ra, v)
        elif op == 0x7:
            events.append(("M", R[rb], R[ra]))
            if R[rb] < 0x80:
                ram[R[rb]] = R[ra]
            else:
                io_write(R[rb], R[ra])
        elif op == 0x8:
            wr(ra, R[ra] + imm)
        elif op == 0x9:
            if R[ra] == 0:
                npc = imm
        elif op == 0xA:
            if R[ra] != 0:
                npc = imm
        elif op == 0xB:
            npc = imm
        elif op == 0xC:
            wr(ra, 1 if R[ra] >= R[rb] else 0)
        elif op == 0xF:
            break
        pc = npc
    return events, R, ram


if __name__ == "__main__":
    with open(sys.argv[1]) as f:
        rows, _ = asm.assemble(f.read())
    ev, R, ram = run(asm.words_of(rows))
    for e in ev:
        print(e)
    print("final regs:", " ".join(f"R{i}={v:02X}" for i, v in enumerate(R)))
