#!/usr/bin/env python3
"""
circsim.py - independent cycle-based simulator for Logisim 2.7.1 .circ files
(restricted to the component set used by this project).

It does NOT reuse the generator's net names: connectivity is rebuilt purely
from the XML geometry (wire end points, component port locations computed
from the component attributes exactly as Logisim 2.7.1 does, tunnel labels,
splitter bit maps and sub-circuit appearance ports).  It therefore detects
opens, accidental shorts, width conflicts, multiple drivers and undriven
nets in the generated file, and then simulates it.

Output mimics `logisim file.circ -tty table`: one tab-separated row of the
top-level output pins (top-down, then left-right order) whenever a value
changes; the simulation stops when the output pin labelled "halt" becomes 1.

Usage: python3 circsim.py file.circ [--max-cycles N] [--header]
"""
import sys
import argparse
import xml.etree.ElementTree as ET
from collections import defaultdict

X = 2  # unknown bit value


def loc(s):
    s = s.strip()[1:-1]
    a, b = s.split(",")
    return (int(a), int(b))


class UF:
    def __init__(self):
        self.p = []

    def new(self):
        self.p.append(len(self.p))
        return len(self.p) - 1

    def find(self, a):
        p = self.p
        while p[a] != a:
            p[a] = p[p[a]]
            a = p[a]
        return a

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[b] = a


# ---------------------------------------------------------------- geometry
def gate_offsets(n, size, bonus, negout):
    axis = size + bonus + (10 if negout else 0)
    if n <= 3:
        if size < 40:
            ss, sd, sle = -5, 10, 10
        elif size < 60 or n <= 2:
            ss, sd, sle = -10, 20, 20
        else:
            ss, sd, sle = -15, 30, 30
    elif n == 4 and size >= 60:
        ss, sd, sle = -5, 20, 0
    else:
        ss, sd, sle = -5, 10, 10
    out = []
    for i in range(n):
        if n & 1:
            dy = ss * (n - 1) + sd * i
        else:
            dy = ss * n + sd * i
            if i >= n // 2:
                dy += sle
        out.append((-axis, dy))
    return out


GATES = {"AND Gate": ("and", 0, False), "OR Gate": ("or", 0, False),
         "XOR Gate": ("xor", 10, False), "NAND Gate": ("and", 0, True),
         "NOR Gate": ("or", 0, True), "XNOR Gate": ("xor", 10, True)}


def ival(a, key, dflt):
    v = a.get(key)
    if v is None:
        return dflt
    v = v.strip()
    return int(v, 16) if v.lower().startswith("0x") else int(v)


