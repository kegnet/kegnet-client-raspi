import os
import sys
import time
import syslog
import traceback
import StringIO
import pyinotify
import base64
import uuid
import requests
from datetime import datetime
from ConfigParser import SafeConfigParser
import M2Crypto
from M2Crypto import EVP
from kegnet import w1therm

TIME_CHECK_TS = 1262304000
MAX_RETRY_INTERVAL = 3600
CONFIG_FILE = '/usr/share/kegnet-client/conf/client.conf'
PEM_FILE = '/usr/share/kegnet-client/conf/privkey.pem'
SPOOL_DIR = '/usr/share/kegnet-client/spool'

lastTemp = 0
lastTempTs = 0

lastRetry = 0
nextRetry = 0
retryCount = 0

syslog.openlog("kegnet-client", logoption=syslog.LOG_PID|syslog.LOG_CONS, facility=syslog.LOG_USER)

def log(level, message, dumpStack=True):
  syslog.syslog(level, message)
  
  if not dumpStack:
    return
  
  exctype, exception, exctraceback = sys.exc_info()
  if exception == None:
    return
  
  #excclass = str(exception.__class__)
  message = str(exception)
  
  excfd = StringIO.StringIO()
  traceback.print_exception(exctype, exception, exctraceback, None, excfd)
  for line in excfd.getvalue().split("\n"):
    syslog.syslog(level, line)

config = SafeConfigParser()
try:
  fileName = config.read(CONFIG_FILE)
  if not fileName:
    log(syslog.LOG_ERR, "failed to load '{0}': {1}".format(CONFIG_FILE, "not found"))
    sys.exit(1)
except Exception as e:
  log(syslog.LOG_ERR, "failed to load '{0}': {1}".format(CONFIG_FILE, e))
  sys.exit(1)

try:
  uuidString = config.get('KegNet', 'uuid')
except Exception as e:
  log(syslog.LOG_ERR, "required parameter '{0}' not found in '{1}'".format('uuid', CONFIG_FILE))
  sys.exit(1)

try:
  serviceBaseURL = config.get('KegNet', 'serviceBaseURL')
except Exception as e:
  log(syslog.LOG_ERR, "required parameter '{0}' not found in '{1}'".format('serviceBaseURL', CONFIG_FILE))
  sys.exit(1)
  
try:
  uuid.UUID(uuidString)
except Exception as e:
  log(syslog.LOG_ERR, "invalid uuid format '{0}' found in '{1}'".format(uuidString, CONFIG_FILE))
  sys.exit(1)

try:
  key = EVP.load_key(PEM_FILE)
except Exception as e:
  log(syslog.LOG_ERR, "failed to load private key from '{0}'".format(PEM_FILE))
  sys.exit(1)

if not os.path.isdir(SPOOL_DIR):
  os.mkdir(SPOOL_DIR)
  
def getTemp():
  global lastTemp, lastTempTs
  
  now = time.time()
  age = now - lastTempTs
  if age > 60:
    try:
      lastTempTs = now
      lastTemp = w1therm.readTemp()
    except Exception as e:
      log(syslog.LOG_ERR, "failed to read temp: {0}".format(e), False)
      return -1
  return lastTemp
  
def failPour(path):
  newPath = path + ".fail"
  os.rename(path, newPath)
  log(syslog.LOG_INFO, "renamed failed pour to '{0}'".format(newPath))

def processPour(path):
  try:
    rawDataFile = open(path, "r")
    rawData = rawDataFile.readline().rstrip()
    rawDataFile.close()
  except Exception as e:
    log(syslog.LOG_ERR, "failed to read pour file '{0}': {1}".format(path, e))
    failPour(path);
    return False
  
  data = rawData.split(',')
  if len(data) != 4:
    log(syslog.LOG_ERR, "invalid pour '{0}': {1}".format(path, data))
    failPour(path);
    return False
  
  # validate this data?    
  pin = data[0]
  pulses = data[1]
  et = data[2]
  ts = data[3]
  
  signData = "{0},{1},{2},{3},{4}".format(uuidString, pin, pulses, et, ts)
  log(syslog.LOG_DEBUG, "pour data {0}".format(signData))
  
  try:
    key.reset_context(md='sha256')
    key.sign_init()
    key.sign_update(signData)
    signature = key.sign_final()
  except Exception as e:
    log(syslog.LOG_ERR, "failed to sign pour data '{0}' for pour '{1}'".format(signData, path))
    failPour(path);
    return False
  
  signatureBase64 = base64.b64encode(signature)
  
  payload={'id':uuidString, 'pin':pin, 'pulses':pulses, 'et':et, 'ts':ts, 'sig':signatureBase64}

  pourURL = "{0}/pour".format(serviceBaseURL)

  try:
    response = requests.post(url=pourURL, data=payload, allow_redirects=True, timeout=10, verify=True)
    response.raise_for_status()
  except Exception as e:
    log(syslog.LOG_ERR, "failed to transmit pour data '{0}' for pour '{1}', will retry".format(signData, path))
    return False
    
  log(syslog.LOG_INFO, "successfully transmitted pour '{0}' to KegNet".format(path))
  
  try:
    os.remove(path)
  except Exception as e:
    log(syslog.LOG_ERR, "failed to delete pour '{0}' will retry: {1}".format(path, e))
    return False

  return True

