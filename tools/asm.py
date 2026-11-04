#!/usr/bin/env python3
"""
asm.py - tiny two-pass assembler for the WM-8 washing-machine microcontroller ISA.

Hand encoding is allowed by the assignment; this script only automates the
same table-driven encoding so the listing/hex files are consistent.

Instruction formats (16 bit):
  R : [15:12] op | [11:9] ra | [8:6] rb | [5:0] 000000 (reserved, ignored)
  I : [15:12] op | [11:9] ra | [8] 0 (reserved, ignored) | [7:0] imm8/target
  N : [15:12] op | [11:0] 0 (reserved, ignored)

Usage:
  python3 asm.py program.asm  -o program.hex  [--listing listing.txt] [--tex listing.tex]
"""
import re
import sys
import argparse

OPCODES = {
    # mnemonic: (opcode, format, operand-shape)
    "NOP":  (0x0, "N", ""),
    "LDI":  (0x1, "I", "r,i"),
    "MOV":  (0x2, "R", "r,r"),
    "ADD":  (0x3, "R", "r,r"),
    "SUB":  (0x4, "R", "r,r"),
    "AND":  (0x5, "R", "r,r"),
    "LD":   (0x6, "R", "r,[r]"),
    "ST":   (0x7, "R", "r,[r]"),
    "ADDI": (0x8, "I", "r,i"),
    "BEQZ": (0x9, "I", "r,t"),
    "BNEZ": (0xA, "I", "r,t"),
    "JMP":  (0xB, "I", "t"),
    "SGEU": (0xC, "R", "r,r"),   # custom: Rd <- (Rd >=u Rs) ? 1 : 0
    "HALT": (0xF, "N", ""),
}


class AsmError(Exception):
    pass


def parse_int(tok, symbols):
    tok = tok.strip()
    if tok in symbols:
        return symbols[tok]
    neg = tok.startswith("-")
    t = tok[1:] if neg else tok
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", t):
        v = int(t, 16)
    elif re.fullmatch(r"0[bB][01]+", t):
        v = int(t, 2)
    elif re.fullmatch(r"[0-9]+", t):
        v = int(t, 10)
    else:
        raise AsmError(f"bad number or unknown symbol '{tok}'")
    v = -v if neg else v
    if not -128 <= v <= 255:
        raise AsmError(f"value {tok} does not fit in 8 bits")
    return v & 0xFF


def parse_reg(tok):
    m = re.fullmatch(r"[rR]([0-7])", tok.strip())
    if not m:
        raise AsmError(f"bad register '{tok}'")
    return int(m.group(1))


def strip_comment(line):
    return line.split(";", 1)[0].rstrip()


