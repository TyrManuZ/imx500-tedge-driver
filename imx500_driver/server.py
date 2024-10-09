import base64
import random
import logging
import json
import re
import time
import queue
import threading
import requests
import datetime
import os
import glob
import hashlib

import paho.mqtt.client as mqtt
from flask import Flask, request

app = Flask(__name__)
# TODO: This is hardcoded for now and needs to be changed to the actual Cumulocity URL from tedge config
C8Y_BASE = 'https://devices.jp.cumulocity.com'
TMP_DIR = '/tmp/imx'
HTTP_SERVER_PORT = 50123
image_cache = queue.Queue(maxsize=10)
inferences_cache = queue.Queue(maxsize=10)

# create tmp folder if not existing

if not os.path.exists(TMP_DIR):
    os.makedirs(TMP_DIR)
files = glob.glob(TMP_DIR + '/*')
for f in files:
    os.remove(f)

@app.route('/images/<filename>', methods=['PUT'])
def handle_images(filename):
    file_id = filename.split('.')[0]
    logging.debug(request)
    image_cache.put((file_id,request.data))
    #logging.debug(file_content)
    #logging.debug(f"Received image {filename} with content {body.decode()}")
    return ('', 200)

@app.route('/inferences/<filename>', methods=['PUT'])
def handle_inferences(filename):
    file_id = filename.split('.')[0]
    logging.debug(request)
    file_content = json.loads(request.data.decode())
    inferences_cache.put((file_id, file_content))
    #logging.debug(file_content)
    #logging.debug(f"Received image {filename} with content {body.decode()}")
    return ('', 200)

@app.route('/file/<filename>', methods=['GET'])
def handle_file_request(filename):
    logging.debug(f"Received request for file: {filename}")
    if os.path.exists(TMP_DIR + '/' + filename):
        with open(TMP_DIR + '/' + filename, 'rb') as fd:
            return (fd.read(), 200)
    else:
        return ('', 404)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),  # Log to stdout
        logging.FileHandler('server.log')  # Log to file
    ]
)

class CumulocityAuthentication():
    def __init__(self):
        self.token = None
        self.source_map = {}

