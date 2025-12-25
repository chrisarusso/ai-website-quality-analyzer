# Website Quality Agent

**Status:** MVP Built + Remote Execution
**Last Updated:** 2025-12-24

## Current Status / Where We Left Off

**Scan Running:** Full savaslabs.com scan running on AWS (ubuntu@3.142.219.101)
- Started: 2025-12-24 ~6:32 PM PT
- Slack notifications enabled (will notify on complete/fail)
- Estimated completion: 10-15 minutes

**To check progress:**
```bash
ssh -i ~/.ssh/AWS-created-nov-27-2025.pem ubuntu@3.142.219.101 'tail -f /home/ubuntu/website-quality-agent/scan-20251224_183202.log'
```

**To fetch report when done:**
```bash
scp -i ~/.ssh/AWS-created-nov-27-2025.pem ubuntu@3.142.219.101:/home/ubuntu/website-quality-agent/report_*.html .
```

---

## Implementation Status

### What's Built ✅

| Component | Status | Notes |
|-----------|--------|-------|
| **Project structure** | ✅ Complete | Modular `src/website_agent/` layout |
| **Playwright crawler** | ✅ Complete | Anti-bot stealth, rate limiting, respects robots.txt |
| **Simple crawler fallback** | ✅ Complete | Requests + BeautifulSoup for simpler sites |
| **SEO analyzer** | ✅ Complete | Title, meta, H1, canonical, Open Graph, structured data + HTML context |
| **Content analyzer (LLM)** | ✅ Complete | Spelling, grammar, formatting via GPT-4o-mini (balanced prompt) |
| **Accessibility analyzer** | ✅ Complete | Alt text, lang, labels, ARIA + surrounding HTML context |
| **Link analyzer** | ✅ Complete | Thin content, JavaScript links detection |
| **Performance analyzer** | ✅ Basic | Page size, resource count, load time |
| **Mobile analyzer** | ✅ Complete | Viewport, touch targets, zoom settings |
| **Compliance analyzer** | ✅ Complete | Privacy policy, cookie consent, tracking detection |
| **CMS analyzer** | ✅ Complete | Drupal/WordPress detection and version checks |
| **SQLite storage** | ✅ Complete | Stores scans, pages, issues |
| **Report aggregator** | ✅ Complete | Scores, all issues, severity filters, crawled URLs list |
| **FastAPI web service** | ✅ Complete | REST API for scans, results, reports |
| **CLI** | ✅ Complete | `website-agent scan`, `serve`, `status`, `report`, `--all` flag |
| **HTML reports** | ✅ Complete | Collapsible categories, severity filters, "Why It Matters" section |
| **Tests** | ✅ Complete | 41 tests passing |
| **Remote execution** | ✅ Complete | `run-remote.sh` with Slack notifications (start/complete/fail) |
| **Unlimited crawling** | ✅ Complete | `--all` flag or `--max-pages 0` for no limit |

### What's Not Yet Built ⏳

| Component | Priority | Notes |
|-----------|----------|-------|
| **axe-core integration** | High | Full WCAG compliance via Playwright injection |
| **Lighthouse integration** | High | Core Web Vitals (LCP, CLS, TBT) |
| **PDF report generation** | Medium | WeasyPrint or Playwright print |
| **Broken link checker** | Medium | HEAD requests to verify external links |
| **Web UI dashboard** | Medium | Beyond basic HTML report |
| **Scheduled monitoring** | Low | Cron-based recurring scans |
| **Delta reports** | Low | Compare scans over time |
| **Freemium gating** | Low | Blur/limit results for free tier |

---

## Phase 2: Auto-Fix Agent

**Status:** Planning
**Target:** POC on savaslabs.com (Drupal + GitHub)

### Overview

Extend the scanner to not just detect issues but propose and apply fixes automatically, with human approval workflow.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Scan Results (Issues)                        │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Fix Classifier                                 │
│                                                                 │
│  Categorizes each issue:                                        │
│  • CONTENT_FIX - Can fix via CMS API (alt text, spelling, etc) │
│  • CODE_FIX - Can fix via Git PR (templates, config)           │
│  • MANUAL_ONLY - Requires human judgment (design decisions)     │
│  • NOT_FIXABLE - Detection-only (3rd party, external)          │
└─────────────────────┬───────────────────────────────────────────┘
                      │
        ┌─────────────┴─────────────┐
        ▼                           ▼