class EventHandler(pyinotify.ProcessEvent):
  def process_IN_MOVED_TO(self, event):
    if event.pathname.endswith('.pour'):
      path = event.pathname
      try:
        log(syslog.LOG_DEBUG, "processing new pour '{0}'".format(path))
        processPour(path)
      except Exception as e:
        log(syslog.LOG_ERR, "caught unexpected exception processing pour '{0}': {1}".format(path, e))

try:
  watchManager = pyinotify.WatchManager()
  watchManager.add_watch(SPOOL_DIR, pyinotify.IN_MOVED_TO)
  eventHandler = EventHandler()
  notifier = pyinotify.Notifier(watchManager, eventHandler, timeout=60000)
except Exception as e:
  log(syslog.LOG_ERR, "failed to initialize inotify WatchManager: {0}".format(e))
  sys.exit(1)
  
def processRetries():
  log(syslog.LOG_DEBUG, "checking for pour retries...");
  
  fileList = os.listdir(SPOOL_DIR)
  if len(fileList) == 0:
    return
  
  global nextRetry, lastRetry, retryCount
  
  now = time.time()
  if (now < nextRetry):
    log(syslog.LOG_DEBUG, "too early to retry on attempt {0}: {1} < {2}".format(retryCount+1, now, nextRetry));
    return
  
  attemptCount = 0;
  successCount = 0;
  
  for fileName in fileList:
    path = "{0}/{1}".format(SPOOL_DIR, fileName)
    if fileName.endswith('.pour'):
      try:
        log(syslog.LOG_DEBUG, "processing retry pour '{0}'".format(path))
        attemptCount += 1
        success = processPour(path)
        if success:
          successCount += 1
      except Exception as e:
        log(syslog.LOG_ERR, "caught unexpected exception processing retry pour '{0}': {1}".format(path, e))
        raise
    else:
      log(syslog.LOG_WARNING, "deleting non-pour file in spool directory {0} ".format(path))
      try:
        os.remove(path)
      except Exception as e:
        log(syslog.LOG_ERR, "failed to delete non-pour '{0}': {1}".format(path, e))
  
  if attemptCount == 0:
    return
  
  failCount = (attemptCount - successCount)
  
  if failCount  == 0:
    log(syslog.LOG_WARNING, "all {0} retries transmitted successfully on attempt {1}".format(successCount, retryCount+1))
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
  
  log(syslog.LOG_WARNING, "{0} of {1} retries failed on attempt {2}, will retry again in {3} seconds".format(failCount, attemptCount, retryCount, nextInterval))

def ping():
  temp = getTemp()
  ts = int(round(time.time()))
  
  log(syslog.LOG_DEBUG, "ping temp '{0}'".format(temp))
  
  signData = "{0},{1},{2}".format(uuidString, temp, ts)
  log(syslog.LOG_DEBUG, "ping data {0}".format(signData))
  
  try:
    key.reset_context(md='sha256')
    key.sign_init()
    key.sign_update(signData)
    signature = key.sign_final()
  except Exception as e:
    log(syslog.LOG_ERR, "failed to sign ping data '{0}'".format(signData))
    return False
  
  signatureBase64 = base64.b64encode(signature)
  
  payload={'id':uuidString, 'temp':temp, 'ts':ts, 'sig':signatureBase64}

  pingURL = "{0}/ping".format(serviceBaseURL)

  try:
    response = requests.post(url=pingURL, data=payload, allow_redirects=True, timeout=10, verify=True)
    response.raise_for_status()
  except Exception as e:
    log(syslog.LOG_ERR, "failed to transmit ping data '{0}'".format(signData))
    return False
    
  log(syslog.LOG_INFO, "successfully transmitted ping temp '{0}' to KegNet".format(temp))  
  
  return True

if time.time() < TIME_CHECK_TS:
  log(syslog.LOG_WARNING, "waiting for the system to synch the local clock...")
  while time.time() < TIME_CHECK_TS:
    time.sleep(10)
    #log(syslog.LOG_WARNING, "waiting for the system to synch the local clock...")

time.sleep(10)
log(syslog.LOG_NOTICE, "starting with baseUrl '{0}' and uuid '{1}'".format(serviceBaseURL, uuidString))

try:
  while True:
    ping()
    while notifier.check_events():
      notifier.read_events()
      notifier.process_events()
    processRetries()
except KeyboardInterrupt as e:
  log(syslog.LOG_NOTICE, "shutting down")
except Exception as e:
  log(syslog.LOG_ERR, "caught unexpected exception during main loop: {0}".format(e))
  raise

notifier.stop();