class IMXMqttHandler(mqtt.Client):
    START_COMMAND = r'start (\d+)'
    STOP_COMMAND = r'stop'
    TOPIC_CONNECT = r'v1/devices/([\w]+)/connect'
    TOPIC_TELEMETRY = r'v1/devices/([\w]+)/telemetry'
    TOPIC_ATTR = r'v1/devices/([\w]+)/attributes'
    TOPIC_ATTR_REQUEST = r'v1/devices/([\w]+)/attributes/request/(\d+)'

    def __init__(self, token_auth: CumulocityAuthentication):
        super().__init__()
        self.token_auth = token_auth
        self.child_devices = set()
        self.download_location_model = {}
        self.download_location_app = {}
        self.device_id_long_map = {}
        self.pending_installations = {}
        self.existing_installations = {}
        #TODO: read from thin-edge config
        self.device_id_prefix = 'home64-raspberry:device'
        #self.device_id_prefix = 'revpi-office:device'
        self.on_message = self.on_message_handle
        self.on_connect = self.on_connect_handle
        self.connect('127.0.0.1', 1883)

    def handle_auth(self, msg):
        self.token_auth = msg.payload.decode().split(',')[-1]

    def handle_attr_request(self, client, userdata, msg):
        regex_match = re.fullmatch(IMXMqttHandler.TOPIC_ATTR_REQUEST, msg.topic)
        device_id = regex_match.group(1)
        req_id = int(regex_match.group(2))
        if msg.payload == b'{}':
            self.publish(f'v1/devices/{device_id}/attributes/response/{req_id}', json.dumps({}))
        else:
            logging.warning(f"Received message on unknown topic {msg.topic}: {msg.payload}")
    
    def handle_c8y_commands(self, client, userdata, msg):
        logging.debug(f"Received message on topic {msg.topic}: {msg.payload}")
        msg_parts = msg.payload.decode().split(',')
        device_id_long = msg_parts[1]
        device_id = msg_parts[1].split(':')[-1]
        self.device_id_long_map[device_id] = device_id_long
        if msg_parts[0] == '511' and device_id in self.child_devices:
            command = msg_parts[2]
            regex_match_start = re.fullmatch(IMXMqttHandler.START_COMMAND, command)
            regex_match_stop = re.fullmatch(IMXMqttHandler.STOP_COMMAND, command)
            if regex_match_start != None:
                interval = int(regex_match_start.group(1))
                logging.info(f"Received start command for device {device_id} with interval {interval}")
                # Set operation to EXECUTING
                self.device_id_prefix = ":".join(msg_parts[1].split(':')[:-1])
                self.publish(f'c8y/s/us/{device_id_long}', '501,c8y_Command')
                self.start_sending_data(device_id, interval)
            elif regex_match_stop != None:
                logging.info(f"Received stop command for device {device_id}")
                # Set operation to EXECUTING
                self.publish(f'c8y/s/us/{device_id_long}', '501,c8y_Command')
                self.stop_sending_data(device_id)
                self.device_id_prefix = ":".join(msg_parts[1].split(':')[:-1])
            else:
                logging.warning(f"Received unknown command {command} for device {device_id}")
                self.publish(f'c8y/s/us/{device_id_long}', '501,c8y_Command')
                time.sleep(2)
                self.publish(f'c8y/s/us/{device_id_long}', '502,c8y_Command,Unsupported command')
        elif msg_parts[0] == '529' and device_id in self.child_devices:
            logging.debug(f"Received software update operation status update for device {device_id}")
            msg_parts = msg_parts[2:]
            logging.debug(msg_parts)
            # split into groups of 4
            install = []
            for i in range(0, len(msg_parts), 5):
                action = msg_parts[i+4]
                if action == 'install' or action == 'update':
                    install.append((msg_parts[i+2], msg_parts[i+3]))
                    self.pending_installations[msg_parts[2]] = msg_parts[:-1]
            self.publish(f'c8y/s/us/{device_id_long}', '501,c8y_SoftwareUpdate')
            if len(install) != 1:
                self.publish(f'c8y/s/us/{device_id_long}', '502,c8y_SoftwareUpdate,Only exactly one piece of software can be installed or updated at a time')
                return
            if install[0][0] == 'imx500-model':
                self.download_model(device_id, install[0][0], install[0][1])
            elif install[0][0] == 'imx500-app':
                self.download_app(device_id, install[0][0], install[0][1])
            else:
                self.publish(f'c8y/s/us/{device_id_long}', '502,c8y_SoftwareUpdate,Unsupported software type')

    def download_model(self, device_id, software_type, software_url):
        # download software
        software = response = requests.get(software_url, headers={'Authorization': 'Bearer ' + token_auth.token}, stream=True)
        with open(TMP_DIR + '/' + software_type, 'wb') as fd:
            for chunk in response.iter_content(chunk_size=1024):
                fd.write(chunk)
        logging.info(f"Downloaded software {software_type} from {software_url}")
        self.install_model_procedure(device_id, software_type)
        
    def install_model_procedure(self, device_id, model_path):
        self.download_location_model[device_id] = model_path
        self.delete_model(device_id)    
        
    def delete_model(self, device_id):
        # TODO: Is that always this value?
        network_id = "000000"       
        # delete existing model
        model_deletion = {
            "OTA": {
                "UpdateModule": "DnnModel",
                "DeleteNetworkID": network_id
            }
        }
        model_deletion_encoded = base64.encodebytes(bytes(json.dumps(model_deletion, indent=None, separators=(',', ':')), 'utf-8')).decode('utf-8')
        model_deletion_message = json.dumps({"configuration/backdoor-EA_Main/placeholder": model_deletion_encoded.rstrip()})
        logging.info(f"Delete existing model for device {device_id}")
        self.message_callback_add(f'v1/devices/{device_id}/attributes', self.pre_install_model)
        self.publish(f'v1/devices/{device_id}/attributes', model_deletion_message)
        # TODO: it seems sometimes we need to immediately install the new model, sometimes we need to wait for the camera response first

    # this method catches the message that we send ourselves (as everything is on the same topic)
    def pre_install_model(self, client, userdata, message):
        regex_match = re.fullmatch(IMXMqttHandler.TOPIC_ATTR, message.topic)
        device_id = regex_match.group(1)
        self.message_callback_remove(f'v1/devices/{device_id}/attributes')
        self.message_callback_add(f'v1/devices/{device_id}/attributes', self.install_model)

    def install_model(self, client, userdata, message):
        regex_match = re.fullmatch(IMXMqttHandler.TOPIC_ATTR, message.topic)
        device_id = regex_match.group(1)
        #TODO: Where is this coming from?
        desired_version = "0311030000000100"
        # install new model
        model_install = {
            "OTA": {
                "UpdateModule": "DnnModel",
                "DesiredVersion": desired_version,
                "PackageUri": "http://192.168.2.138:50123/file/" + self.download_location_model[device_id],
                "HashValue": self.create_hash_for_file(TMP_DIR + '/' + self.download_location_model[device_id])
            }
        }
        model_install_encoded = base64.encodebytes(bytes(json.dumps(model_install, indent=None, separators=(',', ':')), 'utf-8')).decode('utf-8')
        model_install_message = json.dumps({"configuration/backdoor-EA_Main/placeholder": model_install_encoded.rstrip()})
        logging.info(f"Install new model for device {device_id}")
        self.message_callback_remove(f'v1/devices/{device_id}/attributes')
        self.message_callback_add(f'v1/devices/{device_id}/attributes', self.pre_finish_model_installation)
        self.publish(f'v1/devices/{device_id}/attributes', model_install_message)
        del self.download_location_model[device_id]

    # this method catches the message that we send ourselves (as everything is on the same topic)
    def pre_finish_model_installation(self, client, userdata, message):
        regex_match = re.fullmatch(IMXMqttHandler.TOPIC_ATTR, message.topic)
        device_id = regex_match.group(1)
        json_message = json.loads(message.payload.decode())
        if 'state/backdoor-EA_Main/placeholder' in json_message.keys():
            decoded_message = json.loads(base64.b64decode(json_message['state/backdoor-EA_Main/placeholder']).decode('utf-8'))
            if 'OTA' in decoded_message.keys():
                ota = decoded_message['OTA']
                if 'UpdateStatus' in ota.keys():
                    logging.debug(f"Model installation status for device {device_id} is {ota['UpdateStatus']}")
                    if ota['UpdateStatus'] == 'Updating':
                        self.message_callback_remove(f'v1/devices/{device_id}/attributes')
                        self.message_callback_add(f'v1/devices/{device_id}/attributes', self.finish_model_installation)

    def finish_model_installation(self, client, userdata, message):
        regex_match = re.fullmatch(IMXMqttHandler.TOPIC_ATTR, message.topic)
        device_id = regex_match.group(1)
        #logging.debug(f"Received message on topic {message.topic}: {message.payload}")
        # wait until we receive a message that says 'Failed' or 'Done'
        json_message = json.loads(message.payload.decode())
        if 'state/backdoor-EA_Main/placeholder' in json_message.keys():
            decoded_message = json.loads(base64.b64decode(json_message['state/backdoor-EA_Main/placeholder']).decode('utf-8'))
            if 'OTA' in decoded_message.keys():
                ota = decoded_message['OTA']
                if 'UpdateStatus' in ota.keys():
                    logging.debug(f"Model installation status for device {device_id} is {ota['UpdateStatus']}")
                    if ota['UpdateStatus'] == 'Failed':
                        logging.info(f"Model installation failed for device {device_id}")
                        self.publish(f'c8y/s/us/{self.device_id_long_map[device_id]}', '502,c8y_SoftwareUpdate,Model installation failed')
                        self.message_callback_remove(f'v1/devices/{device_id}/attributes')
                    elif ota['UpdateStatus'] == 'Done':
                        logging.info(f"Model installation successful for device {device_id}")
                        self.publish(f'c8y/s/us/{self.device_id_long_map[device_id]}', '503,c8y_SoftwareUpdate')
                        self.message_callback_remove(f'v1/devices/{device_id}/attributes')
                        logging.debug(self.pending_installations)
                        if len(self.pending_installations.keys()) == 1:
                            key, value = self.pending_installations.popitem()
                            self.existing_installations[key] = value
                            self.send_installed_software_list(device_id)

    def send_installed_software_list(self, device_id):
        logging.info(f"Sending installed software list for device {device_id}")
        logging.debug(self.existing_installations)
        software_list = []
        for key, value in self.existing_installations.items():
            software_list.append(value[0])
            software_list.append(value[1])
            software_list.append("")
        self.publish(f'c8y/s/us/{self.device_id_long_map[device_id]}', '116,' + ','.join(software_list))

    def download_app(self, device_id, software_type, software_url):
        # download software
        software = response = requests.get(software_url, headers={'Authorization': 'Bearer ' + token_auth.token}, stream=True)
        with open(TMP_DIR + '/' + software_type, 'wb') as fd:
            for chunk in response.iter_content(chunk_size=1024):
                fd.write(chunk)
        logging.info(f"Downloaded software {software_type} from {software_url}")
        self.download_location_app[device_id] = software_type
        self.install_app(device_id)
        

    def install_app(self, device_id):
        #TODO: Where are these coming from?
        deployment_id = "3b9917c3ae2bbdc9805c4fad1cb5ca95d4cf6f2d7c791706eaac8dcf21fd7607"
        module_id = "node-0b26a"
        # install new model
        app_install = {
            "deploymentId": deployment_id,
            "instanceSpecs": {
                "node": {
                    "moduleId": module_id, 
                    "subscribe": {}, 
                    "publish": {}, 
                    "version": 1, 
                    "entryPoint": "main"
                }
            }, 
            "modules": {
                module_id: {
                    "entryPoint": "main", 
                    "moduleImpl": "wasm", 
                    "downloadUrl": "http://192.168.2.138:50123/file/" + self.download_location_app[device_id],
                    "hash": "0b26aedff2d972cdd3902f0db402af05572bd5e48e660347991f91dc0cc02151"
                    #"hash": self.create_hash_for_file(TMP_DIR + '/' + self.download_location_app[device_id])
                }
            }, 
            "publishTopics": {}, 
            "subscribeTopics": {}
        }
        app_install_encoded = json.dumps(app_install, indent=None, separators=(',', ':'))
        app_install_message = json.dumps({"deployment": app_install_encoded})
        logging.info(f"Install new model for device {device_id}")
        self.message_callback_add(f'v1/devices/{device_id}/attributes', self.finish_app_installation)
        self.publish(f'v1/devices/{device_id}/attributes', app_install_message)
        del self.download_location_app[device_id]

    def finish_app_installation(self, client, userdata, message):
        regex_match = re.fullmatch(IMXMqttHandler.TOPIC_ATTR, message.topic)
        device_id = regex_match.group(1)
        #logging.debug(f"Received message on topic {message.topic}: {message.payload}")
        # wait until we receive a message that says 'Failed' or 'Done'
        json_message = json.loads(message.payload.decode())
        if 'deploymentStatus' in json_message.keys():
            decoded_message = json.loads(json_message['deploymentStatus'])
            if 'modules' in decoded_message.keys():
                modules = decoded_message['modules']
                if not modules:
                    return
                else:
                    logging.debug(f"App installation status for device {device_id} is {str(modules)}")
                    # TODO: still hardocded
                    if 'node-0b26a' in modules.keys():
                        if modules['node-0b26a']['status'] == 'ok':
                            logging.info(f"Model installation successful for device {device_id}")
                            self.publish(f'c8y/s/us/{self.device_id_long_map[device_id]}', '503,c8y_SoftwareUpdate')
                            self.message_callback_remove(f'v1/devices/{device_id}/attributes')
                            self.set_app_configuration(device_id)

    def set_app_configuration(self, device_id):
        # TODO: should be read from a file
        configuration = {"header": {"id": "00", "version": "01.01.00"}, "dnn_output_classes": 1001, "max_predictions": 1001}
        message = {
            "configuration/node/PPL_Parameters": base64.encodebytes(json.dumps(configuration).encode()).decode()
        }
        self.publish(f'v1/devices/{device_id}/attributes', json.dumps(message))

    def create_hash_for_file(self, file_path):
        BUF_SIZE = 65536
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while True:
                data = f.read(BUF_SIZE)
                if not data:
                    break
                sha256.update(data)
        return base64.encodebytes(sha256.digest()).decode('utf-8')

    def handle_attr(self, client, userdata, msg):
        regex_match = re.fullmatch(IMXMqttHandler.TOPIC_ATTR, msg.topic)
        device_id = regex_match.group(1)
        try:
            body = json.loads(msg.payload.decode())
            for key, value in body.items():
                if key == 'state/backdoor-EA_Main/placeholder':
                    value = base64.b64decode(value)
                elif key == 'deploymentStatus':
                    pass
                else:
                    value = json.dumps(value)
                key = key.replace('/', '_')
                self.publish(f'te/device/{device_id}///twin/{key}', value)
        except json.JSONDecodeError:
            logging.warning(f"Couldn't decode message {msg.topic}: {msg.payload}")

    def handle_telemetry(self, client, userdata, msg):
        regex_match = re.fullmatch(IMXMqttHandler.TOPIC_TELEMETRY, msg.topic)
        device_id = regex_match.group(1)
        payload = json.loads(msg.payload.decode())
        #{"ts":1719910486058,"values":{"backdoor-EA_Main/EventLog":{"DeviceID":"Aid-80050001-0000-2000-9002-0000000002cf","Level":"Error","Time":"20240702085445","Component":10,"ErrorCode":2,"Description":""}}}'
        if 'backdoor-EA_Main/EventLog' in payload['values'].keys():
            timestamp = datetime.datetime.fromtimestamp(payload['ts']/1000.0).isoformat()[:-3] + 'Z'
            event_log = payload['values']['backdoor-EA_Main/EventLog']
            event_log['time'] = timestamp
            event_log['text'] = f'{event_log["Level"]} event in component "{event_log["Component"]}" with code "{event_log["ErrorCode"]}"'
            if event_log['Level'] == 'Warn':
                event_log['severity'] = 'warning'
            elif event_log['Level'] == 'Error':
                event_log['severity'] = 'major'
            else:
                event_log['severity'] = 'minor'
            alarm_type = f'imx_alarm_{event_log["Component"]}_{event_log["ErrorCode"]}'
            self.publish(f'te/device/{device_id}///a/{alarm_type}', json.dumps(event_log))
        else:
            logging.warning(f"Received message on unknown topic {msg.topic}: {msg.payload}")

    def handle_device_initialization_response(self, client, userdata, msg):
        logging.info(f"Received response for {msg.topic.split('/')[-1]}: {msg.payload}")
        client.unsubscribe(msg.topic)
        if self.device_id_prefix:
            device_id = msg.topic.split('/')[2]
            self.publish(f'c8y/s/us/{self.device_id_prefix}:{device_id}', '503,c8y_Command')

    def handle_start_inference_response(self, client, userdata, msg):
        logging.info(f"Received response for {msg.topic.split('/')[-1]}: {msg.payload}")
        client.unsubscribe(msg.topic)
        if self.device_id_prefix:
            device_id = msg.topic.split('/')[2]
            self.publish(f'c8y/s/us/{self.device_id_prefix}:{device_id}', '503,c8y_Command')

    def start_sending_data(self, device_id, interval):
        # 50123
        body = {
            "method": "ModuleMethodCall", 
            "params": {
                "moduleMethod": "StartUploadInferenceData", 
                "moduleInstance": "backdoor-EA_Main", 
                "params": {
                    "Mode": 1, 
                    "UploadMethod": "HttpStorage", 
                    "StorageName": "http://192.168.2.138:50123", 
                    "StorageSubDirectoryPath": "images", 
                    "UploadMethodIR": "HttpStorage", 
                    "StorageNameIR": "http://192.168.2.138:50123", 
                    "UploadInterval": int(interval), 
                    "StorageSubDirectoryPathIR": "inferences", 
                    "CropHOffset": 0, 
                    "CropVOffset": 0, 
                    "CropHSize": 4056, 
                    "CropVSize": 3040
                }
            }
        }
        request_id = random.randint(0, 1000000)
        self.message_callback_add(f'v1/devices/{device_id}/rpc/response/{request_id}', self.handle_start_inference_response)
        self.subscribe(f'v1/devices/{device_id}/rpc/response/{request_id}')
        self.publish(f'v1/devices/{device_id}/rpc/request/{request_id}', json.dumps(body))
    
    def stop_sending_data(self, device_id):
        body = {
            "method": "ModuleMethodCall", 
            "params": {
                "moduleMethod": "StopUploadInferenceData", 
                "moduleInstance": "backdoor-EA_Main", 
                "params": {}
            }
        }
        request_id = random.randint(0, 1000000)
        self.message_callback_add(f'v1/devices/{device_id}/rpc/response/{request_id}', self.handle_device_initialization_response)
        self.subscribe(f'v1/devices/{device_id}/rpc/response/{request_id}')
        self.publish(f'v1/devices/{device_id}/rpc/request/{request_id}', json.dumps(body))

    def handle_connect(self, client, userdata, msg):
        regex_match = re.fullmatch(IMXMqttHandler.TOPIC_CONNECT, msg.topic)
        device_id = regex_match.group(1)
        body = {
            "@type": "child-device",
            "name": f"IMX500 Camera {device_id}",
            "type": "imx500-camera",
        }
        self.publish(f'te/device/{device_id}//', json.dumps(body))
        time.sleep(5)
        self.publish(f'te/device/{device_id}///twin/c8y_SupportedOperations', '["c8y_Command", "c8y_SoftwareUpdate"]')
        self.publish(f'te/device/{device_id}///twin/c8y_SupportedSoftwareTypes', '["imx500-model", "imx500-app"]')
        # Bring the camera into initial state
        self.stop_sending_data(device_id)
        self.child_devices.add(device_id)
        self.retrieve_cumulocity_device(device_id)

    def handle_token(self, client, userdata, msg):
        self.token_auth.token = msg.payload.decode().split(',')[-1]
        logging.info(f"Received token: {self.token_auth.token}")
        
    def retrieve_cumulocity_device(self, device_id):
        response = requests.get(C8Y_BASE + f'/identity/externalIds/c8y_Serial/{self.device_id_prefix}:{device_id}', headers={'Authorization': 'Bearer ' + token_auth.token})
        if response.status_code != 200:
            time.sleep(5)
            response = requests.get(C8Y_BASE + f'/identity/externalIds/c8y_Serial/{self.device_id_prefix}:{device_id}', headers={'Authorization': 'Bearer ' + token_auth.token})
        sourceId = response.json()['managedObject']['id']
        logging.info(f"Retrieved Cumulocity device with ID {sourceId} for device {device_id}")
        self.token_auth.source_map[device_id] = sourceId

    def on_connect_handle(self, client, userdata, flags, rc):
        logging.info("Connected to MQTT broker")
        self.message_callback_add('v1/devices/+/connect', self.handle_connect)
        self.message_callback_add('v1/devices/+/attributes', self.handle_attr)
        self.message_callback_add('v1/devices/+/attributes/request/+', self.handle_attr_request)
        self.message_callback_add('v1/devices/+/telemetry', self.handle_telemetry)
        self.message_callback_add('c8y/s/ds', self.handle_c8y_commands)
        self.message_callback_add('c8y/s/dat', self.handle_token)
        self.subscribe('v1/devices/#')
        self.subscribe('c8y/s/ds')
        self.subscribe('c8y/s/dat')
        self.refresh_token()

    def on_message_handle(self, client, userdata, msg):
        logging.warning(f"Received message on unknown topic {msg.topic}: {msg.payload}")

    def refresh_token(self):
        self.publish('c8y/s/uat', '')
            



