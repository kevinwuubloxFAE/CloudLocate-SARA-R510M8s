#====================================================================
# Test device : SARA-R510M8s
# Test FW version : 03.03
# Test Python version: 3.9
# The code version : 2.4 
# run "pip install pyserial" or "python -m pip install pyserial"
# Add criteria to improve the position accuracy (2021/7/12)
# Add fallback methodology and subscribe topic(2021/7/29)
# Modify an issue with lambda x: x[1]["cno"] >= CNO_THRESHOLD (2021/8/4)
# Add UBX commands to switch GPS/GLONASS/Galileo/Beidou only for testing, however CloudLocate is only supported GPS so far.(2021/8/6)
# Add MQTT-SN for testing using ThingStream's SIM card with "TSUDP", MQTTPubData is used for switching MQTT with "True" and MQTT-SN with "False" (2021/8/12)
# The payload size of MQTT-SN is only supported 1017 bytes, thus epochs will be 1~2
#====================================================================

import threading,serial,time,sys
import base64
import codecs
import struct

import binascii
import enum

# this class defines number of fallback configurations available, as enum
class FallbackConfig(enum.Enum):
    FALLBACK_DO_NOT_SEND = 1
    FALLBACK_NO_OF_SATELLITIES_ONLY = 2
    FALLBACK_EXTEND_TIMEOUT = 3
    FALLBACK_EPOCHS = 4

# this map translates fallback configuration enum to its required parameter
FALLBACK_CONFIG = {
    FallbackConfig.FALLBACK_DO_NOT_SEND: True, # this will not use any fallback, and is the default when running this script
    FallbackConfig.FALLBACK_NO_OF_SATELLITIES_ONLY: 4, # this will fallback to only match # of satellites (irrespective of CNO value)
    FallbackConfig.FALLBACK_EXTEND_TIMEOUT: 5, # this will extend the timeout value, so if a match is not found without original time, it will add this more seconds
    FallbackConfig.FALLBACK_EPOCHS: 1 # this will use main configuration but override number of epochs set to 1
}

# Global Variant
SerialPort = "COM5"  # uart port of SARA-R510M8s 
run_retry_times = 1  # To define how many times will be tested.
run_wait_time = 30  #To define the waiting time for the next action.
MQTTPubData = True # True:MQTT; False:MQTT-SN

TIMEOUT = 12 # in seconds
CNO_THRESHOLD = 22
MIN_NO_OF_SATELLITES = 6
MULTIPATH_INDEX = 1 # 1:low 2:medium 3: high
EPOCHS = 2

# set the fallback methodology to use in case main configuration does not yield desired MEASX message
FALLBACK_METHODOLOGY = FallbackConfig.FALLBACK_EPOCHS

# every MEASX message starts with this header
# we need to break read bytes from the receiver based on this header value
MEASX_HEADER = b"\xb5\x62\x02\x14"

# this counter keeps track of the number of valid messages, messages that fit 
# the configuration parameters above
validMessageCounter = 0

# see if fallback methodology is set to extend the timeout. if so, add extended time to TIMEOUT
extendedTime = 0
if FALLBACK_METHODOLOGY == FallbackConfig.FALLBACK_EXTEND_TIMEOUT:
    extendedTime = FALLBACK_CONFIG[FallbackConfig.FALLBACK_EXTEND_TIMEOUT]

# this variable will contain our desired MEASX message(s)
MEASX_MESSAGE = bytearray()

# Delivery platform and get the credentials
Hostname = "mqtt.thingstream.io"
DeviceID = "Your MQTT device ID"
Username = "Your username"
Password = "Your password" 

#MQTT-SN credentials
SNuniqueID = "Your MQTT-SN unique ID"
SNSerevrIP = "10.7.0.55"
SNServerPort = "2442"
SNServerDuration = "300"

# possible values that can be set in GNSS_TYPE configuration parameter
CONSTELLATION_TYPES = {  "GPS": 0,
                        "GALILEO": 2,
                        "BEIDOU": 3,
                        "GLONASS": 6}

GNSS_TYPE = "GPS" # possible values are mentioned in CONSTELLATION_TYPES variable above

# we need to publish our base64 encoded message on this topic
MQTT_PUB_TOPIC = "CloudLocate/GNSS/request"
# we will get a position back on this topic, so we need to subscribe to it
MQTT_SUB_TOPIC = f"CloudLocate/{DeviceID}/GNSS/response"
#MQTT_SUB_TOPIC = f""

