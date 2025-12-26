#!/usr/bin/env python3
"""Regenerate an HTML report from existing scan data in the database.

Usage:
    uv run python scripts/regenerate-report.py [SCAN_ID]

If SCAN_ID is not provided, uses the most recent savaslabs.com scan.
"""

import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from website_agent.storage import SQLiteStore
from website_agent.reporting import ReportAggregator


def main():
    store = SQLiteStore()
    aggregator = ReportAggregator()

    # Get scan ID from args or find most recent savaslabs scan
    if len(sys.argv) > 1:
        scan_id = sys.argv[1]
    else:
        # Find the savaslabs scan with the most issues
        import sqlite3
        conn = sqlite3.connect(store.db_path)
        cursor = conn.execute("""
            SELECT s.id, COUNT(i.id) as issue_count
            FROM scans s
            LEFT JOIN issues i ON s.id = i.scan_id
            WHERE s.url LIKE '%savaslabs%'
            GROUP BY s.id
            ORDER BY issue_count DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        conn.close()

        if not row:
            print("No savaslabs scans found in database")
            sys.exit(1)

        scan_id = row[0]
        print(f"Using scan {scan_id} with {row[1]} issues")

    # Get the scan
    scan = store.get_scan(scan_id)
    if not scan:
        print(f"Scan not found: {scan_id}")
        sys.exit(1)

    print(f"Scan: {scan.id}")
    print(f"URL: {scan.url}")
    print(f"Pages: {len(scan.pages)}")
    print(f"Status: {scan.status}")

    # Count issues
    total_issues = sum(len(p.issues) for p in scan.pages)
    print(f"Total issues: {total_issues}")

    # Generate report with fix UI enabled
    summary = aggregator.aggregate(scan)
    html = aggregator.generate_html_report(scan, summary, enable_fixes=True)

    # Save report
    output_path = Path(f"report_{scan_id}_with_fixes.html")
    output_path.write_text(html)
    print(f"\nReport saved to: {output_path}")
    print(f"File size: {output_path.stat().st_size / 1024:.1f} KB")

    # Open in browser
    import subprocess
    subprocess.run(["open", str(output_path)])
    print("Opened in browser")


if __name__ == "__main__":
    main()
