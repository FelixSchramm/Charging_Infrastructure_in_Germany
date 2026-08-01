"""Profile a data source before committing to a storage architecture.

Answers the questions that ADR 0001 currently guesses at:
  - how large is the response?
  - how many records does it contain?
  - which columns exist after flattening, and how wide are they?
  - how large is the resulting parquet, in full and reduced to a column subset?

Writes nothing outside the runner. Read-only by design.

Usage:
    uv run python scripts/measure_source.py --url https://example.org/api/endpoint
    uv run python scripts/measure_source.py --url ... --keep-columns id,lat,lon,power_kw
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd
import requests

CHUNK = 1 << 20  # 1 MiB


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:,.1f} TB"


def download(url: str, dest: Path, headers: dict[str, str]) -> tuple[int, float]:
    """Stream the response to disk. Returns (bytes, seconds)."""
    started = time.monotonic()
    size = 0
    with requests.get(url, headers=headers, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "unknown")
        with dest.open("wb") as fh:
            for chunk in resp.iter_content(CHUNK):
                fh.write(chunk)
                size += len(chunk)
    elapsed = time.monotonic() - started
    print(f"  content-type      : {content_type}")
    return size, elapsed


def find_records(payload: object, path: str = "$") -> tuple[list, str]:
    """Heuristic: the largest list of dicts in the payload is the record array."""
    best: tuple[list, str] = ([], path)
    if isinstance(payload, list):
        if payload and isinstance(payload[0], dict):
            best = (payload, path)
    elif isinstance(payload, dict):
        for key, value in payload.items():
            candidate, candidate_path = find_records(value, f"{path}.{key}")
            if len(candidate) > len(best[0]):
                best = (candidate, candidate_path)
    return best


def parquet_size(frame: pd.DataFrame, tmpdir: Path, name: str) -> int:
    target = tmpdir / f"{name}.parquet"
    frame.to_parquet(target, compression="zstd", index=False)
    return target.stat().st_size


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Source endpoint to profile")
    parser.add_argument(
        "--keep-columns",
        default="",
        help="Comma-separated subset to size the slim model layer",
    )
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        metavar="NAME:VALUE",
        help="Extra request header, repeatable",
    )
    parser.add_argument("--top", type=int, default=25, help="Widest columns to list")
    args = parser.parse_args()

    headers = {"Accept": "application/json", "User-Agent": "charging-infra-measure/1.0"}
    for raw in args.header:
        name, _, value = raw.partition(":")
        headers[name.strip()] = value.strip()

    lines: list[str] = []

    def emit(text: str = "") -> None:
        print(text)
        lines.append(text)

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        payload_file = tmpdir / "response.raw"

        print(f"Fetching {args.url}")
        size, elapsed = download(args.url, payload_file, headers)

        emit("## Source measurement")
        emit()
        emit(f"- URL: `{args.url}`")
        emit(f"- Response size: **{human(size)}** ({size:,} bytes)")
        emit(f"- Download time: {elapsed:,.1f} s ({human(size / max(elapsed, 0.001))}/s)")

        try:
            payload = json.loads(payload_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            emit(f"- Parsing: **failed** ({exc}). Not JSON, or truncated.")
            _write_summary(lines)
            return 1

        records, path = find_records(payload)
        if not records:
            emit("- Parsing: no record array found. Inspect the payload manually.")
            _write_summary(lines)
            return 1

        emit(f"- Record array: `{path}`")
        emit(f"- Records: **{len(records):,}**")

        frame = pd.json_normalize(records, sep="_")
        emit(f"- Columns after flattening: **{len(frame.columns)}**")
        emit()

        full = parquet_size(frame, tmpdir, "full")
        emit(f"- Parquet (all columns, zstd): **{human(full)}**")

        keep = [c.strip() for c in args.keep_columns.split(",") if c.strip()]
        if keep:
            missing = [c for c in keep if c not in frame.columns]
            present = [c for c in keep if c in frame.columns]
            if missing:
                emit(f"- Requested but missing: {', '.join(f'`{c}`' for c in missing)}")
            if present:
                slim = parquet_size(frame[present], tmpdir, "slim")
                share = slim / full * 100 if full else 0
                emit(
                    f"- Parquet (slim, {len(present)} columns): "
                    f"**{human(slim)}** ({share:.1f} % of full)"
                )
                emit()
                emit(f"  Projected for 365 daily snapshots: {human(slim * 365)}")

        emit()
        emit(f"### Widest columns (top {args.top})")
        emit()
        emit("| column | dtype | parquet bytes | non-null |")
        emit("| --- | --- | ---: | ---: |")

        sizes = []
        for column in frame.columns:
            try:
                sizes.append(
                    (
                        column,
                        str(frame[column].dtype),
                        parquet_size(frame[[column]], tmpdir, "col"),
                        int(frame[column].notna().sum()),
                    )
                )
            except Exception:  # noqa: BLE001 - unserialisable column, skip
                sizes.append((column, str(frame[column].dtype), -1, -1))

        for column, dtype, nbytes, nonnull in sorted(
            sizes, key=lambda row: row[2], reverse=True
        )[: args.top]:
            rendered = human(nbytes) if nbytes >= 0 else "n/a"
            emit(f"| `{column}` | {dtype} | {rendered} | {nonnull:,} |")

        emit()
        emit(
            "> Use these numbers to fill in `04_documents/data-model.md` "
            "and to close OQ-1."
        )

    _write_summary(lines)
    return 0


def _write_summary(lines: list[str]) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