def comp_ports(lib, name, attrs):
    """return list of (portname, dx, dy, width) for a primitive."""
    a = attrs
    facing = a.get("facing", "east")
    if lib == "#Wiring":
        if name in ("Pin", "Tunnel", "Constant", "Probe"):
            return [("p", 0, 0, ival(a, "width", 1))]
        if name == "Clock":
            return [("p", 0, 0, 1)]
        if name == "Splitter":
            if facing != "east":
                raise ValueError("only east splitters supported")
            fan = ival(a, "fanout", 2)
            inc = ival(a, "incoming", 2)
            appear = a.get("appear", "left")
            just = {"left": -1, "right": 1}.get(appear, 0)
            dx0 = 20
            dy0 = -10 * (fan // 2) if just == 0 else (10 if just > 0 else -10 * fan)
            widths = [0] * fan
            for b in range(inc):
                v = a.get(f"bit{b}", str(b * fan // inc) if False else None)
                if v is None:
                    raise ValueError("splitter without explicit bit map")
                if v != "none":
                    widths[int(v)] += 1
            ports = [("c", 0, 0, inc)]
            for i in range(fan):
                ports.append((f"e{i}", dx0, dy0 + 10 * i, widths[i]))
            return ports
    if lib == "#Gates":
        if facing != "east":
            raise ValueError("only east gates supported")
        w = ival(a, "width", 1)
        if name == "NOT Gate":
            dx = -20 if a.get("size") == "20" else -30
            return [("out", 0, 0, w), ("in0", dx, 0, w)]
        kind, bonus, negout = GATES[name]
        n = ival(a, "inputs", 5)
        size = ival(a, "size", 50)
        ports = [("out", 0, 0, w)]
        for i, (dx, dy) in enumerate(gate_offsets(n, size, bonus, negout)):
            ports.append((f"in{i}", dx, dy, w))
        return ports
    if lib == "#Memory":
        if name == "Register":
            w = ival(a, "width", 8)
            return [("Q", 0, 0, w), ("D", -30, 0, w), ("EN", -30, 10, 1),
                    ("CK", -20, 20, 1), ("CLR", -10, 20, 1)]
        aw, dw = ival(a, "addrWidth", 8), ival(a, "dataWidth", 8)
        if name == "ROM":
            return [("D", 0, 0, dw), ("A", -140, 0, aw), ("CS", -90, 40, 1)]
        if name == "RAM":
            if a.get("bus") != "separate":
                raise ValueError("only separate-bus RAM supported")
            return [("D", 0, 0, dw), ("A", -140, 0, aw), ("DIN", -140, 20, dw),
                    ("WE", -110, 40, 1), ("CS", -90, 40, 1), ("CLK", -70, 40, 1),
                    ("OE", -50, 40, 1), ("CLR", -30, 40, 1)]
    if lib == "#Base" and name == "Text":
        return []
    raise ValueError(f"unsupported component {lib}:{name}")


def parse_contents(text):
    lines = text.strip().split("\n")
    hdr = lines[0].split()
    aw, dw = int(hdr[1]), int(hdr[2])
    vals = []
    for ln in lines[1:]:
        for t in ln.split():
            if "*" in t:
                n, v = t.split("*")
                vals += [int(v, 16)] * int(n)
            else:
                vals.append(int(t, 16))
    return aw, dw, vals


# ---------------------------------------------------------------- loader
class Design:
    def __init__(self, path):
        root = ET.parse(path).getroot()
        self.libs = {l.get("name"): l.get("desc") for l in root.findall("lib")}
        self.main = root.find("main").get("name")
        self.circ = {}
        for c in root.findall("circuit"):
            name = c.get("name")
            wires = [(loc(w.get("from")), loc(w.get("to"))) for w in c.findall("wire")]
            comps = []
            for cp in c.findall("comp"):
                lib = cp.get("lib")
                attrs = {}
                for at in cp.findall("a"):
                    attrs[at.get("name")] = at.get("val") if at.get("val") is not None else at.text
                comps.append((self.libs.get(lib) if lib is not None else None,
                              cp.get("name"), loc(cp.get("loc")), attrs))
            ports, anchor = [], None
            ap = c.find("appear")
            if ap is not None:
                for p in ap.findall("circ-port"):
                    cx = int(p.get("x")) + int(p.get("width")) // 2
                    cy = int(p.get("y")) + int(p.get("height")) // 2
                    px, py = p.get("pin").split(",")
                    ports.append(((cx, cy), (int(px), int(py))))
                an = ap.find("circ-anchor")
                anchor = (int(an.get("x")) + int(an.get("width")) // 2,
                          int(an.get("y")) + int(an.get("height")) // 2)
            self.circ[name] = dict(wires=wires, comps=comps, ports=ports, anchor=anchor)
        self.warnings = []

    # build flattened bit-level netlist
    def flatten(self):
        self.uf = UF()
        self.prims = []      # dicts: kind, ports(name->list of bit ids), attrs, path
        self.top_in = []     # (label, bits, loc)
        self.top_out = []
        self.clock_bits = []
        self._inst(self.main, "", None)
        # resolve roots
        f = self.uf.find
        for pr in self.prims:
            for k in pr["ports"]:
                if pr["ports"][k] is not None:
                    pr["ports"][k] = [f(b) for b in pr["ports"][k]]
        self.top_in = [(l, [f(b) for b in bits], lc) for (l, bits, lc) in self.top_in]
        self.top_out = [(l, [f(b) for b in bits], lc) for (l, bits, lc) in self.top_out]
        self.clock_bits = [f(b) for b in self.clock_bits]

    def _inst(self, cname, path, binding):
        """binding: pin location -> list of parent bit ids (None for top)."""
        C = self.circ[cname]
        uf = self.uf
        # point graph
        pts = {}

        def P(p):
            if p not in pts:
                pts[p] = len(pts)
            return pts[p]

        edges = []
        for (a, b) in C["wires"]:
            edges.append((P(a), P(b)))
        endpoints = []   # (point, owner index, port name, width)
        tunnels = defaultdict(list)
        comp_list = []
        for idx, (lib, name, (x, y), attrs) in enumerate(C["comps"]):
            if lib is None:  # sub-circuit instance
                sub = self.circ[name]
                ax, ay = sub["anchor"]
                ports = []
                for (cx, cy), pinloc in sub["ports"]:
                    ports.append((pinloc, x + cx - ax, y + cy - ay))
                comp_list.append(("SUB", name, (x, y), attrs, ports))
                for pinloc, px, py in ports:
                    endpoints.append((P((px, py)), idx, ("pin", pinloc), None))
                continue
            plist = comp_ports(lib, name, attrs)
            comp_list.append((lib, name, (x, y), attrs, plist))
            for (pn, dx, dy, w) in plist:
                endpoints.append((P((x + dx, y + dy)), idx, pn, w))
            if lib == "#Wiring" and name == "Tunnel":
                tunnels[attrs.get("label", "")].append(P((x, y)))
        # point-level union find
        np_ = len(pts)
        par = list(range(np_))

        def fd(a):
            while par[a] != a:
                par[a] = par[par[a]]
                a = par[a]
            return a

        for a, b in edges:
            ra, rb = fd(a), fd(b)
            if ra != rb:
                par[rb] = ra
        for lab, plist in tunnels.items():
            for p in plist[1:]:
                ra, rb = fd(plist[0]), fd(p)
                if ra != rb:
                    par[rb] = ra
        # sanity: component ends lying strictly inside a wire are NOT connected by Logisim
        inv = {v: k for k, v in pts.items()}
        endset = {inv[e[0]] for e in endpoints}
        for (a, b) in C["wires"]:
            for q in endset:
                if q in (a, b):
                    continue
                if a[0] == b[0] == q[0] and min(a[1], b[1]) < q[1] < max(a[1], b[1]):
                    self.warnings.append(f"{path or cname}: port at {q} lies inside wire {a}-{b}")
                if a[1] == b[1] == q[1] and min(a[0], b[0]) < q[0] < max(a[0], b[0]):
                    self.warnings.append(f"{path or cname}: port at {q} lies inside wire {a}-{b}")
        # widths per point-net
        netw = {}
        for (p, idx, pn, w) in endpoints:
            if w is None:
                continue
            r = fd(p)
            if r in netw and netw[r] != w:
                lib, name, lc, attrs, _ = comp_list[idx]
                raise ValueError(f"{path or cname}: width conflict at {inv[p]} ({name} {pn}: {w} vs {netw[r]})")
            netw[r] = w
        # sub-circuit port widths come from the child's pin width
        for (p, idx, pn, w) in endpoints:
            if w is None:
                sub = comp_list[idx][1]
                pinloc = pn[1]
                pw = None
                for (lib, name, lc, attrs) in self.circ[sub]["comps"]:
                    if name == "Pin" and lc == pinloc:
                        pw = ival(attrs, "width", 1)
                r = fd(p)
                if r in netw and netw[r] != pw:
                    raise ValueError(f"{path or cname}: width conflict at sub-circuit {sub} port {inv[p]}")
                netw[r] = pw
        # bit ids for each point-net
        bits = {}

        def B(p):
            r = fd(p)
            if r not in bits:
                bits[r] = [uf.new() for _ in range(netw.get(r, 1))]
            return bits[r]

        # count attachments per net for dangling detection
        attach = defaultdict(int)
        for (p, idx, pn, w) in endpoints:
            attach[fd(p)] += 1
        # components
        for idx, comp in enumerate(comp_list):
            lib, name, (x, y), attrs = comp[0], comp[1], comp[2], comp[3]
            here = f"{path}/{name}@{x},{y}"
            if lib == "SUB":
                child_bind = {}
                for pinloc, px, py in comp[4]:
                    child_bind[pinloc] = B(P((px, py)))
                self._inst(name, f"{path}/{name}@{x},{y}", child_bind)
                continue
            plist = comp[4]
            pb = {}
            for (pn, dx, dy, w) in plist:
                p = P((x + dx, y + dy))
                pb[pn] = B(p) if attach[fd(p)] > 1 or name in ("Pin",) else None
            if lib == "#Wiring" and name == "Tunnel":
                continue
            if lib == "#Wiring" and name == "Splitter":
                c = B(P((x, y)))
                inc = ival(attrs, "incoming", 2)
                fan = ival(attrs, "fanout", 2)
                cnt = [0] * fan
                for b in range(inc):
                    v = attrs.get(f"bit{b}")
                    if v == "none":
                        continue
                    k = int(v)
                    endp = [pp for pp in plist if pp[0] == f"e{k}"][0]
                    eb = B(P((x + endp[1], y + endp[2])))
                    uf.union(c[b], eb[cnt[k]])
                    cnt[k] += 1
                continue
            if lib == "#Wiring" and name == "Pin":
                bitsp = B(P((x, y)))
                is_out = attrs.get("output") == "true"
                if binding is not None:
                    parent = binding.get((x, y))
                    if parent is None:
                        raise ValueError(f"{here}: pin not in appearance")
                    if len(parent) != len(bitsp):
                        raise ValueError(f"{here}: pin width mismatch")
                    for a1, b1 in zip(parent, bitsp):
                        uf.union(a1, b1)
                else:
                    (self.top_out if is_out else self.top_in).append((attrs.get("label", ""), bitsp, (x, y)))
                continue
            if lib == "#Wiring" and name == "Clock":
                self.clock_bits += B(P((x, y)))
                continue
            if lib == "#Base":
                continue
            self.prims.append(dict(lib=lib, name=name, attrs=attrs, ports=pb, path=here))


# ---------------------------------------------------------------- simulator
class Sim:
    def __init__(self, design):
        d = design
        self.d = d
        self.nsig = len(d.uf.p)
        self.val = [X] * self.nsig
        self.comb = []      # combinational prims (gates, ROM/RAM read, constants)
        self.regs = []
        self.rams = []
        drivers = defaultdict(list)
        for pr in d.prims:
            nm, lib = pr["name"], pr["lib"]
            if lib == "#Gates":
                kind = "not" if nm == "NOT Gate" else GATES[nm][0]
                neg = nm in ("NOT Gate", "NAND Gate", "NOR Gate", "XNOR Gate")
                ins = [pr["ports"][k] for k in sorted(pr["ports"]) if k.startswith("in")
                       and pr["ports"][k] is not None]
                out = pr["ports"]["out"]
                if out is None:
                    continue
                g = dict(t="gate", kind=kind, neg=neg, ins=ins, out=out, path=pr["path"])
                self.comb.append(g)
                for b in out:
                    drivers[b].append(pr["path"])
            elif nm == "Constant":
                if pr["ports"]["p"] is None:
                    continue
                v = ival(pr["attrs"], "value", 1)
                self.comb.append(dict(t="const", out=pr["ports"]["p"], v=v, ins=[]))
                for b in pr["ports"]["p"]:
                    drivers[b].append(pr["path"])
            elif nm == "Register":
                r = dict(t="reg", q=pr["ports"]["Q"], dd=pr["ports"]["D"], en=pr["ports"]["EN"],
                         ck=pr["ports"]["CK"], clr=pr["ports"]["CLR"], v=0, path=pr["path"],
                         label=pr["attrs"].get("label", ""))
                self.regs.append(r)
                for b in r["q"] or []:
                    drivers[b].append(pr["path"])
            elif nm in ("ROM", "RAM"):
                aw = ival(pr["attrs"], "addrWidth", 8)
                dw = ival(pr["attrs"], "dataWidth", 8)
                mem = [0] * (1 << aw)
                if nm == "ROM":
                    _, _, vals = parse_contents(pr["attrs"]["contents"])
                    mem[:len(vals)] = vals
                m = dict(t="mem", kind=nm, a=pr["ports"]["A"], out=pr["ports"]["D"], mem=mem,
                         ins=[pr["ports"]["A"]], dw=dw, path=pr["path"])
                if nm == "RAM":
                    m.update(din=pr["ports"]["DIN"], we=pr["ports"]["WE"], ck=pr["ports"]["CLK"])
                    self.rams.append(m)
                self.comb.append(m)
                for b in m["out"]:
                    drivers[b].append(pr["path"])
        for (lab, bits, lc) in d.top_in:
            for b in bits:
                drivers[b].append("pin:" + lab)
        for b in d.clock_bits:
            drivers[b].append("clock")
        self.problems = []
        for b, ds in drivers.items():
            if len(ds) > 1:
                self.problems.append(f"multiple drivers on signal {b}: {ds}")
        self.driven = set(drivers)
        # clock checks
        cset = set(d.clock_bits)
        for r in self.regs:
            if not r["ck"] or r["ck"][0] not in cset:
                self.problems.append(f"register {r['path']} clock not tied to the global clock")
        for m in self.rams:
            if not m["ck"] or m["ck"][0] not in cset:
                self.problems.append(f"RAM {m['path']} clock not tied to the global clock")
        # loads that are undriven
        for g in self.comb:
            for vec in g["ins"]:
                for b in vec or []:
                    if b not in self.driven:
                        self.problems.append(f"undriven input bit {b} of {g.get('path')}")
        for r in self.regs:
            for vec in (r["dd"], r["en"], r["clr"]):
                for b in vec or []:
                    if b not in self.driven:
                        self.problems.append(f"undriven reg input {r['path']}")
        # levelize
        prod = {}
        for i, g in enumerate(self.comb):
            for b in g["out"]:
                prod[b] = i
        indeg = [0] * len(self.comb)
        succ = defaultdict(list)
        for i, g in enumerate(self.comb):
            deps = set()
            for vec in g["ins"]:
                for b in vec or []:
                    if b in prod:
                        deps.add(prod[b])
            for j in deps:
                succ[j].append(i)
                indeg[i] += 1
        order = [i for i in range(len(self.comb)) if indeg[i] == 0]
        k = 0
        while k < len(order):
            for j in succ[order[k]]:
                indeg[j] -= 1
                if indeg[j] == 0:
                    order.append(j)
            k += 1
        if len(order) != len(self.comb):
            self.problems.append("combinational loop detected")
        self.order = [self.comb[i] for i in order]
        for b in d.clock_bits:
            self.val[b] = 0
        self.inputs = {lab: bits for (lab, bits, lc) in d.top_in}
        for lab, bits in self.inputs.items():
            for b in bits:
                self.val[b] = 0

    # helpers
    def rd(self, bits):
        v = 0
        for i, b in enumerate(bits):
            x = self.val[b]
            if x == X:
                return None
            v |= x << i
        return v

    def wr(self, bits, v):
        for i, b in enumerate(bits):
            self.val[b] = X if v is None else (v >> i) & 1

    def set_input(self, label, v):
        self.wr(self.inputs[label], v)

    def eval_comb(self):
        val = self.val
        for r in self.regs:
            if r["q"]:
                self.wr(r["q"], r["v"])
        for g in self.order:
            t = g["t"]
            if t == "gate":
                out = g["out"]
                ins = g["ins"]
                kind = g["kind"]
                for i, ob in enumerate(out):
                    if kind == "not":
                        a = val[ins[0][i]]
                        r = X if a == X else 1 - a
                        val[ob] = r
                        continue
                    if kind == "and":
                        r = 1
                        for vec in ins:
                            a = val[vec[i]]
                            if a == 0:
                                r = 0
                                break
                            if a == X:
                                r = X
                    elif kind == "or":
                        r = 0
                        for vec in ins:
                            a = val[vec[i]]
                            if a == 1:
                                r = 1
                                break
                            if a == X:
                                r = X
                    else:
                        r = 0
                        for vec in ins:
                            a = val[vec[i]]
                            if a == X:
                                r = X
                                break
                            r ^= a
                    if g["neg"] and r != X:
                        r = 1 - r
                    val[ob] = r
            elif t == "const":
                self.wr(g["out"], g["v"])
            elif t == "mem":
                a = self.rd(g["a"])
                self.wr(g["out"], None if a is None else g["mem"][a])

    def settle(self):
        """evaluate, applying asynchronous register clears until stable"""
        for _ in range(10):
            self.eval_comb()
            changed = False
            for r in self.regs:
                if r["clr"] and self.rd(r["clr"]) == 1 and r["v"] != 0:
                    r["v"] = 0
                    changed = True
            if not changed:
                return
        raise RuntimeError("async clear did not settle")

    def edge(self):
        """rising clock edge: all state elements sample pre-edge values simultaneously"""
        new = []
        for r in self.regs:
            clr = self.rd(r["clr"]) if r["clr"] else 0
            en = self.rd(r["en"]) if r["en"] else None
            v = r["v"]
            if clr == 1:
                v = 0
            elif en != 0:
                d = self.rd(r["dd"]) if r["dd"] else None
                if d is not None:
                    v = d
            new.append(v)
        writes = []
        for m in self.rams:
            we = self.rd(m["we"])
            a = self.rd(m["a"])
            if we != 0 and a is not None:
                d = self.rd(m["din"])
                writes.append((m, a, 0 if d is None else d))
        for r, v in zip(self.regs, new):
            r["v"] = v
        for m, a, d in writes:
            m["mem"][a] = d
        self.settle()


def fmt(v, w):
    if v is None:
        return "x" * w if w == 1 else " ".join(["xxxx"] * ((w + 3) // 4))
    s = format(v, f"0{w}b")
    out = []
    for i, ch in enumerate(s):
        out.append(ch)
        k = w - 1 - i
        if k % 4 == 0 and k != 0:
            out.append(" ")
    return "".join(out)


def run(path, max_cycles=100000, header=False, stream=sys.stdout, stimulus=None):
    d = Design(path)
    d.flatten()
    s = Sim(d)
    if d.warnings:
        for w in d.warnings[:20]:
            print("WARNING:", w, file=sys.stderr)
    if s.problems:
        for p in s.problems[:40]:
            print("PROBLEM:", p, file=sys.stderr)
        raise SystemExit(2)
    outs = sorted(d.top_out, key=lambda t: (t[2][1], t[2][0]))
    halt = [o for o in outs if o[0] == "halt"]
    cols = [o for o in outs if o[0] != "halt"]
    if header:
        stream.write("\t".join(o[0] for o in cols) + "\n")
    s.settle()
    prev = None
    for cyc in range(max_cycles + 1):
        if stimulus:
            stimulus(cyc, s)
            s.settle()
        row = [fmt(s.rd(b), len(b)) for (_, b, _) in cols]
        if row != prev:
            stream.write("\t".join(row) + "\n")
            prev = row
        if halt and s.rd(halt[0][1]) == 1:
            break
        s.edge()
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("circ")
    ap.add_argument("--max-cycles", type=int, default=100000)
    ap.add_argument("--header", action="store_true")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()
    if a.stats:
        d = Design(a.circ)
        d.flatten()
        s = Sim(d)
        kinds = defaultdict(int)
        for pr in d.prims:
            kinds[pr["name"]] += 1
        for k, v in sorted(kinds.items()):
            print(f"{v:6d}  {k}")
        print("signals:", s.nsig, " problems:", len(s.problems), " warnings:", len(d.warnings))
        for p in s.problems[:20]:
            print("PROBLEM:", p)
        return
    run(a.circ, a.max_cycles, a.header)


if __name__ == "__main__":
    main()
