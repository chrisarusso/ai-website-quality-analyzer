# Website Quality Agent - Architecture Decisions

This document explains the technical choices made for the implementation.

---

## Playwright as Primary Crawler

**Decision:** Use Playwright with stealth settings as the primary crawling mechanism.

**Why:**
- **JavaScript rendering** - Many modern sites require JS to render content. Playwright executes JS.
- **Anti-bot evasion** - The existing implementation has stealth settings (webdriver detection removal, realistic browser fingerprints) that help avoid blocking.
- **Screenshots** - Can capture visual state for debugging and visual regression.
- **axe-core integration** - Can inject axe-core directly for accessibility testing.

**Tradeoffs:**
- Slower than simple HTTP requests (3-5 seconds per page vs milliseconds)
- Higher resource usage (runs actual browser)
- Requires Chromium installation

---

## LLM for Content Quality (Spelling/Grammar/Formatting)

**Decision:** Use GPT-4o-mini for text quality analysis rather than rule-based tools.

**Why:**
- **Context awareness** - LLM understands that "Drupal" is a proper noun, not a misspelling. Rule-based spellcheckers flag technical terms.
- **Grammar nuance** - LLM catches subtle issues that LanguageTool misses (awkward phrasing, unclear antecedents).
- **Single API call** - One call checks spelling, grammar, and formatting together.
- **Already implemented** - The existing code has a working LLMTextAnalyzer class.

**Tradeoffs:**
- Cost per page (~$0.001-0.005 per page depending on content length)
- Requires OpenAI API key
- Slight latency (1-3 seconds per page)

---

## axe-core for Accessibility

**Decision:** Use axe-core (via Playwright injection) for WCAG compliance checking.

**Why:**
- **Industry standard** - axe-core is used by Google, Microsoft, and most accessibility tools.
- **Comprehensive** - Covers WCAG 2.1 AA automatically.
- **Low false positives** - Well-tuned rules with clear explanations.
- **Playwright integration** - Can inject directly into rendered page.

**Alternative considered:** Custom WCAG checks. Rejected because axe-core is more complete and trusted.

**Status:** Not yet integrated - currently using custom accessibility checks.

---

## Lighthouse for Performance

**Decision:** Use Google Lighthouse CLI for performance metrics.

**Why:**
- **Trusted metrics** - LCP, CLS, TBT are industry-standard Core Web Vitals.
- **Mobile testing** - Built-in mobile emulation.
- **Comprehensive** - Covers performance, accessibility, best practices, SEO.
- **Familiar output** - Clients recognize Lighthouse scores.

**Integration:** Run via CLI (`lighthouse <url> --output json`) or use the npm package programmatically.

**Status:** Not yet integrated - currently using basic performance checks.

---

## SQLite for MVP Storage

**Decision:** Use SQLite for storing crawl results and analysis data.

**Why:**
- **Zero setup** - No database server required.
- **Already implemented** - Existing code uses SQLite.
- **Portable** - Single file, easy to share/backup.
- **Fast enough** - For single-user MVP, SQLite handles thousands of pages fine.

**When to upgrade:** Move to PostgreSQL when building multi-user web service or need concurrent writes.

---

## FastAPI for Web Interface

**Decision:** Use FastAPI for the web API and simple HTML dashboard.

**Why:**
- **Fast development** - Automatic OpenAPI docs, request validation.
- **Async-ready** - Can handle concurrent scan requests.
- **Consistent with knowledge base project** - Same stack.
- **Simple HTML** - No need for React/Vue for MVP; server-rendered HTML is fine.

---

## Severity Scoring System

**Decision:** Use 4-level severity (Critical, High, Medium, Low) with weighted scoring.

**Why:**
- **Actionable** - Users know what to fix first.
- **Familiar** - Matches security vulnerability scoring.
- **Aggregatable** - Can calculate overall site health score.

**Severity mapping:**
- **Critical:** Security vulnerabilities, site-breaking issues, major accessibility barriers
- **High:** SEO blockers, broken navigation, significant performance issues
- **Medium:** Content quality issues, minor accessibility issues, optimization opportunities
- **Low:** Best practice suggestions, minor improvements

---

## Crawling Strategy Options

| Option | Pros | Cons | Use Case |
|--------|------|------|----------|
| **Playwright** (primary) | JS rendering, anti-bot stealth, screenshots | Slow, resource-heavy | Primary crawler, JS-heavy sites |
| **Requests + BeautifulSoup** | Fast, lightweight | No JS, easily blocked | Fallback for simple sites |
| **Crawl4AI** | AI-powered extraction, handles complex sites | Newer, less tested | Alternative to explore |
| **CommonCrawl** | Pre-crawled data, no blocking issues | Data may be stale (monthly) | Supplement for large sites |

