import M2Crypto
from M2Crypto import EVP
import base64
import os
import requests
import json
import pyinotify
from ConfigParser import SafeConfigParser
import syslog
import errno, sys
import uuid
import time
from kegnet import w1therm

TIME_CHECK_TS = 1262304000
CONFIG_DIR = '/usr/share/kegnet/conf'
LOG_DIR = '/usr/share/kegnet/spool'
MAX_RETRY_INTERVAL = 3600

idCounter = 0
lastRetry = 0
nextRetry = 0
retryCount = 0

lastTemp = 0
lastTempTs = 0

syslog.openlog("pourd", logoption=syslog.LOG_PID|syslog.LOG_CONS, facility=syslog.LOG_USER)

configPath = CONFIG_DIR + '/pourd.conf'

config = SafeConfigParser()
try:
  fileName = config.read(configPath)
  if not fileName:
    syslog.syslog(syslog.LOG_ERR, "failed to load {0} {1}".format(configPath, "not found"))
    sys.exit(1)
except Exception as e:
  syslog.syslog(syslog.LOG_ERR, "failed to load {0} {1}".format(configPath, e))
  sys.exit(1)

try:
  uuidString = config.get('pourd', 'uuid')
except Exception as e:
  syslog.syslog(syslog.LOG_ERR, "required parameter '{0}' not found in {1}".format('uuid', configPath))
  sys.exit(1)

try:
  serviceURL = config.get('pourd', 'serviceURL')
except Exception as e:
  syslog.syslog(syslog.LOG_ERR, "required parameter '{0}' not found in {1}".format('serviceURL', configPath))
  sys.exit(1)

try:
  uuid.UUID(uuidString)
except Exception as e:
  syslog.syslog(syslog.LOG_ERR, "invalid uuid format '{0}' found in {1} {2}".format(uuidString, configPath, e))
  sys.exit(1)

keyPath = CONFIG_DIR + "/privkey.pem"
try:
  key = EVP.load_key(keyPath)
except Exception as e:
  syslog.syslog(syslog.LOG_ERR, "failed to load private key from {0} {1}".format(keyPath,  e))
  sys.exit(1)

if not os.path.isdir(LOG_DIR):
  os.mkdir(LOG_DIR)
  
def getTemp():
  global lastTemp, lastTempTs
  
  now = time.time()
  age = now - lastTempTs
  if age > 60:
    try:
      lastTempTs = now
      lastTemp = w1therm.readTemp()
    except Exception as e:
      syslog.syslog(syslog.LOG_ERR, "failed to read temp {0}".format(e))
      return -1
  return lastTemp
  
def failPour(path):
  newPath = path + ".fail"
  os.rename(path, newPath)
  syslog.syslog(syslog.LOG_INFO, "renamed failed pour to {0}".format(newPath))

