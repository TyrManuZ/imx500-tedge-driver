# IMX500 driver for thin-edge.io

This project is WIP.
It is based on reverse engineering the MQTT communication of the cameras.

In order to connect the camera to a thin-edge you will still need the Local Edition tooling for generating the QR code.
Also on first use of the camera you should install the latest firmware via the Local Edition described procedure.

A lot of parts are still hardcoded and need to be replaced before installation. Step by step we will remove the hardcoded parts.
Here is the list of parameters you need to still find in the code and replace (all in the file server.py):

| Replace the parameter | Explanation |
|-----------------|-----------------|
| C8Y_BASE   | Put the same URL that the thin-edge is connecting to   |
| THIN_EDGE_IP   | The IP address of the thin-edge device in the local network (where the camera connects on)  |
| Row 3, Cell 1   | Row 3, Cell 2   |

## Installation

Use the package manager [pip](https://pip.pypa.io/en/stable/) to install the project.
Run the following command inside this directory (where the setup.py is located).

```bash
pip install .
```

## Running the driver

You always need to first run the driver using 

```bash
imx500_driver
```

You should see in the log the encoded authentication token for Cumulocity after starting. If you don't see it, stop the driver and start it again.
Once the driver is running turn on the camera. Currently the driver will not initialize correctly if the camera is already running.

## Running the camera

When the camera is connected to Cumulocity (both LEDs green) you can deploy your model trough the software management. YOu also need to deploy the vision app through the software management (currently only classification is supported).
Note that the vision app is not persisted on the camera. If you restart the camerea you will need to redploy the vision app first before starting to send data.

In order to start sending data go to the Shell and send the following command:
```bash
start ${frequency} ${classes}
```
The frequency is the number of frames until you send (= send every x frames). 
The classes is the amount of classes your model outputs (this is important for parsing the output of the camera)
Example:
```bash
start 100 10
```

In order to stop sending data go to the Shell and send the following command:
```bash
stop
```