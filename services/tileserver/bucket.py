"""Read tile files from object storage (burndown 8.9): list a prefix, read byte ranges.

On CDP in AWS the bucket is behind Ranger RAZ: every S3 request is sent to RAZ
(Kerberos, as the workload user the Workbench Application runs as), RAZ checks
the Ranger S3 policy and returns the signature. Cloudera's ``raz_client``
(a boto3 plugin, in the PBJ Workbench runtimes the Horus runtimes are built
on) does this; the RAZ URL comes from the session's Hadoop core-site.xml. So
there are no AWS keys anywhere, and Ranger audits every read.

Without RAZ (Ozone, MinIO, plain S3) boto3 uses its normal credentials and
S3_ENDPOINT_URL, if set.

Probe, run in a Workbench session before 8.9 is built on it:

    python3 bucket.py s3a://<bucket>/data/horus/<instance>/tiles/

lists the prefix, runs the tile service's checks on every PMTiles file
through range reads, and times small range reads with and without a RAZ
delegation token. Read-only.
"""
from __future__ import annotations

import os
import ssl
import sys
import time
from typing import Callable, Optional
from urllib.parse import urlparse

CORE_SITE = "/etc/hadoop/conf/core-site.xml"
RAZ_URL_KEY = "fs.s3a.ext.raz.rest.host.url"
# Never call RAZ without checking its certificate (raz_client's default is not to).
CA_CANDIDATES = (os.environ.get("RAZ_CA_FILE"), os.environ.get("REQUESTS_CA_BUNDLE"),
                 ssl.get_default_verify_paths().cafile,
                 "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt")


def split_url(url: str) -> tuple[str, str]:
    """s3a://bucket/some/prefix/ -> ("bucket", "some/prefix/")."""
    u = urlparse(url)
    if u.scheme not in ("s3", "s3a") or not u.netloc:
        raise ValueError(f"{url!r} is not s3://bucket/prefix or s3a://bucket/prefix")
    prefix = u.path.lstrip("/")
    return u.netloc, prefix + ("/" if prefix and not prefix.endswith("/") else "")


def raz_url() -> Optional[str]:
    """The RAZ servers from core-site.xml, or None when the environment has no RAZ."""
    if not os.path.exists(CORE_SITE):
        return None
    import xml.etree.ElementTree as ET
    for prop in ET.parse(CORE_SITE).getroot().findall("property"):
        if prop.findtext("name") == RAZ_URL_KEY:
            return (prop.findtext("value") or "").strip() or None
    return None


def ca_file() -> str:
    for path in CA_CANDIDATES:
        if path and os.path.exists(path):
            return path
    raise FileNotFoundError("no CA bundle found for checking RAZ's certificate; set RAZ_CA_FILE")


class Bucket:
    def __init__(self, url: str, delegation_token: bool = True):
        import boto3
        from botocore.config import Config
        self.bucket, self.prefix = split_url(url)
        self.raz = raz_url()
        cfg = Config(retries={"max_attempts": 3, "mode": "standard"}, max_pool_connections=32)
        if self.raz:
            import raz_client
            # The RAZ signer rewrites every request to https://<bucket>.s3.amazonaws.com.
            self.client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"), config=cfg)
            conf = raz_client.Configuration()
            conf.load_xml_file(CORE_SITE)
            if delegation_token:   # one Kerberos exchange per 15 minutes instead of per request
                conf[raz_client.RAZ_CLIENT_USE_DELEGATION_TOKEN] = "true"
            raz_client.configure_ranger_raz(self.client, conf=conf, ssl_file=ca_file())
        else:
            self.client = boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None, config=cfg)

    def list(self) -> list[tuple[str, int]]:
        """(key, size) for every object directly under the prefix."""
        out, token = [], None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": self.prefix, "Delimiter": "/"}
            if token:
                kw["ContinuationToken"] = token
            r = self.client.list_objects_v2(**kw)
            # Skip folder markers ("<prefix>/", written by hdfs dfs -mkdir and the S3 console).
            out += [(o["Key"], o["Size"]) for o in r.get("Contents", []) if not o["Key"].endswith("/")]
            if not r.get("IsTruncated"):
                return out
            token = r["NextContinuationToken"]

    def get_range(self, key: str, start: int, end: int) -> tuple[bytes, int, str]:
        """Bytes start..end (inclusive; S3 shortens a range past the end), the object's
        size, and its ETag."""
        r = self.client.get_object(Bucket=self.bucket, Key=key, Range=f"bytes={start}-{end}")
        total = int(r.get("ContentRange", "/0").rsplit("/", 1)[-1] or 0) or r.get("ContentLength", 0)
        return r["Body"].read(), total, r.get("ETag", "")

    def read_range(self, key: str, offset: int, length: int) -> bytes:
        return self.get_range(key, offset, offset + length - 1)[0]

    def reader(self, key: str) -> Callable[[int, int], bytes]:
        return lambda offset, length: self.read_range(key, offset, length)


def _timed(fn, n: int) -> list[float]:
    times = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t) * 1000)
    return sorted(times)


def probe(url: str) -> int:
    import tilestore
    rz = raz_url()
    print(f"RAZ: {rz or 'none (plain S3 credentials)'}")
    if rz:
        print(f"CA bundle for RAZ: {ca_file()}")
    try:
        b = Bucket(url)
        objects = b.list()
    except Exception as e:   # the reason is what the probe is for
        print(f"FAIL listing {url}: {type(e).__name__}: {e}")
        print("  RazUnauthorizedException means Ranger denied the list: Ranger -> Audits -> Access shows the policy;"
              "\n  an SSL error means RAZ's certificate isn't in the CA bundle (set RAZ_CA_FILE)")
        return 1
    print(f"listed {len(objects)} object(s) under s3://{b.bucket}/{b.prefix}")
    bad = 0
    pmtiles = [(k, s) for k, s in objects if k.endswith(".pmtiles")]
    for key, size in pmtiles:
        t = time.perf_counter()
        try:
            meta, problems = tilestore.read_pmtiles(b.reader(key))
        except Exception as e:
            meta, problems = {}, [f"{type(e).__name__}: {e}"]
        ms = (time.perf_counter() - t) * 1000
        name = key.rsplit("/", 1)[-1]
        if problems:
            bad += 1
            print(f"FAIL {name}: {'; '.join(problems)}")
        else:
            print(f"ok   {name}: {size / 1e9:.2f} GB, {meta['format']}, z{meta['minzoom']}-{meta['maxzoom']}, "
                  f"bounds {meta['bounds']} ({ms:.0f} ms)")
    others = [k.rsplit("/", 1)[-1] for k, _ in objects if not k.endswith(".pmtiles")]
    if others:
        print(f"other objects: {', '.join(others)}")
    if pmtiles:
        key = pmtiles[0][0]
        for token in ((True, False) if rz else (True,)):
            label = ("delegation token" if token else "Kerberos per request") if rz else "plain"
            bb = b if token else Bucket(url, delegation_token=False)
            bb.read_range(key, 0, 16384)   # warm up: token, connections
            t = _timed(lambda: bb.read_range(key, 0, 16384), 20)
            print(f"16 KB range read, {label}: median {t[10]:.0f} ms, p90 {t[17]:.0f} ms, max {t[-1]:.0f} ms")
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(probe(sys.argv[1]))