def processPour(path):
  try:
    rawDataFile = open(path, "r")
    rawData = rawDataFile.readline().rstrip()
    rawDataFile.close()
  except Exception as e:
    syslog.syslog(syslog.LOG_ERR, "failed to read pour file {0} {1}".format(path, e))
    failPour(path);
    return False
  
  data = rawData.split(',')
  if len(data) != 4:
    syslog.syslog(syslog.LOG_ERR, "invalid pour file {0} {1}".format(path, data))
    failPour(path);
    return False
  
  # validate this data?    
  pin = data[0]
  pulses = data[1]
  et = data[2]
  ts = data[3]
  
  signData = "{0},{1},{2},{3},{4}".format(uuidString, pin, pulses, et, ts)
  syslog.syslog(syslog.LOG_DEBUG, "pour data {0}".format(signData))

  try:
    key.reset_context(md='sha256')
    key.sign_init()
    key.sign_update(signData)
    signature = key.sign_final()
  except Exception as e:
    syslog.syslog(syslog.LOG_ERR, "failed to sign pour {0} {1} {2}".format(signData, path, e))
    failPour(path);
    return False
  
  signatureBase64 = base64.b64encode(signature)
  
  global idCounter
  idCounter += 1
  
  params={'id':uuidString, 'pin':pin, 'pulses':pulses, 'et':et, 'ts':ts, 'signatureBase64':signatureBase64}
  payload = {'id':idCounter, 'method':'pour1', 'jsonrpc':'2.0', 'params':params}
  
  try:
    jsonPayload = json.dumps(payload)
  except Exception as e:
    syslog.syslog(syslog.LOG_ERR, "failed to convert pour to json {0} {1} {2}".format(signData, path, e))
    failPour(path);
    return False
  
  try:
    response = requests.post(url=serviceURL, data=jsonPayload, allow_redirects=True, timeout=10, verify=True)
    response.raise_for_status()
  except Exception as e:
    syslog.syslog(syslog.LOG_ERR, "failed to transmit pour {0} {1}, will retry".format(path, e))
    return False
    
  try:
    responseText = response.text
  except Exception as e:
    syslog.syslog(syslog.LOG_ERR, "failed to read pour response {0} {1}, will retry".format(path, e))
    return False
  
  try:
    jsonObject = json.loads(responseText)
  except Exception as e:
    syslog.syslog(syslog.LOG_ERR, "failed to load pour response JSON {0} {1} {2}, will retry".format(path, responseText, e))
    return False
  
  try:
    result = jsonObject['result']
  except Exception as e:
    syslog.syslog(syslog.LOG_ERR, "failed to read pour response JSON result {0} {1} {2}, will retry".format(path, responseText, e))
    return False
  
  if result == 'OK':
    syslog.syslog(syslog.LOG_INFO, "transmitted pour {0} successfully".format(path))
    try:
      os.remove(path)
    except Exception as e:
      syslog.syslog(syslog.LOG_ERR, "failed to delete pour {0} {1}, will retry".format(path, e))
      return False
  else:
    syslog.syslog(syslog.LOG_ERR, "received pour failure response from server {0} for pour {1}".format(result, path)) 
    return False
  
  return True

class EventHandler(pyinotify.ProcessEvent):
  def process_IN_MOVED_TO(self, event):
    if event.pathname.endswith('.pour'):
      path = event.pathname
      try:
        syslog.syslog(syslog.LOG_DEBUG, "processing new pour {0}".format(path))
        processPour(path)
      except Exception as e:
        syslog.syslog(syslog.LOG_ERR, "caught unexpected exception processing pour {0} {1}".format(path, e))

try:
  watchManager = pyinotify.WatchManager()
  watchManager.add_watch(LOG_DIR, pyinotify.IN_MOVED_TO)
  eventHandler = EventHandler()
  notifier = pyinotify.Notifier(watchManager, eventHandler, timeout=60000)
except Exception as e:
  syslog.syslog(syslog.LOG_ERR, "failed to initialize inotify WatchManager {0}".format(e))
  sys.exit(1)
  
def processRetries():
  #syslog.syslog(syslog.LOG_DEBUG, "checking for pour retries...");
  
  fileList = os.listdir(LOG_DIR)
  if len(fileList) == 0:
    return
  
  global nextRetry, lastRetry, retryCount
  
  now = time.time()
  if (now < nextRetry):
    #syslog.syslog(syslog.LOG_DEBUG, "too early to retry on attempt {0} {1} < {2}...".format(retryCount+1, now, nextRetry));
    return
  
  attemptCount = 0;
  successCount = 0;
  
  for file in fileList:
    path = "{0}/{1}".format(LOG_DIR, file)
    if file.endswith('.pour'):
      try:
        syslog.syslog(syslog.LOG_DEBUG, "processing retry pour {0}".format(path))
        attemptCount += 1
        success = processPour(path)
        if success:
          successCount += 1
      except Exception as e:
        syslog.syslog(syslog.LOG_ERR, "caught unexpected exception processing retry pour {0} {1}".format(path, e))
        raise
    else:
      syslog.syslog(syslog.LOG_WARNING, "deleting non-pour file in spool directory {0} ".format(path))
      try:
        os.remove(path)
      except Exception as e:
        syslog.syslog(syslog.LOG_ERR, "failed to delete non-pour {0} {1}".format(path, e))
  
  if attemptCount == 0:
    return
  
  failCount = (attemptCount - successCount)
  
  if failCount  == 0:
    syslog.syslog(syslog.LOG_WARNING, "all {0} retries transmitted successfully on attempt {1}".format(successCount, retryCount+1))
    nextRetry = 0
    lastRetry = 0
    retryCount = 0
    return
  
  # it's important to have a back-off sequence, otherwise the server can 
  # be overwhelmed by retries immediately when it starts up
  
  retryCount += 1
  nextInterval = 30 * retryCount
  if (nextInterval > MAX_RETRY_INTERVAL):
    nextInterval = MAX_RETRY_INTERVAL
  nextRetry = now + nextInterval
  
  syslog.syslog(syslog.LOG_WARNING, "{0} of {1} retries failed on attempt {2}, will retry again in {3} seconds".format(failCount, attemptCount, retryCount, nextInterval))