#we need to publish our base64 encoded message on this topic in the Flows
MQTTSN_PUB_TOPIC = "CloudLocate/GNSS/request"
# we will get a position back on this topic in the Flows, so we need to subscribe to it
MQTTSN_SUB_TOPIC = "CloudLocate/GNSS/position"

# an array to keep track of read MEASX messages, so we can pick the one based on fallback configuration,
# if main configuration does not yield desired MEASX message
READ_RAW_MEASX_MESSAGES = []

#MQTT_MSG = ""
#----------------------------------------------------------------------------- 
# function to see how many satellites are required for fallback strategy when looking at MEASX messages
def get_satellite_count_per_configuration(fl, mx):
    if fl == FallbackConfig.FALLBACK_NO_OF_SATELLITIES_ONLY:
        return len(mx['satellitesInfo'])
    elif fl == FallbackConfig.FALLBACK_EPOCHS:
	# lambda x: x[0] --> svID; lambda x: x[1]["cno"] --> C/No
        filteredMEASX = dict(filter(lambda x: x[1]["cno"] >= CNO_THRESHOLD, mx['satellitesInfo'].items()))
        print(f'... filteredMEASX : {filteredMEASX}')
        return len(filteredMEASX)

# function that goes through MEASX messages to find the one that matches selected fallback methodology
def apply_fallback_logic(fallbackLogic, epochs, satellites):
#	print(f'.. fallback message : {READ_RAW_MEASX_MESSAGES}')
    # first check if we at least have enough messages (as per our required EPOCHS)
	if len(READ_RAW_MEASX_MESSAGES) < epochs:
		return False

	print(f'Using fallback configuration: {fallbackLogic.name}')
    # sort saved messages as per highest CNO (carrier-to-noise)
	READ_RAW_MEASX_MESSAGES.sort(key=lambda x: x['maxCNO'], reverse=True)
	MEASX_MESSAGE = bytearray()
    # start looking for a message that fulfills our fallback criteria
    # index is used to keep track of number of messages that fits our criteria (to be compared against number of epochs)
	index = 0
	for measX in READ_RAW_MEASX_MESSAGES:
		satCount = get_satellite_count_per_configuration(fallbackLogic, measX)
		if satCount >= satellites:
			MEASX_MESSAGE.extend(MEASX_HEADER)
			MEASX_MESSAGE.extend(measX['measxMessage'])
			index = index + 1
        # no need to run the loop if we've found our desired number of epochs
		if (index == epochs): break
	if (index < epochs):
		return False

	return MEASX_MESSAGE

def getTime():
    timeArray = time.localtime()
    otherStyleTime = time.strftime("%Y-%m-%d %H:%M:%S", timeArray)
    return otherStyleTime

def getUTCTime():
    timeArray = time.gmtime()
    otherStyleTime = time.strftime("%Y-%m-%dT%H:%M:%S", timeArray)
    return otherStyleTime

def remove_bytes(buffer, start, end):
    fmt = '%ds %dx %ds' % (start, end-start, len(buffer)-end)  # 3 way split
    return b''.join(struct.unpack(fmt, buffer))
	
def command_send(at_cmd):
	global res_str_at_command
	res_str_at_command = ''

	print(getTime()+':input->'+at_cmd)
	cmd = at_cmd+'\r\n'
	ser.write(cmd.encode())

def Waitfor(at_cmd, timeout):
	global res_str_at_command
	res_str_at_command = ''
	when = int(time.time()) + int(timeout) # get the timestamp
	while True:
		now = int(time.time())
		time.sleep(0.1) #0.05
		if (now > when):
			return False 
		else :
			if at_cmd in res_str_at_command:
				return True
			if "ERROR" in res_str_at_command: #ERROR
				return False
	
def SaveJSON2FFS(str_payload):
	length_str_payload = str(len(str_payload))
	command_send('AT+UDWNFILE="CloudLocate_pub_data.txt",'+ length_str_payload)
	time.sleep(1) #Waitfor(">",2)
	command_send(str_payload)
	Waitfor("OK", 25)
	
def DelJSON_FFS():
	command_send('AT+UDELFILE="CloudLocate_pub_data.txt"')
	Waitfor("OK", 2)