**Recommended approach:**
1. **Primary:** Playwright with stealth settings (already implemented)
2. **Fallback:** Check CommonCrawl for recent data if blocked
3. **Rate limiting:** 3+ seconds between requests, randomized delays

---

## Analysis Components

| Check Category | Tool/Approach | Notes |
|----------------|---------------|-------|
| **Spelling/Grammar/Formatting** | LLM (GPT-4o-mini) | Already implemented, works well |
| **SEO** | Custom checks | Title, meta, H1, structured data, canonical |
| **Accessibility** | axe-core (via Playwright) | Industry standard, comprehensive |
| **Broken Links** | HTTP HEAD requests | Parallel checking with rate limiting |
| **Performance** | Lighthouse CLI or API | Google's standard, trusted metrics |
| **Mobile Responsive** | Playwright viewport testing + Lighthouse | Screenshot at mobile widths |
| **GDPR/Compliance** | Custom pattern matching | Cookie consent, privacy policy detection |
| **CMS Vulnerabilities** | Version detection + CVE database | Drupal/WP version -> known issues |

---

## Data Flow

```
+------------------------------------------------------------------+
|                         INPUT                                     |
|                    URL or Domain                                 |
+-----------------------------+------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                      CRAWL PHASE                                  |
|------------------------------------------------------------------|
|  1. Fetch sitemap.xml (if exists)                                |
|  2. Crawl pages via Playwright (stealth mode)                    |
|  3. Store HTML + metadata in SQLite                              |
|  4. Rate limit: 3-5s between requests                            |
|  5. Fallback: CommonCrawl if blocked                             |
+-----------------------------+------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                    ANALYSIS PHASE                                 |
|------------------------------------------------------------------|
|  Parallel analysis of stored pages:                              |
|                                                                  |
|  +-------------+ +-------------+ +-------------+                 |
|  | LLM Analysis| | SEO Checks  | | Link Checker|                 |
|  | (spelling,  | | (title,meta,| | (broken,    |                 |
|  | grammar,    | | H1, schema) | | 403s, thin) |                 |
|  | formatting) | |             | |             |                 |
|  +-------------+ +-------------+ +-------------+                 |
|                                                                  |
|  +-------------+ +-------------+ +-------------+                 |
|  | axe-core    | | Lighthouse  | | CMS Security|                 |
|  | (WCAG/a11y) | | (perf,      | | (Drupal/WP  |                 |
|  |             | | mobile)     | | versions)   |                 |
|  +-------------+ +-------------+ +-------------+                 |
|                                                                  |
|  +-------------+                                                 |
|  | Compliance  |                                                 |
|  | (GDPR,      |                                                 |
|  | cookies)    |                                                 |
|  +-------------+                                                 |
+-----------------------------+------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                    AGGREGATION                                    |
|------------------------------------------------------------------|
|  - Combine all issues into unified format                        |
|  - Assign severity (Critical, High, Medium, Low)                 |
|  - Calculate scores per category                                 |
|  - Generate summary statistics                                   |
|  - Identify top priority fixes                                   |
+-----------------------------+------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                      OUTPUT                                       |
|------------------------------------------------------------------|
|  +-------------+ +-------------+ +-------------+                 |
|  | Web Dashboard| PDF Report  | | JSON API    |                 |
|  | (searchable,| | (branded,   | |(programmatic|                 |
|  | filterable) | | shareable)  | | access)     |                 |
|  +-------------+ +-------------+ +-------------+                 |
+------------------------------------------------------------------+
```

---

## Storage Options

| Option | Use Case | Notes |
|--------|----------|-------|
| **SQLite** | Local dev, single-user | Already implemented, simple |
| **PostgreSQL** | Production, multi-user | Needed for web service |
| **File system** | Crawled HTML cache | Already implemented |

---

## Output/Reporting Options

| Format | Tool | Notes |
|--------|------|-------|
| **Web UI** | FastAPI + simple HTML/CSS | Searchable, filterable results |
| **PDF** | WeasyPrint or Playwright print | Professional, shareable |
| **JSON** | Native | API access, integrations |

---

## Hosting Options

| Option | Pros | Cons | Cost |
|--------|------|------|------|
| **Local** | Free, simple, fast dev | Not shareable | $0 |
| **Fly.io** | Easy deploy, good free tier | Limited resources on free | Free -> $5/mo |
| **Railway** | Simple, DB included | Smaller free tier | Free -> $5/mo |
| **Render** | Easy, free tier | Cold starts | Free -> $7/mo |

**Recommended:** Local dev -> Fly.io for demo/production
