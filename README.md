# geo-tracker

Mide la frecuencia de citación de [Gravitas AI](https://gravitasai.es) en motores de búsqueda generativos (actualmente Perplexity) sobre un conjunto fijo de 20 consultas objetivo.

## Qué hace

1. Cada lunes a las 09:00 (hora España) un GitHub Action arranca un navegador Chromium headless sobre Ubuntu.
2. Lanza 20 consultas definidas en [`queries.json`](./queries.json) contra `perplexity.ai`.
3. Parsea el DOM renderizado y extrae los dominios citados en el bloque de fuentes.
4. Guarda el resultado en `results/YYYY-MM-DD.json` y hace commit automático al repo.

El fichero resultado contiene un resumen (tasa de citación, top dominios citados, posición de Gravitas cuando aparece) y el detalle por consulta.

## Por qué así (y no con APIs de pago)

La [Sonar API de Perplexity](https://docs.perplexity.ai/) da el mismo dato con más fiabilidad, pero cuesta pagar de entrada. En nuestro volumen son ~0,40 €/mes. Si Cloudflare empieza a bloquear el scraping, migraremos ese script a la API — el esquema JSON de salida está pensado para ser compatible.

## Uso local

```bash
pip install -r requirements.txt
python somv.py                      # todas las queries
python somv.py --query "qué es X"   # consulta ad-hoc
```

## Estructura

```
queries.json          # 20 consultas objetivo, con categoría
somv.py               # script principal (nodriver + BeautifulSoup)
results/              # histórico de JSON por fecha
.github/workflows/    # cron semanal
```

## KPIs que medimos

- **Citation rate**: porcentaje de consultas donde Gravitas aparece en las fuentes.
- **Top cited domains**: dominios que dominan las respuestas del sector (referencia competitiva).
- **Position**: cuándo aparecemos, en qué posición relativa.

## Privacidad

Este repo es público y no contiene datos sensibles. Las queries son todas agregadas, sin PII.

## Licencia

CC0 1.0 Universal. Ver [LICENSE](LICENSE).
