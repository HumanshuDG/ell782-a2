#!/usr/bin/env python3
"""events.py - list architectural write events (register WB, data-memory/IO stores) from a tty table."""
import sys
sys.path.insert(0, __import__('os').path.dirname(__file__))
from show import load
hdr, rows = load(sys.argv[1])
for r in rows:
    ev = []
    if r['WB_WE']:
        ev.append(f"R{r['WB_RD']} <- {r['WB_DATA']:02X}  (pc {r['MEMWB_PC']:02X})")
    if r['D_WE']:
        ev.append(f"MEM[{r['D_ADDR']:02X}] <- {r['D_WDATA']:02X}  (pc {r['EXMEM_PC']:02X})")
    if ev:
        print(f"cyc {r['CYC']:4d}: " + " ; ".join(ev))
