import pika
import json
import base64

QUEUE_NAME = "queue1"   # Change if you have a custom queue

def decode_celery_message(body):
    """
    Celery messages have an envelope like:
    {
        "body": "base64-encoded-json",
        "headers": {...},
        "properties": {...}
    }
    This extracts and decodes the real JSON task body.
    """
    try:
        envelope = json.loads(body)

        # Extract the inner base64 encoded body
        raw_body_b64 = envelope.get("body")
        decoded_inner = base64.b64decode(raw_body_b64)

        # Now parse the actual Celery payload JSON
        task_data = json.loads(decoded_inner)

        return task_data

    except Exception as e:
        return {"error_decoding": str(e), "raw": body}


def main():
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host="localhost")
    )
    channel = connection.channel()

    print(f"Watching queue: {QUEUE_NAME}")
    print("-" * 60)

    while True:
        method, header, body = channel.basic_get(QUEUE_NAME, auto_ack=False)

        if not method:
            print("No more messages in queue.")
            break

        print("\n--- RAW MESSAGE RECEIVED ---")
        print("Delivery tag:", method.delivery_tag)

        decoded = decode_celery_message(body.decode())

        print("\n--- DECODED CELERY TASK ---")
        print(json.dumps(decoded, indent=4))

        # Requeue so Celery can still consume it
        channel.basic_nack(method.delivery_tag, requeue=True)

    connection.close()


if __name__ == "__main__":
    main()

