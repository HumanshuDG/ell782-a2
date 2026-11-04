#!/usr/bin/env python3
"""show.py - pretty-print a tty table (header line required) with hex values."""
import sys
HEX = {'PC','IFID_PC','IDEX_PC','EXMEM_PC','MEMWB_PC','WB_DATA','D_ADDR','D_WDATA','DISP','ACT','T_COUNT','T_LIMIT','WL','RPM','IFID_IR'}
def v(s):
    s = s.replace(' ', '')
    return None if ('x' in s or 'E' in s) else int(s, 2)
def load(path):
    lines = open(path).read().splitlines()
    hdr = lines[0].split('\t')
    rows = []
    for ln in lines[1:]:
        rows.append({h: v(x) for h, x in zip(hdr, ln.split('\t'))})
    return hdr, rows
if __name__ == '__main__':
    path = sys.argv[1]
    cols = sys.argv[2].split(',')
    lo = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    hi = int(sys.argv[4]) if len(sys.argv) > 4 else 10**9
    hdr, rows = load(path)
    print(' '.join(f'{c[:7]:>7}' for c in cols))
    for r in rows:
        if not lo <= r['CYC'] <= hi: continue
        print(' '.join(f"{('x' if r[c] is None else (format(r[c],'X') if c in HEX else r[c])):>7}" for c in cols))