def file_uploader():
    while True:
        inference_item = inferences_cache.get()
        image_item = image_cache.get()
        if inference_item is None:
            time.sleep(1)
        else:
            HEADERS = {
                'Authorization': 'Bearer ' + token_auth.token,
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            inference_file_id, file_content = inference_item
            file_content['type'] = 'imx_inference'
            file_content['source'] = {
                #TODO: this is hardcoded for now and needs to change ones the camera can be identified on HTTP as well
                'id': token_auth.source_map['me'],
            }
            file_content['time'] = datetime.datetime.strptime(inference_file_id, '%Y%m%d%H%M%S%f').isoformat()[:-3] + 'Z'
            file_content['text'] = 'Inference result'
            #logging.debug(file_content)
            response = requests.post(C8Y_BASE + '/event/events', data=json.dumps(file_content), headers=HEADERS)
            #logging.debug(response.status_code)
            #logging.debug(response.json())
            eventId = response.json()['id']
            logging.debug(f"Created event with ID {eventId}")

            image_file_id, image_content = image_item
            IMAGE_HEADERS = {
                'Authorization': 'Bearer ' + token_auth.token,
                'Content-Type': 'application/octet-stream', 
                'Content-Disposition': f'attachment; filename="{image_file_id}.jpg"'
            }
            requests.post(C8Y_BASE + '/event/events/' + eventId + '/binaries', data=image_content, headers=IMAGE_HEADERS)
        inferences_cache.task_done()
        image_cache.task_done()

def main():
    # Start the Flask server 
    token_auth = CumulocityAuthentication()
    mqtt_client = IMXMqttHandler(token_auth)
    mqtt_client.loop_start()
    threading.Thread(target=file_uploader, daemon=True).start()

    # Start the HTTP server
    app.run(host='0.0.0.0', port=HTTP_SERVER_PORT)

if __name__ == "__main__":
    main()
    
