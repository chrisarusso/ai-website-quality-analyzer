# Website Quality Agent

**Status:** Planning
**Last Updated:** 2025-12-21

## Overview

Automated agent that crawls websites, detects quality issues, and optionally fixes them. Can log into Drupal/WordPress sites to make corrections. Runs on schedule or triggered by site changes.

## AI Readiness Categories Coverage

- ✅ Agents, Assistants & Automation
- ✅ Data & Engineering
- ✅ Generative AI
- ✅ Privacy, Security & Compliance
- ✅ Product Strategy
- ✅ Search & Content Discoverability
- ✅ Training & Empowerment
- ❌ Personalization

## Quality Checks

### Content Quality
- Spelling errors (proven: caught "ROT"→"ROI", client misspellings)
- Grammar issues
- Broken links (internal and external)
- Missing alt text on images
- Inconsistent terminology

### SEO
- Missing/duplicate title tags
- Missing/duplicate meta descriptions
- Missing H1 tags
- Image optimization
- Canonical URLs
- Open Graph tags
- Structured data

### Accessibility (WCAG)
- Alt text on images
- Form labels
- ARIA attributes
- Video captions
- Color contrast
- Keyboard navigation

### Security
- XSS/SQLi patterns
- Mixed content (HTTP on HTTPS)
- CSRF vulnerabilities
- Missing SRI (Subresource Integrity)
- Outdated CMS version

### Drupal/WordPress Specific
- Taxonomy terms not checked in views (proven issue found)
- Broken menu links
- Missing required fields
- Module/plugin conflicts
- Database query optimization

## Features

### Read-Only Mode (MVP)
- Crawl site and generate report
- Visual diff for detected issues
- Email/Slack alerts
- Weekly scheduled scans

### Interactive Mode
- Agent logs into CMS
- Makes fixes on staging site
- Takes screenshots for approval
- Creates documentation of changes
- Submits PR or publishes after approval

### Subscription Service
- Monitor site 24/7
- Fix issues automatically (with approval workflow)
- Monthly report of fixes
- Track improvement over time

## Technical Architecture

### Crawler
- Crawl4AI for AI-powered scraping
- Respect robots.txt
- Rate limiting
- Screenshot capability

### Analysis Engine
- LLM for content quality (spelling, grammar, context)
- Deterministic checks for SEO/accessibility
- Visual regression comparison
- Pattern matching for security issues

### CMS Integration
- Headless browser (Playwright/Puppeteer)
- Login automation
- CRUD operations via UI or API
- Staging environment testing

### Reporting
- Structured JSON output
- Visual diff reports
- Severity scoring (critical, high, medium, low)
- Trend analysis over time

## Business Model

### Freemium SaaS
- **Free**: 1 site scan/month
- **Pro ($29/month)**: Unlimited scans + monitoring
- **Agency ($99/month)**: White-label + client reporting + auto-fix

### One-Time Audit
- **Deep Audit ($500-1000)**: Comprehensive report + remediation plan

## MVP Scope

**Phase 1 (2 weeks)**
- Basic crawler with spelling/grammar/broken links
- Generate PDF report
- Run on-demand via CLI

**Phase 2 (1 week)**
- Add SEO + WCAG checks
- Web UI for running scans
- Email reports

**Phase 3 (2 weeks)**
- Scheduled scans
- Drupal/WordPress login capability
- Staging site auto-fix with approval workflow

## Success Metrics

- Issues caught: Target 10+ per site
- False positive rate: <5%
- Fix accuracy: 95%+ correct auto-fixes
- Time saved: 2 hours/week per client
- Revenue: $1000 MRR within 3 months

## Proof Points

- Already caught real errors on savaslabs.com
- Forbes AI billionaires page has misspelling (validation opportunity)
- RIF site has taxonomy term issue (proven)

## Open Questions

- [ ] What's the approval workflow for auto-fixes?
- [ ] How to handle dynamic content (React/Vue)?
- [ ] What's the right balance of automation vs human review?
- [ ] How to price for different site sizes?
- [ ] Should agent create git commits or direct CMS edits?

## Related Work

- Website quality analyzer: Core functionality already built
- Drupal/WordPress update agent: CMS interaction patterns
- Visual regression testing: Screenshot comparison

## Next Steps

- [ ] Test existing analyzer on 5 client sites
- [ ] Document top 20 issues found
- [ ] Design approval workflow UI
- [ ] Create pricing calculator based on site complexity
- [ ] Build competitor analysis (Grammarly, Screaming Frog, WAVE)
