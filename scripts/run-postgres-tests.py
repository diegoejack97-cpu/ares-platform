"""Integration release gate: missing DB, skipped tests, or no tests all fail."""

import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def main() -> int:
    if not os.environ.get("ARES_TEST_DATABASE_URL"):
        print("ARES_TEST_DATABASE_URL is required; database tests cannot be skipped")
        return 1
    with tempfile.TemporaryDirectory(prefix="ares-integration-") as directory:
        report = Path(directory) / "junit.xml"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "backend/tests",
                "-m",
                "integration",
                "-q",
                "--tb=short",
                f"--junitxml={report}",
            ]
        )
        if not report.exists():
            return result.returncode or 1
        cases = ET.parse(report).findall(".//testcase")
        skipped = sum(case.find("skipped") is not None for case in cases)
        print(f"PostgreSQL release gate: {len(cases)} tests, {skipped} skipped")
        return result.returncode or int(not cases or skipped > 0)


if __name__ == "__main__":
    raise SystemExit(main())
