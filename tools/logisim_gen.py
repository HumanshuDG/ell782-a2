#!/usr/bin/env python3
"""
logisim_gen.py - a small library that emits Logisim 2.7.1 (.circ, XML v1.0) files.

Every component port is connected by a short wire stub to a labelled Tunnel,
so each sub-circuit is a readable, labelled "netlist schematic".  Port
geometry is taken from the Logisim 2.7.1 sources (AbstractGate, NotGate,
Register, SplitterParameters, Mem/Ram/Rom, Pin/Probe, Constant, Clock) so
the generated files load and simulate unchanged in Logisim 2.7.1 and can be
imported by Logisim-Evolution.

Only these built-in components are used: Pin, Tunnel, Splitter, Constant,
Clock (Wiring); AND/OR/NOR/XOR/NOT gates (Gates); Register, ROM, RAM
(Memory); Text (Base).  No Plexers/Arithmetic library is even loaded.
"""
import math
from xml.sax.saxutils import escape, quoteattr

LIB_WIRING, LIB_GATES, LIB_MEM, LIB_BASE = "0", "1", "4", "6"
TFONT = "SansSerif plain 10"


def r10(v):
    return int(math.ceil(v / 10.0)) * 10


def tw(label):
    """approximate pixel width of a tunnel (incl. arrow) for layout"""
    return 6 * len(label) + 18


GATE_KIND = {
    "AND": ("AND Gate", 0, False), "OR": ("OR Gate", 0, False),
    "XOR": ("XOR Gate", 10, False), "NAND": ("NAND Gate", 0, True),
    "NOR": ("NOR Gate", 0, True), "XNOR": ("XNOR Gate", 10, True),
}


