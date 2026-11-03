"""Doctor diagnostic checks."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
from typing import List, Optional, Tuple
import urllib.request

from . import config
from . import fetch
from . import fulltext_check
from . import health


def get_doc_paths() -> Tuple[Path, Path]:
    """Return absolute paths to INSTALL.md and TROUBLESHOOT.md."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    return (repo_root / "INSTALL.md").resolve(), (repo_root / "TROUBLESHOOT.md").resolve()


def check_python_version() -> Tuple[str, bool, str]:
    """Check Python version >= 3.11."""
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 11)
    return ("Python Version", ok, f"{v.major}.{v.minor}.{v.micro}")


def check_home_writable(path: Optional[Path] = None) -> Tuple[str, bool, str]:
    """Check that FIN_NEWS_HOME directory is writable."""
    target_home = path or config.home()
    try:
        target_home.mkdir(parents=True, exist_ok=True)
        test_file = target_home / ".doctor_test_write"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        return ("FIN_NEWS_HOME Writable", True, str(target_home))
    except Exception as e:
        return ("FIN_NEWS_HOME Writable", False, f"Cannot write to {target_home}: {e}")


def check_network_connectivity(test_url: str = "https://vnexpress.net") -> Tuple[str, bool, str]:
    """Check network connectivity."""
    try:
        req = urllib.request.Request(
            test_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return ("Network Connectivity", True, f"Connected ({test_url})")
            return ("Network Connectivity", False, f"Status code {resp.status}")
    except Exception as e:
        return ("Network Connectivity", False, str(e))


check_network = check_network_connectivity


def run(check_network: bool = True, check_sources: bool = True) -> List[Tuple[str, bool, str]]:
    """Run standard doctor checks and return list of (name, passed, detail)."""
    results = [
        check_python_version(),
        check_home_writable(),
    ]

    if check_network:
        results.append(check_network_connectivity())

    if check_sources:
        try:
            sources = config.load("sources").get("sources", {})
            for sid, scfg in sources.items():
                if scfg.get("enabled", True):
                    _, h = fetch.fetch_source(sid, scfg, limit=1)
                    results.append((f"Source: {sid}", h.status == "ok", f"{h.status}: {h.detail}"))
        except Exception as e:
            results.append(("Sources Check", False, str(e)))

    return results


def run_fulltext(
    sources_cfg: Optional[dict] = None,
    profile: Optional[dict] = None,
    opener=None
) -> List[dict]:
    """Run fulltext check concurrently for all enabled sources (20s timeout each)."""
    if sources_cfg is None:
        sources_cfg = config.load("sources")
    if profile is None:
        profile = config.load("profile")

    sources = sources_cfg.get("sources", {})
    enabled_sources = {sid: scfg for sid, scfg in sources.items() if scfg.get("enabled", True)}

    results = []
    with ThreadPoolExecutor(max_workers=min(10, max(1, len(enabled_sources)))) as executor:
        future_to_sid = {
            executor.submit(fulltext_check.check_source, sid, scfg, profile, opener=opener): sid
            for sid, scfg in enabled_sources.items()
        }
        for future in future_to_sid:
            sid = future_to_sid[future]
            try:
                res = future.result(timeout=20)
                results.append(res)
            except Exception as e:
                results.append({
                    "source": sid,
                    "status": "error",
                    "tier": "",
                    "chars": 0,
                    "url": "",
                    "error": str(e),
                    "text": "",
                })

    health.record_fulltext_health(results)
    results.sort(key=lambda r: r.get("source", ""))
    return results
