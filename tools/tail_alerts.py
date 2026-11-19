"""Read-only: print recent alerts from horus-<instance>-alerts (burndown 4.1).

Run in a Workbench session (the brokers are private):

    python tools/tail_alerts.py            # last 20 alerts, then a count by type
    python tools/tail_alerts.py --follow   # keep printing new alerts

Uses a throwaway consumer group and commits nothing, so it never moves another
consumer's offsets. No secrets are printed.
"""
import argparse
import collections
import json
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "provision"))
os.chdir(ROOT)
import config as cfgmod  # noqa: E402
import horus  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--last", type=int, default=20, help="alerts to show from the end of the topic")
    ap.add_argument("--follow", action="store_true")
    args = ap.parse_args()

    from confluent_kafka import Consumer, TopicPartition

    cfg = cfgmod.load()
    rep = horus.status(cfg)
    brokers = rep.gateway_env.get("KAFKA_BROKERS", "")
    if not brokers:
        print("Kafka brokers not found; is the Kafka Data Hub AVAILABLE?")
        return 1
    ca = horus._ca_bundle(rep.env_name)
    c = Consumer({
        "bootstrap.servers": brokers,
        "security.protocol": "SASL_SSL",
        "sasl.mechanism": "PLAIN",
        "sasl.username": cfg.workload_user,
        "sasl.password": cfg.workload_password,
        "ssl.ca.location": ca,
        "group.id": f"horus-tail-{uuid.uuid4().hex[:8]}",
        "enable.auto.commit": False,
    })
    topic = cfg.alerts_topic
    md = c.list_topics(topic, timeout=30).topics.get(topic)
    if md is None or md.error is not None:
        print(f"{topic} not found; run provision/horus.py create --yes")
        return 1
    parts, total = [], 0
    for p in md.partitions:
        lo, hi = c.get_watermark_offsets(TopicPartition(topic, p), timeout=30)
        total += hi - lo
        parts.append(TopicPartition(topic, p, max(lo, hi - args.last)))
    print(f"{topic}: {total} alerts retained")
    c.assign(parts)

    rows, by_type, idle = [], collections.Counter(), 0
    while True:
        m = c.poll(2.0)
        if m is None:
            idle += 1
            if not args.follow and idle >= 3:
                break
            continue
        idle = 0
        if m.error():
            print("error:", m.error())
            continue
        a = json.loads(m.value())
        by_type[a.get("alert_type")] += 1
        line = (f"{a.get('detected_at')}  {a.get('severity', ''):<6} {a.get('alert_type', ''):<16} "
                f"{a.get('asset_type', '')} {a.get('asset_name')} ({a.get('asset_id')})  {a.get('summary')}")
        if args.follow:
            print(line, flush=True)
        else:
            rows.append((a.get("detected_at") or "", line))
    for _, line in sorted(rows)[-args.last:]:
        print(line)
    if by_type:
        print("\nshown, by type:", dict(by_type))
    c.close()
    os.unlink(ca)
    return 0


if __name__ == "__main__":
    sys.exit(main())
