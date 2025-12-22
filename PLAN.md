# Website Quality Agent

**Status:** Planning
**Last Updated:** 2025-12-21

## Overview

Automated agent that crawls websites, detects quality issues, and generates comprehensive reports. Designed for both internal client demos and as a potential freemium SaaS product. Focus on detection and reporting first; auto-fix capabilities are Phase 2+.

## Use Cases

### UC1: Client Demo / Prospect Scan
- **Who:** Savas sales/account team
- **Trigger:** Manual - before or during a client conversation
- **Input:** Client's website URL
- **Output:** Professional report highlighting 5-10 key issues with severity
- **Goal:** Demonstrate value, create conversation starter, show expertise
- **Time:** Should complete in < 5 minutes for small sites

### UC2: Self-Service Freemium Scan
- **Who:** Anyone (inbound marketing)
- **Trigger:** Visitor enters URL on public web page
- **Input:** Single URL or domain
- **Output:** Teaser report - shows issue counts by category, 2-3 sample issues, blur/gate the rest
- **Goal:** Lead generation, demonstrate capability, convert to paid
- **Upsell:** "We found 47 issues. Get the full report for $X" or "Subscribe for ongoing monitoring"

### UC3: Full Comprehensive Audit
- **Who:** Paying customers or internal QA
- **Trigger:** Manual request or scheduled
- **Input:** Full domain
- **Output:** Complete report with all issues, severity, location, recommendations
- **Includes:** All pages crawled, all check categories, exportable, filterable
- **Delivery:** Web dashboard + PDF export option

