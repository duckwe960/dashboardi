#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FisiSketch — editor interativo de esquemas de física
=====================================================
Requisitos: apenas Python 3.8+ (o tkinter já vem junto no Windows/macOS).
  Linux: se faltar o tkinter ->  sudo apt install python3-tk

Rodar:   python fisisketch.py

Como usar
---------
• Escolha um componente na barra da esquerda e clique no quadro.
  Componentes de dois pontos (mola, vetor, cota, superfície, haste...) são
  criados ARRASTANDO do ponto inicial até o final.
• "Selecionar" (tecla Esc): clique para selecionar, arraste para mover,
  arraste as alças azuis para esticar / girar / redimensionar.
• Edite tudo no painel da direita: rótulos, cores, espiras, raios, ângulos,
  coordenadas exatas...
• Rótulos aceitam uma notação estilo LaTeX simplificada:
      x_M    m_{c}    e^2    \\theta   \\mu   \\omega   \\hat{e}_1   \\vec{F}   \\dot{x}
• Atalhos: Del apaga · Ctrl+Z / Ctrl+Y desfaz/refaz · Ctrl+D duplica
           setas movem 1 px (Shift = 10 px) · Ctrl+S salva · Ctrl+O abre
           PageUp / PageDown mudam a ordem (frente / trás)
