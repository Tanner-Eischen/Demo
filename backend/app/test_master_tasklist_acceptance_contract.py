from __future__ import annotations

import re
import unittest
from pathlib import Path


PR_HEADER_RE = re.compile(r"^### \[[ x]\] PR(\d+):")
AC_RE = re.compile(r"\bAC-PR(\d+)-(\d+)\b")
TEST_RE = re.compile(r"\bTEST-PR(\d+)-(\d+)\b")
AC_COVER_RE = re.compile(r"\(covers (AC-PR\d+-\d+)\)")


class MasterTasklistAcceptanceContractTests(unittest.TestCase):
    def test_every_pr_has_acceptance_criteria_and_linked_tests(self) -> None:
        tasklist = Path(__file__).resolve().parents[2] / "docs" / "MASTER_TASKLIST.md"
        text = tasklist.read_text(encoding="utf-8")
        lines = text.splitlines()

        sections: dict[int, list[str]] = {}
        current_pr: int | None = None

        for line in lines:
            header = PR_HEADER_RE.match(line)
            if header:
                current_pr = int(header.group(1))
                sections[current_pr] = []
                continue
            if current_pr is not None:
                sections[current_pr].append(line)

        self.assertEqual(
            list(range(1, 17)),
            sorted(sections.keys()),
            "Tasklist must include PR1-PR16 sections.",
        )

        for pr_num, body_lines in sections.items():
            body = "\n".join(body_lines)
            ac_ids = [m.group(0) for m in AC_RE.finditer(body) if int(m.group(1)) == pr_num]
            test_ids = [m.group(0) for m in TEST_RE.finditer(body) if int(m.group(1)) == pr_num]
            covered_ac_ids = [m.group(1) for m in AC_COVER_RE.finditer(body)]

            self.assertGreaterEqual(
                len(ac_ids),
                1,
                f"PR{pr_num} must define at least one acceptance criterion (AC-PR{pr_num}-N).",
            )
            self.assertGreaterEqual(
                len(test_ids),
                1,
                f"PR{pr_num} must define at least one test item (TEST-PR{pr_num}-N).",
            )
            self.assertTrue(
                set(covered_ac_ids).intersection(set(ac_ids)),
                f"PR{pr_num} test items must reference at least one local acceptance criterion with '(covers AC-PR{pr_num}-N)'.",
            )


if __name__ == "__main__":
    unittest.main()
