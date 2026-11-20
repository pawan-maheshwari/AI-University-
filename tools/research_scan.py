#!/usr/bin/env python3
"""Weekly Research & Policy scan for AI University.

Runs every Monday from .github/workflows/research-policy-scan.yml. It:
  1. collects the week's most-discussed AI research papers (Hugging Face Daily Papers,
     with arXiv as a fallback) and AI policy updates (US Federal Register, GOV.UK and
     regional news searches for the EU, UK, US, China, India, Africa and multilateral bodies),
  2. writes a dated brief, research-updates/YYYY-MM-DD.html,
  3. adds that week to research-updates.json, which the Research and Policy Lab pages read,
  4. adds the brief to sitemap.xml.

Standard library only. If the ANTHROPIC_API_KEY secret is set, Claude writes a short
editorial overview and a one-line "why it matters" for each item; otherwise the brief
uses the papers' abstracts and the news snippets.

Usage:
  python3 tools/research_scan.py                 # live run, writes files
  python3 tools/research_scan.py --dry-run       # live fetch, prints summary, writes to /tmp
  python3 tools/research_scan.py --fixtures DIR  # offline test using saved responses
"""
import argparse, datetime as dt, email.utils, html, json, os, re, sys, time
import urllib.parse, urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://ai-university.co.in"
UA = "AI-University-weekly-scan/1.0 (+https://ai-university.co.in)"
KEEP_WEEKS = 26
N_RESEARCH = 10
N_POLICY = 14
FIXTURES = None

# ------------------------------------------------------------------ fetching
def fetch(url, data=None, headers=None, timeout=30):
    if FIXTURES:
        key = re.sub(r"[^A-Za-z0-9]+", "_", url)[:150]
        path = os.path.join(FIXTURES, key)
        if os.path.exists(path):
            return open(path, "rb").read()
        raise OSError("no fixture for " + url)
    h = {"User-Agent": UA, "Accept": "*/*"}
    h.update(headers or {})
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - network errors of every kind
            last = e
            time.sleep(2 + attempt * 3)
    raise last

def clean(s, n=None):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    if n and len(s) > n:
        s = s[: n].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return s

def norm_title(t):
    return re.sub(r"[^a-z0-9 ]", "", t.lower())[:70]

# ------------------------------------------------------------------ research
CATS = [
    ("Agents", r"\bagent|tool use|tool-use|computer use|web navigation|multi-agent"),
    ("Alignment & Safety", r"alignment|safety|jailbreak|red.?team|harmful|reward hacking|interpretab|deception"),
    ("Reasoning", r"reasoning|chain-of-thought|math|theorem|planning|test-time"),
    ("Multimodal AI", r"vision-language|multimodal|\bvlm|image|video|audio|speech"),
    ("Efficiency", r"efficien|quantiz|distill|pruning|sparse|inference cost|long.context|kv cache"),
    ("Robotics", r"robot|embodied|manipulation|locomotion"),
    ("Evaluation", r"benchmark|evaluation|leaderboard"),
    ("Large Language Models", r"language model|\bllm|pretrain|fine-tun|instruction"),
]

def categorise(text):
    t = text.lower()
    for name, rx in CATS:
        if re.search(rx, t):
            return name
    return "Machine Learning"

def hf_daily(today):
    """Top papers of the last 7 days on Hugging Face Daily Papers, by upvotes."""
    seen, out = set(), []
    for d in range(1, 8):
        day = (today - dt.timedelta(days=d)).isoformat()
        try:
            rows = json.loads(fetch("https://huggingface.co/api/daily_papers?date=" + day))
        except Exception as e:  # noqa: BLE001
            print("  hf", day, "skipped:", e, file=sys.stderr)
            continue
        for r in rows:
            p = r.get("paper") or {}
            pid = p.get("id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            authors = [a.get("name", "") for a in p.get("authors", []) if a.get("name")]
            summary = clean(p.get("summary") or r.get("summary"))
            out.append({
                "title": clean(p.get("title") or r.get("title")),
                "authors": (", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")) or "—",
                "abstract": summary,
                "link": "https://arxiv.org/abs/" + pid,
                "date": (p.get("publishedAt") or day)[:10],
                "score": int(p.get("upvotes") or r.get("upvotes") or 0),
                "source": "Hugging Face Daily Papers",
            })
    out.sort(key=lambda x: -x["score"])
    return out