• Arquivo → Exportar SVG (vetorial; ótimo para LaTeX, Word, Inkscape) ou EPS.
• Os esquemas são salvos em JSON, então dá para editar/gerar por script também.
"""

import copy
import json
import math
import re
import unicodedata

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, colorchooser, filedialog, messagebox

# ==========================================================================
# Texto com índices e símbolos: "x_M", "m_{c}", "e^2", "\theta", "\hat{e}_1"
# ==========================================================================
GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "kappa": "κ", "lambda": "λ",
    "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ",
    "tau": "τ", "phi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω", "ell": "ℓ",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Pi": "Π",
    "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "cdot": "·", "times": "×", "pm": "±", "infty": "∞", "deg": "°",
}


def latexish(s):
    s = str(s)
    for k in sorted(GREEK, key=len, reverse=True):
        s = s.replace("\\" + k, GREEK[k])
    s = re.sub(r"\\hat\{([^}]*)\}", lambda m: m.group(1) + "\u0302", s)
    s = re.sub(r"\\vec\{([^}]*)\}", lambda m: m.group(1) + "\u20d7", s)
    s = re.sub(r"\\dot\{([^}]*)\}", lambda m: m.group(1) + "\u0307", s)
    s = re.sub(r"\\ddot\{([^}]*)\}", lambda m: m.group(1) + "\u0308", s)
    return unicodedata.normalize("NFC", s)


def parse_rich(s):
    """Divide o texto em segmentos (texto, modo): 0 normal, 1 subscrito, 2 sobrescrito."""
    s = latexish(s)
    segs, buf, i = [], "", 0
    while i < len(s):
        c = s[i]
        if c in "_^" and i + 1 < len(s):
            if buf:
                segs.append((buf, 0))
                buf = ""
            mode = 1 if c == "_" else 2
            if s[i + 1] == "{":
                j = s.find("}", i + 2)
                j = len(s) if j == -1 else j
                segs.append((s[i + 2:j], mode))
                i = j + 1
            else:
                j = i + 2
                while j < len(s) and unicodedata.combining(s[j]):
                    j += 1
                segs.append((s[i + 1:j], mode))
                i = j
        else:
            buf += c
            i += 1
    if buf:
        segs.append((buf, 0))
    return segs


def seg_style(size, mode):
    """(tamanho da fonte, deslocamento vertical) de um segmento."""
    if mode == 0:
        return size, 0.0
    return size * 0.7, (size * 0.35 if mode == 1 else -size * 0.45)


# ==========================================================================
# Geometria e primitivas de desenho (independentes do tkinter)
# ==========================================================================
def unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return 1.0, 0.0, 0.0
    return dx / L, dy / L, L


def up_normal(ux, uy):
    """Normal à direção (ux, uy) apontando 'para cima' (ou para a esquerda se vertical)."""
    nx, ny = -uy, ux
    if ny > 1e-9 or (abs(ny) <= 1e-9 and nx > 0):
        nx, ny = -nx, -ny
    return nx, ny


def arrow_dims(width):
    return 9 + 2.2 * width, 3.5 + 1.3 * width


def Ln(pts, color="#000000", width=1.5, dash=False, arrow="none"):
    return {"t": "line", "pts": [tuple(p) for p in pts], "color": color,
            "width": float(width), "dash": bool(dash), "arrow": arrow}


def Pg(pts, outline="#000000", fill="", width=1.5):
    return {"t": "poly", "pts": [tuple(p) for p in pts], "outline": outline,
            "fill": fill, "width": float(width)}


def Ov(cx, cy, r, outline="#000000", fill="", width=1.5):
    return {"t": "oval", "cx": cx, "cy": cy, "r": float(r), "outline": outline,
            "fill": fill, "width": float(width)}


def Tx(x, y, s, size=16, color="#000000", anchor="c", italic=True):
    return {"t": "text", "x": x, "y": y, "s": str(s), "size": float(size),
            "color": color, "anchor": anchor, "italic": bool(italic)}


def hatch(a, b, side, spacing, length, angle, color, width):
    """Hachuras ao longo do segmento a-b, do lado 'side' (+1 / -1)."""
    ux, uy, Lt = unit(a, b)
    nx, ny = -uy * side, ux * side
    ang = math.radians(angle)
    dx = math.cos(ang) * nx - math.sin(ang) * ux
    dy = math.cos(ang) * ny - math.sin(ang) * uy
    out, k, spacing = [], 0.0, max(2.0, float(spacing))
    while k <= Lt + 1e-6:
        qx, qy = a[0] + ux * k, a[1] + uy * k
        out.append(Ln([(qx, qy), (qx + dx * length, qy + dy * length)], color, width))
        k += spacing
    return out


# ==========================================================================
# Componentes
# ==========================================================================
SHAPES = {}


def register(cls):
    SHAPES[cls.kind] = cls
    return cls


STYLE = [("cor", "Cor do traço", "color"), ("espessura", "Espessura", "float")]


class Shape:
    kind = "base"
    title = "Forma"
    points = []          # pares de chaves (x, y) que viram alças arrastáveis
    template = [(0, 0)]  # posição padrão das alças ao criar
    drag_handle = None   # alça que acompanha o mouse na criação (None = só clique)
    defaults = {}
    specs = []           # (chave, rótulo, tipo) mostrados no painel
    _next_uid = 1

    def __init__(self, props=None):
        self.p = copy.deepcopy(self.defaults)
        if props:
            self.p.update(props)
        self.uid = Shape._next_uid
        Shape._next_uid += 1

    @classmethod
    def create_at(cls, x, y):
        s = cls()
        for (xk, yk), (dx, dy) in zip(cls.points, cls.template):
            s.p[xk], s.p[yk] = x + dx, y + dy
        return s

    def pt(self, i):
        xk, yk = self.points[i]
        return (self.p[xk], self.p[yk])

    def handles(self):
        return [self.pt(i) for i in range(len(self.points))]

    def set_handle(self, i, x, y):
        xk, yk = self.points[i]
        self.p[xk], self.p[yk] = x, y

    def translate(self, dx, dy):
        for xk, yk in self.points:
            self.p[xk] += dx
            self.p[yk] += dy

    def after_create_drag(self):
        pass

    def guides(self):
        """Linhas auxiliares mostradas só quando selecionado."""
        return []

    def prims(self):
        return []

    def to_dict(self):
        return {"kind": self.kind, "props": copy.deepcopy(self.p)}


def shape_from_dict(d):
    cls = SHAPES[d["kind"]]
    return cls(d.get("props", {}))


# --------------------------------------------------------------------------
@register
class Bloco(Shape):
    kind, title = "bloco", "Bloco / massa"
    points = [("x1", "y1"), ("x2", "y2")]
    template = [(0, 0), (140, 60)]
    drag_handle = 1
    defaults = dict(x1=0, y1=0, x2=0, y2=0, rotulo="M", fonte=18,
                    posicao_rotulo="centro", preenchimento="#e3e3e3",
                    cor="#000000", espessura=1.5)
    specs = [("rotulo", "Rótulo", "text"),
             ("fonte", "Tamanho do rótulo", "float"),
             ("posicao_rotulo", "Posição do rótulo",
              ("choice", ["centro", "acima", "abaixo", "canto superior"])),
             ("preenchimento", "Preenchimento", "color")] + STYLE

    def prims(self):
        p = self.p
        x1, x2 = sorted((p["x1"], p["x2"]))
        y1, y2 = sorted((p["y1"], p["y2"]))
        out = [Pg([(x1, y1), (x2, y1), (x2, y2), (x1, y2)],
                  p["cor"], p["preenchimento"], p["espessura"])]
        f, pos, cx = p["fonte"], p["posicao_rotulo"], (x1 + x2) / 2
        if pos == "acima":
            out.append(Tx(cx, y1 - f * 0.8, p["rotulo"], f, p["cor"]))
        elif pos == "abaixo":
            out.append(Tx(cx, y2 + f * 0.8, p["rotulo"], f, p["cor"]))
        elif pos == "canto superior":
            out.append(Tx(x2 - 6, y1 + f * 0.75, p["rotulo"], f, p["cor"], "e"))
        else:
            out.append(Tx(cx, (y1 + y2) / 2, p["rotulo"], f, p["cor"]))
        return out


# --------------------------------------------------------------------------
@register
class Disco(Shape):
    kind, title = "disco", "Disco / roda / partícula"
    points = [("cx", "cy"), ("rx", "ry")]
    template = [(0, 0), (45, 0)]
    drag_handle = 1
    defaults = dict(cx=0, cy=0, rx=0, ry=0, rotulo="m", rotulo_raio="r",
                    fonte=16, mostrar_raio=True, mostrar_centro=True,
                    preenchimento="#dcdcdc", cor="#000000", espessura=1.5)
    specs = [("rotulo", "Rótulo", "text"),
             ("rotulo_raio", "Rótulo do raio", "text"),
             ("fonte", "Tamanho do rótulo", "float"),
             ("mostrar_raio", "Mostrar raio", "bool"),
             ("mostrar_centro", "Mostrar centro", "bool"),
             ("preenchimento", "Preenchimento", "color")] + STYLE

    def prims(self):
        p = self.p
        c, e = (p["cx"], p["cy"]), (p["rx"], p["ry"])
        ux, uy, r = unit(c, e)
        f = p["fonte"]
        out = [Ov(c[0], c[1], max(r, 1), p["cor"], p["preenchimento"], p["espessura"])]
        if p["mostrar_raio"] and r > 2:
            out.append(Ln([c, e], p["cor"], max(1.0, p["espessura"] * 0.8)))
            nx, ny = up_normal(ux, uy)
            out.append(Tx((c[0] + e[0]) / 2 + nx * f * 0.65,
                          (c[1] + e[1]) / 2 + ny * f * 0.65,
                          p["rotulo_raio"], f * 0.9, p["cor"]))
        if p["mostrar_centro"]:
            out.append(Ov(c[0], c[1], 2.5, p["cor"], p["cor"], 1))
        d = r * 0.7071
        out.append(Tx(c[0] + d + 4, c[1] - d - f * 0.4, p["rotulo"], f, p["cor"], "w"))
        return out


# --------------------------------------------------------------------------
def spring_points(a, b, coils, w, end, style):
    ux, uy, Lt = unit(a, b)
    if Lt < 1e-6:
        return [a, b]
    nx, ny = -uy, ux
    end = max(0.0, min(end, Lt * 0.3))
    Le = Lt - 2 * end
    s = (a[0] + ux * end, a[1] + uy * end)
    pts = [a, s]
    n_coils = max(1, int(coils))
    if style == "zigue-zague":
        n = n_coils * 2
        for i in range(n):
            t, sg = (i + 0.5) / n, (1 if i % 2 == 0 else -1)
            pts.append((s[0] + ux * Le * t + nx * sg * w / 2,
                        s[1] + uy * Le * t + ny * sg * w / 2))
    else:  # espiral (laços), como nos livros
        steps, amp = n_coils * 24, w * 0.35
        for i in range(1, steps + 1):
            t = i / steps
            th = 2 * math.pi * n_coils * t
            along = Le * t - amp * (1 - math.cos(th))
            perp = (w / 2) * math.sin(th)
            pts.append((s[0] + ux * along + nx * perp, s[1] + uy * along + ny * perp))
    pts.append((a[0] + ux * (end + Le), a[1] + uy * (end + Le)))
    pts.append(b)
    return pts


@register
class Mola(Shape):
    kind, title = "mola", "Mola"
    points = [("x1", "y1"), ("x2", "y2")]
    template = [(0, 0), (120, 0)]
    drag_handle = 1
    defaults = dict(x1=0, y1=0, x2=0, y2=0, rotulo="k", fonte=16,
                    lado_rotulo="acima", estilo="espiral", espiras=7,
                    largura=16, pontas=12, cor="#000000", espessura=1.4)
    specs = [("rotulo", "Rótulo", "text"),
             ("fonte", "Tamanho do rótulo", "float"),
             ("lado_rotulo", "Lado do rótulo", ("choice", ["acima", "abaixo", "nenhum"])),
             ("estilo", "Estilo", ("choice", ["espiral", "zigue-zague"])),
             ("espiras", "Nº de espiras", "int"),
             ("largura", "Largura", "float"),
             ("pontas", "Trecho reto nas pontas", "float")] + STYLE

    def prims(self):
        p = self.p
        a, b = self.pt(0), self.pt(1)
        out = [Ln(spring_points(a, b, p["espiras"], p["largura"], p["pontas"], p["estilo"]),
                  p["cor"], p["espessura"])]
        if p["lado_rotulo"] != "nenhum":
            ux, uy, _ = unit(a, b)
            nx, ny = up_normal(ux, uy)
            sg = 1 if p["lado_rotulo"] == "acima" else -1
            d = p["largura"] / 2 + p["fonte"] * 0.75
            out.append(Tx((a[0] + b[0]) / 2 + nx * d * sg, (a[1] + b[1]) / 2 + ny * d * sg,
                          p["rotulo"], p["fonte"], p["cor"]))
        return out


# --------------------------------------------------------------------------
@register
class Amortecedor(Shape):
    kind, title = "amortecedor", "Amortecedor"
    points = [("x1", "y1"), ("x2", "y2")]
    template = [(0, 0), (120, 0)]
    drag_handle = 1
    defaults = dict(x1=0, y1=0, x2=0, y2=0, rotulo="c", fonte=16,
                    lado_rotulo="acima", largura=18, cor="#000000", espessura=1.5)
    specs = [("rotulo", "Rótulo", "text"),
             ("fonte", "Tamanho do rótulo", "float"),
             ("lado_rotulo", "Lado do rótulo", ("choice", ["acima", "abaixo", "nenhum"])),
             ("largura", "Largura", "float")] + STYLE

    def prims(self):
        p = self.p
        a, b = self.pt(0), self.pt(1)
        ux, uy, Lt = unit(a, b)
        nx, ny = -uy, ux
        w, col, wd = p["largura"], p["cor"], p["espessura"]

        def at(t, s=0.0):
            return (a[0] + ux * Lt * t + nx * s, a[1] + uy * Lt * t + ny * s)

        out = [Ln([a, at(0.3)], col, wd),
               Ln([at(0.3, -w / 2), at(0.3, w / 2)], col, wd),
               Ln([at(0.3, -w / 2), at(0.68, -w / 2)], col, wd),
               Ln([at(0.3, w / 2), at(0.68, w / 2)], col, wd),
               Ln([at(0.5, -w * 0.38), at(0.5, w * 0.38)], col, wd * 1.8),
               Ln([at(0.5), b], col, wd)]
        if p["lado_rotulo"] != "nenhum":
            un = up_normal(ux, uy)
            sg = 1 if p["lado_rotulo"] == "acima" else -1
            d = w / 2 + p["fonte"] * 0.75
            m = at(0.49)
            out.append(Tx(m[0] + un[0] * d * sg, m[1] + un[1] * d * sg,
                          p["rotulo"], p["fonte"], col))
        return out


# --------------------------------------------------------------------------
@register
class Haste(Shape):
    kind, title = "haste", "Haste / pêndulo"
    points = [("x1", "y1"), ("x2", "y2")]
    template = [(0, 0), (40, 110)]
    drag_handle = 1
    defaults = dict(x1=0, y1=0, x2=0, y2=0, rotulo_haste="L", rotulo_massa="m",
                    fonte=16, raio_massa=9, preenchimento="#000000",
                    mostrar_pivo=True, tracejada=False, cor="#000000", espessura=2)
    specs = [("rotulo_haste", "Rótulo da haste", "text"),
             ("rotulo_massa", "Rótulo da massa", "text"),
             ("fonte", "Tamanho do rótulo", "float"),
             ("raio_massa", "Raio da massa (0 = sem)", "float"),
             ("preenchimento", "Cor da massa", "color"),
             ("mostrar_pivo", "Mostrar pivô", "bool"),
             ("tracejada", "Tracejada", "bool")] + STYLE

    def prims(self):
        p = self.p
        a, b = self.pt(0), self.pt(1)
        f, r = p["fonte"], max(0.0, p["raio_massa"])
        out = [Ln([a, b], p["cor"], p["espessura"], p["tracejada"])]
        if r > 0:
            out.append(Ov(b[0], b[1], r, p["cor"], p["preenchimento"], 1))
        if p["mostrar_pivo"]:
            out.append(Ov(a[0], a[1], 4, p["cor"], "#ffffff", 1.2))
        ux, uy, _ = unit(a, b)
        nx, ny = up_normal(ux, uy)
        out.append(Tx((a[0] + b[0]) / 2 + nx * f * 0.7, (a[1] + b[1]) / 2 + ny * f * 0.7,
                      p["rotulo_haste"], f, p["cor"]))
        out.append(Tx(b[0] + r + 5, b[1] + r * 0.3, p["rotulo_massa"], f, p["cor"], "w"))
        return out


# --------------------------------------------------------------------------
def bezier(a, c, b, n=48):
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        pts.append((u * u * a[0] + 2 * u * t * c[0] + t * t * b[0],
                    u * u * a[1] + 2 * u * t * c[1] + t * t * b[1]))
    return pts


@register
class Corda(Shape):
    kind, title = "corda", "Corda / curva / trajetória"
    points = [("x1", "y1"), ("cx", "cy"), ("x2", "y2")]
    template = [(0, 0), (60, -50), (120, 0)]
    drag_handle = 2
    defaults = dict(x1=0, y1=0, cx=0, cy=0, x2=0, y2=0, rotulo="", fonte=16,
                    seta="nenhuma", tracejada=False, cor="#7f8c8d", espessura=3)
    specs = [("rotulo", "Rótulo", "text"),
             ("fonte", "Tamanho do rótulo", "float"),
             ("seta", "Seta", ("choice", ["nenhuma", "fim", "início", "ambas"])),
             ("tracejada", "Tracejada", "bool")] + STYLE

    def after_create_drag(self):
        a, b = self.pt(0), self.pt(2)
        ux, uy, L = unit(a, b)
        nx, ny = up_normal(ux, uy)
        self.set_handle(1, (a[0] + b[0]) / 2 + nx * L * 0.3, (a[1] + b[1]) / 2 + ny * L * 0.3)

    def guides(self):
        return [Ln([self.pt(0), self.pt(1), self.pt(2)], "#93c5fd", 1, True)]

    def prims(self):
        p = self.p
        arrow = {"nenhuma": "none", "fim": "last", "início": "first", "ambas": "both"}[p["seta"]]
        pts = bezier(self.pt(0), self.pt(1), self.pt(2))
        out = [Ln(pts, p["cor"], p["espessura"], p["tracejada"], arrow)]
        if p["rotulo"]:
            m = pts[len(pts) // 2]
            ux, uy, _ = unit(pts[len(pts) // 2 - 1], pts[len(pts) // 2 + 1])
            nx, ny = up_normal(ux, uy)
            out.append(Tx(m[0] + nx * p["fonte"] * 0.8, m[1] + ny * p["fonte"] * 0.8,
                          p["rotulo"], p["fonte"], p["cor"]))
        return out


# --------------------------------------------------------------------------
@register
class Superficie(Shape):
    kind, title = "superficie", "Chão / parede / teto"
    points = [("x1", "y1"), ("x2", "y2")]
    template = [(0, 0), (300, 0)]
    drag_handle = 1
    defaults = dict(x1=0, y1=0, x2=0, y2=0, lado="A", espacamento=9,
                    comprimento_hachura=8, angulo_hachura=45,
                    cor="#000000", espessura=1.8)
    specs = [("lado", "Lado da hachura", ("choice", ["A", "B"])),
             ("espacamento", "Espaçamento", "float"),
             ("comprimento_hachura", "Comprimento hachura", "float"),
             ("angulo_hachura", "Ângulo hachura (°)", "float")] + STYLE

    def prims(self):
        p = self.p
        a, b = self.pt(0), self.pt(1)
        side = 1 if p["lado"] == "A" else -1
        return [Ln([a, b], p["cor"], p["espessura"])] + hatch(
            a, b, side, p["espacamento"], p["comprimento_hachura"], p["angulo_hachura"],
            p["cor"], max(0.8, p["espessura"] * 0.55))


# --------------------------------------------------------------------------
@register
class Articulacao(Shape):
    kind, title = "articulacao", "Pino / apoio / articulação"
    points = [("x", "y")]
    template = [(0, 0)]
    defaults = dict(x=0, y=0, estilo="círculo", raio=4.5, rotulo="", fonte=15,
                    preenchimento="#ffffff", cor="#000000", espessura=1.3)
    specs = [("estilo", "Estilo",
              ("choice", ["ponto", "círculo", "apoio fixo", "apoio móvel", "teto"])),
             ("raio", "Raio do pino", "float"),
             ("rotulo", "Rótulo", "text"),
             ("fonte", "Tamanho do rótulo", "float"),
             ("preenchimento", "Preenchimento", "color")] + STYLE

    def prims(self):
        p = self.p
        x, y, r = p["x"], p["y"], max(1.0, p["raio"])
        col, w, est = p["cor"], p["espessura"], p["estilo"]
        out = []
        if est == "apoio fixo":
            h, bw = 22, 14
            out.append(Pg([(x, y), (x - bw, y + h), (x + bw, y + h)], col, p["preenchimento"], w))
            a, b = (x - bw - 6, y + h), (x + bw + 6, y + h)
            out += [Ln([a, b], col, w)] + hatch(a, b, 1, 6, 7, 45, col, 1)
        elif est == "apoio móvel":
            h, bw, rr = 16, 13, 3.5
            out.append(Pg([(x, y), (x - bw, y + h), (x + bw, y + h)], col, p["preenchimento"], w))
            out.append(Ov(x - 7, y + h + rr, rr, col, p["preenchimento"], w))
            out.append(Ov(x + 7, y + h + rr, rr, col, p["preenchimento"], w))
            a, b = (x - bw - 6, y + h + 2 * rr), (x + bw + 6, y + h + 2 * rr)
            out += [Ln([a, b], col, w)] + hatch(a, b, 1, 6, 7, 45, col, 1)
        elif est == "teto":
            a, b = (x - 22, y), (x + 22, y)
            out += [Ln([a, b], col, w * 1.3)] + hatch(a, b, -1, 6, 7, 45, col, 1)
        if est == "ponto":
            out.append(Ov(x, y, r, col, col, 1))
        elif est != "teto":
            out.append(Ov(x, y, r, col, p["preenchimento"], w))
        if p["rotulo"]:
            out.append(Tx(x + r + 8, y - r - 8, p["rotulo"], p["fonte"], col, "w"))
        return out


# --------------------------------------------------------------------------
@register
class Vetor(Shape):
    kind, title = "vetor", "Vetor / força / seta"
    points = [("x1", "y1"), ("x2", "y2")]
    template = [(0, 0), (80, 0)]
    drag_handle = 1
    defaults = dict(x1=0, y1=0, x2=0, y2=0, rotulo="\\vec{F}", fonte=16,
                    posicao_rotulo="ponta", tracejado=False,
                    cor="#c0392b", espessura=2)
    specs = [("rotulo", "Rótulo", "text"),
             ("fonte", "Tamanho do rótulo", "float"),
             ("posicao_rotulo", "Posição do rótulo",
              ("choice", ["ponta", "meio", "meio (outro lado)", "base"])),
             ("tracejado", "Tracejado", "bool")] + STYLE

    def prims(self):
        p = self.p
        a, b = self.pt(0), self.pt(1)
        ux, uy, _ = unit(a, b)
        nx, ny = up_normal(ux, uy)
        f, pos = p["fonte"], p["posicao_rotulo"]
        out = [Ln([a, b], p["cor"], p["espessura"], p["tracejado"], "last")]
        if pos == "ponta":
            tx, ty = b[0] + ux * f * 0.8, b[1] + uy * f * 0.8
        elif pos == "base":
            tx, ty = a[0] - ux * f * 0.8, a[1] - uy * f * 0.8
        else:
            sg = 1 if pos == "meio" else -1
            tx = (a[0] + b[0]) / 2 + nx * f * 0.75 * sg
            ty = (a[1] + b[1]) / 2 + ny * f * 0.75 * sg
        out.append(Tx(tx, ty, p["rotulo"], f, p["cor"]))
        return out


# --------------------------------------------------------------------------
@register
class Cota(Shape):
    kind, title = "cota", "Cota / distância"
    points = [("x1", "y1"), ("x2", "y2")]
    template = [(0, 0), (150, 0)]
    drag_handle = 1
    defaults = dict(x1=0, y1=0, x2=0, y2=0, rotulo="x", fonte=16,
                    lado_rotulo="acima", marcas=True, cor="#000000", espessura=1.1)
    specs = [("rotulo", "Rótulo", "text"),
             ("fonte", "Tamanho do rótulo", "float"),
             ("lado_rotulo", "Lado do rótulo", ("choice", ["acima", "abaixo"])),
             ("marcas", "Marcas nas pontas", "bool")] + STYLE

    def prims(self):
        p = self.p
        a, b = self.pt(0), self.pt(1)
        ux, uy, _ = unit(a, b)
        nx, ny = up_normal(ux, uy)
        out = [Ln([a, b], p["cor"], p["espessura"], False, "both")]
        if p["marcas"]:
            for q in (a, b):
                out.append(Ln([(q[0] + nx * 7, q[1] + ny * 7), (q[0] - nx * 7, q[1] - ny * 7)],
                              p["cor"], p["espessura"]))
        sg = 1 if p["lado_rotulo"] == "acima" else -1
        d = p["fonte"] * 0.75 * sg
        out.append(Tx((a[0] + b[0]) / 2 + nx * d, (a[1] + b[1]) / 2 + ny * d,
                      p["rotulo"], p["fonte"], p["cor"]))
        return out


# --------------------------------------------------------------------------
@register
class Angulo(Shape):
    kind, title = "angulo", "Ângulo (arco)"
    points = [("cx", "cy")]
    template = [(0, 0)]
    defaults = dict(cx=0, cy=0, raio=35, inicio=0, extensao=45, rotulo="\\theta",
                    fonte=16, seta=True, mostrar_lados=False, comprimento_lados=70,
                    cor="#000000", espessura=1.2)
    specs = [("rotulo", "Rótulo", "text"),
             ("fonte", "Tamanho do rótulo", "float"),
             ("raio", "Raio", "float"),
             ("inicio", "Ângulo inicial (°)", "float"),
             ("extensao", "Abertura (°, + anti-horário)", "float"),
             ("seta", "Seta no fim", "bool"),
             ("mostrar_lados", "Desenhar os lados", "bool"),
             ("comprimento_lados", "Comprimento dos lados", "float")] + STYLE

    def prims(self):
        p = self.p
        cx, cy, r = p["cx"], p["cy"], max(2.0, p["raio"])
        a0, ext = p["inicio"], p["extensao"]
        n = max(8, int(abs(ext) / 3))
        pts = []
        for i in range(n + 1):
            a = math.radians(a0 + ext * i / n)
            pts.append((cx + r * math.cos(a), cy - r * math.sin(a)))
        out = []
        if p["mostrar_lados"]:
            for ang in (a0, a0 + ext):
                a = math.radians(ang)
                L = p["comprimento_lados"]
                out.append(Ln([(cx, cy), (cx + L * math.cos(a), cy - L * math.sin(a))],
                              p["cor"], p["espessura"], True))
        out.append(Ln(pts, p["cor"], p["espessura"], False, "last" if p["seta"] else "none"))
        am = math.radians(a0 + ext / 2)
        rr = r + p["fonte"] * 0.8
        out.append(Tx(cx + rr * math.cos(am), cy - rr * math.sin(am), p["rotulo"], p["fonte"], p["cor"]))
        return out


# --------------------------------------------------------------------------
@register
class Eixos(Shape):
    kind, title = "eixos", "Sistema de eixos"
    points = [("x", "y")]
    template = [(0, 0)]
    defaults = dict(x=0, y=0, comprimento=45, rotulo_x="\\hat{e}_1",
                    rotulo_y="\\hat{e}_2", terceiro_eixo=False, rotulo_z="\\hat{e}_3",
                    fonte=15, cor="#000000", espessura=1.4)
    specs = [("comprimento", "Comprimento", "float"),
             ("rotulo_x", "Rótulo horizontal", "text"),
             ("rotulo_y", "Rótulo vertical", "text"),
             ("terceiro_eixo", "Terceiro eixo (diagonal)", "bool"),
             ("rotulo_z", "Rótulo 3º eixo", "text"),
             ("fonte", "Tamanho do rótulo", "float")] + STYLE

    def prims(self):
        p = self.p
        x, y, L, f, c, w = p["x"], p["y"], p["comprimento"], p["fonte"], p["cor"], p["espessura"]
        out = [Ln([(x, y), (x + L, y)], c, w, False, "last"),
               Ln([(x, y), (x, y - L)], c, w, False, "last"),
               Tx(x + L + f * 0.8, y, p["rotulo_x"], f, c),
               Tx(x, y - L - f * 0.8, p["rotulo_y"], f, c)]
        if p["terceiro_eixo"]:
            d = L * 0.65
            out += [Ln([(x, y), (x - d, y + d)], c, w, False, "last"),
                    Tx(x - d - f * 0.6, y + d + f * 0.6, p["rotulo_z"], f, c)]
        return out


# --------------------------------------------------------------------------
@register
class Texto(Shape):
    kind, title = "texto", "Texto / equação"
    points = [("x", "y")]
    template = [(0, 0)]
    defaults = dict(x=0, y=0, texto="\\mu = 0", fonte=18, italico=True,
                    ancora="centro", cor="#000000")
    specs = [("texto", "Texto", "text"),
             ("fonte", "Tamanho", "float"),
             ("italico", "Itálico", "bool"),
             ("ancora", "Alinhamento", ("choice", ["centro", "esquerda", "direita"])),
             ("cor", "Cor", "color")]

    def prims(self):
        p = self.p
        an = {"centro": "c", "esquerda": "w", "direita": "e"}[p["ancora"]]
        return [Tx(p["x"], p["y"], p["texto"], p["fonte"], p["cor"], an, p["italico"])]


# ==========================================================================
# Exportação SVG (vetorial)
# ==========================================================================
SVG_FONTS = "'Times New Roman', 'Liberation Serif', 'DejaVu Serif', serif"


def _esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _svg_color(c, empty_ok=True):
    c = str(c or "").strip()
    if c.lower() in ("", "none", "transparente"):
        return "none" if empty_ok else "#000000"
    return c


def _text_width_estimate(pr):
    w = 0.0
    for txt, mode in parse_rich(pr["s"]):
        fs, _ = seg_style(pr["size"], mode)
        w += len(txt) * fs * 0.55
    return w


def prims_bbox(prims):
    xs, ys = [], []
    for pr in prims:
        if pr["t"] in ("line", "poly"):
            for x, y in pr["pts"]:
                xs.append(x)
                ys.append(y)
        elif pr["t"] == "oval":
            xs += [pr["cx"] - pr["r"], pr["cx"] + pr["r"]]
            ys += [pr["cy"] - pr["r"], pr["cy"] + pr["r"]]
        elif pr["t"] == "text" and pr["s"].strip():
            w = _text_width_estimate(pr)
            x0 = {"c": pr["x"] - w / 2, "w": pr["x"], "e": pr["x"] - w}[pr["anchor"]]
            xs += [x0, x0 + w]
            ys += [pr["y"] - pr["size"], pr["y"] + pr["size"]]
    if not xs:
        return 0, 0, 100, 100
    return min(xs), min(ys), max(xs), max(ys)


def _svg_arrowhead(tip, prev, w, color):
    ux, uy, _ = unit(prev, tip)
    hl, hw = arrow_dims(w)
    bx, by = tip[0] - ux * hl, tip[1] - uy * hl
    pts = [tip, (bx - uy * hw, by + ux * hw), (bx + uy * hw, by - ux * hw)]
    return ('<polygon points="%s" fill="%s" stroke="none"/>'
            % (" ".join("%.2f,%.2f" % q for q in pts), color)), (tip[0] - ux * hl * 0.85,
                                                                 tip[1] - uy * hl * 0.85)


def svg_document(shapes, margin=15):
    allp = [pr for s in shapes for pr in s.prims()]
    x0, y0, x1, y1 = prims_bbox(allp)
    x0, y0, x1, y1 = x0 - margin, y0 - margin, x1 + margin, y1 + margin
    W, H = x1 - x0, y1 - y0
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<svg xmlns="http://www.w3.org/2000/svg" width="%.0f" height="%.0f" '
           'viewBox="%.2f %.2f %.2f %.2f">' % (W, H, x0, y0, W, H),
           '<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="white"/>' % (x0, y0, W, H)]
    for pr in allp:
        t = pr["t"]
        if t == "line":
            pts = list(pr["pts"])
            if len(pts) < 2:
                continue
            col = _svg_color(pr["color"], False)
            heads = []
            if pr["arrow"] in ("last", "both"):
                h, pts[-1] = _svg_arrowhead(pts[-1], pts[-2], pr["width"], col)
                heads.append(h)
            if pr["arrow"] in ("first", "both"):
                h, pts[0] = _svg_arrowhead(pts[0], pts[1], pr["width"], col)
                heads.append(h)
            dash = ' stroke-dasharray="6 4"' if pr["dash"] else ""
            out.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="%.2f" '
                       'stroke-linecap="round" stroke-linejoin="round"%s/>'
                       % (" ".join("%.2f,%.2f" % q for q in pts), col, pr["width"], dash))
            out += heads
        elif t == "poly":
            out.append('<polygon points="%s" fill="%s" stroke="%s" stroke-width="%.2f" '
                       'stroke-linejoin="round"/>'
                       % (" ".join("%.2f,%.2f" % q for q in pr["pts"]),
                          _svg_color(pr["fill"]), _svg_color(pr["outline"]), pr["width"]))
        elif t == "oval":
            out.append('<circle cx="%.2f" cy="%.2f" r="%.2f" fill="%s" stroke="%s" '
                       'stroke-width="%.2f"/>' % (pr["cx"], pr["cy"], pr["r"],
                                                  _svg_color(pr["fill"]),
                                                  _svg_color(pr["outline"]), pr["width"]))
        elif t == "text" and pr["s"].strip():
            anchor = {"c": "middle", "w": "start", "e": "end"}[pr["anchor"]]
            style = "italic" if pr["italic"] else "normal"
            s = ('<text x="%.2f" y="%.2f" font-family="%s" font-size="%.2f" fill="%s" '
                 'text-anchor="%s" dominant-baseline="central" font-style="%s">'
                 % (pr["x"], pr["y"], SVG_FONTS, pr["size"], _svg_color(pr["color"], False),
                    anchor, style))
            cur = 0.0
            for txt, mode in parse_rich(pr["s"]):
                fs, off = seg_style(pr["size"], mode)
                s += '<tspan dy="%.2f" font-size="%.2f">%s</tspan>' % (off - cur, fs, _esc(txt))
                cur = off
            out.append(s + "</text>")
    out.append("</svg>")
    return "\n".join(out)


# ==========================================================================
# Cena de exemplo (inspirada no carrinho com disco e pêndulo)
# ==========================================================================
def example_scene():
    d = 49.5  # raio 70 a 45°
    return [
        {"kind": "superficie", "props": dict(x1=60, y1=330, x2=860, y2=330, lado="A")},
        {"kind": "superficie", "props": dict(x1=60, y1=200, x2=60, y2=330, lado="A")},
        {"kind": "superficie", "props": dict(x1=860, y1=240, x2=860, y2=330, lado="B")},
        {"kind": "mola", "props": dict(x1=60, y1=305, x2=200, y2=305, rotulo="k")},
        {"kind": "mola", "props": dict(x1=720, y1=305, x2=860, y2=305, rotulo="k")},
        {"kind": "bloco", "props": dict(x1=200, y1=290, x2=720, y2=330, rotulo="M",
                                        posicao_rotulo="canto superior")},
        {"kind": "corda", "props": dict(x1=395, y1=175, cx=640, cy=220, x2=560, y2=440)},
        {"kind": "disco", "props": dict(cx=340, cy=220, rx=340 - d, ry=220 - d,
                                        rotulo="m_c", rotulo_raio="r")},
        {"kind": "haste", "props": dict(x1=352, y1=245, x2=480, y2=312, rotulo_haste="L_p",
                                        rotulo_massa="", raio_massa=0, espessura=1.5)},
        {"kind": "haste", "props": dict(x1=480, y1=312, x2=560, y2=440, rotulo_haste="",
                                        rotulo_massa="m_p", raio_massa=9)},
        {"kind": "angulo", "props": dict(cx=480, cy=312, raio=42, inicio=-90, extensao=32,
                                         rotulo="\\phi", mostrar_lados=True,
                                         comprimento_lados=110)},
        {"kind": "articulacao", "props": dict(x=480, y=312, estilo="círculo")},
        {"kind": "texto", "props": dict(x=362, y=262, texto="d", fonte=15)},
        {"kind": "cota", "props": dict(x1=60, y1=170, x2=200, y2=170, rotulo="x_M")},
        {"kind": "cota", "props": dict(x1=60, y1=130, x2=340, y2=130, rotulo="x_c")},
        {"kind": "cota", "props": dict(x1=60, y1=490, x2=860, y2=490, rotulo="D",
                                       lado_rotulo="abaixo")},
        {"kind": "vetor", "props": dict(x1=920, y1=140, x2=920, y2=190, rotulo="g",
                                        cor="#000000", espessura=1.5)},
        {"kind": "texto", "props": dict(x=150, y=365, texto="\\mu = 0")},
        {"kind": "eixos", "props": dict(x=90, y=440)},
    ]


# ==========================================================================
# Desenho no tkinter
# ==========================================================================
FONT_CANDIDATES = ["Times New Roman", "Liberation Serif", "DejaVu Serif",
                   "Nimbus Roman", "Times"]
FONT_FAMILY = "Times"
_FONT_CACHE = {}
_COLOR_OK = {}


def get_font(px, italic):
    key = (max(6, int(round(px))), bool(italic))
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = tkfont.Font(family=FONT_FAMILY, size=-key[0],
                                       slant="italic" if key[1] else "roman")
    return _FONT_CACHE[key]


def tkcolor(widget, col, empty_ok=False):
    col = str(col or "").strip()
    if col.lower() in ("", "none", "transparente"):
        return "" if empty_ok else "#000000"
    if col not in _COLOR_OK:
        try:
            widget.winfo_rgb(col)
            _COLOR_OK[col] = True
        except tk.TclError:
            _COLOR_OK[col] = False
    return col if _COLOR_OK[col] else ("" if empty_ok else "#000000")


def tk_draw(cv, prims, tags):
    for pr in prims:
        t = pr["t"]
        if t == "line":
            flat = [v for q in pr["pts"] for v in q]
            if len(flat) < 4:
                continue
            w = max(0.5, pr["width"])
            kw = dict(fill=tkcolor(cv, pr["color"]), width=w, capstyle=tk.ROUND,
                      joinstyle=tk.ROUND, tags=tags)
            if pr["dash"]:
                kw["dash"] = (6, 4)
            if pr["arrow"] != "none":
                hl, hw = arrow_dims(w)
                kw["arrow"] = pr["arrow"]
                kw["arrowshape"] = (hl, hl, hw)
                kw["capstyle"] = tk.BUTT
            cv.create_line(*flat, **kw)
        elif t == "poly":
            flat = [v for q in pr["pts"] for v in q]
            cv.create_polygon(*flat, outline=tkcolor(cv, pr["outline"], True),
                              fill=tkcolor(cv, pr["fill"], True), width=pr["width"],
                              joinstyle=tk.ROUND, tags=tags)
        elif t == "oval":
            r = pr["r"]
            cv.create_oval(pr["cx"] - r, pr["cy"] - r, pr["cx"] + r, pr["cy"] + r,
                           outline=tkcolor(cv, pr["outline"], True),
                           fill=tkcolor(cv, pr["fill"], True), width=pr["width"], tags=tags)
        elif t == "text" and pr["s"].strip():
            segs = parse_rich(pr["s"])
            parts = []
            for txt, mode in segs:
                fs, off = seg_style(pr["size"], mode)
                f = get_font(fs, pr["italic"])
                parts.append((txt, f, off, f.measure(txt)))
            total = sum(p[3] for p in parts)
            x = {"c": pr["x"] - total / 2, "w": pr["x"], "e": pr["x"] - total}[pr["anchor"]]
            col = tkcolor(cv, pr["color"])
            for txt, f, off, w in parts:
                cv.create_text(x, pr["y"] + off, text=txt, anchor="w", font=f,
                               fill=col, tags=tags)
                x += w


# ==========================================================================
# Aplicativo
# ==========================================================================
class App:
    W, H = 2000, 1400

    def __init__(self, root):
        global FONT_FAMILY
        fams = set(tkfont.families(root))
        for f in FONT_CANDIDATES:
            if f in fams:
                FONT_FAMILY = f
                break
        self.root = root
        root.title("FisiSketch — esquemas de física")
        root.geometry("1320x800")
        self.shapes = []
        self.sel = None
        self.undo_stack, self.redo_stack = [], []
        self.filename = None
        self._drag = None
        self._edit_key = None
        self._swatches = {}
        self._first_entry = None
        self.tool_var = tk.StringVar(value="select")
        self.snap_var = tk.BooleanVar(value=True)
        self.grid_var = tk.BooleanVar(value=True)
        self.grid_size = tk.IntVar(value=10)
        self._build_menu()
        self._build_ui()
        self._bind_keys()
        self.set_scene(example_scene())

    # ---------------------------------------------------------------- UI
    def _build_menu(self):
        m = tk.Menu(self.root)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="Novo", accelerator="Ctrl+N", command=self.new)
        fm.add_command(label="Abrir…", accelerator="Ctrl+O", command=self.open)
        fm.add_command(label="Salvar", accelerator="Ctrl+S", command=self.save)
        fm.add_command(label="Salvar como…", command=lambda: self.save(True))
        fm.add_separator()
        fm.add_command(label="Exportar SVG…", command=self.export_svg)
        fm.add_command(label="Exportar EPS…", command=self.export_eps)
        fm.add_separator()
        fm.add_command(label="Carregar exemplo", command=lambda: (self.push_undo(),
                                                                 self.set_scene(example_scene())))
        fm.add_separator()
        fm.add_command(label="Sair", command=self.root.destroy)
        m.add_cascade(label="Arquivo", menu=fm)
        em = tk.Menu(m, tearoff=0)
        em.add_command(label="Desfazer", accelerator="Ctrl+Z", command=self.undo)
        em.add_command(label="Refazer", accelerator="Ctrl+Y", command=self.redo)
        em.add_separator()
        em.add_command(label="Duplicar", accelerator="Ctrl+D", command=self.duplicate)
        em.add_command(label="Excluir", accelerator="Del", command=self.delete)
        em.add_separator()
        em.add_command(label="Trazer para frente", accelerator="PgUp",
                       command=lambda: self.reorder(+1))
        em.add_command(label="Enviar para trás", accelerator="PgDn",
                       command=lambda: self.reorder(-1))
        m.add_cascade(label="Editar", menu=em)
        vm = tk.Menu(m, tearoff=0)
        vm.add_checkbutton(label="Mostrar grade", variable=self.grid_var, command=self.refresh)
        vm.add_checkbutton(label="Encaixar na grade", variable=self.snap_var)
        m.add_cascade(label="Exibir", menu=vm)
        self.root.config(menu=m)

    def _build_ui(self):
        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True)

        # --- barra de ferramentas (esquerda)
        left = ttk.Frame(main, padding=6)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Ferramentas", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(0, 4))
        tools = [("select", "↖  Selecionar / mover")] + [(k, c.title) for k, c in SHAPES.items()]
        for val, txt in tools:
            tk.Radiobutton(left, text=txt, variable=self.tool_var, value=val, indicatoron=0,
                           anchor="w", width=26, padx=8, pady=4, relief="flat",
                           selectcolor="#cfe3ff", command=self._tool_changed).pack(fill="x", pady=1)
        ttk.Separator(left).pack(fill="x", pady=8)
        ttk.Checkbutton(left, text="Mostrar grade", variable=self.grid_var,
                        command=self.refresh).pack(anchor="w")
        ttk.Checkbutton(left, text="Encaixar na grade", variable=self.snap_var).pack(anchor="w")
        gf = ttk.Frame(left)
        gf.pack(anchor="w", pady=4)
        ttk.Label(gf, text="Passo da grade:").pack(side="left")
        ttk.Spinbox(gf, from_=2, to=100, width=5, textvariable=self.grid_size,
                    command=self.refresh).pack(side="left", padx=4)
        ttk.Separator(left).pack(fill="x", pady=8)
        ttk.Label(left, foreground="#555", justify="left", wraplength=210, text=(
            "Rótulos: x_M, m_{c}, e^2,\n\\theta, \\mu, \\omega,\n\\hat{e}_1, \\vec{F}, \\dot{x}"
        )).pack(anchor="w")

        # --- painel de propriedades (direita)
        right = ttk.Frame(main, padding=(4, 6))
        right.pack(side="right", fill="y")
        ttk.Label(right, text="Propriedades", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        outer = ttk.Frame(right)
        outer.pack(fill="both", expand=True)
        self.pcanvas = tk.Canvas(outer, width=320, highlightthickness=0)
        psb = ttk.Scrollbar(outer, orient="vertical", command=self.pcanvas.yview)
        self.pframe = ttk.Frame(self.pcanvas)
        self.pcanvas.create_window((0, 0), window=self.pframe, anchor="nw")
        self.pframe.bind("<Configure>",
                         lambda e: self.pcanvas.configure(scrollregion=self.pcanvas.bbox("all")))
        self.pcanvas.configure(yscrollcommand=psb.set)
        self.pcanvas.pack(side="left", fill="both", expand=True)
        psb.pack(side="right", fill="y")

        # --- quadro de desenho (centro)
        center = ttk.Frame(main)
        center.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(center, bg="white", highlightthickness=0,
                                scrollregion=(0, 0, self.W, self.H))
        hs = ttk.Scrollbar(center, orient="horizontal", command=self.canvas.xview)
        vs = ttk.Scrollbar(center, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hs.set, yscrollcommand=vs.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        center.rowconfigure(0, weight=1)
        center.columnconfigure(0, weight=1)

        self.status = ttk.Label(self.root, anchor="w", padding=(8, 2))
        self.status.pack(fill="x", side="bottom")

        cv = self.canvas
        cv.bind("<ButtonPress-1>", self.on_press)
        cv.bind("<B1-Motion>", self.on_motion)
        cv.bind("<ButtonRelease-1>", self.on_release)
        cv.bind("<Double-Button-1>", self.on_double)
        cv.bind("<Motion>", self.on_hover)
        self.root.bind_all("<MouseWheel>", self._wheel)
        self.root.bind_all("<Shift-MouseWheel>", lambda e: self._wheel(e, horizontal=True))
        self.root.bind_all("<Button-4>", self._wheel)
        self.root.bind_all("<Button-5>", self._wheel)

    def _bind_keys(self):
        r = self.root
        for seq, fn in [("<Delete>", self.delete), ("<BackSpace>", self.delete),
                        ("<Control-z>", self.undo), ("<Control-Z>", self.undo),
                        ("<Control-y>", self.redo), ("<Control-d>", self.duplicate),
                        ("<Prior>", lambda: self.reorder(+1)),
                        ("<Next>", lambda: self.reorder(-1)),
                        ("<Escape>", self.escape)]:
            r.bind(seq, lambda e, f=fn: None if self._typing() else (f(), "break")[1])
        r.bind("<Control-s>", lambda e: self.save())
        r.bind("<Control-o>", lambda e: self.open())
        r.bind("<Control-n>", lambda e: self.new())
        for key, dx, dy in [("Left", -1, 0), ("Right", 1, 0), ("Up", 0, -1), ("Down", 0, 1)]:
            r.bind("<%s>" % key, lambda e, a=dx, b=dy: self.nudge(a, b))
            r.bind("<Shift-%s>" % key, lambda e, a=dx, b=dy: self.nudge(a * 10, b * 10))

    def _typing(self):
        w = self.root.focus_get()
        return isinstance(w, (tk.Entry, ttk.Entry, ttk.Combobox, ttk.Spinbox))

    def _wheel(self, e, horizontal=False):
        w = self.root.winfo_containing(e.x_root, e.y_root)
        if w is None:
            return
        if getattr(e, "num", None) == 4:
            step = -1
        elif getattr(e, "num", None) == 5:
            step = 1
        else:
            step = -1 if e.delta > 0 else 1
        path = str(w)
        if path.startswith(str(self.pcanvas)):
            self.pcanvas.yview_scroll(step, "units")
        elif path == str(self.canvas):
            (self.canvas.xview_scroll if horizontal else self.canvas.yview_scroll)(step * 2, "units")

    # ---------------------------------------------------------------- helpers
    def cxy(self, e):
        return self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)

    def snapxy(self, x, y):
        if not self.snap_var.get():
            return round(x, 1), round(y, 1)
        try:
            g = max(1, int(self.grid_size.get()))
        except (tk.TclError, ValueError):
            g = 10
        return round(x / g) * g, round(y / g) * g

    def find_uid(self, uid):
        for s in self.shapes:
            if s.uid == uid:
                return s
        return None

    def hit_shape(self, x, y):
        items = self.canvas.find_overlapping(x - 4, y - 4, x + 4, y + 4)
        for it in reversed(items):
            for t in self.canvas.gettags(it):
                if t.startswith("s") and t[1:].isdigit():
                    return self.find_uid(int(t[1:]))
        return None

    def hit_handle(self, x, y):
        if not self.sel:
            return None
        for i, (hx, hy) in enumerate(self.sel.handles()):
            if abs(hx - x) <= 7 and abs(hy - y) <= 7:
                return i
        return None

    # ---------------------------------------------------------------- desenho
    def refresh(self):
        cv = self.canvas
        cv.delete("all")
        if self.grid_var.get():
            try:
                g = max(4, int(self.grid_size.get()))
            except (tk.TclError, ValueError):
                g = 10
            for i, x in enumerate(range(0, self.W + 1, g)):
                cv.create_line(x, 0, x, self.H, fill="#dde4ee" if i % 5 == 0 else "#f0f3f8", tags="grid")
            for i, y in enumerate(range(0, self.H + 1, g)):
                cv.create_line(0, y, self.W, y, fill="#dde4ee" if i % 5 == 0 else "#f0f3f8", tags="grid")
        for s in self.shapes:
            try:
                tk_draw(cv, s.prims(), ("shape", "s%d" % s.uid))
            except Exception as ex:  # um valor estranho não deve travar o programa
                self.status.config(text="Erro ao desenhar %s: %s" % (s.title, ex))
        if self.sel:
            tk_draw(cv, self.sel.guides(), ("ui",))
            bb = cv.bbox("s%d" % self.sel.uid)
            if bb:
                cv.create_rectangle(bb[0] - 4, bb[1] - 4, bb[2] + 4, bb[3] + 4,
                                    outline="#3b82f6", dash=(4, 3), tags="ui")
            for hx, hy in self.sel.handles():
                cv.create_rectangle(hx - 5, hy - 5, hx + 5, hy + 5, fill="white",
                                    outline="#2563eb", width=1.5, tags="ui")

    def set_scene(self, dicts):
        self.shapes = [shape_from_dict(d) for d in dicts]
        self.sel = None
        self.refresh()
        self.build_props()

    def snapshot(self):
        return json.dumps([s.to_dict() for s in self.shapes])

    # ---------------------------------------------------------------- undo
    def push_undo(self):
        self.undo_stack.append(self.snapshot())
        del self.undo_stack[:-300]
        self.redo_stack.clear()
        self._edit_key = None

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.snapshot())
            self.set_scene(json.loads(self.undo_stack.pop()))
            self._edit_key = None

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.snapshot())
            self.set_scene(json.loads(self.redo_stack.pop()))
            self._edit_key = None

    # ---------------------------------------------------------------- edição
    def delete(self):
        if self.sel:
            self.push_undo()
            self.shapes.remove(self.sel)
            self.sel = None
            self.refresh()
            self.build_props()

    def duplicate(self):
        if self.sel:
            self.push_undo()
            s = shape_from_dict(self.sel.to_dict())
            s.translate(20, 20)
            self.shapes.append(s)
            self.sel = s
            self.refresh()
            self.build_props()

    def reorder(self, d):
        if not self.sel:
            return
        i = self.shapes.index(self.sel)
        j = max(0, min(len(self.shapes) - 1, i + d))
        if i != j:
            self.push_undo()
            self.shapes.insert(j, self.shapes.pop(i))
            self.refresh()

    def nudge(self, dx, dy):
        if self._typing() or not self.sel:
            return
        key = ("nudge", self.sel.uid)
        if self._edit_key != key:
            self.push_undo()
            self._edit_key = key
        self.sel.translate(dx, dy)
        self.refresh()
        self.build_props()
        return "break"

    def escape(self):
        self.tool_var.set("select")
        self._tool_changed()
        self.sel = None
        self.refresh()
        self.build_props()

    def _tool_changed(self):
        t = self.tool_var.get()
        self.canvas.config(cursor="arrow" if t == "select" else "crosshair")
        if t == "select":
            self.status.config(text="Selecionar: clique num objeto; arraste para mover ou use as alças.")
        else:
            cls = SHAPES[t]
            how = "arraste para definir o tamanho" if cls.drag_handle is not None else "clique para posicionar"
            self.status.config(text="Inserir %s: %s." % (cls.title.lower(), how))

    # ---------------------------------------------------------------- mouse
    def on_press(self, e):
        self.canvas.focus_set()
        x, y = self.cxy(e)
        tool = self.tool_var.get()
        if tool != "select":
            cls = SHAPES[tool]
            sx, sy = self.snapxy(x, y)
            self.push_undo()
            s = cls.create_at(sx, sy)
            self.shapes.append(s)
            self.sel = s
            if cls.drag_handle is not None:
                self._drag = {"mode": "create", "shape": s, "h": cls.drag_handle,
                              "start": (x, y), "moved": False}
            else:
                self._drag = None
                self.tool_var.set("select")
                self._tool_changed()
            self.refresh()
            self.build_props()
            return
        h = self.hit_handle(x, y)
        if h is not None:
            self._drag = {"mode": "handle", "shape": self.sel, "h": h, "pushed": False}
            return
        s = self.hit_shape(x, y)
        if s is not self.sel:
            self.sel = s
            self.build_props()
        if s:
            self._drag = {"mode": "move", "shape": s, "press": (x, y),
                          "orig": s.handles()[0], "pushed": False}
        else:
            self._drag = None
        self.refresh()

    def on_motion(self, e):
        d = self._drag
        if not d:
            return
        x, y = self.cxy(e)
        s = d["shape"]
        if d["mode"] == "create":
            if not d["moved"] and math.hypot(x - d["start"][0], y - d["start"][1]) < 5:
                return
            d["moved"] = True
            s.set_handle(d["h"], *self.snapxy(x, y))
            s.after_create_drag()
        elif d["mode"] == "handle":
            if not d["pushed"]:
                self.push_undo()
                d["pushed"] = True
            s.set_handle(d["h"], *self.snapxy(x, y))
        else:
            if not d["pushed"]:
                if math.hypot(x - d["press"][0], y - d["press"][1]) < 2:
                    return
                self.push_undo()
                d["pushed"] = True
            ox, oy = d["orig"]
            nx, ny = self.snapxy(ox + x - d["press"][0], oy + y - d["press"][1])
            hx, hy = s.handles()[0]
            s.translate(nx - hx, ny - hy)
        self.refresh()
        self.status.config(text="x=%.0f  y=%.0f" % (x, y))

    def on_release(self, e):
        d = self._drag
        self._drag = None
        if d and d["mode"] == "create":
            self.tool_var.set("select")
            self._tool_changed()
        if d and (d.get("pushed") or d.get("moved")):
            self.build_props()

    def on_double(self, e):
        if self.sel and self._first_entry is not None:
            self._first_entry.focus_set()
            self._first_entry.select_range(0, "end")

    def on_hover(self, e):
        if self._drag is None and self.tool_var.get() == "select":
            x, y = self.cxy(e)
            over_h = self.hit_handle(x, y) is not None
            self.canvas.config(cursor="tcross" if over_h else "arrow")

    # ---------------------------------------------------------------- painel
    def build_props(self):
        for w in self.pframe.winfo_children():
            w.destroy()
        self._swatches = {}
        self._first_entry = None
        s = self.sel
        if not s:
            ttk.Label(self.pframe, justify="left", wraplength=300, padding=6, text=(
                "Nenhum objeto selecionado.\n\n"
                "• Escolha um componente à esquerda e clique/arraste no quadro.\n"
                "• Clique num objeto para editá-lo aqui.\n"
                "• Duplo clique num objeto vai direto para o primeiro rótulo.\n"
                "• Cores: nomes (red, navy) ou #rrggbb; 'none' = sem preenchimento."
            )).pack(anchor="w")
            return
        ttk.Label(self.pframe, text=s.title, font=("TkDefaultFont", 11, "bold"),
                  padding=(6, 4)).pack(anchor="w")
        for key, label, typ in s.specs:
            self._prop_row(s, key, label, typ)
        ttk.Separator(self.pframe).pack(fill="x", pady=6, padx=6)
        ttk.Label(self.pframe, text="Geometria", font=("TkDefaultFont", 9, "bold"),
                  padding=(6, 0)).pack(anchor="w")
        for xk, yk in s.points:
            self._prop_row(s, xk, xk, "float")
            self._prop_row(s, yk, yk, "float")
        bf = ttk.Frame(self.pframe, padding=6)
        bf.pack(fill="x", pady=6)
        ttk.Button(bf, text="Duplicar", command=self.duplicate).grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        ttk.Button(bf, text="Excluir", command=self.delete).grid(row=0, column=1, sticky="ew", padx=2, pady=2)
        ttk.Button(bf, text="↑ Frente", command=lambda: self.reorder(+1)).grid(row=1, column=0, sticky="ew", padx=2, pady=2)
        ttk.Button(bf, text="↓ Trás", command=lambda: self.reorder(-1)).grid(row=1, column=1, sticky="ew", padx=2, pady=2)
        bf.columnconfigure(0, weight=1)
        bf.columnconfigure(1, weight=1)

    def _prop_row(self, s, key, label, typ):
        fr = ttk.Frame(self.pframe, padding=(6, 1))
        fr.pack(fill="x")
        ttk.Label(fr, text=label, width=22, anchor="w").pack(side="left")
        val = s.p.get(key)
        if typ == "bool":
            var = tk.BooleanVar(value=bool(val))
            ttk.Checkbutton(fr, variable=var).pack(side="left")
        elif isinstance(typ, tuple) and typ[0] == "choice":
            var = tk.StringVar(value=val)
            ttk.Combobox(fr, textvariable=var, values=typ[1], state="readonly",
                         width=15).pack(side="left")
        elif typ == "color":
            var = tk.StringVar(value=val)
            ttk.Entry(fr, textvariable=var, width=10).pack(side="left")
            sw = tk.Button(fr, width=2, relief="groove",
                           bg=tkcolor(self.root, val, True) or "white",
                           command=lambda: self._pick_color(var))
            sw.pack(side="left", padx=4)
            self._swatches[key] = sw
        else:
            if isinstance(val, float):
                shown = ("%.2f" % val).rstrip("0").rstrip(".")
            else:
                shown = str(val)
            var = tk.StringVar(value=shown)
            ent = ttk.Entry(fr, textvariable=var, width=17)
            ent.pack(side="left")
            if typ == "text" and self._first_entry is None:
                self._first_entry = ent
        var.trace_add("write", lambda *a: self.on_prop(s, key, typ, var))

    def _pick_color(self, var):
        try:
            init = var.get() if tkcolor(self.root, var.get(), True) else None
            c = colorchooser.askcolor(color=init, parent=self.root)[1]
        except tk.TclError:
            c = colorchooser.askcolor(parent=self.root)[1]
        if c:
            var.set(c)

    def on_prop(self, s, key, typ, var):
        try:
            raw = var.get()
            if typ == "float":
                v = float(str(raw).replace(",", "."))
            elif typ == "int":
                v = int(float(str(raw).replace(",", ".")))
            elif typ == "bool":
                v = bool(raw)
            else:
                v = str(raw)
        except (ValueError, tk.TclError):
            return  # valor incompleto enquanto digita
        if typ == "color":
            col = tkcolor(self.root, v, True)
            if v.strip() and v.strip().lower() not in ("none", "transparente") and not col:
                return  # cor ainda inválida
            if key in self._swatches:
                self._swatches[key].config(bg=col or "white")
        if s.p.get(key) == v:
            return
        k = (s.uid, key)
        if self._edit_key != k:
            self.push_undo()
            self._edit_key = k
        s.p[key] = v
        self.refresh()

    # ---------------------------------------------------------------- arquivos
    def new(self):
        self.push_undo()
        self.filename = None
        self.set_scene([])

    def open(self):
        path = filedialog.askopenfilename(filetypes=[("Esquema FisiSketch", "*.json"),
                                                     ("Todos", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            dicts = data["shapes"] if isinstance(data, dict) else data
            for d in dicts:
                if d.get("kind") not in SHAPES:
                    raise ValueError("componente desconhecido: %r" % d.get("kind"))
            self.push_undo()
            self.set_scene(dicts)
            self.filename = path
            self.root.title("FisiSketch — " + path)
        except Exception as ex:
            messagebox.showerror("Erro ao abrir", str(ex))

    def save(self, ask=False):
        path = self.filename
        if ask or not path:
            path = filedialog.asksaveasfilename(defaultextension=".json",
                                                filetypes=[("Esquema FisiSketch", "*.json")])
            if not path:
                return
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"app": "FisiSketch", "version": 1,
                       "shapes": [s.to_dict() for s in self.shapes]}, f,
                      ensure_ascii=False, indent=1)
        self.filename = path
        self.root.title("FisiSketch — " + path)
        self.status.config(text="Salvo em " + path)

    def export_svg(self):
        if not self.shapes:
            return
        path = filedialog.asksaveasfilename(defaultextension=".svg", filetypes=[("SVG", "*.svg")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(svg_document(self.shapes))
            self.status.config(text="SVG exportado: " + path)

    def export_eps(self):
        if not self.shapes:
            return
        path = filedialog.asksaveasfilename(defaultextension=".eps", filetypes=[("EPS", "*.eps")])
        if not path:
            return
        cv = self.canvas
        cv.itemconfigure("grid", state="hidden")
        cv.itemconfigure("ui", state="hidden")
        bb = cv.bbox("shape")
        if bb:
            cv.postscript(file=path, colormode="color", x=bb[0] - 10, y=bb[1] - 10,
                          width=bb[2] - bb[0] + 20, height=bb[3] - bb[1] + 20)
        self.refresh()
        self.status.config(text="EPS exportado: " + path)


def main():
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("clam")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
