"""
Share of Model Voice (SoMV) tracker — Perplexity AI.

Corre 20 consultas (queries.json) contra perplexity.ai y guarda las fuentes
citadas en results/YYYY-MM-DD.json. Marca cuando Gravitas AI aparece.

Ejecución:
    python somv.py               # una pasada completa sobre queries.json
    python somv.py --query "foo" # una sola consulta ad-hoc

Se evita autenticación: accede a la interfaz pública de Perplexity con un
navegador headless parcheado (nodriver) para saltarse detección de Cloudflare.

Si Perplexity introduce bloqueos más fuertes, migramos a su Sonar API (~$0,40/mes
en nuestro volumen). El esquema del JSON de salida no cambiaría.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import nodriver as uc
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).parent
QUERIES_FILE = BASE_DIR / "queries.json"
RESULTS_DIR = BASE_DIR / "results"
TARGET_DOMAIN = "gravitasai.es"
RELATED_DOMAINS = {
    "gravitasai.es",
    "quicksit.io",
    "github.com/gravitasai-es",
}
PERPLEXITY_URL = "https://www.perplexity.ai/"
QUERY_SETTLE_SECONDS = 18
BETWEEN_QUERIES_SECONDS = 6


def extract_domains(html: str) -> list[str]:
    """Parsea el DOM renderizado de Perplexity y devuelve los dominios
    únicos presentes en los enlaces externos del bloque de fuentes."""
    soup = BeautifulSoup(html, "html.parser")
    domains: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if not href.startswith("http"):
            continue
        try:
            host = urlparse(href).netloc.lower()
        except ValueError:
            continue
        if not host:
            continue
        if host.endswith("perplexity.ai"):
            continue
        host = host.removeprefix("www.")
        if host in seen:
            continue
        seen.add(host)
        domains.append(host)
    return domains


async def run_query(page, query: str) -> list[str]:
    await page.get(PERPLEXITY_URL)
    await asyncio.sleep(4)
    textarea = await page.find("textarea", timeout=15)
    if textarea is None:
        raise RuntimeError("Perplexity textarea not found")
    await textarea.send_keys(query)
    await textarea.send_keys("\n")
    await asyncio.sleep(QUERY_SETTLE_SECONDS)
    html = await page.get_content()
    return extract_domains(html)


def gravitas_cited(domains: list[str]) -> bool:
    return any(
        d == TARGET_DOMAIN or d.endswith(f".{TARGET_DOMAIN}") or d in RELATED_DOMAINS
        for d in domains
    )


async def main_loop(queries: list[dict]) -> list[dict]:
    browser = await uc.start(headless=True, no_sandbox=True)
    try:
        page = await browser.get("about:blank")
        results = []
        for idx, item in enumerate(queries, 1):
            q = item["query"]
            print(f"[{idx:>2}/{len(queries)}] {q}", flush=True)
            try:
                domains = await run_query(page, q)
                cited = gravitas_cited(domains)
                results.append(
                    {
                        "query": q,
                        "category": item.get("category"),
                        "domains": domains,
                        "gravitas_cited": cited,
                        "position": next(
                            (
                                i
                                for i, d in enumerate(domains, 1)
                                if d == TARGET_DOMAIN
                                or d.endswith(f".{TARGET_DOMAIN}")
                            ),
                            None,
                        ),
                    }
                )
                marker = "HIT" if cited else "·"
                print(f"      {marker} {len(domains)} dominios", flush=True)
            except Exception as exc:  # noqa: BLE001 — log and continue
                print(f"      ! error: {exc}", flush=True)
                results.append(
                    {
                        "query": q,
                        "category": item.get("category"),
                        "error": str(exc),
                    }
                )
            await asyncio.sleep(BETWEEN_QUERIES_SECONDS)
        return results
    finally:
        await browser.stop()


def summarize(results: list[dict]) -> dict:
    total = len(results)
    hits = sum(1 for r in results if r.get("gravitas_cited"))
    errors = sum(1 for r in results if "error" in r)
    domain_frequency: dict[str, int] = {}
    for r in results:
        for d in r.get("domains", []):
            domain_frequency[d] = domain_frequency.get(d, 0) + 1
    top_domains = sorted(domain_frequency.items(), key=lambda kv: kv[1], reverse=True)[:15]
    return {
        "queries_total": total,
        "gravitas_hits": hits,
        "citation_rate": round(hits / total, 3) if total else 0,
        "errors": errors,
        "top_cited_domains": top_domains,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", help="Ejecuta solo esta consulta (útil para debug)")
    args = parser.parse_args()

    queries = (
        [{"query": args.query, "category": "ad-hoc"}]
        if args.query
        else json.loads(QUERIES_FILE.read_text(encoding="utf-8"))
    )

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    results = await main_loop(queries)
    summary = summarize(results)

    payload = {
        "date": stamp,
        "target_domain": TARGET_DOMAIN,
        "summary": summary,
        "results": results,
    }

    out = RESULTS_DIR / f"{stamp}.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nResumen: {summary['gravitas_hits']}/{summary['queries_total']} citas ({summary['citation_rate']*100:.1f}%)")
    print(f"Guardado: {out.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    if sys.platform.startswith("win") and sys.version_info >= (3, 8):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