def arxiv_recent():
    q = urllib.parse.urlencode({
        "search_query": "cat:cs.AI OR cat:cs.CL OR cat:cs.LG OR cat:cs.CY",
        "sortBy": "submittedDate", "sortOrder": "descending", "max_results": "40"})
    raw = fetch("https://export.arxiv.org/api/query?" + q)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in ET.fromstring(raw).findall("a:entry", ns):
        authors = [clean(a.findtext("a:name", "", ns)) for a in e.findall("a:author", ns)]
        out.append({
            "title": clean(e.findtext("a:title", "", ns)),
            "authors": ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else ""),
            "abstract": clean(e.findtext("a:summary", "", ns)),
            "link": clean(e.findtext("a:id", "", ns)).replace("http://", "https://"),
            "date": e.findtext("a:published", "", ns)[:10],
            "score": 0, "source": "arXiv",
        })
    return out

def collect_research(today):
    items = []
    try:
        items = hf_daily(today)
    except Exception as e:  # noqa: BLE001
        print("  hf failed:", e, file=sys.stderr)
    if len(items) < N_RESEARCH:
        try:
            items += arxiv_recent()
        except Exception as e:  # noqa: BLE001
            print("  arxiv failed:", e, file=sys.stderr)
    seen, out = set(), []
    for it in items:
        k = norm_title(it["title"])
        if not it["title"] or k in seen:
            continue
        seen.add(k)
        it["cat"] = categorise(it["title"] + " " + it["abstract"])
        it["note"] = clean(it["abstract"], 320)
        out.append(it)
        if len(out) >= N_RESEARCH:
            break
    return out

# ------------------------------------------------------------------ policy
REGIONS = [
    ("European Union", '("AI Act" OR "AI Office" OR "artificial intelligence") (EU OR "European Commission" OR "European Parliament") regulation'),
    ("United Kingdom", '"artificial intelligence" (UK government OR DSIT OR "AI Security Institute") policy'),
    ("United States", '"artificial intelligence" (executive order OR Congress OR NIST OR "state law") policy'),
    ("China", '"artificial intelligence" China (CAC OR regulation OR rules OR governance)'),
    ("India", '"artificial intelligence" India (MeitY OR "IndiaAI" OR policy OR guidelines)'),
    ("Africa", '"artificial intelligence" (Africa OR "South Africa" OR Nigeria OR Kenya OR "African Union") policy'),
    ("Multilateral", '"artificial intelligence" (OECD OR UNESCO OR "United Nations" OR G7 OR G20) governance'),
]
POLICY_RX = re.compile(r"\b(law|act|bill|regulat|policy|rule|guidance|guideline|framework|executive order|"
                       r"strategy|govern|standard|code of practice|consultation|ban|compliance|treaty|summit|minist)", re.I)

def parse_rss(raw, region, source_default):
    out = []
    root = ET.fromstring(raw)
    for it in root.iter("item"):
        title = clean(it.findtext("title"))
        src_el = it.find("source")
        src = clean(src_el.text) if src_el is not None and src_el.text else source_default
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        pub = it.findtext("pubDate") or ""
        try:
            d = email.utils.parsedate_to_datetime(pub).date().isoformat()
        except Exception:  # noqa: BLE001
            d = ""
        desc = clean(it.findtext("description"), 260)
        if norm_title(desc).startswith(norm_title(title)[:40]):   # news feeds often repeat the headline
            desc = ""
        out.append({"region": region, "title": title, "link": clean(it.findtext("link")),
                    "source": src, "date": d, "desc": desc})
    return out