def assemble(text):
    """Returns (rows, symbols). rows = list of dicts: addr, word, src, label, comment."""
    symbols = {}
    items = []          # (addr, mnemonic, operands, src, label, comment, lineno)
    pc = 0
    pending_labels = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        comment = raw.split(";", 1)[1].strip() if ";" in raw else ""
        line = strip_comment(raw).strip()
        if not line:
            continue
        m = re.match(r"^\.equ\s+([A-Za-z_]\w*)\s*,\s*(\S+)$", line)
        if m:
            symbols[m.group(1)] = parse_int(m.group(2), symbols)
            continue
        m = re.match(r"^\.org\s+(\S+)$", line)
        if m:
            pc = parse_int(m.group(1), symbols)
            continue
        while True:
            m = re.match(r"^([A-Za-z_]\w*)\s*:\s*(.*)$", line)
            if not m:
                break
            lab = m.group(1)
            if lab in symbols:
                raise AsmError(f"line {lineno}: duplicate label {lab}")
            symbols[lab] = pc
            pending_labels.append(lab)
            line = m.group(2).strip()
        if not line:
            continue
        parts = line.split(None, 1)
        mnem = parts[0].upper()
        ops = parts[1] if len(parts) > 1 else ""
        if mnem not in OPCODES:
            raise AsmError(f"line {lineno}: unknown mnemonic {mnem}")
        items.append((pc, mnem, ops, line, ",".join(pending_labels), comment, lineno))
        pending_labels = []
        pc += 1
        if pc > 256:
            raise AsmError("program exceeds 256 words")

    rows = []
    for (addr, mnem, ops, src, label, comment, lineno) in items:
        op, fmt, shape = OPCODES[mnem]
        try:
            ra = rb = imm = 0
            o = [x.strip() for x in ops.split(",")] if ops.strip() else []
            if shape == "":
                if o:
                    raise AsmError("no operands expected")
            elif shape == "r,i" or shape == "r,t":
                if len(o) != 2:
                    raise AsmError("expected 2 operands")
                ra = parse_reg(o[0]); imm = parse_int(o[1], symbols)
            elif shape == "t":
                if len(o) != 1:
                    raise AsmError("expected 1 operand")
                imm = parse_int(o[0], symbols)
            elif shape == "r,r":
                if len(o) != 2:
                    raise AsmError("expected 2 operands")
                ra = parse_reg(o[0]); rb = parse_reg(o[1])
            elif shape == "r,[r]":
                if len(o) != 2:
                    raise AsmError("expected 2 operands")
                ra = parse_reg(o[0])
                mm = re.fullmatch(r"\[\s*([rR][0-7])\s*\]", o[1])
                if not mm:
                    raise AsmError("expected [Rs]")
                rb = parse_reg(mm.group(1))
            if fmt == "R":
                word = (op << 12) | (ra << 9) | (rb << 6)
            elif fmt == "I":
                word = (op << 12) | (ra << 9) | imm
            else:
                word = op << 12
        except AsmError as e:
            raise AsmError(f"line {lineno} ({src}): {e}")
        rows.append(dict(addr=addr, word=word, src=src, label=label,
                         comment=comment, fmt=fmt))
    return rows, symbols


def to_logisim_hex(rows, size=256):
    mem = [0] * size
    for r in rows:
        mem[r["addr"]] = r["word"]
    # trim trailing zeros
    last = max([r["addr"] for r in rows] + [0])
    words = mem[: last + 1]
    lines = ["v2.0 raw"]
    for i in range(0, len(words), 8):
        lines.append(" ".join(f"{w:04x}" for w in words[i:i + 8]))
    return "\n".join(lines) + "\n"


def words_of(rows, size=256):
    mem = [0] * size
    for r in rows:
        mem[r["addr"]] = r["word"]
    return mem


def listing_text(rows):
    out = ["ADDR  HEX   FMT  LABEL          ASSEMBLY                     ; COMMENT"]
    for r in rows:
        out.append(f"{r['addr']:02X}    {r['word']:04X}  {r['fmt']}    "
                   f"{(r['label'] + ':') if r['label'] else '':14s} {r['src']:28s} ; {r['comment']}")
    return "\n".join(out) + "\n"


def tex_escape(s):
    rep = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
           "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\^{}",
           ">": r"$>$", "<": r"$<$"}
    return "".join(rep.get(c, c) for c in s)


def listing_tex(rows):
    out = []
    for r in rows:
        lab = tex_escape(r["label"]) if r["label"] else ""
        out.append(f"\\texttt{{{r['addr']:02X}}} & \\texttt{{{r['word']:04X}}} & {r['fmt']} & "
                   f"\\texttt{{{lab}}} & \\texttt{{{tex_escape(r['src'])}}} & "
                   f"{{\\footnotesize {tex_escape(r['comment'])}}} \\\\")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("-o", "--out")
    ap.add_argument("--listing")
    ap.add_argument("--tex")
    a = ap.parse_args()
    with open(a.src) as f:
        rows, _ = assemble(f.read())
    if a.out:
        with open(a.out, "w") as f:
            f.write(to_logisim_hex(rows))
    if a.listing:
        with open(a.listing, "w") as f:
            f.write(listing_text(rows))
    if a.tex:
        with open(a.tex, "w") as f:
            f.write(listing_tex(rows))
    if not (a.out or a.listing or a.tex):
        sys.stdout.write(listing_text(rows))


if __name__ == "__main__":
    main()
