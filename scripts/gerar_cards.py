#!/usr/bin/env python3
"""
Gera os cards do perfil (stats, linguagens, streak, atividade e troféus) como SVG.

Por que existe: as instâncias públicas do GitHub Readme Stats, Activity Graph e
Trophies estavam fora do ar em 11/2026 (503 / 402 DEPLOYMENT_DISABLED). Gerando
aqui, dentro do próprio repo, o perfil não depende de servidor de ninguém.

Uso:
  GITHUB_TOKEN=xxx python scripts/gerar_cards.py Kaio193 dist
  python scripts/gerar_cards.py Kaio193 dist        # sem token: modo público (REST + calendário HTML)

Só usa biblioteca padrão do Python, então roda em qualquer runner sem pip install.
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from html import escape

# ---------------------------------------------------------------- tema
BG = "#05080f"
PANEL = "#0a1322"
LINE = "#12304a"
CYAN = "#00e5ff"
JADE = "#19d3a2"
PINK = "#ff2e88"
TEXT = "#d6ecff"
DIM = "#5f7f9e"
MONO = "'JetBrains Mono','Fira Code',Consolas,'Courier New',monospace"
SANS = "'Segoe UI',Ubuntu,'Helvetica Neue',Arial,sans-serif"

FALLBACK_COLORS = {
    "Java": "#b07219", "CSS": "#663399", "HTML": "#e34c26", "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6", "PHP": "#4F5D95", "Python": "#3572A5", "Kotlin": "#A97BFF",
    "Shell": "#89e051", "PowerShell": "#012456", "C": "#555555", "C++": "#f34b7d", "Dart": "#00B4AB",
}

API = "https://api.github.com"
UA = {"User-Agent": "kaio193-profile-cards"}


# ---------------------------------------------------------------- coleta
def http(url, data=None, token=None):
    headers = dict(UA)
    if token:
        headers["Authorization"] = f"bearer {token}"
    if data is not None:
        data = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def gql(token, query, variables):
    res = json.loads(http(f"{API}/graphql", {"query": query, "variables": variables}, token))
    if "errors" in res:
        raise RuntimeError(res["errors"])
    return res["data"]


Q_USER = """
query($login:String!){ user(login:$login){
  createdAt
  followers{ totalCount }
  pullRequests{ totalCount }
  repositories(ownerAffiliations:OWNER, isFork:false, first:100, privacy:PUBLIC){
    totalCount
    nodes{ stargazerCount languages(first:10, orderBy:{field:SIZE, direction:DESC}){
      edges{ size node{ name color } } } }
  }
}}"""

Q_YEAR = """
query($login:String!,$from:DateTime!,$to:DateTime!){ user(login:$login){
  contributionsCollection(from:$from,to:$to){
    totalCommitContributions
    restrictedContributionsCount
    contributionCalendar{ weeks{ contributionDays{ date contributionCount } } }
  }
}}"""


def coletar_com_token(login, token):
    u = gql(token, Q_USER, {"login": login})["user"]
    langs, stars = {}, 0
    for repo in u["repositories"]["nodes"]:
        stars += repo["stargazerCount"]
        for e in repo["languages"]["edges"]:
            n = e["node"]["name"]
            cor = e["node"]["color"] or FALLBACK_COLORS.get(n, CYAN)
            langs.setdefault(n, [0, cor])[0] += e["size"]

    # A API só devolve 1 ano por consulta, então anda ano a ano desde a criação da conta
    days, commits = {}, 0
    inicio = dt.datetime.fromisoformat(u["createdAt"].replace("Z", "+00:00"))
    agora = dt.datetime.now(dt.timezone.utc)
    cur = inicio
    while cur < agora:
        fim = min(cur + dt.timedelta(days=365), agora)
        c = gql(token, Q_YEAR, {"login": login, "from": cur.isoformat(), "to": fim.isoformat()})
        cc = c["user"]["contributionsCollection"]
        commits += cc["totalCommitContributions"] + cc["restrictedContributionsCount"]
        for w in cc["contributionCalendar"]["weeks"]:
            for d in w["contributionDays"]:
                days[d["date"]] = d["contributionCount"]
        cur = fim
    return {
        "commits": commits, "prs": u["pullRequests"]["totalCount"],
        "repos": u["repositories"]["totalCount"], "stars": stars,
        "followers": u["followers"]["totalCount"], "langs": langs, "days": days,
    }


def coletar_publico(login):
    """Sem token: REST público + calendário do perfil (só o último ano)."""
    repos = json.loads(http(f"{API}/users/{login}/repos?per_page=100&type=owner"))
    user = json.loads(http(f"{API}/users/{login}"))
    langs, stars = {}, 0
    for r in repos:
        if r["fork"]:
            continue
        stars += r["stargazers_count"]
        for n, size in json.loads(http(r["languages_url"])).items():
            langs.setdefault(n, [0, FALLBACK_COLORS.get(n, CYAN)])[0] += size
    html = http(f"https://github.com/users/{login}/contributions")
    ids = re.findall(r'data-date="([\d-]+)" id="(contribution-day-component-[\d-]+)"', html)
    tips = dict(re.findall(r'for="(contribution-day-component-[\d-]+)"[^>]*>([^<]*)', html))
    days = {}
    for data, i in ids:
        m = re.match(r"(\d+) contribution", tips.get(i, ""))
        days[data] = int(m.group(1)) if m else 0
    return {
        "commits": None, "prs": None, "repos": sum(1 for r in repos if not r["fork"]),
        "stars": stars, "followers": user["followers"], "langs": langs, "days": days,
    }


# ---------------------------------------------------------------- cálculos
def calcular(d):
    hoje = dt.date.today()
    dias = {dt.date.fromisoformat(k): v for k, v in d["days"].items() if dt.date.fromisoformat(k) <= hoje}
    ano = [hoje - dt.timedelta(days=i) for i in range(365)]
    d["ano_total"] = sum(dias.get(x, 0) for x in ano)
    d["ano_ativos"] = sum(1 for x in ano if dias.get(x, 0) > 0)
    d["total"] = sum(dias.values())

    # streak atual: se hoje ainda está zerado, não quebra — conta a partir de ontem
    atual, x = 0, hoje if dias.get(hoje, 0) else hoje - dt.timedelta(days=1)
    while dias.get(x, 0) > 0:
        atual, x = atual + 1, x - dt.timedelta(days=1)
    maior = seq = 0
    for k in sorted(dias):
        seq = seq + 1 if dias[k] > 0 else 0
        maior = max(maior, seq)
    d["streak"], d["maior_streak"] = atual, maior
    d["ultimos"] = [(hoje - dt.timedelta(days=i), dias.get(hoje - dt.timedelta(days=i), 0)) for i in range(30, -1, -1)]
    if d["commits"] is None:
        d["commits"] = d["ano_total"]
    return d


# ---------------------------------------------------------------- desenho
def moldura(w, h, titulo, corpo, sub=""):
    """Moldura HUD padrão: fundo, cantos em L, título com cursor e scanline."""
    c = 14
    cantos = "".join(
        f'<path d="{p}" stroke="{CYAN}" stroke-width="2" fill="none"/>'
        for p in (
            f"M8 {8 + c} V8 H{8 + c}", f"M{w - 8 - c} 8 H{w - 8} V{8 + c}",
            f"M8 {h - 8 - c} V{h - 8} H{8 + c}", f"M{w - 8 - c} {h - 8} H{w - 8} V{h - 8 - c}",
        )
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{escape(titulo)}">
<title>{escape(titulo)}</title>
<defs>
  <linearGradient id="g" x1="0" x2="1"><stop offset="0" stop-color="{CYAN}"/><stop offset="1" stop-color="{JADE}"/></linearGradient>
  <linearGradient id="scan" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="{CYAN}" stop-opacity="0"/><stop offset=".5" stop-color="{CYAN}" stop-opacity=".07"/><stop offset="1" stop-color="{CYAN}" stop-opacity="0"/></linearGradient>
  <pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M24 0H0V24" fill="none" stroke="{LINE}" stroke-width=".5" opacity=".55"/></pattern>
</defs>
<style>
  .t{{font:600 13px {MONO};fill:{CYAN};letter-spacing:2px}}
  .s{{font:400 11px {MONO};fill:{DIM}}}
  .l{{font:400 12px {SANS};fill:{DIM}}}
  .v{{font:700 20px {MONO};fill:{TEXT}}}
  .big{{font:700 34px {MONO};fill:url(#g)}}
  .in{{opacity:0;animation:in .6s ease forwards}}
  @keyframes in{{to{{opacity:1}}}}
  .blink{{animation:b 1s steps(1) infinite}} @keyframes b{{50%{{opacity:0}}}}
  .sweep{{animation:sw 4s linear infinite}} @keyframes sw{{from{{transform:translateY(-{h}px)}}to{{transform:translateY({h}px)}}}}
  @media (prefers-reduced-motion: reduce){{.in{{animation:none;opacity:1}}.blink,.sweep{{animation:none}}}}
</style>
<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="10" fill="{BG}" stroke="{LINE}"/>
<rect x="1" y="1" width="{w - 2}" height="{h - 2}" rx="10" fill="url(#grid)"/>
{cantos}
<text x="26" y="34" class="t">{escape(titulo)}<tspan class="blink" fill="{JADE}"> _</tspan></text>
<text x="{w - 26}" y="34" class="s" text-anchor="end">{escape(sub)}</text>
<line x1="26" y1="46" x2="{w - 26}" y2="46" stroke="{LINE}"/>
{corpo}
<rect class="sweep" x="0" y="0" width="{w}" height="{h // 2}" fill="url(#scan)" pointer-events="none"/>
</svg>'''


def fmt(n):
    return f"{n:,}".replace(",", ".")


def card_stats(d):
    w, h = 480, 210
    itens = [
        ("Contribuições (12 meses)", d["ano_total"]), ("Commits", d["commits"]),
        ("Pull requests", d["prs"] if d["prs"] is not None else "—"),
        ("Repositórios públicos", d["repos"]), ("Estrelas recebidas", d["stars"]),
    ]
    corpo = ""
    for i, (rot, val) in enumerate(itens):
        y = 76 + i * 26
        val = fmt(val) if isinstance(val, int) else val
        corpo += (f'<g class="in" style="animation-delay:{.15 * i:.2f}s">'
                  f'<rect x="26" y="{y - 9}" width="4" height="4" fill="{JADE}"/>'
                  f'<text x="40" y="{y}" class="l">{rot}</text>'
                  f'<text x="300" y="{y}" class="v" text-anchor="end" style="font-size:15px">{val}</text></g>')
    # anel: dias ativos no último ano (métrica real, nada de "rank" inventado)
    r, cx, cy = 52, 392, 126
    circ = 2 * 3.14159 * r
    frac = d["ano_ativos"] / 365
    corpo += f'''<g transform="rotate(-90 {cx} {cy})">
  <circle cx="{cx}" cy="{cy}" r="{r}" stroke="{LINE}" stroke-width="8" fill="none"/>
  <circle cx="{cx}" cy="{cy}" r="{r}" stroke="url(#g)" stroke-width="8" fill="none" stroke-linecap="round"
    stroke-dasharray="{circ:.1f}" stroke-dashoffset="{circ:.1f}">
    <animate attributeName="stroke-dashoffset" from="{circ:.1f}" to="{circ * (1 - frac):.1f}" dur="1.6s" begin=".3s" fill="freeze"/>
  </circle>
  <circle cx="{cx}" cy="{cy}" r="{r + 12}" stroke="{CYAN}" stroke-width="1" fill="none" stroke-dasharray="2 8" opacity=".6">
    <animateTransform attributeName="transform" type="rotate" from="0 {cx} {cy}" to="360 {cx} {cy}" dur="24s" repeatCount="indefinite"/>
  </circle>
</g>
<text x="{cx}" y="{cy + 4}" class="v" text-anchor="middle">{d["ano_ativos"]}</text>
<text x="{cx}" y="{cy + 22}" class="s" text-anchor="middle">dias ativos</text>'''
    return moldura(w, h, "SYS.DIAGNOSTICS", corpo, "últimos 365 dias")


def card_langs(d):
    w, h = 480, 210
    total = sum(v[0] for v in d["langs"].values()) or 1
    top = sorted(d["langs"].items(), key=lambda kv: -kv[1][0])[:5]
    corpo = ""
    for i, (nome, (size, cor)) in enumerate(top):
        y = 74 + i * 26
        pct = size / total
        larg = 250 * pct
        corpo += (f'<g class="in" style="animation-delay:{.12 * i:.2f}s">'
                  f'<circle cx="31" cy="{y - 4}" r="4" fill="{cor}"/>'
                  f'<text x="42" y="{y}" class="l" style="fill:{TEXT}">{escape(nome)}</text>'
                  f'<rect x="150" y="{y - 9}" width="250" height="8" rx="4" fill="{LINE}"/>'
                  f'<rect x="150" y="{y - 9}" width="0" height="8" rx="4" fill="{cor}">'
                  f'<animate attributeName="width" from="0" to="{larg:.1f}" dur="1s" begin="{.2 + .12 * i:.2f}s" fill="freeze"/></rect>'
                  f'<text x="454" y="{y}" class="s" text-anchor="end">{pct * 100:.1f}%</text></g>')
    return moldura(w, h, "LANG.MODULES", corpo, "por tamanho de código")


def card_streak(d):
    w, h = 980, 210
    cols = [(163, fmt(d["total"]), "Contribuições", "desde a criação"),
            (490, str(d["streak"]), "Sequência atual", "dias seguidos"),
            (817, str(d["maior_streak"]), "Maior sequência", "recorde")]
    corpo = ""
    for i, (x, val, rot, sub) in enumerate(cols):
        destaque = i == 1
        corpo += f'<g class="in" style="animation-delay:{.2 * i:.1f}s">'
        if destaque:
            corpo += (f'<circle cx="{x}" cy="112" r="44" fill="none" stroke="url(#g)" stroke-width="3"/>'
                      f'<circle cx="{x}" cy="112" r="52" fill="none" stroke="{PINK}" stroke-width="1" stroke-dasharray="3 6" opacity=".7">'
                      f'<animateTransform attributeName="transform" type="rotate" from="360 {x} 112" to="0 {x} 112" dur="18s" repeatCount="indefinite"/></circle>')
        corpo += (f'<text x="{x}" y="{124 if destaque else 118}" class="{"big" if destaque else "v"}" text-anchor="middle">{val}</text>'
                  f'<text x="{x}" y="180" class="l" text-anchor="middle" style="fill:{TEXT}">{rot}</text>'
                  f'<text x="{x}" y="196" class="s" text-anchor="middle">{sub}</text></g>')
    corpo += f'<line x1="326" y1="70" x2="326" y2="190" stroke="{LINE}"/><line x1="654" y1="70" x2="654" y2="190" stroke="{LINE}"/>'
    return moldura(w, h, "STREAK.CORE", corpo, dt.date.today().strftime("%d/%m/%Y"))


def card_activity(d):
    w, h = 980, 270
    pts = d["ultimos"]
    maxv = max([c for _, c in pts] + [4])
    x0, x1, y0, y1 = 60, w - 34, 70, 215
    passo = (x1 - x0) / (len(pts) - 1)
    coords = [(x0 + i * passo, y1 - (c / maxv) * (y1 - y0)) for i, (_, c) in enumerate(pts)]
    linha = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area = f"M{x0},{y1} L" + " L".join(f"{x:.1f},{y:.1f}" for x, y in coords) + f" L{x1},{y1} Z"
    comp = 0.0
    for (ax, ay), (bx, by) in zip(coords, coords[1:]):
        comp += ((bx - ax) ** 2 + (by - ay) ** 2) ** .5
    grade = ""
    for k in range(5):
        yy = y1 - k * (y1 - y0) / 4
        grade += (f'<line x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}" stroke="{LINE}" stroke-dasharray="2 4"/>'
                  f'<text x="{x0 - 10}" y="{yy + 4:.1f}" class="s" text-anchor="end">{round(maxv * k / 4)}</text>')
    rotulos = "".join(f'<text x="{coords[i][0]:.1f}" y="{y1 + 20}" class="s" text-anchor="middle">{pts[i][0].strftime("%d/%m")}</text>'
                      for i in range(0, len(pts), 5))
    pontos = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{BG}" stroke="{CYAN}" stroke-width="2" class="in" style="animation-delay:{1.2 + i * .02:.2f}s"/>'
                     for i, (x, y) in enumerate(coords) if pts[i][1] > 0)
    corpo = f'''<defs><linearGradient id="area" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="{CYAN}" stop-opacity=".35"/><stop offset="1" stop-color="{CYAN}" stop-opacity="0"/></linearGradient>
<filter id="glow"><feGaussianBlur stdDeviation="2.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
{grade}{rotulos}
<path d="{area}" fill="url(#area)" class="in" style="animation-delay:1s"/>
<polyline points="{linha}" fill="none" stroke="{CYAN}" stroke-width="2.5" stroke-linejoin="round" filter="url(#glow)"
  stroke-dasharray="{comp:.0f}" stroke-dashoffset="{comp:.0f}">
  <animate attributeName="stroke-dashoffset" from="{comp:.0f}" to="0" dur="1.8s" fill="freeze"/></polyline>
{pontos}'''
    return moldura(w, h, "ACTIVITY.LOG", corpo, f"últimos 31 dias · {sum(c for _, c in pts)} contribuições")


def card_trophies(d):
    """Conquistas com níveis por limite. Bloqueadas aparecem apagadas — sem inflar nada."""
    niveis = ["C", "B", "A", "S"]
    regras = [
        ("COMMITS", d["commits"], [10, 100, 500, 1000]),
        ("REPOS", d["repos"], [1, 5, 15, 30]),
        ("STREAK", d["maior_streak"], [3, 7, 30, 100]),
        ("DIAS ATIVOS", d["ano_ativos"], [7, 30, 100, 200]),
        ("LINGUAGENS", len(d["langs"]), [2, 4, 6, 10]),
        ("ESTRELAS", d["stars"], [1, 10, 50, 200]),
        ("PULL REQS", d["prs"] or 0, [1, 10, 50, 100]),
    ]
    w, h, lado = 980, 200, 116
    gap = (w - 52 - lado * len(regras)) / (len(regras) - 1)
    corpo = ""
    for i, (nome, val, lim) in enumerate(regras):
        nivel = sum(1 for x in lim if val >= x)
        x = 26 + i * (lado + gap)
        on = nivel > 0
        cor = [DIM, JADE, CYAN, "#7c8cff", PINK][nivel]
        prox = f"próx.: {lim[nivel]}" if nivel < 4 else "máximo"
        hexa = " ".join(f"{x + lado / 2 + 30 * c:.1f},{95 + 30 * s:.1f}" for c, s in
                        [(0, -1), (.866, -.5), (.866, .5), (0, 1), (-.866, .5), (-.866, -.5)])
        corpo += (f'<g class="in" style="animation-delay:{.1 * i:.1f}s"><g opacity="{1 if on else .45}">'
                  f'<rect x="{x:.1f}" y="58" width="{lado}" height="128" rx="8" fill="{PANEL}" stroke="{cor if on else LINE}"/>'
                  f'<polygon points="{hexa}" fill="none" stroke="{cor}" stroke-width="2"/>'
                  f'<text x="{x + lado / 2:.1f}" y="104" text-anchor="middle" style="font:700 22px {MONO};fill:{cor}">{niveis[nivel - 1] if on else "—"}</text>'
                  f'<text x="{x + lado / 2:.1f}" y="148" text-anchor="middle" class="s" style="fill:{TEXT};letter-spacing:1px">{nome}</text>'
                  f'<text x="{x + lado / 2:.1f}" y="164" text-anchor="middle" class="s">{fmt(val)} · {prox}</text></g></g>')
    return moldura(w, h, "ACHIEVEMENTS", corpo, "C → B → A → S")


# ---------------------------------------------------------------- main
def main():
    login = sys.argv[1] if len(sys.argv) > 1 else "Kaio193"
    saida = sys.argv[2] if len(sys.argv) > 2 else "dist"
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    try:
        dados = coletar_com_token(login, token) if token else coletar_publico(login)
    except Exception as e:  # GraphQL falhou (token sem permissão, limite etc.): cai pro modo público
        print(f"aviso: GraphQL falhou ({e}); usando modo público", file=sys.stderr)
        dados = coletar_publico(login)
    dados = calcular(dados)
    os.makedirs(saida, exist_ok=True)
    cards = {"stats.svg": card_stats, "langs.svg": card_langs, "streak.svg": card_streak,
             "activity.svg": card_activity, "trophies.svg": card_trophies}
    for nome, fn in cards.items():
        with open(os.path.join(saida, nome), "w", encoding="utf-8") as f:
            f.write(fn(dados))
    print(json.dumps({k: v for k, v in dados.items() if k not in ("days", "ultimos")}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
