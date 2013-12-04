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
import requests.exceptions
from datetime import datetime
from ConfigParser import SafeConfigParser
import M2Crypto
from M2Crypto import EVP
from subprocess import call
from kegnet import w1therm

TIME_CHECK_TS = 1262304000
MAX_RETRY_INTERVAL = 3600
CONFIG_FILE = '/usr/share/kegnet-client/conf/client.conf'
PEM_FILE = '/usr/share/kegnet-client/conf/privkey.pem'
SPOOL_DIR = '/usr/share/kegnet-client/spool'
CA_BUNDLE = '/usr/share/kegnet-client/conf/ca.crt'

lastTemp = 0
lastTempTs = 0

lastRetry = 0
nextRetry = 0
retryCount = 0

syslog.openlog("kegnet-client", logoption=syslog.LOG_PID|syslog.LOG_CONS, facility=syslog.LOG_USER)

call(["gpio", "mode", "2", "output"])

def log(level, message, dumpStack=True):
  syslog.syslog(level, message)
  
  exctype, exception, exctraceback = sys.exc_info()
  if exception == None:
    return
  
  #excclass = str(exception.__class__)
  cause = str(exception)
  syslog.syslog(level, cause)
  
  if not dumpStack:
    return
    
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

def setLED(status):
  code = "off"
  if (status):
    code = "on"
  call(["gpio", "write", "2", code])
  
def post(url, payload):
  tryCount = 1;
  
  while True:
    try:
      return requests.post(url=url, data=payload, allow_redirects=True, timeout=10, verify=CA_BUNDLE)
    except requests.exceptions.ConnectionError as e:
      log(syslog.LOG_INFO, "post to {0} failed on try {1}: ConnectionError".format(url, tryCount), False)
      time.sleep(10)
    except requests.exceptions.Timeout as e:
      log(syslog.LOG_INFO, "post to {0} failed on try {1}: Timeout".format(url, tryCount), False)
    except Exception as e:
      raise
    
    tryCount = tryCount + 1
    if (tryCount > 3):
      raise
  
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
    response = post(pourURL, payload)
  except Exception as e:
    log(syslog.LOG_ERR, "failed to transmit pour '{0}', will retry".format(path), False)
    return False
  
  remove = True
  
  if 200 <= response.status_code < 300:
    log(syslog.LOG_INFO, "KegNet accepted pour '{0}'".format(path))
  elif 500 <= response.status_code < 600:
    log(syslog.LOG_INFO, "KegNet refused pour '{0}': {1}".format(path, response))
    remove = False
  else:
    log(syslog.LOG_INFO, "KegNet failed pour '{0}': {1}".format(path, response))
  
  if remove:
    try:
      log(syslog.LOG_INFO, "deleting pour '{0}'".format(path))
      os.remove(path)
    except Exception as e:
      log(syslog.LOG_ERR, "failed to delete pour '{0}' will retry: {1}".format(path, e))
      return False

  if 200 <= response.status_code < 300:
    return True
  else:
    return False

class EventHandler(pyinotify.ProcessEvent):
  def process_IN_MOVED_TO(self, event):
    if event.pathname.endswith('.pour'):
      path = event.pathname
      try:
        log(syslog.LOG_DEBUG, "processing new pour '{0}'".format(path))
        setLED(processPour(path))
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
    response = post(pingURL, payload)
  except Exception as e:
    log(syslog.LOG_ERR, "failed to transmit ping '{0}'".format(signData), False)
    return False
  
  if 200 <= response.status_code < 300:
    log(syslog.LOG_INFO, "KegNet accepted ping '{0}'".format(signData))
    return True
  elif 500 <= response.status_code < 600:
    log(syslog.LOG_INFO, "KegNet refused ping '{0}': {1}".format(signData, response))
    return True
  else:
    log(syslog.LOG_INFO, "KegNet failed ping '{0}': {1}".format(signData, response))
    return False

if time.time() < TIME_CHECK_TS:
  log(syslog.LOG_WARNING, "waiting for the system to synch the local clock...")
  while time.time() < TIME_CHECK_TS:
    time.sleep(10)
    #log(syslog.LOG_WARNING, "waiting for the system to synch the local clock...")

time.sleep(10)
log(syslog.LOG_NOTICE, "starting with baseUrl '{0}' and uuid '{1}'".format(serviceBaseURL, uuidString))

try:
  while True:
    setLED(ping())
    while notifier.check_events():
      notifier.read_events()
      notifier.process_events()
    processRetries()
except KeyboardInterrupt as e:
  log(syslog.LOG_NOTICE, "shutting down")
  setLED(False)
except Exception as e:
  log(syslog.LOG_ERR, "caught unexpected exception during main loop: {0}".format(e))
  setLED(False)
  raise

setLED(False)
notifier.stop();