┌───────────────────┐     ┌───────────────────┐
│  Content Fixer    │     │   Code Fixer      │
│  (Drupal API)     │     │   (GitHub PRs)    │
└────────┬──────────┘     └────────┬──────────┘
         │                         │
         ▼                         ▼
┌───────────────────┐     ┌───────────────────┐
│ Create unpublished│     │  Create PR with:  │
│ revision with:    │     │  - Diff           │
│ - Proposed change │     │  - Screenshots    │
│ - Before/after    │     │  - Issue details  │
└────────┬──────────┘     └────────┬──────────┘
         │                         │
         └──────────┬──────────────┘
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Approval Queue                                  │
│                                                                 │
│  • Web UI showing pending fixes                                 │
│  • Before/after preview                                         │
│  • One-click approve/reject per fix                            │
│  • Batch approve by category                                    │
│  • Slack notifications for new fixes                           │
└─────────────────────────────────────────────────────────────────┘
```

### Issue-to-Fix Mapping

| Issue Type | Fix Type | Method | Confidence |
|------------|----------|--------|------------|
| Missing alt text (content images) | CONTENT_FIX | Drupal API - update media entity | High (AI generates alt) |
| Missing alt text (theme images) | CODE_FIX | Git PR - update template | High |
| Spelling errors | CONTENT_FIX | Drupal API - update node body | High (have suggestion) |
| Grammar errors | CONTENT_FIX | Drupal API - update node body | Medium (verify suggestion) |
| Missing meta description | CONTENT_FIX | Drupal API - update node field | Medium (AI generates) |
| Empty link text | CODE_FIX | Git PR - update template | High |
| Missing lang attribute | CODE_FIX | Git PR - update html.html.twig | High |
| Missing H1 | CODE_FIX | Git PR - update page template | Medium |
| Multiple H1s | CODE_FIX | Git PR - change extra H1→H2 | Medium |
| Missing canonical | CODE_FIX | Git PR - add metatag | High |
| Cookie consent missing | MANUAL_ONLY | Needs design/legal decision | N/A |
| Third-party tracking | MANUAL_ONLY | Business decision | N/A |

### POC Scope (Savas Labs)

#### POC 1: Alt Text Fixer (Highest Impact)
**Goal:** Auto-generate alt text for images missing it, submit as draft revisions

**Steps:**
1. From scan, get list of images missing alt text with their URLs
2. For each image:
   - Download the image
   - Use GPT-4o vision to generate descriptive alt text
   - Find the image in Drupal (via JSON:API query by URL)
   - Create a revision with the new alt text (unpublished)
   - Log the proposed change
3. Notify via Slack: "X images have proposed alt text - review at [URL]"

**Drupal Integration:**
```bash
# Get media entities via JSON:API
GET /jsonapi/media/image?filter[field_media_image.uri][value]=public://...

