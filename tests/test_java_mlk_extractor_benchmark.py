import unittest

from tests.java_mlk_extractor_benchmark import run_benchmark


class JavaMLKExtractorBenchmarkTests(unittest.TestCase):
    def test_fixture_benchmark_matches_expectations(self) -> None:
        result = run_benchmark()
        summary = result["summary"]

        self.assertEqual(summary["cases"], 35)
        self.assertEqual(summary["tp"], 13)
        self.assertEqual(summary["fp"], 0)
        self.assertEqual(summary["fn"], 0)
        self.assertEqual(summary["tn"], 22)


if __name__ == "__main__":
    unittest.main()
