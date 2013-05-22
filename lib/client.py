import os
import sys
import time
import syslog
import traceback
import StringIO
import pyinotify
import xively
from datetime import datetime
from ConfigParser import SafeConfigParser
from kegnet import w1therm

TEMP_DATASTREAM = "temp"
POUR_PULSES_DATASTREAM = "pour-pulses"
POUR_TIME_DATASTREAM = "pour-time"

TIME_CHECK_TS = 1262304000
CONFIG_FILE = '/usr/share/kegnet-client/conf/client.conf'
SPOOL_DIR = '/usr/share/kegnet-client/spool'
MAX_RETRY_INTERVAL = 3600

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
  
  excclass = str(exception.__class__)
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
  apiKey = config.get('xively', 'apiKey')
except Exception as e:
  syslog.syslog(syslog.LOG_ERR, "required parameter '{0}' not found in '{1}'".format('apiKey', CONFIG_FILE))
  sys.exit(1)

try:
  feedId = config.get('xively', 'feedId')
except Exception as e:
  log(syslog.LOG_ERR, "required parameter '{0}' not found in '{1}'".format('feedId', CONFIG_FILE))
  sys.exit(1)

if not os.path.isdir(SPOOL_DIR):
  os.mkdir(SPOOL_DIR)

try:
  api = xively.XivelyAPIClient(apiKey)
except Exception as e:
  log(syslog.LOG_ERR, "failed to create Xively client with apiKey '{0}': {1}".format(apiKey, e))
  sys.exit(1)

try:
  feed = api.feeds.get(feedId)
except Exception as e:
  log(syslog.LOG_ERR, "failed get Xively feed '{0}' with apiKey '{1}': {2}".format(feedId, apiKey, e))
  sys.exit(1)
  
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

def getDatastream(feed, name):
  global feedId, apiKey
  
  try:
    datastream = feed.datastreams.get(name)
    return datastream
  except:
    log(syslog.LOG_INFO, "creating new Xively dataStream '{0}'".format(name), False)
    
  try:
    datastream = feed.datastreams.create(name, tags=name)
  except:
    log(syslog.LOG_INFO, "failed to create new Xively dataStream '{0}' for feedId '{1}' and apiKey '{2}': {3}".format(name, feedId, apiKey, e))
    
  return datastream
  
def updateDataStream(name, ts, value):
  global feed;

  try:
    dataStream = getDatastream(feed, name)
  except:
    log(syslog.LOG_INFO, "failed to get Xively dataStream '{0}': {1}".format(name, e))
    return False
  
  dataStream.max_value = None
  dataStream.min_value = None
  dataStream.current_value = value
  dataStream.at = ts
  
  try:
    dataStream.update()
  except Exception as e:
    log(syslog.LOG_ERR, "failed to update Xively dataStream '{0}': {1}".format(name, e))
    return False
  
  log(syslog.LOG_DEBUG, "updated Xively dataStream '{0}' with value {1}".format(name, value))
  
  return True
  
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
    log(syslog.LOG_ERR, "invalid pour file '{0}': {1}".format(path, data))
    failPour(path);
    return False
  
  # validate this data?    
  pin = int(data[0])
  pulses = int(data[1])
  et = float(data[2])
  ts = datetime.utcfromtimestamp(float(data[3]))
  
  pulsesUpdated = updateDataStream("{0}-{1}".format(POUR_PULSES_DATASTREAM, pin), ts, pulses)
  if not pulsesUpdated:
    log(syslog.LOG_ERR, "failed to update Xively with pour '{0}', will retry".format(path))
    return False
  
  etUpdated = updateDataStream("{0}-{1}".format(POUR_TIME_DATASTREAM, pin), ts, et)
  if not etUpdated:
    log(syslog.LOG_ERR, "failed to update Xively with pour '{0}', will retry".format(path))
    return False
    
  log(syslog.LOG_INFO, "successfully transmitted pour '{0}' to Xively".format(path))
  
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
  
  log(syslog.LOG_DEBUG, "ping temp '{0}'".format(temp))

  updated = updateDataStream(TEMP_DATASTREAM, datetime.utcnow(), temp)
  if not updated:
    log(syslog.LOG_ERR, "failed to update Xively with temp '{0}'".format(temp))
    return False
  
  log(syslog.LOG_INFO, "successfully transmitted temp '{0}' to Xively".format(temp))
  
  return True

if time.time() < TIME_CHECK_TS:
  log(syslog.LOG_WARNING, "waiting for the system to synch the local clock...")
  while time.time() < TIME_CHECK_TS:
    time.sleep(10)
    #log(syslog.LOG_WARNING, "waiting for the system to synch the local clock...")

time.sleep(10)
log(syslog.LOG_NOTICE, "starting with feedId '{0}' apiKey '{1}'".format(feedId, apiKey))

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