#	time.sleep(2)
				
def PDP_Context_activate(activate_flag):
	if (activate_flag==1):
		print('.. PDP Context activate')
		command_send('at+cops?;+CSQ;+CGATT?')
		#time.sleep(2)
		Waitfor("OK", 2)
		
		command_send('AT+UPSD=0,100,1')
		time.sleep(0.1)
	
		command_send('AT+UPSD=0,0,0')
		time.sleep(0.1)
	
		command_send('AT+UPSDA=0,3')
		Waitfor("+UUPSDA", 5)
	else:
		print('.. PDP Context deactivate')
		command_send('AT+UPSDA=0,4')
		Waitfor("+UUPSDD", 5)

def SetMQTTProfile():
	print('.. Save MQTT profile')
# Unique Client ID
	command_send('AT+UMQTT=0,"'+DeviceID+'"')
	time.sleep(0.5)

# Host server
	command_send('AT+UMQTT=2,"'+Hostname+'"')
	time.sleep(0.5)

# Username and password
	command_send('AT+UMQTT=4,"'+Username+'","'+Password+'"')
	time.sleep(0.5)
	
# keep alive time (seconds)
	command_send('AT+UMQTT=10,60')  
	time.sleep(0.5)

# Save MQTT profile
	command_send('AT+UMQTTNV=2')  
	time.sleep(0.5)

def SetMQTTSNProfile():
	print('.. Save MQTT-SN profile')
# Client ID
	command_send('AT+UMQTTSN=0,"'+SNuniqueID+'"')
	time.sleep(0.5)

# Host and Port
	command_send('AT+UMQTTSN=2,"'+SNSerevrIP+'",'+SNServerPort+'')
	time.sleep(0.5)

# Duration (seconds)
	command_send('AT+UMQTTSN=8,'+SNServerDuration)  
	time.sleep(0.5)

# Save MQTT-SN profile
#	command_send('AT+UMQTTSNNV=2')  
#	time.sleep(0.5)
 		
def SubPOSTOPIC():
	if MQTT_SUB_TOPIC:
		print('.. Subscribe a TOPIC as '+ MQTT_SUB_TOPIC)
		command_send('AT+UMQTTC=4,0,"'+MQTT_SUB_TOPIC+'"')
		Waitfor("+UUMQTTC: 4,1,0,",30)

def PubDataCloud():
# Restore MQTT profile from NVM
	command_send('AT+UMQTTNV=1')  
	time.sleep(0.5)
	
# Connect MQTT broker
	print('.. Connect MQTT broker')
	command_send('AT+UMQTTC=1') 
	if(Waitfor("+UUMQTTC: 1,1", 120)):

		#subscribe a topic for the positon
		SubPOSTOPIC()

		# publish payload from FFS
		print('.. Publish JSON to TS')
		command_send('AT+UMQTTC=3,0,0,"'+ MQTT_PUB_TOPIC +'","CloudLocate_pub_data.txt"') 
		Waitfor("+UUMQTTC: 3,1", 30)
		
		if MQTT_SUB_TOPIC:
			if (Waitfor("+UUMQTTC: 6,1",30)):
				command_send('AT+UMQTTC=6')
				Waitfor("OK",5)
				
		# disconnect MQTT broker
		command_send('AT+UMQTTC=0') 
		Waitfor("+UUMQTTC: 0,1", 30)

def MQTTSNPubDataCloud():
# Restore MQTT profile from NVM
#	command_send('AT+UMQTTSNNV=1')  
#	time.sleep(0.5)

# Connect MQTTSN Thing
	print('.. Connect a MQTT-SN Thing')
	command_send('AT+UMQTTSNC=1') 
	if(Waitfor("+UUMQTTSNC: 1,1", 120)):
		
		#Register a Topic for CloudLocate
		print('.. Register a Topic')
		command_send('AT+UMQTTSNC=2,"'+MQTTSN_PUB_TOPIC+'"')
		if(Waitfor("+UUMQTTSNC: 2,1,1", 60)):
			
			if(MQTTSN_SUB_TOPIC):
				#Subscribe a Topic for getting back the position
				print('.. Subscribe a Topic for getting back the position')
				command_send('AT+UMQTTSNC=5,1,0,"'+MQTTSN_SUB_TOPIC+'"')
				Waitfor("+UUMQTTSNC: 5,1,0,2", 15)
			
			# Publish a File within 1017 bytes to TopicID "1"
			print('.. Publish message to TopicID "1"')
			command_send('AT+UMQTTSNC=11,0,0,0,"1","CloudLocate_pub_data.txt"')
			Waitfor("+UUMQTTSNC: 11,1",30)
				
			if (MQTTSN_SUB_TOPIC):
				if(Waitfor("+UUMQTTSNC: 9,1",30)):
					command_send('AT+UMQTTSNC=9,1')
					Waitfor("OK",5)

