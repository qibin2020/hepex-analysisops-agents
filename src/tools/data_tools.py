"""
Data download tools for ATLAS Open Data.
Ported from hepex-analysisops-benchmark/src/utils/atlas_download.py

These tools allow the purple agent to download ATLAS Open Data files
when needed, without relying on shared filesystem with the benchmark.
"""

from __future__ import annotations

import logging
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

try:
    import atlasopenmagic as atom
    HAS_ATOM = True
except ImportError:
    HAS_ATOM = False


logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    url: str
    local_path: str
    ok: bool
    skipped: bool
    expected_size: Optional[int]
    local_size: int
    error: Optional[str] = None


# -----------------------------
# Low-level HTTP helpers (urllib)
# -----------------------------
def _head_content_length(url: str, timeout: int = 30) -> Optional[int]:
    """
    Return Content-Length from HEAD if available, else None.
    """
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        cl = resp.headers.get("Content-Length")
        if cl is None:
            return None
        try:
            return int(cl)
        except ValueError:
            return None


def _download_to_file(url: str, dst_path: str, timeout: int = 120, chunk_size: int = 1024 * 1024) -> int:
    """
    Download url to dst_path (overwrite). Returns bytes written.
    Uses streaming read to avoid urlretrieve pitfalls.
    """
    req = urllib.request.Request(url, method="GET")
    written = 0
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        with open(dst_path, "wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                written += len(chunk)
    return written


def _ensure_one_file(
    url: str,
    output_dir: str,
    timeout_head: int = 30,
    timeout_get: int = 120,
    max_retries: int = 2,
    verbose: bool = False,
) -> DownloadResult:
    """
    Ensure a single file is present and complete (by Content-Length if available).
    """
    filename = os.path.basename(url)
    local_path = os.path.join(output_dir, filename)
    part_path = local_path + ".part"

    # Local size (if any)
    local_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0

    # Expected size from HEAD (best effort)
    expected_size: Optional[int] = None
    try:
        expected_size = _head_content_length(url, timeout=timeout_head)
    except Exception:
        expected_size = None  # server may not support HEAD / transient issues

    # If we can validate size and it matches -> skip
    if expected_size is not None and os.path.exists(local_path) and local_size == expected_size:
        return DownloadResult(
            url=url,
            local_path=local_path,
            ok=True,
            skipped=True,
            expected_size=expected_size,
            local_size=local_size,
        )

    # Download with retries
    last_err: Optional[str] = None
    for attempt in range(max_retries + 1):
        try:
            # clean stale part
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except OSError:
                    pass

            if verbose:
                msg = f"[download] {filename}"
                if expected_size is not None:
                    msg += f" (expected {expected_size} bytes)"
                if os.path.exists(local_path):
                    msg += f" [local {local_size} bytes -> redownload]"
                print(msg)

            written = _download_to_file(url, part_path, timeout=timeout_get)

            # Verify if we know expected_size
            if expected_size is not None and written != expected_size:
                raise RuntimeError(f"size mismatch: wrote {written}, expected {expected_size}")

            # Atomic move into place
            os.replace(part_path, local_path)

            final_size = os.path.getsize(local_path)
            return DownloadResult(
                url=url,
                local_path=local_path,
                ok=True,
                skipped=False,
                expected_size=expected_size,
                local_size=final_size,
            )

        except Exception as e:
            last_err = str(e)
            # backoff
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
            continue

    # Failed
    final_size = os.path.getsize(local_path) if os.path.exists(local_path) else 0
    return DownloadResult(
        url=url,
        local_path=local_path,
        ok=False,
        skipped=False,
        expected_size=expected_size,
        local_size=final_size,
        error=last_err,
    )


# -----------------------------
# Tool: download ATLAS Open Data files
# -----------------------------
def download_atlas_data_tool(
    skim: str = "2muons",
    release: str = "2025e-13tev-beta",
    dataset: str = "data",
    protocol: str = "https",
    output_dir: str = "",  # Will use HEPEX_DATA_DIR if empty
    max_files: int = 1,
    workers: int = 4,
) -> Dict[str, Any]:
    """
    Tool: Download ATLAS Open Data files to local storage.

    This tool downloads ROOT files from ATLAS Open Data using the atlasopenmagic library.
    Files are cached locally and reused if already present and complete.

    Parameters
    ----------
    skim : str
        The skim/channel to download (e.g., "2muons", "2lep", "4lep").
    release : str
        The ATLAS Open Data release (e.g., "2025e-13tev-beta").
    dataset : str
        Dataset type (e.g., "data", "mc").
    protocol : str
        Transfer protocol ("https" or "root").
    output_dir : str
        Local directory to store downloaded files.
    max_files : int
        Maximum number of files to download (0 = all).
    workers : int
        Number of parallel download workers.

    Returns
    -------
    dict:
        {
            "status": "ok" | "error",
            "local_paths": [str, ...],  # paths to downloaded files
            "n_ok": int,
            "n_fail": int,
            "n_requested": int,
            "output_dir": str,
            "release": str,
            "dataset": str,
            "skim": str,
            "notes": str
        }
    """
    if not HAS_ATOM:
        logger.error("atlasopenmagic library is not installed. Cannot download ATLAS data.")
        return {
            "status": "error",
            "local_paths": [],
            "n_ok": 0,
            "n_fail": 0,
            "n_requested": 0,
            "notes": "atlasopenmagic library is not installed. Cannot download ATLAS data.",
        }

    try:
        # Resolve base_dir: use param if set, else HEPEX_DATA_DIR, else fallback
        base_dir = output_dir if output_dir and output_dir.strip() else os.environ.get("HEPEX_DATA_DIR", "/tmp/atlas_data")
        
        # Build full path: base_dir/release/dataset/skim (matches Green Agent structure)
        full_output_dir = os.path.join(base_dir, release, dataset, skim)

        logger.info(
            "Starting ATLAS data download: release=%s dataset=%s skim=%s output_dir=%s max_files=%s workers=%s",
            release,
            dataset,
            skim,
            os.path.abspath(full_output_dir),
            max_files,
            workers,
        )
        
        atom.set_release(release)
        os.makedirs(full_output_dir, exist_ok=True)

        # Get URL list
        files_list = atom.get_urls(dataset, skim, protocol=protocol, cache=False)
        
        urls = []
        for entry in sorted(files_list):
            # atlasopenmagic returns "root::https://.../file.root"
            if "::" in entry:
                urls.append(entry.split("::", 1)[1])
            else:
                urls.append(entry)

        if max_files and max_files > 0:
            urls = urls[:max_files]

        logger.info("Resolved %s remote ROOT file(s) for download.", len(urls))

        if not urls:
            logger.warning(
                "No files found for release=%s dataset=%s skim=%s.",
                release,
                dataset,
                skim,
            )
            return {
                "status": "error",
                "local_paths": [],
                "n_ok": 0,
                "n_fail": 0,
                "n_requested": 0,
                "output_dir": os.path.abspath(full_output_dir),
                "release": release,
                "dataset": dataset,
                "skim": skim,
                "notes": f"No files found for skim={skim}, dataset={dataset}, release={release}",
            }

        results: List[DownloadResult] = []
        ok_paths: List[str] = []

        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            futs = [ex.submit(_ensure_one_file, url, full_output_dir, verbose=False) for url in urls]
            for fut in as_completed(futs):
                r = fut.result()
                results.append(r)
                if r.ok:
                    ok_paths.append(r.local_path)

        # Keep stable order: same as urls
        url_to_path = {r.url: r.local_path for r in results if r.ok}
        local_paths_ordered = [url_to_path[u] for u in urls if u in url_to_path]

        n_ok = sum(1 for r in results if r.ok)
        n_fail = sum(1 for r in results if not r.ok)

        failed_details = [{"url": r.url, "error": r.error} for r in results if not r.ok]

        logger.info(
            "Finished ATLAS data download: ok=%s fail=%s requested=%s output_dir=%s",
            n_ok,
            n_fail,
            len(urls),
            os.path.abspath(full_output_dir),
        )
        if failed_details:
            for failed in failed_details:
                logger.warning("Download failed: url=%s error=%s", failed["url"], failed["error"])

        return {
            "status": "ok" if n_fail == 0 else "partial",
            "local_paths": local_paths_ordered,
            "n_ok": n_ok,
            "n_fail": n_fail,
            "n_requested": len(urls),
            "output_dir": os.path.abspath(full_output_dir),
            "release": release,
            "dataset": dataset,
            "skim": skim,
            "notes": f"Downloaded {n_ok}/{len(urls)} files successfully.",
            "failed": failed_details if failed_details else None,
        }

    except Exception as e:
        logger.exception("ATLAS data download failed.")
        return {
            "status": "error",
            "local_paths": [],
            "n_ok": 0,
            "n_fail": 0,
            "n_requested": 0,
            "output_dir": os.path.abspath(output_dir) if output_dir else None,
            "notes": f"Download failed: {type(e).__name__}: {e}",
        }


def list_local_root_files_tool(
    directory: str,
    pattern: str = "*.root",
) -> Dict[str, Any]:
    """
    Tool: List ROOT files in a local directory.

    Parameters
    ----------
    directory : str
        Directory to search for ROOT files.
    pattern : str
        Glob pattern to match files (default: "*.root").

    Returns
    -------
    dict:
        {
            "status": "ok" | "error",
            "files": [str, ...],
            "n_files": int,
            "directory": str,
            "notes": str
        }
    """
    import glob

    try:
        if not os.path.isdir(directory):
            return {
                "status": "error",
                "files": [],
                "n_files": 0,
                "directory": directory,
                "notes": f"Directory does not exist: {directory}",
            }

        search_pattern = os.path.join(directory, pattern)
        files = sorted(glob.glob(search_pattern))

        return {
            "status": "ok",
            "files": files,
            "n_files": len(files),
            "directory": os.path.abspath(directory),
            "notes": f"Found {len(files)} files matching '{pattern}'.",
        }

    except Exception as e:
        return {
            "status": "error",
            "files": [],
            "n_files": 0,
            "directory": directory,
            "notes": f"Error listing files: {type(e).__name__}: {e}",
        }


def test_download_atlas_data_tool():
    # construct json 
    kwargs = {
        "skim": "2muons",
        "release": "2025e-13tev-beta",
        "dataset": "data",
        "protocol": "https", # Must be https for urllib download
        "output_dir": "/tmp/atlas_data",
        "max_files": 1,
        "workers": 4,
    }

    print(f"Testing download_atlas_data_tool with: {kwargs}")
    result = download_atlas_data_tool(**kwargs)
    print("Result:", result)

if __name__ == "__main__":
    test_download_atlas_data_tool()
