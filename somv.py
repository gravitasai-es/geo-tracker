"""
Share of Model Voice (SoMV) tracker — Perplexity AI.

Corre 20 consultas (queries.json) contra perplexity.ai y guarda las fuentes
citadas en results/YYYY-MM-DD.json. Marca cuando Gravitas AI aparece.

Ejecución:
    python somv.py               # pasada completa sobre queries.json
    python somv.py --query "foo" # consulta ad-hoc

Implementación con Playwright (Chromium headless). Si Perplexity introduce
bloqueos anti-bot más fuertes en el futuro, migrar a su Sonar API.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.async_api import (  # type: ignore[import-not-found]
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

BASE_DIR = Path(__file__).parent
QUERIES_FILE = BASE_DIR / "queries.json"
RESULTS_DIR = BASE_DIR / "results"
TARGET_DOMAIN = "gravitasai.es"
RELATED_HOSTS = {
    "gravitasai.es",
    "quicksit.io",
    "github.com",  # nuestra org vive ahí
}
PERPLEXITY_URL = "https://www.perplexity.ai/"
QUERY_SETTLE_SECONDS = 18
BETWEEN_QUERIES_SECONDS = 5
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def extract_domains(html: str) -> list[str]:
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
        if not host or host.endswith("perplexity.ai"):
            continue
        host = host.removeprefix("www.")
        if host in seen:
            continue
        seen.add(host)
        domains.append(host)
    return domains


def gravitas_cited(domains: list[str]) -> bool:
    for d in domains:
        if d == TARGET_DOMAIN or d.endswith(f".{TARGET_DOMAIN}"):
            return True
    return False


async def run_query(page, query: str) -> list[str]:
    await page.goto(PERPLEXITY_URL, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    textarea = page.locator("textarea").first
    await textarea.wait_for(state="visible", timeout=15000)
    await textarea.fill(query)
    await textarea.press("Enter")

    # Esperar a que Perplexity sintetice la respuesta y renderice fuentes.
    await page.wait_for_timeout(QUERY_SETTLE_SECONDS * 1000)
    html = await page.content()
    return extract_domains(html)


async def main_loop(queries: list[dict]) -> list[dict]:
    results: list[dict] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            user_agent=USER_AGENT,
            locale="es-ES",
            viewport={"width": 1440, "height": 900},
        )
        page = await context.new_page()

        for idx, item in enumerate(queries, 1):
            q = item["query"]
            print(f"[{idx:>2}/{len(queries)}] {q}", flush=True)
            try:
                domains = await run_query(page, q)
                cited = gravitas_cited(domains)
                position = next(
                    (
                        i
                        for i, d in enumerate(domains, 1)
                        if d == TARGET_DOMAIN or d.endswith(f".{TARGET_DOMAIN}")
                    ),
                    None,
                )
                results.append(
                    {
                        "query": q,
                        "category": item.get("category"),
                        "domains": domains,
                        "gravitas_cited": cited,
                        "position": position,
                    }
                )
                marker = "HIT" if cited else "·"
                print(f"      {marker} {len(domains)} dominios", flush=True)
            except PlaywrightTimeoutError as exc:
                print(f"      ! timeout: {exc}", flush=True)
                results.append(
                    {"query": q, "category": item.get("category"), "error": f"timeout: {exc}"}
                )
            except Exception as exc:  # noqa: BLE001
                print(f"      ! error: {exc}", flush=True)
                results.append(
                    {"query": q, "category": item.get("category"), "error": str(exc)}
                )
            await page.wait_for_timeout(BETWEEN_QUERIES_SECONDS * 1000)

        await context.close()
        await browser.close()
    return results


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
    parser.add_argument("--query", help="Ejecuta solo esta consulta (debug)")
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

    print(
        f"\nResumen: {summary['gravitas_hits']}/{summary['queries_total']} citas "
        f"({summary['citation_rate']*100:.1f}%)"
    )
    print(f"Guardado: {out.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