# disconnect MQTT broker
	print('Disconnect a MQTT-SN Thing')
	command_send('AT+UMQTTSNC=0')
	Waitfor("+UUMQTTSNC: 0,1", 30)
	
def CloudLocate_run():
	print('.. Retrieve UBX-RXM-MEASX')
	# GNSS on
	command_send('at+UGPS=1,1')  #no aiding:1,0; local aiding:1,1; offline:1,2; online:1,4; autonomous:1,8;   
	Waitfor("OK", 10)

	global MEASX_MESSAGE
	global EPOCHS

	FALLBACK_METHODOLOGY_STATUS = True
	# this counter keeps track of the number of valid messages, messages that fit 
	# the configuration parameters above
	global validMessageCounter
	validMessageCounter = 0
	
	if(GNSS_TYPE == "GPS"):
		command_send('AT+UGUBX="B562063E3C000000200700081000010001010101030000000101020408000000010103081000000001010400080000000101050003000100050106080E0000000001307F"') #GPS+QZSS (UBX-CFG-GNSS)
		Waitfor("OK", 1)
	elif(GNSS_TYPE == "GALILEO"):
		command_send('AT+UGUBX="B562063E3C000000200700081000000001010101030000000101020408000100010103081000000001010400080000000101050003000000000106080E00000000012A31"') #Galileo
		Waitfor("OK", 1)
	elif (GNSS_TYPE == "BEIDOU"):
		command_send('AT+UGUBX="B562063E3C000000200700081000000001010101030000000101020408000000010103081000010001010400080000000101050003000000000106080E00000000012A29"') #Beidou
		Waitfor("OK", 1)
		command_send('AT+UGUBX="B5620617140000400002000000000100000100000000000000007550"') #extend3digit(UBX-CFG-NMEA)
		Waitfor("OK", 1)
	elif (GNSS_TYPE == "GLONASS"):
		command_send('AT+UGUBX="B562063E3C000000200700081000000001010101030000000101020408000000010103081000000001010400080000000101050003000000000106080E00010001012B13"') #GLONASS
		Waitfor("OK", 1)

	time.sleep(5)
	startTime = time.time()
	while (time.time()-startTime) <= (TIMEOUT + extendedTime) and validMessageCounter < EPOCHS :
		command_send('AT+UGUBX="B562021400001644"') #UBX-RXM-MEASX
		Waitfor("OK", 10)	#timeout is defined by at commands manual	

	# GNSS off
	command_send('at+UGPS=0')
	Waitfor("OK", 10)

	# ninth step: see if we were able to get MEASX messages as per our requirement
	if validMessageCounter < EPOCHS :
	    # we did not find any MEASX message as per our requirement,
		# so, we will check processed MEASX messages to see if they fall under our fallback criteria
		if (FALLBACK_METHODOLOGY == FallbackConfig.FALLBACK_DO_NOT_SEND):
			print("No fallback configuration selected. Please tweak your desired criteria (or choose a different fallback methodology) to get MEASX message")
			FALLBACK_METHODOLOGY_STATUS = False  #exit()
    
		# if this fallback is selected, we've already extended the timeout in main loop, and we did not find any MEASX message
		if (FALLBACK_METHODOLOGY == FallbackConfig.FALLBACK_EXTEND_TIMEOUT):
			print('No message found while using fallback configuration. Please tweak your desired criteria (or choose a different fallback methodology) to get MEASX message')
			FALLBACK_METHODOLOGY_STATUS = False  #exit()

		if FALLBACK_METHODOLOGY == FallbackConfig.FALLBACK_NO_OF_SATELLITIES_ONLY:
			fallback_result = apply_fallback_logic(FallbackConfig.FALLBACK_NO_OF_SATELLITIES_ONLY, EPOCHS, FALLBACK_CONFIG[FallbackConfig.FALLBACK_NO_OF_SATELLITIES_ONLY])
			if fallback_result == False:
				print('No message found while using fallback configuration. Please tweak your desired criteria (or choose a different fallback methodology) to get MEASX message')
				FALLBACK_METHODOLOGY_STATUS = False  #exit()
			MEASX_MESSAGE = fallback_result

		elif FALLBACK_METHODOLOGY == FallbackConfig.FALLBACK_EPOCHS:
			fallback_result = apply_fallback_logic(FallbackConfig.FALLBACK_EPOCHS, FALLBACK_CONFIG[FallbackConfig.FALLBACK_EPOCHS], MIN_NO_OF_SATELLITES)
			if fallback_result == False:
				print('No message found while using fallback configuration. Please tweak your desired criteria (or choose a different fallback methodology) to get MEASX message')
				FALLBACK_METHODOLOGY_STATUS = False  #exit()
			MEASX_MESSAGE = fallback_result

	if FALLBACK_METHODOLOGY_STATUS == False :
		return False

	print(f"Final Measx: {MEASX_MESSAGE.hex()}")
	print(".. Measure time : "+ str(int((time.time()-startTime))) +" seconds")

    # tenth step: convert our MEASX byte-array into base64 encoded string
	BASE64_ENC_PAYLOAD = base64.b64encode(MEASX_MESSAGE).decode()
	MEASX_MESSAGE = bytearray()  #clear buffer
	
	# eleventh step: create JSON payload, which will be sent to CloudLocate, 
	# exit if it exceeds 8KB
	MQTT_MSG ='{"body":"'+BASE64_ENC_PAYLOAD+'","headers":{"UTCDateTime":"'+getUTCTime()+'"}}'
