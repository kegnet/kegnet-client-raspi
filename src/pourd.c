#include <stdio.h>
#include <stdlib.h>
#include <glib.h>
#include <string.h>
#include <errno.h>
#include <stdlib.h>
#include <wiringPi.h>
#include <unistd.h>
#include <syslog.h>
#include <sys/stat.h>

#define TIME_CHECK_TS 1262304000

#define CONFIG_DIR "/usr/share/kegnet-client/conf"
#define LOG_DIR "/usr/share/kegnet-client/spool"
#define GROUP_NAME "pourd"

#define DEFAULT_POUR_DELAY_MS 1000
#define DEFAULT_MIN_POUR_PULSES 200

#define LED_PIN 2

typedef struct
{
  int pour_delay_ms;
  int min_pour_pulses;
} Configuration;

static volatile int globalCount = 0;

void pulse()
{
  globalCount++;
}

int main(int argc, const char* argv[])
{
  openlog("pourd", LOG_PID|LOG_CONS, LOG_USER);

  int pin = -1;

  if (argc == 2) {
    pin = atoi(argv[1]);
  }

  if (pin == -1 || argc != 2) {
    syslog(LOG_ERR, "usage: pourd <wiringPi pin number (3-6)>\n");
    printf("usage: pourd <wiringPi pin number (3-6)>\n");
    exit(EXIT_FAILURE);
  }

  char pinStr[3];
  sprintf(pinStr, "%d", pin);

  GError *error = NULL;

  char configFileName[1024];
  sprintf(configFileName, "%s/pourd%s.conf", CONFIG_DIR, pinStr);

  GKeyFile *keyfile;
  keyfile = g_key_file_new();
  if (! g_key_file_load_from_file(keyfile, configFileName, G_KEY_FILE_NONE, &error))
  {
    syslog(LOG_ERR, "pin%s failed to load %s %s", pinStr, configFileName, error->message);
    exit(EXIT_FAILURE);
  }

  if (! g_key_file_has_group(keyfile, GROUP_NAME))
  {
    syslog(LOG_ERR, "pin%s no group '%s' in %s", pinStr, GROUP_NAME, configFileName);
    exit(EXIT_FAILURE);
  }

  Configuration *conf;
  conf = g_slice_new(Configuration);

  conf->pour_delay_ms = g_key_file_get_integer(keyfile, GROUP_NAME, "pour_delay_ms", &error);
  if (error != NULL)
  {
    syslog(LOG_WARNING, "pin%s failure parsing '%s' from %s %s", pinStr, "pour_delay_ms", configFileName, error->message);
  }

  if (conf->pour_delay_ms == 0)
    conf->pour_delay_ms = DEFAULT_POUR_DELAY_MS;

  conf->min_pour_pulses = g_key_file_get_integer(keyfile, GROUP_NAME, "min_pour_pulses", &error);
  if (error != NULL)
  {
    syslog(LOG_WARNING, "pin%s failure parsing '%s' from %s %s", pinStr, "min_pour_pulses", configFileName, error->message);
  }

  if (conf->min_pour_pulses == 0)
    conf->min_pour_pulses = DEFAULT_MIN_POUR_PULSES;

  g_key_file_free(keyfile);

  time_t now;
  time(&now);

  if (now < TIME_CHECK_TS)
  {
    syslog(LOG_WARNING, "pin%s waiting for the system to synch the local clock...", pinStr);
    time(&now);
    while (now < TIME_CHECK_TS)
    {
      sleep(10);
      time(&now);
//      syslog(LOG_WARNING, "waiting for the system to synch the local clock...");
    }
  }

  syslog(LOG_NOTICE, "pin%s starting for with pour_delay_ms %d, min_pour_pulses %d", pinStr, conf->pour_delay_ms, conf->min_pour_pulses);

  if (wiringPiSetup() != 0)
  {
    syslog(LOG_ERR, "pin%s wiringPi setup failed %s", pinStr, strerror(errno));
    exit(EXIT_FAILURE);
  }

  if (wiringPiISR(pin, INT_EDGE_RISING, &pulse) != 0)
  {
    syslog(LOG_ERR, "pin%s failed setup ISR %s", pinStr, strerror(errno));
    exit(EXIT_FAILURE);
  }
  
  for (;;)
  {
    int pulseCount = 0;
    int delayCount = 0;

    while (globalCount == 0) {
      delay(200);
    }

    pulseCount = globalCount;

    time_t st;
    time(&st);
    
    int pollCount = 0;

//    pinMode(LED_PIN, INPUT);
    
    int priorLEDState = digitalRead(LED_PIN);
    syslog(LOG_DEBUG, "LED%s current state is %s", LED_PIN, (priorLEDState > 0 ? "ON" : "OFF"));

    while (globalCount > pulseCount || (delayCount * 50) < conf->pour_delay_ms)
    {
      if (globalCount == pulseCount)
        delayCount++;
      else
        delayCount = 0;

      pulseCount = globalCount;
      syslog(LOG_DEBUG, "pin%s pouring... pulses=%d delay=%d", pinStr, pulseCount, delayCount);
      
      digitalWrite(LED_PIN, (pollCount % 2 ? HIGH : LOW));
      pollCount++;
      
      delay(50);
    }

    syslog(LOG_DEBUG, "LED%s restoring state to %s", LED_PIN, priorLEDState > 0 ? "ON" : "OFF");
    digitalWrite(LED_PIN, priorLEDState);

    globalCount = 0;

    time_t ft;
    time(&ft);

    int et = (ft - st);

    if (pulseCount < conf->min_pour_pulses) {
      syslog(LOG_DEBUG, "pin%s NON POUR: %d pulses in %d seconds", pinStr, pulseCount, et);
      continue;
    }

    syslog(LOG_INFO, "pin%s POUR: %d pulses in %d seconds", pinStr, pulseCount, et);

    char tempFileName[1024];
    sprintf(tempFileName, "%s/%s%d.tmp", LOG_DIR, pinStr, st);

    syslog(LOG_DEBUG, "pin%s logging pour to %s", pinStr, tempFileName);

    FILE *tempFile;
    tempFile = fopen(tempFileName, "w");
    if (tempFile == NULL)
    {
      syslog(LOG_ERR, "pin%s failed to open %s %s", pinStr, tempFileName, strerror(errno));
      continue;
    }

    int printCount = -1;
    printCount = fprintf(tempFile, "%d,%d,%d,%d", pin, pulseCount, et, st);
    if (printCount <= 0)
    {
      syslog(LOG_ERR, "pin%s failed to write %s %s", pinStr, tempFileName, strerror(errno));
      continue;
    }

    fclose(tempFile);

    char logFileName[1024];
    sprintf(logFileName, "%s/%s%d.pour", LOG_DIR, pinStr, st);

    int renameResult = 0;
    renameResult = rename(tempFileName, logFileName);
    if (renameResult == 0)
    {
      syslog(LOG_DEBUG, "pin%s renamed pour to %s", pinStr, logFileName);
    }
    else
    {
      syslog(LOG_ERR, "pin%s failed to rename %s to %s %s", pinStr, tempFileName, logFileName, strerror(errno));
      continue;
    }
  }

  exit(EXIT_SUCCESS);
}

