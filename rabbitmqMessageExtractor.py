import pika
import json

connection = pika.BlockingConnection(
    pika.ConnectionParameters('localhost')
)
channel = connection.channel()

method_frame, header_frame, body = channel.basic_get('queue1', auto_ack=False)

if method_frame:
    print("Message:", body.decode())
    channel.basic_nack(method_frame.delivery_tag, requeue=True)
else:
    print("Queue is empty")

connection.close()