#	print(MQTT_MSG)
	
	if (MQTTPubData == True):
		if len(MQTT_MSG) > 8192:
			print("Cannot send MQTT message greath than 8KB. Please reduce the number of EPOCHS in configuration parameters to reduce the size.")
			return False
	else :
		if len(MQTT_MSG) > 1017:
			print("Cannot send MQTT-SN message greath than 1017 Bytes. Please reduce the number of EPOCHS in configuration parameters to reduce the size.")
			return False

	# Delet JSON file on FFS
	DelJSON_FFS()
	# Save JSON file into FFS
	SaveJSON2FFS(MQTT_MSG)
	
	# Publish data out ThingStream	
	if (MQTTPubData == True):
		PubDataCloud()
	else :
		MQTTSNPubDataCloud()
		
def showHelp():
	print('================')
	print('Press "run" to perform CloudLocate')
	print('Press "AT" to perform AT commands')
	print('Press "q" to exit')

def getINTnum(number):
#	print(str(number))
	if number >= 48 and number <= 57:
		number -= 48
	if number >= 65 and number <= 90:
		number -= 65
		number += 10
	if number >= 97 and number <= 122:
		number -= 97
		number += 10

	return number

def getUBXPayload(payload):
	UBXpayload = b''

	i = 0
	while i < (len(payload)):
		#two bytes convert to one byte
		UBXpayload += bytes([(getINTnum(payload[i])*16 +getINTnum(payload[i+1]))])
		i += 2
	return UBXpayload