def ping():
  temp = getTemp()
  
  signData = "{0},{1}".format(uuidString, temp)
  syslog.syslog(syslog.LOG_DEBUG, "ping data {0}".format(signData))

  try:
    key.reset_context(md='sha256')
    key.sign_init()
    key.sign_update(signData)
    signature = key.sign_final()
  except Exception as e:
    syslog.syslog(syslog.LOG_ERR, "failed to sign ping {0} {2}".format(signData, e))
    return False
  
  signatureBase64 = base64.b64encode(signature)
  
  global idCounter
  idCounter += 1
  
  params={'id':uuidString, 'temp':temp, 'signatureBase64':signatureBase64}
  payload = {'id':idCounter, 'method':'ping1', 'jsonrpc':'2.0', 'params':params}
  
  try:
    jsonPayload = json.dumps(payload)
  except Exception as e:
    syslog.syslog(syslog.LOG_ERR, "failed to convert ping to json {0} {1}".format(signData, e))
    return False
  
  try:
    response = requests.post(url=serviceURL, data=jsonPayload, allow_redirects=True, timeout=10, verify=True)
    response.raise_for_status()
  except Exception as e:
    syslog.syslog(syslog.LOG_ERR, "failed to transmit ping {0} {1}, will retry".format(signData, e))
    return False
    
  try:
    responseText = response.text
  except Exception as e:
    syslog.syslog(syslog.LOG_ERR, "failed to read ping response {0} {1}, will retry".format(signData, e))
    return False
  
  try:
    jsonObject = json.loads(responseText)
  except Exception as e:
    syslog.syslog(syslog.LOG_ERR, "failed to load ping response JSON {0} {1}, will retry".format(signData, e))
    return False
  
  try:
    result = jsonObject['result']
  except Exception as e:
    syslog.syslog(syslog.LOG_ERR, "failed to read ping response JSON result {0} {1} {2}".format(signData, responseText, e))
    return False
  
  if result == 'OK':
    syslog.syslog(syslog.LOG_INFO, "transmitted ping {0} successfully".format(signData))
  else:
    syslog.syslog(syslog.LOG_ERR, "received ping failure response from server {0} for {1}".format(result, signData)) 
    return False
  
  return True

if time.time() < TIME_CHECK_TS:
  syslog.syslog(syslog.LOG_WARNING, "waiting for the system to synch the local clock...")
  while time.time() < TIME_CHECK_TS:
    time.sleep(10)
    #syslog.syslog(syslog.LOG_WARNING, "waiting for the system to synch the local clock...")
    
syslog.syslog(syslog.LOG_NOTICE, "starting for {0} with webservice url {1}".format(uuidString, serviceURL))

try:
  while True:
    while notifier.check_events():
      notifier.read_events()
      notifier.process_events()
    ping()
    processRetries()
except KeyboardInterrupt as e:
  syslog.syslog(syslog.LOG_NOTICE, "shutting down")
except Exception as e:
  syslog.syslog(syslog.LOG_ERR, "caught unexpected exception during main loop {0}".format(e))
  raise

notifier.stop();