def gate_geom(kind, n, size=50):
    """Port offsets of a Logisim 2.7.1 gate facing east (AbstractGate.getInputOffset)."""
    name, bonus, negout = GATE_KIND[kind]
    axis = size + bonus + (10 if negout else 0)
    ni = n + 1 if n % 2 == 0 else n
    height = max(10 * ni, size)
    bounds = (-axis, -height // 2, axis, height)
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
    offs = []
    for i in range(n):
        if n & 1:
            dy = ss * (n - 1) + sd * i
        else:
            dy = ss * n + sd * i
            if i >= n // 2:
                dy += sle
        offs.append((-axis, dy))
    return name, bounds, offs


def probe_bounds(width, facing):
    if width <= 1:
        w, h = 20, 20
    elif width <= 8:
        w, h = 10 * max(2, width), 20
    elif width <= 16:
        w, h = 80, 40
    else:
        w, h = 80, 60
    if facing == "east":
        return (-w, -h // 2, w, h)
    return (0, -h // 2, w, h)


class GenError(Exception):
    pass


class Circuit:
    def __init__(self, name, maxh=1500, gapx=40):
        self.name = name
        self.items = []
        self.wires = []
        self.netw = {}
        self.drv = {}
        self.load = {}
        self.ins = []        # (name, width, (x, y))
        self.outs = []
        self.maxh = maxh
        self.gapx = gapx
        self.top = 40
        self.colx = 40
        self.coly = self.top
        self.colw = 0
        self.box_w = None
        self.appear_xml = ""
        self.finished = False
        self.label_counter = {}

    # ------------------------------------------------------------ nets
    def _net(self, net, w, d, who):
        if net in self.netw and self.netw[net] != w:
            raise GenError(f"[{self.name}] net '{net}' width {self.netw[net]} vs {w} ({who})")
        self.netw[net] = w
        if d == "out":
            self.drv.setdefault(net, []).append(who)
        else:
            self.load.setdefault(net, []).append(who)

    def check(self):
        errs = []
        for net in self.netw:
            n = len(self.drv.get(net, []))
            if n == 0:
                errs.append(f"[{self.name}] net '{net}' has no driver (loads: {self.load.get(net)})")
            if n > 1:
                errs.append(f"[{self.name}] net '{net}' has {n} drivers: {self.drv[net]}")
        if errs:
            raise GenError("\n".join(errs))

    # ------------------------------------------------------------ layout
    def newcol(self, gap=None):
        if self.colw == 0 and self.coly == self.top:
            return
        self.colx += self.colw + (self.gapx if gap is None else gap)
        self.coly = self.top
        self.colw = 0

    def text(self, s, size=14, bold=True):
        h = size + 14
        if self.coly + h > self.top + self.maxh:
            self.newcol()
        x, y = self.colx, self.coly + size
        font = f"SansSerif {'bold' if bold else 'plain'} {size}"
        self.items.append(
            f'<comp lib="{LIB_BASE}" loc="({r10(x)},{r10(y)})" name="Text">\n'
            f'      <a name="text" val={quoteattr(s)}/>\n'
            f'      <a name="font" val="{font}"/>\n'
            f'      <a name="halign" val="left"/>\n'
            f'      <a name="valign" val="base"/>\n    </comp>')
        self.coly += h + 6
        self.colw = max(self.colw, int(len(s) * size * 0.62))

    def _place(self, lib, cname, attrs, bounds, ports, conn, text_attrs=None, who=None):
        """ports: list of dicts(name,dx,dy,w,side,dir). conn: port name -> net."""
        who = who or cname
        segs, tuns = [], []
        groups = {"W": [], "E": [], "S": []}
        for p in ports:
            net = conn.get(p["name"])
            if net is None:
                continue
            self._net(net, p["w"], p["dir"], f"{who}.{p['name']}")
            groups[p["side"]].append((p, net))
        bx, by, bw, bh = bounds
        for side in ("W", "E"):
            g = sorted(groups[side], key=lambda t: t[0]["dy"])
            tmax = max([tw(n) for _, n in g], default=0)
            dense = any(g[i + 1][0]["dy"] - g[i][0]["dy"] < 20 for i in range(len(g) - 1))
            for i, (p, net) in enumerate(g):
                L = 20 + (r10(tmax + 10) if (dense and i % 2 == 1) else 0)
                x0, y0 = p["dx"], p["dy"]
                x1 = x0 - L if side == "W" else x0 + L
                segs.append(((x0, y0), (x1, y0)))
                tuns.append((x1, y0, "east" if side == "W" else "west", net, self.netw[net]))
        gs = sorted(groups["S"], key=lambda t: t[0]["dx"])
        xl = bx - 20
        for k, (p, net) in enumerate(gs):
            y1 = by + bh + 10 + 20 * k
            segs.append(((p["dx"], p["dy"]), (p["dx"], y1)))
            segs.append(((p["dx"], y1), (xl, y1)))
            tuns.append((xl, y1, "east", net, self.netw[net]))
        # bounding box of the cell
        xs = [bx, bx + bw]
        ys = [by, by + bh]
        for (a, b) in segs:
            xs += [a[0], b[0]]
            ys += [a[1], b[1]]
        for (x, y, f, net, w) in tuns:
            t = tw(net)
            if f == "east":
                xs += [x - t]
            else:
                xs += [x + t]
            ys += [y - 9, y + 9]
        minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
        if text_attrs:  # label above component
            miny -= 16
        cw, ch = maxx - minx, maxy - miny
        if self.coly + ch > self.top + self.maxh and self.coly > self.top:
            self.newcol()
        ox = r10(self.colx - minx)
        oy = r10(self.coly - miny)
        self.coly = oy + maxy + 20
        self.colw = max(self.colw, ox + maxx - self.colx)
        # emit
        self.items.append(comp_xml(lib, cname, (ox, oy), attrs))
        for (a, b) in segs:
            self.wires.append(((a[0] + ox, a[1] + oy), (b[0] + ox, b[1] + oy)))
        for (x, y, f, net, w) in tuns:
            at = [("facing", f), ("width", w), ("label", net), ("labelfont", TFONT)]
            self.items.append(comp_xml(LIB_WIRING, "Tunnel", (x + ox, y + oy), at))
        return (ox, oy)

    # ------------------------------------------------------------ primitives
    def inp(self, name, w=1, net=None, label=None, tristate=False):
        net = net or name
        b = probe_bounds(w, "east")
        attrs = [("facing", "east"), ("width", w)]
        attrs += [("tristate", "false"), ("label", label or name), ("labelloc", "north")]
        b = (b[0], b[1] - 14, b[2], b[3] + 14)
        loc = self._place(LIB_WIRING, "Pin", attrs, b,
                          [dict(name="p", dx=0, dy=0, w=w, side="E", dir="out")], {"p": net},
                          who=f"pin:{name}")
        self.ins.append((label or name, w, loc))
        return loc

    def outp(self, name, w=1, net=None, label=None):
        net = net or name
        b = probe_bounds(w, "west")
        attrs = [("facing", "west"), ("output", "true"), ("width", w)]
        attrs += [("label", label or name), ("labelloc", "north")]
        b = (b[0], b[1] - 14, b[2], b[3] + 14)
        loc = self._place(LIB_WIRING, "Pin", attrs, b,
                          [dict(name="p", dx=0, dy=0, w=w, side="W", dir="in")], {"p": net},
                          who=f"pin:{name}")
        self.outs.append((label or name, w, loc))
        return loc

    def gate(self, kind, ins, out, w=1, size=50, label=None):
        if len(ins) < 2:
            raise GenError(f"[{self.name}] gate {kind} needs >=2 inputs")
        name, bounds, offs = gate_geom(kind, len(ins), size)
        ports = [dict(name="out", dx=0, dy=0, w=w, side="E", dir="out")]
        conn = {"out": out}
        for i, (ox, oy) in enumerate(offs):
            ports.append(dict(name=f"in{i}", dx=ox, dy=oy, w=w, side="W", dir="in"))
            conn[f"in{i}"] = ins[i]
        attrs = [("width", w), ("size", size), ("inputs", len(ins))]
        if label:
            attrs.append(("label", label))
        return self._place(LIB_GATES, name, attrs, bounds, ports, conn, who=f"{kind}->{out}")

    def inv(self, a, out, w=1):
        attrs = [("width", w)]
        ports = [dict(name="out", dx=0, dy=0, w=w, side="E", dir="out"),
                 dict(name="in", dx=-30, dy=0, w=w, side="W", dir="in")]
        return self._place(LIB_GATES, "NOT Gate", attrs, (-30, -9, 30, 18), ports,
                           {"out": out, "in": a}, who=f"NOT->{out}")

    def reg(self, d, q, w=1, en=None, clr="RST", clk="CLK", label=None):
        attrs = [("width", w), ("trigger", "rising")]
        if label:
            attrs += [("label", label), ("labelfont", "SansSerif bold 10")]
        ports = [dict(name="Q", dx=0, dy=0, w=w, side="E", dir="out"),
                 dict(name="D", dx=-30, dy=0, w=w, side="W", dir="in"),
                 dict(name="EN", dx=-30, dy=10, w=1, side="W", dir="in"),
                 dict(name="CK", dx=-20, dy=20, w=1, side="S", dir="in"),
                 dict(name="CLR", dx=-10, dy=20, w=1, side="S", dir="in")]
        conn = {"Q": q, "D": d, "CK": clk}
        if en:
            conn["EN"] = en
        if clr:
            conn["CLR"] = clr
        return self._place(LIB_MEM, "Register", attrs, (-30, -20, 30, 40), ports, conn,
                           text_attrs=bool(label), who=f"REG:{q}")

    def _splitter(self, combined, w, parts, combined_dir):
        """parts: list of (net, lo, hi). bit i -> end index or none."""
        n = len(parts)
        bitmap = ["none"] * w
        ports = [dict(name="c", dx=0, dy=0, w=w, side="W", dir=combined_dir)]
        conn = {"c": combined}
        pd = "out" if combined_dir == "in" else "in"
        for i, (net, lo, hi) in enumerate(parts):
            for b in range(lo, hi + 1):
                if bitmap[b] != "none":
                    raise GenError(f"[{self.name}] splitter bit {b} used twice ({combined})")
                bitmap[b] = str(i)
            if net is not None:
                ports.append(dict(name=f"e{i}", dx=20, dy=-10 * n + 10 * i, w=hi - lo + 1,
                                  side="E", dir=pd))
                conn[f"e{i}"] = net
        attrs = [("facing", "east"), ("fanout", n), ("incoming", w), ("appear", "left")]
        attrs += [(f"bit{b}", bitmap[b]) for b in range(w)]
        return self._place(LIB_WIRING, "Splitter", attrs, (0, -10 * n - 5, 20, 10 * n + 10),
                           ports, conn, who=f"SPLIT:{combined}")

    def split(self, bus, w, parts):
        """bus (driven elsewhere) -> parts. parts: list of (net, lo, hi) or (net, bit)."""
        return self._splitter(bus, w, [p if len(p) == 3 else (p[0], p[1], p[1]) for p in parts], "in")

    def join(self, bus, w, parts):
        """parts (driven elsewhere) -> bus."""
        return self._splitter(bus, w, [p if len(p) == 3 else (p[0], p[1], p[1]) for p in parts], "out")

    def rep(self, src, dst, n):
        """replicate 1-bit net src into n-bit net dst (splitter fan-in of the same net)."""
        bitmap = [str(i) for i in range(n)]
        ports = [dict(name="c", dx=0, dy=0, w=n, side="W", dir="out")]
        conn = {"c": dst}
        for i in range(n):
            ports.append(dict(name=f"e{i}", dx=20, dy=-10 * n + 10 * i, w=1, side="E", dir="in"))
            conn[f"e{i}"] = src
        attrs = [("facing", "east"), ("fanout", n), ("incoming", n), ("appear", "left")]
        attrs += [(f"bit{b}", bitmap[b]) for b in range(n)]
        return self._place(LIB_WIRING, "Splitter", attrs, (0, -10 * n - 5, 20, 10 * n + 10),
                           ports, conn, who=f"REP:{dst}")

    def const(self, net, w, val):
        attrs = [("facing", "east"), ("width", w), ("value", hex(val))]
        cw = 10 * max(2, (w + 3) // 4) + 10
        return self._place(LIB_WIRING, "Constant", attrs, (-cw, -9, cw, 18),
                           [dict(name="p", dx=0, dy=0, w=w, side="E", dir="out")], {"p": net},
                           who=f"CONST:{net}")

    def clock(self, net, label="CLK"):
        attrs = [("facing", "east"), ("highDuration", 1), ("lowDuration", 1), ("label", label),
                 ("labelloc", "north")]
        return self._place(LIB_WIRING, "Clock", attrs, (-20, -24, 20, 34),
                           [dict(name="p", dx=0, dy=0, w=1, side="E", dir="out")], {"p": net},
                           who="CLOCK")

    def rom(self, addr, data, aw, dw, words, label=None):
        attrs = [("addrWidth", aw), ("dataWidth", dw)]
        contents = rom_contents(aw, dw, words)
        ports = [dict(name="D", dx=0, dy=0, w=dw, side="E", dir="out"),
                 dict(name="A", dx=-140, dy=0, w=aw, side="W", dir="in")]
        attrs.append(("contents", contents))
        return self._place(LIB_MEM, "ROM", attrs, (-140, -40, 140, 80), ports,
                           {"D": data, "A": addr}, who=f"ROM:{data}")

    def ram(self, addr, din, dout, we, clk, aw, dw):
        attrs = [("addrWidth", aw), ("dataWidth", dw), ("bus", "separate")]
        ports = [dict(name="D", dx=0, dy=0, w=dw, side="E", dir="out"),
                 dict(name="A", dx=-140, dy=0, w=aw, side="W", dir="in"),
                 dict(name="DIN", dx=-140, dy=20, w=dw, side="W", dir="in"),
                 dict(name="WE", dx=-110, dy=40, w=1, side="S", dir="in"),
                 dict(name="CLK", dx=-70, dy=40, w=1, side="S", dir="in")]
        return self._place(LIB_MEM, "RAM", attrs, (-140, -40, 140, 80), ports,
                           {"D": dout, "A": addr, "DIN": din, "WE": we, "CLK": clk},
                           who=f"RAM:{dout}")

    def sub(self, sdef, conn, label=None):
        """instantiate a finished Circuit sdef. conn: port name -> net"""
        if not sdef.finished:
            raise GenError(f"sub-circuit {sdef.name} not finished")
        ports = []
        for i, (nm, w, _) in enumerate(sdef.ins):
            ports.append(dict(name=nm, dx=0, dy=20 * i, w=w, side="W", dir="in"))
        for j, (nm, w, _) in enumerate(sdef.outs):
            ports.append(dict(name=nm, dx=sdef.box_w, dy=20 * j, w=w, side="E", dir="out"))
        known = {p["name"] for p in ports}
        for k in conn:
            if k not in known:
                raise GenError(f"[{self.name}] {sdef.name} has no port {k}")
        for p in ports:
            if p["dir"] == "in" and p["name"] not in conn:
                raise GenError(f"[{self.name}] {sdef.name} input {p['name']} unconnected")
        n = max(len(sdef.ins), len(sdef.outs))
        attrs = [("label", label)] if label else []
        if label:
            attrs.append(("labelfont", "SansSerif bold 11"))
        return self._place(None, sdef.name, attrs, (0, -10, sdef.box_w, 20 * n + 16),
                           ports, conn, text_attrs=bool(label), who=f"{sdef.name}:{label or ''}")

    # ------------------------------------------------------------ finish
    def finish(self, title=None):
        """build custom appearance: inputs on the left, outputs on the right, 20 px pitch."""
        self.check()
        li = max([len(n) for n, _, _ in self.ins] + [1])
        lo = max([len(n) for n, _, _ in self.outs] + [1])
        title = title or self.name
        self.box_w = max(60, r10(6 * li + 6 * lo + 26), r10(7 * len(title) + 10))
        n = max(len(self.ins), len(self.outs))
        X0, Y0 = 50, 50
        h = 20 * n + 16
        a = [f'<rect fill="#f4f8ff" height="{h}" stroke="#000000" stroke-width="2" '
             f'width="{self.box_w}" x="{X0}" y="{Y0}"/>']
        for i, (nm, w, _) in enumerate(self.ins):
            a.append(f'<text font-family="SansSerif" font-size="10" text-anchor="start" '
                     f'x="{X0 + 5}" y="{Y0 + 14 + 20 * i}">{escape(nm)}</text>')
        for j, (nm, w, _) in enumerate(self.outs):
            a.append(f'<text font-family="SansSerif" font-size="10" text-anchor="end" '
                     f'x="{X0 + self.box_w - 5}" y="{Y0 + 14 + 20 * j}">{escape(nm)}</text>')
        a.append(f'<text font-family="SansSerif" font-size="11" font-weight="bold" '
                 f'text-anchor="middle" x="{X0 + self.box_w // 2}" y="{Y0 + h - 4}">'
                 f'{escape(title)}</text>')
        for i, (nm, w, (px, py)) in enumerate(self.ins):
            cx, cy = X0, Y0 + 10 + 20 * i
            a.append(f'<circ-port height="8" pin="{px},{py}" width="8" x="{cx - 4}" y="{cy - 4}"/>')
        for j, (nm, w, (px, py)) in enumerate(self.outs):
            cx, cy = X0 + self.box_w, Y0 + 10 + 20 * j
            a.append(f'<circ-port height="10" pin="{px},{py}" width="10" x="{cx - 5}" y="{cy - 5}"/>')
        a.append(f'<circ-anchor facing="east" height="6" width="6" x="{X0 - 3}" y="{Y0 + 10 - 3}"/>')
        self.appear_xml = "    <appear>\n" + "\n".join("      " + s for s in a) + "\n    </appear>\n"
        self.finished = True
        return self

    def finish_top(self):
        self.check()
        self.appear_xml = ""
        self.finished = True
        return self

    def to_xml(self):
        out = [f'  <circuit name={quoteattr(self.name)}>',
               f'    <a name="circuit" val={quoteattr(self.name)}/>',
               '    <a name="clabel" val=""/>',
               '    <a name="clabelup" val="east"/>',
               '    <a name="clabelfont" val="SansSerif plain 12"/>']
        if self.appear_xml:
            out.append(self.appear_xml.rstrip("\n"))
        for (a, b) in self.wires:
            if a != b:
                out.append(f'    <wire from="({a[0]},{a[1]})" to="({b[0]},{b[1]})"/>')
        for it in self.items:
            out.append("    " + it)
        out.append("  </circuit>")
        return "\n".join(out)


def comp_xml(lib, name, loc, attrs):
    head = (f'<comp lib="{lib}" loc="({loc[0]},{loc[1]})" name={quoteattr(name)}>'
            if lib is not None else f'<comp loc="({loc[0]},{loc[1]})" name={quoteattr(name)}>')
    if not attrs:
        return head[:-1] + "/>"
    lines = [head]
    for k, v in attrs:
        if k == "contents":
            lines.append(f'      <a name="contents">{escape(str(v))}</a>')
        else:
            lines.append(f'      <a name="{k}" val={quoteattr(str(v))}/>')
    lines.append("    </comp>")
    return "\n".join(lines)


def rom_contents(aw, dw, words):
    n = 1 << aw
    words = list(words) + [0] * (n - len(words))
    last = max([i for i, v in enumerate(words) if v] + [-1])
    body = words[: last + 1]
    lines = [f"addr/data: {aw} {dw}"]
    for i in range(0, len(body), 8):
        lines.append(" ".join(f"{v:x}" for v in body[i:i + 8]))
    return "\n".join(lines) + "\n"


def project_xml(circuits, main):
    hdr = f'''<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<project source="2.7.1" version="1.0">
This file is intended to be loaded by Logisim (http://www.cburch.com/logisim/).
  <lib desc="#Wiring" name="{LIB_WIRING}"/>
  <lib desc="#Gates" name="{LIB_GATES}"/>
  <lib desc="#Memory" name="{LIB_MEM}"/>
  <lib desc="#Base" name="{LIB_BASE}">
    <tool name="Text Tool">
      <a name="text" val=""/>
      <a name="font" val="SansSerif plain 12"/>
      <a name="halign" val="center"/>
      <a name="valign" val="base"/>
    </tool>
  </lib>
  <main name={quoteattr(main)}/>
  <options>
    <a name="gateUndefined" val="ignore"/>
    <a name="simlimit" val="1000"/>
    <a name="simrand" val="0"/>
  </options>
  <mappings>
    <tool lib="{LIB_BASE}" map="Button2" name="Menu Tool"/>
    <tool lib="{LIB_BASE}" map="Button3" name="Menu Tool"/>
    <tool lib="{LIB_BASE}" map="Ctrl Button1" name="Menu Tool"/>
  </mappings>
  <toolbar>
    <tool lib="{LIB_BASE}" name="Poke Tool"/>
    <tool lib="{LIB_BASE}" name="Edit Tool"/>
    <tool lib="{LIB_BASE}" name="Text Tool"/>
    <sep/>
    <tool lib="{LIB_WIRING}" name="Pin">
      <a name="tristate" val="false"/>
    </tool>
    <tool lib="{LIB_WIRING}" name="Pin">
      <a name="facing" val="west"/>
      <a name="output" val="true"/>
      <a name="labelloc" val="east"/>
    </tool>
    <tool lib="{LIB_GATES}" name="NOT Gate"/>
    <tool lib="{LIB_GATES}" name="AND Gate"/>
    <tool lib="{LIB_GATES}" name="OR Gate"/>
  </toolbar>
'''
    body = "\n".join(c.to_xml() for c in circuits)
    return hdr + body + "\n</project>\n"