def getNMEASX(rawMessage):
	# third step: read message from receiver
	# rawMessage = ser.read_until(MEASX_HEADER)
	
	# fourth step: calculate size of payload contained inside read MEASX message
	size = (rawMessage[1]<<8)|rawMessage[0]
	#checking size for a valid measx message
	if(size <= 33) :
		print(f"Message skipped: {rawMessage.hex()}")
		#skipping this message
		#continue
	# fifth step: extract actual MEASX payload (without header, and checksum)
	measxMessagePayload = rawMessage[2:size+2]
	# sixth step: get the number of satellites contained in this message
	numSv = measxMessagePayload[34]
	print("Number of satellites: ", numSv)
	# need to save this message for fallback logic
	processedMeasxMessage = {
		'measxMessage': rawMessage[0:size+4],
		'maxCNO': 0,
		'satellitesInfo': { }
	}
	satelliteCount = 0
	# seventh step: for the number of satellites contained in the message
	# we need to see if every satellite's data falls as per our configuration
	# because a single MEASX message can contain more than one satellite's information
	for i in range(0, numSv):
	# eight step: only accept the message if it fulfills our criteria, based on configuration parameters above
		gnss = measxMessagePayload[44+24*i]
		if gnss == CONSTELLATION_TYPES[GNSS_TYPE]: 
			# carrier-to-noise ratio
			cNO = measxMessagePayload[46+24*i]
			# save maximum CNO value as a separate key in stored measx message
			if cNO > processedMeasxMessage['maxCNO']:
				processedMeasxMessage['maxCNO'] = cNO
			multipathIndex = measxMessagePayload[47+24*i]
			svID = measxMessagePayload[45+24*i]
			processedMeasxMessage['satellitesInfo'][svID] = {'cno': cNO, 'mpi': multipathIndex }
			if cNO >= CNO_THRESHOLD and multipathIndex <= MULTIPATH_INDEX:    
				satelliteCount = satelliteCount + 1
				print(f"gnss: {gnss} ... svID:{svID} ... cNO: {cNO} ... multipathIndex: {multipathIndex}")
	# saving processed message for fallback logic  
	READ_RAW_MEASX_MESSAGES.append(processedMeasxMessage)

	if satelliteCount >= MIN_NO_OF_SATELLITES:
#		global MEASX_MESSAGE
		MEASX_MESSAGE.extend(MEASX_HEADER)
		MEASX_MESSAGE.extend(bytearray(rawMessage[0:size+4]))
		global validMessageCounter
		validMessageCounter = validMessageCounter + 1

class Response(threading.Thread):
	def __init__(self, ser):
		super().__init__()
		self.ser =ser
		self.flag= True
	def run(self):
		ser = self.ser
		while self.flag:
			res_bytes=self.ser.readline()
			res_str=str(res_bytes.decode()).replace('\r\n','')
			if len(res_str) >1:
				print(getTime()+':output->'+res_str)
				global res_str_at_command #creating global scope variable
				res_str_at_command = res_str
# Convert UBX-RXM-MEASX to base64			
			if b'\x42\x35\x36\x32\x30\x32\x31\x34' in res_bytes: #+UGUBX: "B5620214
				res_bytes = remove_bytes(res_bytes,0,9) # remove <+UGUBX: ">
				if b'\x0d\x0a' in res_bytes:
					res_bytes = remove_bytes(res_bytes,(len(res_bytes)-3),len(res_bytes)) #remove <"\x0d\x0a>
					res_bytes = remove_bytes(res_bytes,0,8) #12
					getNMEASX(getUBXPayload(res_bytes))
	
	def stop(self):
		self.flag = False

try:
    ser = serial.Serial(port=SerialPort, baudrate=115200, timeout=2)
except Exception:
    print('connect serial error!')
    sys.exit(1)
print('connect..')

response = Response(ser)
response.start()

print('=== Startup ===')
command_send('ate0')
time.sleep(0.1)

showHelp()

while True:
	at = input('')
 
	if at=='':
		continue
	if at == 'HELP':
		showHelp()
	if at=='q':
		response.stop()
		sys.exit()
	if at == 'run':

# Whether "tsudp" APN is set.
		if(MQTTPubData == False): # MQTT-SN
			command_send('at+cgdcont?')
			when = int(time.time()) + int(2) # waiting for 2 seconds
			while True:
				now = int(time.time())
				if (now > when):
					print(res_str_at_command)
					print('*** TS SIM card with "tsudp" is needed for MQTT-SN ***')
					print('*** APN is incorrect ***')
					response.stop()
					sys.exit()
				else :
					if "tsudp" in res_str_at_command:
						break

		PDP_Context_activate(1)
			
		if (MQTTPubData == True):
			SetMQTTProfile()
		else :
			SetMQTTSNProfile()
			
		command_send('at+UGPRF=1')  #Set GNSS channel 
		Waitfor("OK", 2)
		
		Measure_count=0
		while True:
			if (Measure_count >= int(run_retry_times)):
				print('... Measure Done')
				PDP_Context_activate(0)
				showHelp()
				break
			else:
				Measure_count +=1
				CloudLocate_run()
				if (Measure_count < int(run_retry_times)):
					print('.. Waiting '+str(run_wait_time)+ ' seconds for the next action. Remaining testing times : '+str(run_retry_times - Measure_count))
					# waiting for the next action.
					time.sleep(int(run_wait_time))
			
	else:
		command_send(at)

