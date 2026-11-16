"""Create the Horus topic on the Streams Messaging Data Hub (idempotent)."""
from __future__ import annotations

from typing import List


def ensure_topic(brokers: List[str], user: str, password: str, ca_file: str, topic: str,
                 partitions: int = 3, replication: int = 3, log=print) -> bool:
    """Returns True if the topic was created, False if it already existed."""
    from confluent_kafka.admin import AdminClient, NewTopic  # lazy: only needed here

    admin = AdminClient({
        "bootstrap.servers": ",".join(brokers),
        "security.protocol": "SASL_SSL",
        "sasl.mechanism": "PLAIN",
        "sasl.username": user,
        "sasl.password": password,
        "ssl.ca.location": ca_file,
        "socket.timeout.ms": 30000,
    })
    md = admin.list_topics(timeout=30)
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