def gnews(region, query):
    q = urllib.parse.quote(query + " when:7d")
    raw = fetch("https://news.google.com/rss/search?q=" + q + "&hl=en&gl=US&ceid=US:en")
    return parse_rss(raw, region, "News")

def federal_register(today):
    since = (today - dt.timedelta(days=7)).isoformat()
    q = urllib.parse.urlencode({
        "conditions[term]": '"artificial intelligence"',
        "conditions[publication_date][gte]": since,
        "conditions[type][]": "RULE", "per_page": "20", "order": "relevance"}, doseq=True)
    q += "&conditions[type][]=PRORULE&conditions[type][]=PRESDOCU&conditions[type][]=NOTICE"
    data = json.loads(fetch("https://www.federalregister.gov/api/v1/documents.json?" + q))
    out = []
    for r in data.get("results", [])[:6]:
        agencies = ", ".join(a.get("name", "") for a in r.get("agencies", [])[:2])
        out.append({"region": "United States", "title": clean(r.get("title")), "link": r.get("html_url", ""),
                    "source": "Federal Register" + (" · " + agencies if agencies else ""),
                    "date": r.get("publication_date", ""), "desc": clean(r.get("abstract"), 260), "primary": True})
    return out

def govuk(today):
    raw = fetch("https://www.gov.uk/search/news-and-communications.atom?keywords=artificial+intelligence&order=updated-newest")
    ns = {"a": "http://www.w3.org/2005/Atom"}
    since = today - dt.timedelta(days=7)
    out = []
    for e in ET.fromstring(raw).findall("a:entry", ns):
        d = (e.findtext("a:updated", "", ns) or "")[:10]
        try:
            if dt.date.fromisoformat(d) < since:
                continue
        except ValueError:
            pass
        link = e.find("a:link", ns)
        out.append({"region": "United Kingdom", "title": clean(e.findtext("a:title", "", ns)),
                    "link": link.get("href") if link is not None else "", "source": "GOV.UK",
                    "date": d, "desc": clean(e.findtext("a:summary", "", ns), 260), "primary": True})
    return out[:4]

def collect_policy(today):
    pool = []
    for name, fn in (("federal register", lambda: federal_register(today)), ("gov.uk", lambda: govuk(today))):
        try:
            pool += fn()
        except Exception as e:  # noqa: BLE001
            print("  " + name + " failed:", e, file=sys.stderr)
    for region, query in REGIONS:
        try:
            pool += [x for x in gnews(region, query) if POLICY_RX.search(x["title"])]
        except Exception as e:  # noqa: BLE001
            print("  news", region, "failed:", e, file=sys.stderr)
    since = (today - dt.timedelta(days=8)).isoformat()
    seen, per, out = set(), {}, []
    # primary sources first, then newest
    pool.sort(key=lambda x: x.get("date") or "", reverse=True)   # newest first…
    pool.sort(key=lambda x: not x.get("primary"))                # …official sources ahead of news
    for it in pool:
        k = norm_title(it["title"])
        if not it["title"] or k in seen or (it["date"] and it["date"] < since):
            continue
        if per.get(it["region"], 0) >= 3:
            continue
        seen.add(k)
        per[it["region"]] = per.get(it["region"], 0) + 1
        it.pop("primary", None)
        out.append(it)
    order = [r for r, _ in REGIONS]
    out.sort(key=lambda x: (order.index(x["region"]) if x["region"] in order else 99, x["date"]), reverse=False)
    return out[:N_POLICY]

