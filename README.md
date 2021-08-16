# CloudLocate using SARA-R510M8s
## Introduction 
The purpose of this guide is to learn how to get  the real-time MEASX messages from [u-blox SARA-R510M8s EVK](https://www.u-blox.com/en/product/evk-r5) without using u-center, and sending the message to the [CloudLocate](https://www.u-blox.com/en/product/cloudlocate) service.

The python code is developing from [Developer.ThingStream](https://developer.thingstream.io/guides/location-services/cloudlocate-getting-started/getting-real-time-measx-messages-from-gnss#h.zi36djdj2y43) and modifying using SARA-R510M8s.

The credentials of a "CloudLocate Location Thing" and a "Thing" with MQTT can be created in the [ThingStream](https://www.u-blox.com/en/product/thingstream)

A "CloudLocate Location Thing" and a "CloudLocate node" in the Flows are available. You may choose either one or use both of them with double charged

The [IoT SIM](https://www.u-blox.com/en/product/iot-sim-card) with MQTT-SN is also available in the code.

## Modify the parameters for testing
### Global Variant
In the line 39 : 

SerialPort = "COM5"  # uart port of SARA-R510M8s 

run_retry_times = 1  # To define how many times will be tested.

run_wait_time = 30  # To define the waiting time(seconds) for the next action.

MQTTPubData = False # To define which protocol will be tested, True:MQTT; False:MQTT-SN

TIMEOUT = 12 # Timeout time in seconds

CNO_THRESHOLD = 22 # Carrier-to-noise

MIN_NO_OF_SATELLITES = 6

MULTIPATH_INDEX = 1 # 1:low 2:medium 3: high

EPOCHS = 2 # To define how many epochs will be used, more epochs will get the better position accuracy 

### Credentials
In the line 70:  

#it can be created by a "Location Thing" or a "Thing" in the ThingStream

Hostname = "mqtt.thingstream.io" 

DeviceID = "Your device ID"

Username = "Your username"

Password = "Your password" 


### MQTT-SN credentials
In the lin 76:

SNuniqueID = "Your MQTT-SN unique ID"  #The unique ID is [IoT SIM](https://www.u-blox.com/en/product/iot-sim-card).

### A Topic with "Location node" for publishing and subscribing in the Flows
In the line 96:

MQTTSN_PUB_TOPIC = "CloudLocate/GNSS/request"  #we need to publish our base64 encoded message on this topic in the Flows

MQTTSN_SUB_TOPIC = "CloudLocate/GNSS/position"  # we will get a position back on this topic in the Flows, so we need to subscribe to it

## Execute the python code
The code is made under Python3.9

C:\>python.exe at_cloudlocate_test.py

connect..

=== Startup ===

2021-08-16 12:53:16:input->ate0

2021-08-16 12:53:16:output->OK  # module is ready

================

Press "run" to perform CloudLocate

Press "AT" to perform AT commands

Press "q" to exit