# Update with new alt text (creates revision)
PATCH /jsonapi/media/image/{uuid}
{
  "data": {
    "type": "media--image",
    "id": "{uuid}",
    "attributes": {
      "field_media_image": {
        "alt": "AI-generated alt text here"
      }
    }
  }
}
```

**AI Alt Text Generation:**
```python
# Use GPT-4o vision
response = openai.chat.completions.create(
    model="gpt-4o",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "Generate concise, descriptive alt text for this image. Be specific but brief (under 125 chars). Don't start with 'Image of' or 'Picture of'."},
            {"type": "image_url", "image_url": {"url": image_url}}
        ]
    }]
)
```

#### POC 2: Spelling/Grammar Fixer
**Goal:** Apply spelling/grammar fixes to content, submit as draft revisions

**Steps:**
1. From scan, get spelling/grammar issues with context
2. For each issue:
   - Find the node containing this text (search via JSON:API)
   - Get current body content
   - Apply the fix (replace misspelled word or grammar issue)
   - Create revision with fix (unpublished)
   - Log before/after
3. Notify via Slack

**Challenge:** Locating exact content in Drupal
- May need to search across multiple fields (body, summary, custom fields)
- Need to handle HTML entities and formatting

#### POC 3: Code Template Fixer
**Goal:** Create GitHub PRs for template-level issues

**Steps:**
1. Clone Savas Labs repo
2. For each code-fixable issue:
   - Identify which template file to modify
   - Make the change (add lang attr, fix empty link, etc.)
   - Stage the change
3. Create a single PR with all template fixes
4. Include in PR description:
   - List of issues fixed
   - Before/after for each
   - Link to scan report

**Example Fixes:**
```twig
{# Before: Missing lang attribute #}
<html>

{# After #}
<html lang="en">
```

```twig
{# Before: Empty link #}
<a href="{{ url }}" class="social-icon">
  <i class="fa fa-twitter"></i>
</a>

{# After #}
<a href="{{ url }}" class="social-icon" aria-label="Twitter">
  <i class="fa fa-twitter" aria-hidden="true"></i>
</a>
```

### Approval Workflow

#### Option A: Drupal Content Moderation (Content Fixes)
- Create revisions in "Draft" or "Needs Review" state
- Editors review in Drupal admin
- Approve → publishes the revision
- Reject → deletes the revision

#### Option B: Custom Approval UI (All Fixes)
- Web dashboard showing all pending fixes
- Group by type (alt text, spelling, code)
- Preview before/after
- Approve individually or batch
- On approve: publishes revision OR merges PR
- On reject: discards fix, optionally adds to ignore list

#### Option C: Slack-Based Approval (Quick POC)
- Post each fix to Slack with buttons
- ✅ Approve / ❌ Reject buttons
- On approve: API call to publish/merge
- Simple but doesn't scale

### Data Model Extension

```python
class ProposedFix(BaseModel):
    """A proposed fix for an issue."""
    id: str
    issue_id: str  # Reference to original issue
    scan_id: str
    fix_type: Literal["CONTENT_FIX", "CODE_FIX", "MANUAL_ONLY"]
    status: Literal["pending", "approved", "rejected", "applied"]

    # What to change
    target_type: str  # "drupal_media", "drupal_node", "git_file"
    target_id: str    # UUID, node ID, or file path
    field_name: Optional[str]  # For Drupal: which field

    # The fix
    original_value: str
    proposed_value: str

    # Metadata
    confidence: float  # 0-1, how confident we are in the fix
    ai_generated: bool  # Was this generated by AI?
    created_at: datetime
    reviewed_at: Optional[datetime]
    reviewed_by: Optional[str]

    # For code fixes
    pr_url: Optional[str]
    commit_sha: Optional[str]
```

### Configuration

```yaml
# fixer_config.yaml
drupal:
  base_url: https://savaslabs.com
  api_endpoint: /jsonapi
  auth:
    type: oauth  # or basic, api_key
    client_id: ${DRUPAL_CLIENT_ID}
    client_secret: ${DRUPAL_CLIENT_SECRET}

  # Content moderation states
  draft_state: draft
  published_state: published

github:
  repo: savaslabs/savaslabs.com  # or wherever the theme is
  base_branch: main
  pr_prefix: "fix/website-quality-"

  # Labels to add to PRs
  labels:
    - automated
    - website-quality

openai:
  model: gpt-4o  # For vision/alt text
  temperature: 0.3

slack:
  webhook_url: ${SLACK_WEBHOOK_URL}
  channel: "#website-quality"
  notify_on:
    - new_fixes_proposed
    - fix_approved
    - fix_rejected

approval:
  mode: slack  # slack, dashboard, drupal_moderation
  auto_approve_threshold: 0.95  # Auto-approve if confidence > 95%
  batch_size: 10  # Max fixes to propose at once
```

### Implementation Order

1. **Week 1: Alt Text Fixer POC**
   - [ ] Set up Drupal API authentication
   - [ ] Image → alt text generation with GPT-4o vision
   - [ ] Create draft revisions in Drupal
   - [ ] Basic Slack notification
   - [ ] Test on 10 images from savaslabs.com

2. **Week 2: Spelling/Grammar Fixer**
   - [ ] Content search in Drupal (find node by text)
   - [ ] Text replacement logic
   - [ ] Revision creation
   - [ ] Expand Slack notifications

3. **Week 3: Code Template Fixer**
   - [ ] GitHub API integration
   - [ ] Template file identification
   - [ ] Change generation for common issues
   - [ ] PR creation workflow

4. **Week 4: Approval Dashboard**
   - [ ] Simple web UI for reviewing fixes
   - [ ] Before/after preview
   - [ ] Approve/reject actions
   - [ ] Integration with Drupal/GitHub

### Success Metrics

- **Alt text coverage:** 0% → 90%+ of images have alt text
- **Time to fix:** Days → Minutes (from detection to proposed fix)
- **Approval rate:** Target 80%+ of AI suggestions approved
- **False positive rate:** <5% of suggestions rejected as incorrect

### Security Considerations

- Drupal API credentials stored securely (not in code)
- GitHub token with minimal required permissions
- All changes create revisions/PRs (never direct publish)
- Audit log of all proposed and applied changes
- Rate limiting to avoid overwhelming CMS

### Future Enhancements

- **Learning from rejections:** If a fix is rejected, learn why and improve
- **Bulk operations:** "Fix all spelling errors" with one approval
- **Scheduled runs:** Weekly scan + fix proposal
- **Multi-site support:** Same agent for multiple Drupal sites
- **Custom fix rules:** Define site-specific fixes (e.g., brand name spelling)

### Recent Changes

**2025-12-24:**
- **Report improvements:**
  - Added HTML context for all issues (shows actual code to fix)
  - Added severity filter checkboxes (Critical/High/Medium/Low)
  - Added "Why These Issues Matter" educational section
  - Added collapsible list of all crawled URLs with status/issue counts
  - Issues now show surrounding HTML for accessibility problems
- **Content analyzer rebalanced:**
  - Updated LLM prompt to reduce false positives (was flagging correct words)
  - Grammar issues now include original text + suggested fix
  - Spelling detection works but sites tested are clean
- **Remote execution with Slack:**
  - `run-remote.sh` now sends Slack notifications on start/complete/fail
  - Configured for AWS EC2 (ubuntu@3.142.219.101)
  - Scan survives disconnection (runs via nohup)
  - Report includes pages crawled, issues found, score, duration
- **Unlimited page crawling:**
  - Added `--all` flag to crawl all pages
  - `--max-pages 0` also means unlimited
- **Ran scans on:**
  - americanpackaging.com (74 pages, 811 issues)
  - savaslabs.com (running now on AWS)

**2025-12-22:**
- Built complete MVP from scratch
- All 10 check categories implemented
- Scoring algorithm: logarithmic curve normalized by page count
- HTML reports show all issues (not just top 10) with collapsible sections
- Added `start.sh`, `scan-overnight.sh`, `run-remote.sh` scripts
- First successful scan: savaslabs.com (49 pages, 1260 issues, 7 min)

### Test Results

Latest scan of savaslabs.com:
- **Pages:** 49
- **Total issues:** 1,260
- **Overall score:** 8.3/100 (many accessibility issues)
- **By category:**
  - SEO: 51/100 (177 issues)
  - Grammar: 80/100 (25 issues)
  - Formatting: 92/100 (15 issues)
  - Accessibility: 0/100 (626 issues - needs alt text)
  - Compliance: 49/100 (145 issues)
  - Performance: 56/100 (120 issues)
  - Mobile: 76/100 (54 issues)
  - Security: 60/100 (98 issues)

---

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

### Completed ✅
1. [x] Set up new project structure in `website-quality-agent/`
2. [x] Port and refactor existing `website_analyzer.py` into modular structure
3. [x] Build simple FastAPI web interface
4. [x] Create HTML report templates

### Up Next
5. [ ] Add axe-core integration for full WCAG accessibility testing
6. [ ] Add Lighthouse CLI integration for Core Web Vitals
7. [ ] Add broken link checker (HEAD requests to external URLs)
8. [ ] Create PDF report generation
9. [ ] Test on 5 client sites, document results
10. [ ] Deploy to Fly.io for demo access

### Quick Start

```bash
# Run a local scan (quick, limited pages)
uv run website-agent scan https://example.com --max-pages 20

# Run a local scan (all pages, takes longer)
uv run website-agent scan https://example.com --all --output html

# Run on remote AWS server (survives disconnection, Slack notifications)
./run-remote.sh https://example.com

# Check remote scan progress
ssh -i ~/.ssh/AWS-created-nov-27-2025.pem ubuntu@3.142.219.101 'tail -f /home/ubuntu/website-quality-agent/scan-*.log'

# Fetch report from remote
scp -i ~/.ssh/AWS-created-nov-27-2025.pem ubuntu@3.142.219.101:/home/ubuntu/website-quality-agent/report_*.html .

# Start the local web API
./start.sh
```

### Environment Config (.env)

Key settings configured:
- `OPENAI_API_KEY` - For LLM content analysis
- `REMOTE_HOST=3.142.219.101` - AWS EC2 instance
- `REMOTE_USER=ubuntu`
- `REMOTE_SSH_KEY=~/.ssh/AWS-created-nov-27-2025.pem`
- `SLACK_WEBHOOK_URL` - For scan notifications
