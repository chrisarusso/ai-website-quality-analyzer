# Website Quality Agent

**Status:** MVP Built + Remote Execution
**Last Updated:** 2025-12-27

Automated agent that crawls websites, detects quality issues, and generates comprehensive reports. Designed for both internal client demos and as a potential freemium SaaS product.

**Related docs:**
- [docs/STATUS.md](docs/STATUS.md) - Implementation status, recent changes, test results
- [docs/BACKLOG.md](docs/BACKLOG.md) - Future improvements, known issues
- [docs/PHASE2-AUTOFIX.md](docs/PHASE2-AUTOFIX.md) - Auto-fix agent planning
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - Technical decisions and rationale

---

## Use Cases

### UC1: Client Demo / Prospect Scan
- **Who:** Savas sales/account team
- **Trigger:** Manual - before or during a client conversation
- **Input:** Client's website URL
- **Output:** Professional report highlighting 5-10 key issues with severity
- **Time:** < 5 minutes for small sites

### UC2: Self-Service Freemium Scan
- **Who:** Anyone (inbound marketing)
- **Trigger:** Visitor enters URL on public web page
- **Output:** Teaser report - issue counts by category, 2-3 samples, blur/gate the rest
- **Goal:** Lead generation, convert to paid

### UC3: Full Comprehensive Audit
- **Who:** Paying customers or internal QA
- **Output:** Complete report with all issues, severity, location, recommendations
- **Delivery:** Web dashboard + PDF export

### UC4: Scheduled Monitoring (Phase 2)
- **Who:** Subscription customers
- **Output:** Delta report (what's new, fixed, worse)
- **Notifications:** Email/Slack on new critical issues

---

## MVP Quality Checks

10 high-impact check categories:

| Category | What's Checked |
|----------|----------------|
| **SEO** | Title, meta, H1, canonical, structured data, Open Graph |
| **Spelling** | LLM-powered, context-aware (ignores proper nouns, tech terms) |
| **Grammar** | LLM-powered grammar analysis |
| **Formatting** | Spacing, punctuation, heading hierarchy |
| **Accessibility** | Alt text, lang, labels, ARIA, focus indicators |
| **Links** | Broken links, 403s, thin content |
| **Compliance** | Cookie consent, privacy policy, tracking disclosure |
| **Performance** | Page size, load time, resource count |
| **Mobile** | Viewport, touch targets, responsive images |
| **CMS Security** | Drupal/WP version detection, CVEs, exposed config |

---

## Project Structure

```
website-quality-agent/
├── src/website_agent/
│   ├── crawler/           # Playwright + fallback crawlers
│   ├── analyzers/         # 10 analyzer modules
│   ├── reporting/         # Aggregation, HTML reports
│   ├── storage/           # SQLite store
│   ├── api/               # FastAPI web service
│   └── cli.py             # CLI interface
├── docs/                  # Detailed documentation
├── tests/                 # 41 tests passing
└── scripts/               # Deployment scripts
```

---

## Business Model

### Freemium SaaS
- **Free:** 1 scan/month, summary only
- **Pro ($29/month):** Unlimited scans, full reports, PDF export
- **Agency ($99/month):** White-label, client dashboard, API, scheduled monitoring

### One-Time Audit
- **Deep Audit ($500-1000):** Comprehensive report + remediation plan + consultation

---

## Success Metrics

- Issues caught: Target 10+ per site
- False positive rate: <5%
- Scan time: <5 min for sites under 50 pages
- Report clarity: Users can act without explanation
- Demo conversion: 20%+ of demos lead to engagement

---

## Proof Points

- Caught real errors on savaslabs.com (spelling, accessibility)
- Forbes AI billionaires page has misspelling (validation opportunity)
- RIF site has taxonomy term issue (proven Drupal-specific detection)

---

## Next Steps

### Completed
1. [x] Project structure in `website-quality-agent/`
2. [x] Port/refactor existing code into modular structure
3. [x] FastAPI web interface
4. [x] HTML report templates
5. [x] Remote execution with Slack notifications

### Up Next
6. [ ] Add axe-core integration for full WCAG testing
7. [ ] Add Lighthouse CLI for Core Web Vitals
8. [ ] Add broken link checker (external URLs)
9. [ ] Create PDF report generation
10. [ ] Deploy to Fly.io for demo access

---

## Related Work

- **Existing code:** `/projects/savas/not/RAG-test-Slack/website_analyzer.py` (1800+ lines)
- **Competitors:** Screaming Frog, WAVE, Lighthouse, Grammarly, Sucuri
