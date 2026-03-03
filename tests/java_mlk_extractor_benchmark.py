import json
import sys
from pathlib import Path
from typing import Dict


REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_SRC = REPO_ROOT / "src"
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from tstool.analyzer.Java_TS_analyzer import Java_TSAnalyzer  # noqa: E402
from tstool.dfbscan_extractor.Java.Java_MLK_extractor import (  # noqa: E402
    Java_MLK_Extractor,
)


CASE_MANIFEST: Dict[str, Dict[str, object]] = {
    "MLKCase01_CloseableLeak.java": {"method": "run", "expected_leak": True},
    "MLKCase02_CloseableClosed.java": {"method": "run", "expected_leak": False},
    "MLKCase03_TryWithResourcesSafe.java": {
        "method": "run",
        "expected_leak": False,
    },
    "MLKCase04_ThreadLocalLeak.java": {"method": "run", "expected_leak": True},
    "MLKCase05_ThreadLocalSafe.java": {"method": "run", "expected_leak": False},
    "MLKCase06_CollectionLeak.java": {"method": "add", "expected_leak": True},
    "MLKCase07_CollectionSafe.java": {
        "method": "addAndClear",
        "expected_leak": False,
    },
    "MLKCase08_ListenerLeak.java": {"method": "run", "expected_leak": True},
    "MLKCase09_ListenerSafe.java": {"method": "run", "expected_leak": False},
    "MLKCase10_CacheLeak.java": {"method": "putValue", "expected_leak": True},
    "MLKCase11_CacheSafe.java": {
        "method": "putAndRemove",
        "expected_leak": False,
    },
    "MLKCase12_CloseableLeakByAssign.java": {
        "method": "run",
        "expected_leak": True,
    },
    "MLKCase13_HelperCloseSafe.java": {"method": "run", "expected_leak": False},
    "MLKCase14_HelperChainCloseSafe.java": {"method": "run", "expected_leak": False},
    "MLKCase15_ReturnedResourceLeak.java": {"method": "run", "expected_leak": True},
    "MLKCase16_ReturnedResourceSafe.java": {"method": "run", "expected_leak": False},
    "MLKCase17_ConditionalCloseLeak.java": {"method": "run", "expected_leak": True},
    "MLKCase18_FinallyCloseSafe.java": {"method": "run", "expected_leak": False},
    "MLKCase19_CatchOnlyCloseLeak.java": {"method": "run", "expected_leak": True},
    "MLKCase20_FinallyHelperCloseSafe.java": {"method": "run", "expected_leak": False},
    "MLKCase21_CatchHelperCloseLeak.java": {"method": "run", "expected_leak": True},
    "MLKCase22_BranchBothCloseSafe.java": {"method": "run", "expected_leak": False},
    "MLKCase23_BranchBothHelperCloseSafe.java": {
        "method": "run",
        "expected_leak": False,
    },
    "MLKCase24_CustomAutoCloseableLeak.java": {
        "method": "run",
        "expected_leak": True,
    },
    "MLKCase25_CustomAutoCloseableSafe.java": {"method": "run", "expected_leak": False},
    "MLKCase26_ConditionalAcquireAndCloseSafe.java": {
        "method": "run",
        "expected_leak": False,
    },
    "MLKCase27_ConditionalAcquireAndHelperCloseSafe.java": {
        "method": "run",
        "expected_leak": False,
    },
    "MLKCase28_SwitchAllCloseSafe.java": {"method": "run", "expected_leak": False},
    "MLKCase29_SwitchAllHelperCloseSafe.java": {
        "method": "run",
        "expected_leak": False,
    },
    "MLKCase30_SwitchNoDefaultLeak.java": {"method": "run", "expected_leak": True},
    "MLKCase31_SwitchRuleAllCloseSafe.java": {"method": "run", "expected_leak": False},
    "MLKCase32_SwitchFallthroughSafe.java": {"method": "run", "expected_leak": False},
    "MLKCase33_SwitchOneBranchLeak.java": {"method": "run", "expected_leak": True},
    "MLKCase34_SwitchBranchAcquireCloseSafe.java": {
        "method": "run",
        "expected_leak": False,
    },
    "MLKCase35_SwitchBranchAcquireHelperCloseSafe.java": {
        "method": "run",
        "expected_leak": False,
    },
}


def load_java_files(case_dir: Path) -> Dict[str, str]:
    return {
        str(path.resolve()): path.read_text(encoding="utf-8")
        for path in sorted(case_dir.glob("*.java"))
    }


def run_benchmark() -> Dict[str, object]:
    case_dir = REPO_ROOT / "benchmark" / "Java" / "toy" / "MLK"
    code_in_files = load_java_files(case_dir)
    analyzer = Java_TSAnalyzer(code_in_files, "Java", max_symbolic_workers_num=1)
    extractor = Java_MLK_Extractor(analyzer)
    summaries = extractor.build_project_summaries()

    tp = fp = fn = tn = 0
    details = []

    for file_name, meta in CASE_MANIFEST.items():
        file_path = str((case_dir / file_name).resolve())
        functions = [
            function
            for function in analyzer.function_env.values()
            if function.file_path == file_path
            and function.function_name == meta["method"]
        ]
        if not functions:
            raise RuntimeError(f"Method {meta['method']} not found in {file_name}")
        function = functions[0]
        summary = summaries.get(function.function_id)
        if summary is None:
            raise RuntimeError(f"Summary not found for {file_name}::{meta['method']}")

        leak_sources = summary.leak_sources()
        predicted_leak = len(leak_sources) > 0
        expected_leak = bool(meta["expected_leak"])

        if expected_leak and predicted_leak:
            tp += 1
        elif not expected_leak and predicted_leak:
            fp += 1
        elif expected_leak and not predicted_leak:
            fn += 1
        else:
            tn += 1

        details.append(
            {
                "file": file_name,
                "method": meta["method"],
                "expected_leak": expected_leak,
                "predicted_leak": predicted_leak,
                "sources": sorted(summary.acquired_values.keys()),
                "sinks": sorted(summary.released_names),
                "transfers": sorted(summary.transferred_names),
                "leak_sources": [value.name for value in leak_sources],
            }
        )

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    accuracy = (tp + tn) / len(CASE_MANIFEST)

    return {
        "summary": {
            "cases": len(CASE_MANIFEST),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "accuracy": round(accuracy, 4),
        },
        "details": details,
    }


def main() -> None:
    print(json.dumps(run_benchmark(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