### UC4: Scheduled Monitoring (Phase 2)
- **Who:** Subscription customers
- **Trigger:** Automated - weekly/monthly schedule
- **Input:** Configured domain
- **Output:** Delta report (what's new, what's fixed, what's worse)
- **Notifications:** Email/Slack when new critical issues appear

**MVP Focus:** UC1 + UC3 (same scan, different audiences). UC2 is a wrapper that limits output. UC4 is Phase 2.

## MVP Quality Checks

The MVP focuses on 10 high-impact check categories:

### 1. SEO Insights
- Missing/duplicate title tags
- Missing/duplicate meta descriptions
- Missing or multiple H1 tags
- Canonical URL issues
- Structured data presence (schema.org)
- Open Graph tags
- Sitemap and robots.txt validation

### 2. Spelling Issues
- LLM-powered spelling detection
- Context-aware (ignores proper nouns, technical terms)
- Suggestions for corrections

### 3. Grammar Issues
- LLM-powered grammar analysis
- Subject-verb agreement
- Tense consistency
- Punctuation errors
- Run-on sentences

### 4. Formatting/Copy Structure
- Spacing inconsistencies (double spaces, missing spaces)
- Inconsistent punctuation
- Heading hierarchy issues
- List formatting problems
- Paragraph structure

### 5. Accessibility/WCAG Issues
- Images without alt text
- Color contrast issues
- Missing form labels
- Keyboard navigation problems
- ARIA attribute issues
- Language declaration
- Focus indicators

### 6. Broken Links & Content Issues
- Internal broken links (404s)
- External broken links
- 403 Forbidden errors exposed to users
- Thin content pages (very little copy)
- Redirect chains

### 7. GDPR/Compliance Considerations
- Cookie consent mechanism detection
- Privacy policy presence
- Accessibility statement presence
- Third-party tracking disclosure

### 8. Performance (Lighthouse-style)
- Page load time
- Time to First Byte (TTFB)
- Largest Contentful Paint (LCP)
- Cumulative Layout Shift (CLS)
- Total Blocking Time (TBT)
- Resource optimization opportunities

### 9. Mobile Responsive Best Practices
- Viewport meta tag
- Touch target sizes
- Responsive images
- Mobile-specific layout issues
- Text readability at mobile sizes

### 10. CMS Vulnerability Exposure
- Drupal version detection and known CVEs
- WordPress version detection and known CVEs
- Outdated plugin/module detection
- Exposed configuration files
- Admin panel exposure
- Default credentials paths

## Technical Architecture

### Crawling Strategy

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

### Analysis Components

| Check Category | Tool/Approach | Notes |
|----------------|---------------|-------|
| **Spelling/Grammar/Formatting** | LLM (GPT-4o-mini) | Already implemented, works well |
| **SEO** | Custom checks | Title, meta, H1, structured data, canonical |
| **Accessibility** | axe-core (via Playwright) | Industry standard, comprehensive |
| **Broken Links** | HTTP HEAD requests | Parallel checking with rate limiting |
| **Performance** | Lighthouse CLI or API | Google's standard, trusted metrics |
| **Mobile Responsive** | Playwright viewport testing + Lighthouse | Screenshot at mobile widths |
| **GDPR/Compliance** | Custom pattern matching | Cookie consent, privacy policy detection |
| **CMS Vulnerabilities** | Version detection + CVE database | Drupal/WP version → known issues |

### Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         INPUT                                    │
│                    URL or Domain                                │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                      CRAWL PHASE                                 │
├─────────────────────────────────────────────────────────────────┤
│  1. Fetch sitemap.xml (if exists)                               │
│  2. Crawl pages via Playwright (stealth mode)                   │
│  3. Store HTML + metadata in SQLite                             │
│  4. Rate limit: 3-5s between requests                           │
│  5. Fallback: CommonCrawl if blocked                            │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ANALYSIS PHASE                                │
├─────────────────────────────────────────────────────────────────┤
│  Parallel analysis of stored pages:                             │
│                                                                 │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐            │
│  │ LLM Analysis │ │ SEO Checks   │ │ Link Checker │            │
│  │ (spelling,   │ │ (title, meta,│ │ (broken,     │            │
│  │ grammar,     │ │ H1, schema)  │ │ 403s, thin)  │            │
│  │ formatting)  │ │              │ │              │            │
│  └──────────────┘ └──────────────┘ └──────────────┘            │
│                                                                 │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐            │
│  │ axe-core     │ │ Lighthouse   │ │ CMS Security │            │
│  │ (WCAG/a11y)  │ │ (perf,       │ │ (Drupal/WP   │            │
│  │              │ │ mobile)      │ │ versions)    │            │
│  └──────────────┘ └──────────────┘ └──────────────┘            │
│                                                                 │
│  ┌──────────────┐                                               │
│  │ Compliance   │                                               │
│  │ (GDPR,       │                                               │
│  │ cookies)     │                                               │
│  └──────────────┘                                               │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AGGREGATION                                   │
├─────────────────────────────────────────────────────────────────┤
│  • Combine all issues into unified format                       │
│  • Assign severity (Critical, High, Medium, Low)                │
│  • Calculate scores per category                                │
│  • Generate summary statistics                                  │
│  • Identify top priority fixes                                  │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                      OUTPUT                                      │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐            │
│  │ Web Dashboard│ │ PDF Report   │ │ JSON API     │            │
│  │ (searchable, │ │ (branded,    │ │ (programmatic│            │
│  │ filterable)  │ │ shareable)   │ │ access)      │            │
│  └──────────────┘ └──────────────┘ └──────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

### Storage Options

| Option | Use Case | Notes |
|--------|----------|-------|
| **SQLite** | Local dev, single-user | Already implemented, simple |
| **PostgreSQL** | Production, multi-user | Needed for web service |
| **File system** | Crawled HTML cache | Already implemented |

### Output/Reporting Options

| Format | Tool | Notes |
|--------|------|-------|
| **Web UI** | FastAPI + simple HTML/CSS | Searchable, filterable results |
| **PDF** | WeasyPrint or Playwright print | Professional, shareable |
| **JSON** | Native | API access, integrations |

### Hosting Options

| Option | Pros | Cons | Cost |
|--------|------|------|------|
| **Local** | Free, simple, fast dev | Not shareable | $0 |
| **Fly.io** | Easy deploy, good free tier | Limited resources on free | Free → $5/mo |
| **Railway** | Simple, DB included | Smaller free tier | Free → $5/mo |
| **Render** | Easy, free tier | Cold starts | Free → $7/mo |

**Recommended:** Local dev → Fly.io for demo/production

## Project Structure

```
website-quality-agent/
├── src/
│   └── website_agent/
│       ├── __init__.py
│       ├── config.py              # Environment configuration
│       ├── models.py              # Pydantic models for issues, reports
│       ├── crawler/
│       │   ├── __init__.py
│       │   ├── playwright_crawler.py   # Primary Playwright-based crawler
│       │   ├── simple_crawler.py       # Requests/BS4 fallback
│       │   └── common_crawl.py         # CommonCrawl integration
│       ├── analyzers/
│       │   ├── __init__.py
│       │   ├── base.py                 # Base analyzer interface
│       │   ├── seo_analyzer.py         # SEO checks
│       │   ├── content_analyzer.py     # Spelling, grammar, formatting (LLM)
│       │   ├── accessibility_analyzer.py  # WCAG/axe-core
│       │   ├── link_analyzer.py        # Broken links, 403s
│       │   ├── performance_analyzer.py # Lighthouse integration
│       │   ├── mobile_analyzer.py      # Responsive checks
│       │   ├── compliance_analyzer.py  # GDPR, cookies
│       │   └── cms_analyzer.py         # Drupal/WP vulnerabilities
│       ├── reporting/
│       │   ├── __init__.py
│       │   ├── aggregator.py           # Combine results, calculate scores
│       │   ├── pdf_generator.py        # PDF report generation
│       │   └── templates/              # HTML/PDF templates
│       ├── storage/
│       │   ├── __init__.py
│       │   └── sqlite_store.py         # SQLite storage
│       ├── api/
│       │   ├── __init__.py
│       │   └── app.py                  # FastAPI web service
│       └── cli.py                      # Command-line interface
├── tests/
│   ├── __init__.py
│   ├── test_analyzers.py
│   ├── test_crawler.py
│   └── test_models.py
├── pyproject.toml
├── .env.example
└── PLAN.md
```

## Architecture Decision Rationale

### Playwright as Primary Crawler

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

### LLM for Content Quality (Spelling/Grammar/Formatting)

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

### axe-core for Accessibility

**Decision:** Use axe-core (via Playwright injection) for WCAG compliance checking.

**Why:**
- **Industry standard** - axe-core is used by Google, Microsoft, and most accessibility tools.
- **Comprehensive** - Covers WCAG 2.1 AA automatically.
- **Low false positives** - Well-tuned rules with clear explanations.
- **Playwright integration** - Can inject directly into rendered page.

**Alternative considered:** Custom WCAG checks. Rejected because axe-core is more complete and trusted.

### Lighthouse for Performance

**Decision:** Use Google Lighthouse CLI for performance metrics.

**Why:**
- **Trusted metrics** - LCP, CLS, TBT are industry-standard Core Web Vitals.
- **Mobile testing** - Built-in mobile emulation.
- **Comprehensive** - Covers performance, accessibility, best practices, SEO.
- **Familiar output** - Clients recognize Lighthouse scores.

**Integration:** Run via CLI (`lighthouse <url> --output json`) or use the npm package programmatically.

### SQLite for MVP Storage

**Decision:** Use SQLite for storing crawl results and analysis data.

**Why:**
- **Zero setup** - No database server required.
- **Already implemented** - Existing code uses SQLite.
- **Portable** - Single file, easy to share/backup.
- **Fast enough** - For single-user MVP, SQLite handles thousands of pages fine.

**When to upgrade:** Move to PostgreSQL when building multi-user web service or need concurrent writes.

### FastAPI for Web Interface

**Decision:** Use FastAPI for the web API and simple HTML dashboard.

**Why:**
- **Fast development** - Automatic OpenAPI docs, request validation.
- **Async-ready** - Can handle concurrent scan requests.
- **Consistent with knowledge base project** - Same stack.
- **Simple HTML** - No need for React/Vue for MVP; server-rendered HTML is fine.

### Severity Scoring System

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

## Business Model

### Freemium SaaS
- **Free:** 1 site scan/month, summary only (issue counts, 3 sample issues)
- **Pro ($29/month):** Unlimited scans, full reports, PDF export
- **Agency ($99/month):** White-label reports, client dashboard, API access, scheduled monitoring

### One-Time Audit
- **Deep Audit ($500-1000):** Comprehensive report + prioritized remediation plan + consultation

## Success Metrics

- Issues caught: Target 10+ per site
- False positive rate: <5%
- Scan time: <5 min for sites under 50 pages
- Report clarity: Users can act without explanation
- Demo conversion: 20%+ of demos lead to engagement

## Proof Points

- Already caught real errors on savaslabs.com (spelling, accessibility)
- Forbes AI billionaires page has misspelling (validation opportunity)
- RIF site has taxonomy term issue (proven Drupal-specific detection)
- Existing code at `/projects/savas/not/RAG-test-Slack/website_analyzer.py` (1800+ lines)

## Future Enhancements

After MVP, expand to cover additional quality checks organized by category:

### Content Quality (Expanded)
- Reading level analysis (Flesch-Kincaid score)
- Passive voice detection
- Sentence length distribution
- Word complexity/jargon detection
- Clichés and buzzwords
- Brand voice consistency
- Outdated content detection (stale dates, past events)
- Placeholder text detection ("Lorem ipsum", "Coming soon")
- Missing/weak CTAs
- Value proposition clarity

### SEO (Expanded)
- Twitter Card validation
- Schema.org markup validation
- FAQ schema opportunities
- How-to schema opportunities
- Local business schema
- Breadcrumb schema
- XML sitemap validation
- Redirect chains and loops
- Soft 404 detection
- URL structure analysis
- Trailing slash consistency
- Parameter canonicalization
- Hreflang for multilingual sites
- Internal linking depth analysis
- Anchor text distribution
- Image filename optimization
- Next-gen image formats (WebP, AVIF)

### Accessibility (Expanded)
- Skip navigation links
- Focus management
- ARIA live regions
- Accessible modals/dialogs
- Table accessibility
- PDF accessibility
- Video captions and audio descriptions
- Touch target size validation
- Motion/animation (prefers-reduced-motion)
- Reading order (visual vs DOM)

### Security (Expanded)
- Content Security Policy analysis
- Cookie security (HttpOnly, Secure, SameSite)
- CORS misconfiguration
- Clickjacking protection (X-Frame-Options)
- HSTS configuration
- API key exposure in JavaScript
- Directory listing detection
- Backup file exposure (.bak, .old, .zip)
- Source control exposure (.git/)
- Debug mode detection
- Verbose error messages
- Open redirects
- DOM-based XSS patterns

### Performance (Expanded)
- Time to First Byte (TTFB)
- First Contentful Paint (FCP)
- Time to Interactive (TTI)
- Render-blocking resource detection
- Unused CSS/JS detection
- Image lazy loading validation
- Font loading optimization
- Browser caching headers
- CDN usage detection
- HTTP/2 or HTTP/3 usage
- Preconnect/prefetch opportunities
- Third-party script impact

### UX/Usability
- 404 page quality
- Search functionality presence
- Navigation depth (clicks to content)
- Breadcrumb presence
- Consistent navigation
- Mobile menu functionality
- Form validation feedback
- Error message clarity
- Print styles

### Technical/Code Quality
- W3C HTML validation
- CSS validation
- Console errors
- Deprecated API usage
- Outdated library detection
- Known vulnerable dependencies

### Compliance (Expanded)
- Privacy policy completeness
- Cookie policy completeness
- Terms of service presence
- Data collection transparency
- Industry-specific compliance indicators (HIPAA, PCI-DSS)

### Brand & Marketing
- Social media links validation
- Contact information completeness
- Trust signals (testimonials, certifications)
- Newsletter signup presence

### AI Engine Optimization (AEO/GEO)
- FAQ content format
- Q&A schema markup
- Citation-worthy content
- Source attribution
- Expert author signals (E-E-A-T)
- Content freshness dates
- Topic coverage depth

## Open Questions

- [x] ~~Should agent create git commits or direct CMS edits?~~ → Detection first, auto-fix is Phase 2+
- [ ] How to handle CommonCrawl integration for blocked sites?
- [ ] What's the right scan depth limit for freemium tier?
- [ ] How to price for different site sizes (pages)?
- [ ] Should we integrate with existing SEO tools (Screaming Frog, Ahrefs)?

## Related Work

- **Existing code:** `/projects/savas/not/RAG-test-Slack/website_analyzer.py`
  - 1800+ lines, comprehensive implementation
  - Playwright crawler with anti-bot stealth
  - LLM text analysis (spelling, grammar)
  - SEO, WCAG, security checks
  - SQLite storage option
  - Needs: axe-core integration, Lighthouse integration, better reporting

- **Competitors to study:**
  - Screaming Frog (SEO crawler)
  - WAVE (accessibility)
  - Lighthouse (performance)
  - Grammarly (content)
  - Sucuri/Wordfence (security)

## Next Steps

1. [ ] Set up new project structure in `website-quality-agent/`
2. [ ] Port and refactor existing `website_analyzer.py` into modular structure
3. [ ] Add axe-core integration for accessibility
4. [ ] Add Lighthouse CLI integration for performance
5. [ ] Build simple FastAPI web interface
6. [ ] Create report templates (HTML dashboard + PDF)
7. [ ] Test on 5 client sites, document results
8. [ ] Deploy to Fly.io for demo access
