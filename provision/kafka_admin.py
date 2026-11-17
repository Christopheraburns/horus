"""Create and inspect the Horus topic on the Streams Messaging Data Hub."""
from __future__ import annotations

import time
from typing import List, Optional


def _admin(brokers: List[str], user: str, password: str, ca_file: str, timeout_s: int = 30):
    """Connected AdminClient plus cluster metadata. Fails fast on bad credentials
    (librdkafka otherwise retries an auth failure until the timeout)."""
    from confluent_kafka import KafkaException
    from confluent_kafka.admin import AdminClient  # lazy: only needed here

    errors: List[str] = []
    admin = AdminClient({
        "bootstrap.servers": ",".join(brokers),
        "security.protocol": "SASL_SSL",
        "sasl.mechanism": "PLAIN",
        "sasl.username": user,
        "sasl.password": password,
        "ssl.ca.location": ca_file,
        "socket.timeout.ms": 30000,
        "error_cb": lambda err: errors.append(str(err)),
    })
    deadline = time.time() + timeout_s
    while True:
        try:
            return admin, admin.list_topics(timeout=5)
        except KafkaException as e:
            auth = next((m for m in errors if "Authentication" in m or "SASL" in m), None)
            if auth:
                raise RuntimeError(
                    f"kafka: login rejected for {user} ({auth.split(':')[-1].strip()}) -- "
                    "check HORUS_WORKLOAD_USER/PASSWORD, then sync users to the environment") from None
            if time.time() > deadline:
                raise RuntimeError(f"kafka: brokers unreachable after {timeout_s}s "
                                   f"({errors[-1] if errors else e})") from None


def topic_partitions(brokers: List[str], user: str, password: str, ca_file: str,
                     topic: str) -> Optional[int]:
    """Partition count, or None if the topic does not exist. Read-only."""
    _, md = _admin(brokers, user, password, ca_file)
    t = md.topics.get(topic)
    return len(t.partitions) if t is not None else None


def ensure_topic(brokers: List[str], user: str, password: str, ca_file: str, topic: str,
                 partitions: int = 3, replication: int = 3, log=print) -> bool:
    """Returns True if the topic was created, False if it already existed."""
    from confluent_kafka.admin import NewTopic

    admin, md = _admin(brokers, user, password, ca_file)
    if topic in md.topics:
        log(f"kafka: topic {topic} already exists")
        return False
    replication = min(replication, len(md.brokers))
    fut = admin.create_topics([NewTopic(topic, num_partitions=partitions, replication_factor=replication)])
    try:
        fut[topic].result(60)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "TOPIC_AUTHORIZATION_FAILED" in msg or "Authorization" in msg:
            raise RuntimeError(
                f"kafka: {user} may not create topics -- add a Ranger Kafka policy granting "
                f"Create/Publish/Consume/Describe on topic {topic} (service cm_kafka)") from e
        raise
    log(f"kafka: created topic {topic} ({partitions} partitions, RF {replication})")
    return True