# ------------------------------------------------------------------ optional Claude editorial
def editorial(research, policy):
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key or FIXTURES:
        return None
    model = os.environ.get("AIU_SCAN_MODEL", "claude-sonnet-5-5")
    payload = {
        "research": [{"i": i, "title": r["title"], "abstract": r["abstract"][:900]} for i, r in enumerate(research)],
        "policy": [{"i": i, "region": p["region"], "title": p["title"], "source": p["source"], "snippet": p["desc"]}
                   for i, p in enumerate(policy)],
    }
    prompt = (
        "You edit AI University's weekly Research & Policy brief for executives and students. "
        "Using ONLY the items below (do not add facts that are not in them), return strict JSON: "
        '{"research_overview": "2-3 sentences on this week\'s research themes", '
        '"policy_overview": "2-3 sentences on this week\'s policy themes, neutral in tone", '
        '"research": [{"i": 0, "why": "one plain-English sentence on why it matters"}], '
        '"policy": [{"i": 0, "why": "one neutral sentence on what changed or why it matters", "drop": false}]}. '
        'Set "drop": true for policy items that are not really about AI law, regulation, governance or public policy. '
        "No markdown.\n\nITEMS:\n" + json.dumps(payload, ensure_ascii=False))
    body = json.dumps({"model": model, "max_tokens": 3000,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    try:
        raw = fetch("https://api.anthropic.com/v1/messages", data=body, timeout=120, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        text = "".join(b.get("text", "") for b in json.loads(raw).get("content", []))
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception as e:  # noqa: BLE001
        print("  editorial skipped:", e, file=sys.stderr)
        return None

def apply_editorial(ed, research, policy):
    if not ed:
        return research, policy, None, None
    for r in ed.get("research", []):
        if isinstance(r.get("i"), int) and r["i"] < len(research) and r.get("why"):
            research[r["i"]]["why"] = clean(r["why"], 260)
    drop = set()
    for p in ed.get("policy", []):
        if isinstance(p.get("i"), int) and p["i"] < len(policy):
            if p.get("drop"):
                drop.add(p["i"])
            elif p.get("why"):
                policy[p["i"]]["why"] = clean(p["why"], 260)
    policy = [p for i, p in enumerate(policy) if i not in drop]
    return research, policy, clean(ed.get("research_overview"), 700), clean(ed.get("policy_overview"), 700)

# ------------------------------------------------------------------ outputs
def week_label(d):
    start = d - dt.timedelta(days=7)
    return start.strftime("%-d %b") + " – " + (d - dt.timedelta(days=1)).strftime("%-d %b %Y")

def render_html(week):
    e = lambda s: html.escape(s or "", quote=True)  # noqa: E731
    cat_counts = {}
    for r in week["research"]:
        cat_counts[r["cat"]] = cat_counts.get(r["cat"], 0) + 1
    reg_counts = {}
    for p in week["policy"]:
        reg_counts[p["region"]] = reg_counts.get(p["region"], 0) + 1
    def bars(counts, color):
        if not counts:
            return ""
        mx = max(counts.values())
        return "".join(
            f'<div class="bar"><span>{e(k)}</span><i style="width:{v / mx * 100:.0f}%;background:{color}"></i><b>{v}</b></div>'
            for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
    res = "".join(
        f'''<article class="item"><div class="meta"><span class="tag">{e(r["cat"])}</span><span>{e(r["date"])}</span>'''
        f'''{"<span>▲ " + str(r["score"]) + "</span>" if r.get("score") else ""}</div>'''
        f'''<h3><a href="{e(r["link"])}" target="_blank" rel="noopener">{e(r["title"])}</a></h3>'''
        f'''<div class="by">{e(r["authors"])}</div>'''
        f'''{"<p class='why'><b>Why it matters.</b> " + e(r["why"]) + "</p>" if r.get("why") else ""}'''
        f'''<p>{e(r["note"])}</p></article>''' for r in week["research"]) or '<p class="empty">No papers were collected this week.</p>'
    pol = "".join(
        f'''<article class="item pol"><div class="meta"><span class="tag">{e(p["region"])}</span><span>{e(p["date"])}</span><span>{e(p["source"])}</span></div>'''
        f'''<h3><a href="{e(p["link"])}" target="_blank" rel="noopener">{e(p["title"])}</a></h3>'''
        f'''{"<p class='why'>" + e(p["why"]) + "</p>" if p.get("why") else ("<p>" + e(p["desc"]) + "</p>" if p.get("desc") and norm_title(p["desc"]) != norm_title(p["title"]) else "")}'''
        f'''</article>''' for p in week["policy"]) or '<p class="empty">No policy updates were collected this week.</p>'
    ro = f'<p class="ov">{e(week["research_overview"])}</p>' if week.get("research_overview") else ""
    po = f'<p class="ov">{e(week["policy_overview"])}</p>' if week.get("policy_overview") else ""
    return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(week["title"])} · AI University</title>
<meta name="description" content="AI University weekly brief: the most-discussed AI research papers and AI policy updates for {e(week["label"])}.">
<link rel="canonical" href="{SITE}/{e(week["file"])}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=EB+Garamond:wght@500;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{{--cr:#8C1515;--gold:#B8962E;--ink:#1A1917;--ink3:#3D3933;--slate:#6B6560;--border:#E5E0D8;--ivory:#F9F7F4}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Inter,-apple-system,sans-serif;background:var(--ivory);color:var(--ink3);line-height:1.6;font-size:15px}}
.wrap{{max-width:900px;margin:0 auto;padding:0 22px}}
header{{background:var(--ink);color:#fff;padding:34px 0 30px}}
header a{{color:#E8D9A8;font-size:13px;text-decoration:none}}
.eyebrow{{font-size:11px;letter-spacing:2.4px;text-transform:uppercase;font-weight:700;color:var(--gold)}}
h1{{font-family:'EB Garamond',serif;font-size:clamp(30px,5vw,44px);line-height:1.1;margin:8px 0 6px}}
h2{{font-family:'EB Garamond',serif;font-size:30px;color:var(--ink);margin:36px 0 6px}}
.sub{{color:#C9C4BB;font-size:14px}}
.stats{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:22px}}
.card{{background:#fff;border:1px solid var(--border);border-radius:6px;padding:16px 18px}}
.bar{{display:grid;grid-template-columns:150px 1fr 24px;gap:8px;align-items:center;font-size:12.5px;margin:5px 0}}
.bar i{{display:block;height:9px;border-radius:5px}}
.ov{{font-size:16px;color:var(--ink);background:#fff;border-left:4px solid var(--gold);padding:12px 16px;margin:10px 0 6px}}
.item{{background:#fff;border:1px solid var(--border);border-radius:4px;padding:18px 22px;margin-top:12px}}
.item.pol{{border-top:3px solid var(--cr)}}
.meta{{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;color:var(--slate);margin-bottom:6px}}
.tag{{color:var(--cr);font-weight:700;letter-spacing:1px;text-transform:uppercase;font-size:11px}}
h3{{font-family:'EB Garamond',serif;font-size:20px;line-height:1.25}}
h3 a{{color:var(--ink);text-decoration:none}} h3 a:hover{{color:var(--cr)}}
.by{{font-size:12.5px;font-style:italic;color:var(--slate);margin:3px 0 8px}}
.why{{color:var(--ink);margin:6px 0}}
.item p{{font-size:14px}}
.empty{{color:var(--slate);padding:14px 0}}
footer{{font-size:12px;color:var(--slate);padding:30px 0 50px;border-top:1px solid var(--border);margin-top:40px}}
@media(max-width:640px){{.stats{{grid-template-columns:1fr}}.bar{{grid-template-columns:110px 1fr 20px}}}}
@media print{{header{{background:#fff;color:var(--ink)}}.sub{{color:var(--slate)}}.item{{break-inside:avoid}}}}
</style></head><body>
<header><div class="wrap"><a href="../index.html">← AI University</a>
<div class="eyebrow" style="margin-top:18px">Weekly Research &amp; Policy Brief</div>
<h1>{e(week["label"])}</h1>
<div class="sub">{len(week["research"])} research papers · {len(week["policy"])} policy updates · compiled {e(week["date"])}</div></div></header>
<main class="wrap">
<div class="stats"><div class="card"><div class="eyebrow">Research by theme</div>{bars(cat_counts, "#8C1515")}</div>
<div class="card"><div class="eyebrow">Policy by region</div>{bars(reg_counts, "#B8962E")}</div></div>
<h2>Research Library — this week</h2><p style="color:var(--slate)">Most-discussed new AI papers{" (ranked by community upvotes)" if any(r.get("score") for r in week["research"]) else ""}.</p>{ro}{res}
<h2>Policy Lab — this week</h2><p style="color:var(--slate)">AI law, regulation and governance updates from official sources and news coverage.</p>{po}{pol}
</main>
<footer><div class="wrap">Compiled automatically every Monday from Hugging Face Daily Papers, arXiv, the US Federal Register, GOV.UK and news coverage{"; summaries written with Claude" if week.get("editorial") else ""}. Headlines link to the original sources; verify details there before relying on them. <a href="../index.html">AI University</a> · planetAI LLP</div></footer>
</body></html>
'''

def update_sitemap(path, url):
    try:
        s = open(path, encoding="utf-8").read()
    except OSError:
        return
    if url in s:
        return
    entry = f"  <url>\n    <loc>{url}</loc>\n    <changefreq>yearly</changefreq>\n    <priority>0.6</priority>\n  </url>\n</urlset>"
    open(path, "w", encoding="utf-8").write(s.replace("</urlset>", entry, 1))

def main():
    global FIXTURES
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fixtures")
    ap.add_argument("--date", help="run as if today were YYYY-MM-DD")
    ap.add_argument("--out", default=ROOT)
    a = ap.parse_args()
    FIXTURES = a.fixtures
    today = dt.date.fromisoformat(a.date) if a.date else dt.datetime.now(dt.timezone.utc).date()
    out_root = "/tmp/aiu-scan" if a.dry_run else a.out
    os.makedirs(os.path.join(out_root, "research-updates"), exist_ok=True)

    print("Scanning research…")
    research = collect_research(today)
    print("Scanning policy…")
    policy = collect_policy(today)
    if not research and not policy:
        print("Nothing collected — leaving the site unchanged.", file=sys.stderr)
        return 1
    research, policy, ro, po = apply_editorial(editorial(research, policy), research, policy)

    fname = f"research-updates/{today.isoformat()}.html"
    week = {"date": today.isoformat(), "label": "Week of " + week_label(today),
            "title": "Weekly AI Research & Policy Brief — " + week_label(today),
            "file": fname, "research_overview": ro, "policy_overview": po, "editorial": bool(ro or po),
            "research": [{k: r.get(k) for k in ("title", "authors", "cat", "note", "why", "link", "date", "score", "source")} for r in research],
            "policy": [{k: p.get(k) for k in ("region", "title", "desc", "why", "link", "source", "date")} for p in policy]}

    open(os.path.join(out_root, fname), "w", encoding="utf-8").write(render_html(week))
    idx_path = os.path.join(out_root, "research-updates.json")
    src_idx = os.path.join(ROOT, "research-updates.json")
    try:
        idx = json.load(open(idx_path if os.path.exists(idx_path) else src_idx, encoding="utf-8"))
    except (OSError, ValueError):
        idx = {"weeks": []}
    weeks = [w for w in idx.get("weeks", []) if w.get("date") != week["date"]]
    weeks.insert(0, week)
    idx = {"updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "weeks": weeks[:KEEP_WEEKS]}
    json.dump(idx, open(idx_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not a.dry_run:
        update_sitemap(os.path.join(out_root, "sitemap.xml"), f"{SITE}/{fname}")
    print(f"Wrote {fname}: {len(research)} papers, {len(policy)} policy items"
          f"{' (with editorial)' if week['editorial'] else ''} → {out_root}")
    for p in policy:
        print("   ", p["region"], "|", p["title"][:90])
    return 0

if __name__ == "__main__":
    sys.exit(main())
