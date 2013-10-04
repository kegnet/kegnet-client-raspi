<html>
  <head>
    <title>KegNet Client Configuration</title>
    <meta charset="UTF-8">
    <link type="text/css" rel="stylesheet" href="style.css"/>
    <script type="text/javascript" src="wifi.js"></script>
  </head>
  <body>
    <div class="container">
      <div class="title">KegNet Client WiFi Configuration</div>
      <hr/>
      <br/>
<?php
  $checkResult = checkWifi();
  $hasWifi = $checkResult[0];
  if (! $hasWifi) { ?>
    No attached WiFi hardware detected!<br/>
<?php } else { 
  $scanResult = scanWifi();
  $scanOk = $scanResult[0];
  $hasResults = $scanResult[1];
  if (! $scanOk) { ?>
    WiFi network scanning failed!<br/>
<?php } else if (! $hasResults) { ?>
    No WiFi networks found in range!<br/>
<?php } 
  if (! $hasResults) { ?>
    <br/>
    Diagnostic report:<br/>
    <textarea rows="10" cols="70" wrap="hard">
iwconfig results:
<?php echo var_dump($checkResult) ?>
iwlist results:
<?php echo var_dump($scanResult) ?>
    </textarea>
<?php } else {
    $networks = $scanResult[3]; 
    usort($networks, "cmp"); ?>
    <form name="form" id="form" method="post" action="connect.php">
      <?php echo sizeof($networks); ?> WiFi networks found in range!<br/>
      <br/>
      <table>
        <tr>
          <th>&nbsp;</th>
          <th>Name</th>
          <th>Signal Strength</th>
          <th>Type</th>
          <th>Password</th>
        </tr>
    <?php foreach ($networks as $network) { ?>
        <tr>
          <td>
            <input type="radio" id="address" name="address" value="<?php echo urlencode($network['address']) ?>" onclick="javascript:showPassword();"/>
            <input type="hidden" id="<?php echo urlencode($network['address']) ?>_sid" name="<?php echo urlencode($network['address']) ?>_sid" value="<?php echo htmlspecialchars($network['essid']) ?>"/>
            <input type="hidden" id="<?php echo urlencode($network['address']) ?>_type" name="<?php echo urlencode($network['address']) ?>_type" value="<?php echo $network['type'] ?>"/>
          </td>
          <td><?php echo htmlspecialchars($network['essid']) ?></td>
          <td><?php echo $network['strength'] ?>%</td>
          <td><?php echo $network['type'] ?></td>
          <td><?php echo $network['key'] ?></td>
        </tr>
    <?php } ?>
      </table>
      <br/>
      Select your network and click Connect.  You will be prompted to enter the password if required.<br/>
      <br/>
      <div class="buttonBar">
        <div class="buttons">
          <span id="passwordBox" class="passwordBox" style="visibility:hidden;">
            Password: <input type="password" id="password" name="password" size="20"/>
          </span>
          <input type="submit" value="Connect" onclick="javascript:return checkPassword();"/>
        </div>
      </div>
    </form>
  <?php } ?>
<?php } ?>
  </div>
  <pre>
<?php echo var_dump($scanResult) ?>
  </pre>
  </body>
</html>
<?php
  function checkWifi()
  {
    $lines = null;
    $ret = -1;
    exec('sudo iwconfig wlan0', $lines, $ret);
    if ($ret != 0) {
      return array(false, $ret, $lines);
    } else {
      return array(true, $ret, $lines);
    }
  }

  function scanWifi()
  {
    $lines = null;
    $ret = -1;

    exec('sudo iwlist wlan0 scan', $lines, $ret);
    if ($ret != 0) {
      return array(false, false, $ret, $lines);
    }

    $hasResults = false;
    $results = array();
    $current = null;
    $currentIE = null;

    foreach ($lines as $raw) {
      $line = trim($raw);

      if (strlen($line) == 0)
        continue;

      $matches = null;

      if (preg_match('/Scan completed/', $line, $matches)) {
        $hasResults = true;
      }
      else if (preg_match('/No scan results/', $line, $matches)) {
        $hasResults = false;
      }
      else if (preg_match('/Cell (.*) - Address: (.*)/', $line, $matches)) {
        if ($currentIE != null) {
          array_push($current['ie'], $currentIE);
          $currentIE = null;
        }
          
        if ($current != null) {
          array_push($results, $current);
        }
  
        $current = array();
        $current['ie'] = array();
        $current['index'] = $matches[1];
        $current['address'] = $matches[2];
      }
      else if (preg_match('/ESSID:"(.*)"/', $line, $matches)) {
        $current['essid'] = $matches[1];
      }
      else if (preg_match('/Protocol:(.*)/', $line, $matches)) {
        $current['protocol'] = $matches[1];
      }
      else if (preg_match('/Mode:(.*)/', $line, $matches)) {
        $current['mode'] = $matches[1];
      }
      else if (preg_match('/Frequency:(.*)/', $line, $matches)) {
        $current['frequency'] = $matches[1];
      }
      else if (preg_match('/Encryption key:(.*)/', $line, $matches)) {
        $current['key'] = $matches[1];
        
        if ($current['key'] == 'off') {
          $current['type'] = 'open';
        } else {
          $current['type'] = 'wep';
        }
      }
      else if (preg_match('/Bit Rates:(.*)/', $line, $matches)) {
        $current['bitrates'] = $matches[1];
      }
      else if (preg_match('/Extra:(.*)/', $line, $matches)) {
        if (! array_key_exists('extra', $current)) {
          $current['extra'] = array();
        }
        array_push($current['extra'], $matches[1]);
      }
      else if (preg_match('/IE: (.*)/', $line, $matches)) {
        if ($currentIE != null) {
          array_push($current['ie'], $currentIE);
        }
        
        $current['type'] = 'wpa';
        
        $currentIE = array();
        $currentIE['type'] = $matches[1];
      }
      else if (preg_match('/Group Cipher.*: (.*)/', $line, $matches)) {
        $currentIE['group_ciphers'] = $matches[1];
      }
      else if (preg_match('/Pairwise Ciphers.*: (.*)/', $line, $matches)) {
        $currentIE['pairwise_ciphers'] = $matches[1];
      }
      else if (preg_match('/Authentication Suites.*: (.*)/', $line, $matches)) {
        $currentIE['authentication_suites'] = $matches[1];
      }
      else if (preg_match('/Quality=(.*)\/100.*Signal level=(.*)\/100/', $line, $matches)) {
        $current['quality'] = trim($matches[1]);
        $current['signal'] = trim($matches[2]);
        $current['strength'] = round(($current['signal'] + $current['quality']) / 2);
      }
      else if (preg_match('/Quality:(.*)  Signal level:(.*)  Noise level:(.*)/', $line, $matches)) {
        $current['quality'] = trim($matches[1]);
        $current['signal'] = trim($matches[2]);
        $current['noise'] = trim($matches[3]);
        $current['strength'] = $current['quality'];
      } else {
        echo "no match: $line\n";
      }
    }

    if ($currentIE != null) {
      array_push($current['ie'], $currentIE);
    }

    if ($current != null) {
      array_push($results, $current);
    }
    
    return array(true, $hasResults, $ret, $results);
  }

  function cmp($a, $b)
  {
    $rankA = $a['strength'];
    $rankB = $b['strength'];

    if ($rankA > $rankB)
      return -1;
    else
      return 1;
  }
?>
