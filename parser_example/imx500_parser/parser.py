import paho.mqtt.client as mqtt
import json

# Define the MQTT broker details
BROKER = '127.0.0.1'
PORT = 1883
SUBSCRIBE_TOPIC = 'aitrios/me/inferences'
PUBLISH_TOPIC = 'output/topic'
LABELS = {}

file_path = 'labels.txt'

# Define the parsing function
def parse_payload(payload):
    global LABELS
    # Implement your parsing logic here
    parsed_data = json.loads(payload)  # Example: convert payload to uppercase
    data = parsed_data['Inferences'][0]['O']
    print(f"Payload: {data}")
    max_key = max(data, key=data.get)
    max_value = data[max_key]
    label = LABELS[int(max_key)]
    print(f"Label: {label}, Confidence: {max_value}, Key: {max_key}")
    return parsed_data

# Define the callback for when a message is received
def on_message(client, userdata, message):
    payload = message.payload.decode('utf-8')
    #print(f"Received message: {payload}")
    
    # Parse the payload
    parsed_data = parse_payload(payload)
    #print(f"Parsed data: {parsed_data}")
    
    # Publish the parsed data to another topic
    #client.publish(PUBLISH_TOPIC, parsed_data)
    #print(f"Published parsed data to {PUBLISH_TOPIC}")

# Define the callback for when the client connects to the broker
def on_connect(client, userdata, flags, rc):
    print(f"Connected with result code {rc}")
    client.subscribe(SUBSCRIBE_TOPIC)
    print(f"Subscribed to {SUBSCRIBE_TOPIC}")

def load_labels(file_path):
    result_dict = {}
    with open(file_path, 'r') as file:
        for row_number, row_content in enumerate(file, start=0):
            result_dict[row_number] = row_content.strip()
    return result_dict

def main():
    # Create an MQTT client instance
    client = mqtt.Client()
    global LABELS
    LABELS = load_labels(file_path)

    # Assign the callback functions
    client.on_connect = on_connect
    client.on_message = on_message

    # Connect to the MQTT broker
    client.connect(BROKER, PORT, 60)

    # Start the MQTT client loop
    client.loop_forever()