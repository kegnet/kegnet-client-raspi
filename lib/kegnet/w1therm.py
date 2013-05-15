import os

CONFIG_DIR = '/usr/share/kegnet/conf'
LOG_DIR = '/usr/share/kegnet/'
DEVICES_LIST = '/sys/bus/w1/devices/w1_bus_master1/w1_master_slaves'
DEVICES_DIR = '/sys/bus/w1/devices/'

def readTemp():
  if not os.path.exists(DEVICES_LIST):
    raise IOError("device list files does not exist: {0}".format(DEVICES_LIST))

  try:
    deviceNamesFile = open(DEVICES_LIST, 'r')
  except Exception as e:
    raise IOError("error opening device list file: {0} {1}".format(DEVICES_LIST, e))
  
  deviceName = deviceNamesFile.readline().rstrip()
  if len(deviceName) <= 0:
    raise IOError("invalid device name: {0}".format(deviceName))
  
  if deviceName == 'not found.':
    raise IOError("no w1 temperature probes found")
  
  deviceFileName = DEVICES_DIR + deviceName + "/w1_slave"
  
  try:
    deviceFile = open(deviceFileName, 'r')
  except Exception as e:
    raise IOError("error opening device file: {0} {1}".format(deviceFileName, e))

  lines = deviceFile.readlines()
  if len(lines) <= 0:
    raise IOError("device file was empty: {0}".format(lines))
  
  for line in lines:
    tokens = line.rsplit(' ')
    for token in tokens:
      if token.startswith("t="):
        tempStr = token.lstrip("t=")
        try:
          tempInt = int(tempStr)
        except Exception as e:
          raise IOError("invalid temp integer: {0} {1}".format(tempStr, e))
        
        if tempInt == 85000:
          raise IOError("probe returned unitialized value: {0}".format(tempStr))
        
        if tempInt == 0:
          raise IOError("probe returned invalid value: {0}".format(tempStr))

        return tempInt
  
  raise IOError("temp value not found: {0} ".format(lines))

if __name__ == "__main__":
  try:
    c = readTemp() * .001
    f = c * 1.8000 + 32.00
    print u"{0} \N{DEGREE SIGN}C / {1} \N{DEGREE SIGN}F".format(c, f)
  except Exception as e:
    print e
    
