"""Builds figures/workflow.html (SVG) and renders workflow.png with headless Chrome.

All numbers are real outputs from the 200-line run (jev-latest, claude-haiku-5-5).
"""
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1400, 820

INK, MUTE, FAINT, LINE, PAPER = "#1d1d1b", "#6f6d68", "#a8a49b", "#d6d1c6", "#fbfaf7"
JEV = "#2c4f7c"
SANS = "'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "Menlo, 'SF Mono', Consolas, monospace"

out = []


def t(x, y, s, size=13, fill=INK, weight=400, family=SANS, anchor="start", ls=0, italic=False):
    st = "font-style:italic;" if italic else ""
    out.append(
        f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" fill="{fill}" '
        f'font-weight="{weight}" text-anchor="{anchor}" letter-spacing="{ls}" style="{st}">{s}</text>'
    )


def rect(x, y, w, h, fill="none", stroke=LINE, sw=1, rx=2, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')


def line(x1, y1, x2, y2, stroke=LINE, sw=1):
    out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{sw}"/>')


def arrow(pts, stroke=MUTE):
    """Orthogonal connector through points, open arrowhead at the end."""
    d = "M" + " L".join(f"{x},{y}" for x, y in pts)
    out.append(f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="1.2" marker-end="url(#ah)"/>')


def label(x, y, num, s):
    t(x, y, f"{num}", 11, MUTE, 600, ls=1)
    t(x + 16, y, s, 11, MUTE, 600, ls=1.2)


# ------------------------------------------------------------------ header
t(48, 58, "How one bank statement line gets categorized", 24, INK, 600)
t(48, 84, "Two real lines from the test run. Jev returns a probability for every category; a threshold decides what posts without review.", 14, MUTE)
line(48, 108, W - 48, 108)

# ------------------------------------------------------------------ 1. statement
YA, YB = 262, 442  # vertical centres of row A and row B
label(48, 146, "1", "BANK STATEMENT")
rect(48, 192, 404, 290, fill="#ffffff")
t(64, 220, "Date", 11, MUTE, 600)
t(152, 220, "Transaction details", 11, MUTE, 600)
t(436, 220, "Amount (INR)", 11, MUTE, 600, anchor="end")
line(48, 232, 452, 232)
rows = [
    (YA, "2016-07-18", "CASHDEP/GURGAON/", "582,500.00 Cr", True, "A"),
    (YA + 60, "2017-07-18", "FDRL/INTERNAL FUND TRANSFE", "500,000.00 Cr", False, ""),
    (YA + 120, "2017-08-16", "INDO GIBL Indiaforensic STL01071", "133,900.00 Dr", False, ""),
    (YB, "2018-04-30", "CR811511963467/RMCPL10677/2", "5,000.00 Dr", True, "B"),
]
for y, d, det, amt, hot, tag in rows:
    c = INK if hot else FAINT
    if hot:
        rect(49, y - 20, 402, 34, fill="#f1efe9", stroke="none", rx=0)
        t(36, y + 4, tag, 12, INK, 700, anchor="middle")
    t(64, y + 2, d, 12, c, 400, MONO)
    t(152, y + 2, det if (hot or len(det) <= 22) else det[:21] + "…", 12, c, 400, MONO)
    t(436, y + 2, amt, 12, c, 400, MONO, anchor="end")
    if y != YB:
        line(60, y + 30, 440, y + 30, "#eeebe4")

# ------------------------------------------------------------------ 2. Jev
label(506, 146, "2", "TYPED QUESTIONS → JEV")
JX, JY, JW, JH = 506, 212, 252, 270
rect(JX, JY, JW, JH, fill="#ffffff", stroke=JEV, sw=1.4)
out.append(f'<text x="{JX + 16}" y="{JY + 30}" font-family="{MONO}" font-size="13"><tspan fill="{INK}" font-weight="600">category</tspan><tspan fill="{MUTE}">: choice</tspan></text>')
for i, opt in enumerate(["customer_receipt", "cash_deposit", "internal_transfer", "vendor_payment"]):
    t(JX + 32, JY + 56 + i * 21, opt, 12, INK, 400, MONO)
t(JX + 32, JY + 56 + 4 * 21, "… 7 more (11 total)", 12, FAINT, 400, MONO)
line(JX + 16, JY + 170, JX + JW - 16, JY + 170, "#eeebe4")
out.append(f'<text x="{JX + 16}" y="{JY + 196}" font-family="{MONO}" font-size="13"><tspan fill="{INK}" font-weight="600">is_intercompany</tspan><tspan fill="{MUTE}">: yes/no</tspan></text>')
t(JX + 16, JY + 246, "jev-latest · median 262 ms", 12, JEV, 500)

arrow([(452, YA), (478, YA), (478, JY + 70), (JX - 4, JY + 70)])
arrow([(452, YB), (478, YB), (478, JY + 200), (JX - 4, JY + 200)])

# ------------------------------------------------------------------ 3. probabilities
label(812, 146, "3", "PROBABILITY FOR EACH OPTION")
PX, PW = 812, 282
BX, BW = PX + 152, 80  # bar start / max width


def bars(y0, items):
    for i, (name, p) in enumerate(items):
        y = y0 + i * 22
        top = i == 0
        t(PX + 14, y + 4, name, 12, INK if top else MUTE, 500 if top else 400, MONO)
        rect(BX, y - 6, BW, 9, fill="#eeebe4", stroke="none", rx=0)
        if p > 0:
            rect(BX, y - 6, max(BW * p, 1.5), 9, fill=JEV if top else "#9fb0c7", stroke="none", rx=0)
        t(PX + PW - 12, y + 4, f"{p:.2f}", 12, INK if top else MUTE, 500 if top else 400, MONO, anchor="end")


AH = 74
rect(PX, YA - AH / 2, PW, AH, fill="#ffffff")
bars(YA - 10, [("cash_deposit", 1.00), ("all other 10", 0.00)])
BH = 124
rect(PX, YB - BH / 2, PW, BH, fill="#ffffff")
bars(YB - 40, [("vendor_payment", 0.35), ("other", 0.21), ("customer_receipt", 0.15), ("bank_fee_interest", 0.08)])
t(PX + 14, YB + 52, "+ 7 smaller", 11, FAINT, 400, MONO)

arrow([(JX + JW, JY + 70), (786, JY + 70), (786, YA), (PX - 4, YA)])
arrow([(JX + JW, JY + 200), (786, JY + 200), (786, YB), (PX - 4, YB)])

# ------------------------------------------------------------------ 4. threshold
label(1126, 146, "4", "THRESHOLD  p ≥ 0.95")
OX, OW = 1126, 226
rect(OX, YA - 24, OW, 48, fill=INK, stroke=INK)
t(OX + 16, YA - 2, "Auto-post to ledger", 14, "#ffffff", 600)
t(OX + 16, YA + 15, "p = 1.00", 12, "#c9c6bf", 400, MONO)
rect(OX, YB - 24, OW, 48, fill="#ffffff", stroke=INK, sw=1.2)
t(OX + 16, YB - 2, "Analyst review queue", 14, INK, 600)
t(OX + 16, YB + 15, "p = 0.35, no clear winner", 12, MUTE, 400, MONO)
arrow([(PX + PW, YA), (OX - 4, YA)])
arrow([(PX + PW, YB), (OX - 4, YB)])

# ------------------------------------------------------------------ Haiku comparison
HY = 560
line(48, HY, W - 48, HY)
t(48, HY + 38, "FOR COMPARISON: CLAUDE HAIKU 5.5 ON THE SAME LINES", 11, MUTE, 600, ls=1.2)
t(48, HY + 64, "Returns one label and a confidence number it writes into its answer. There is no probability per option.", 14, INK)

cols = [(48, "A", "CASHDEP/GURGAON/", "cash_deposit", "0.95"), (720, "B", "CR811511963467/RMCPL10677/2", "internal_transfer", "0.55")]
for x, tag, det, cat, conf in cols:
    rect(x, HY + 86, 632, 64, fill="#ffffff")
    t(x + 18, HY + 124, tag, 12, INK, 700)
    t(x + 42, HY + 124, det, 12, MUTE, 400, MONO)
    t(x + 330, HY + 124, "→", 13, MUTE)
    t(x + 354, HY + 124, cat, 12, INK, 500, MONO)
    t(x + 614, HY + 124, f'confidence "{conf}"', 12, INK, 400, MONO, anchor="end")

t(48, HY + 186, "In 200 lines Haiku used only 14 distinct confidence values, 30% of them exactly 0.60, and never went above 0.95.", 13, MUTE)
t(48, HY + 206, "A ≥ 0.95 rule would auto-post 6.5% of lines with Haiku and 18.5% with Jev.", 13, MUTE)

# ------------------------------------------------------------------ footer
t(48, H - 24, "Data: Kaggle “Bank Transaction Data” (apoorvwatsky), 200-line sample. Models: jev-latest (TypeSafe), claude-haiku-5-5 (Anthropic). Nov 2026.", 11, FAINT)

svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
<path d="M1,1 L9,5 L1,9" fill="none" stroke="{MUTE}" stroke-width="1.4"/></marker></defs>
<rect width="{W}" height="{H}" fill="{PAPER}"/>
{''.join(out)}
</svg>"""

html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Workflow figure</title>
<style>html,body{{margin:0;background:{PAPER}}}svg{{display:block}}</style></head><body>{svg}</body></html>"""

open(os.path.join(HERE, "workflow.svg"), "w").write(svg)
open(os.path.join(HERE, "workflow.html"), "w").write(html)

chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
subprocess.run(
    [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
     f"--window-size={W},{H}", f"--screenshot={os.path.join(HERE, 'workflow.png')}",
     "file://" + os.path.join(HERE, "workflow.html")],
    check=True, capture_output=True,
)
print("wrote", os.path.join(HERE, "workflow.png"))
