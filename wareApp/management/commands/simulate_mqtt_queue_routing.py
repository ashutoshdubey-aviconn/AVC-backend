import re
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from wareApp.mqtt.routing import QUEUE_ONE, QUEUE_TWO, queue_for_gateway_topic
from wareApp.mqtt.topics import TopicParseError


TOPIC_PATTERN = re.compile(r"(/Acclivate/iOmniControl/[^\s]+?/in/[^\s]+)")


class Command(BaseCommand):
    help = "Dry-run MQTT queue routing against topic records in Celery logs."

    def add_arguments(self, parser):
        parser.add_argument("logs", nargs="+", help="Celery log files to inspect.")
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Stop after this many topic records per log; 0 reads all records.",
        )

    def handle(self, *args, **options):
        for log_name in options["logs"]:
            self._simulate(Path(log_name), options["limit"])

    def _simulate(self, log_path: Path, limit: int) -> None:
        if not log_path.is_file():
            raise CommandError(f"Log file does not exist: {log_path}")

        outcomes = Counter()
        message_types = Counter()
        with log_path.open(encoding="utf-8", errors="replace") as log_file:
            for line in log_file:
                match = TOPIC_PATTERN.search(line)
                if not match:
                    continue

                topic = match.group(1)
                outcomes["records"] += 1
                try:
                    queue = queue_for_gateway_topic(topic)
                except TopicParseError:
                    outcomes["malformed"] += 1
                    continue

                message_type = topic.split("/")[6].split("_", 1)[0]
                message_types[message_type] += 1
                if queue is None:
                    outcomes["unassigned"] += 1
                else:
                    outcomes[queue] += 1

                if limit and outcomes["records"] >= limit:
                    break

        self.stdout.write(f"{log_path}: {outcomes['records']} MQTT topic records")
        self.stdout.write(
            f"  {QUEUE_ONE}: {outcomes[QUEUE_ONE]}, {QUEUE_TWO}: {outcomes[QUEUE_TWO]}, "
            f"unassigned: {outcomes['unassigned']}, malformed: {outcomes['malformed']}"
        )
        self.stdout.write(
            "  message types: "
            + ", ".join(
                f"{message_type}={count}"
                for message_type, count in sorted(message_types.items())
            )
        )