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
      <textarea rows="15" cols="72" wrap="hard" disabled="disabled">
<?php $ok = connect(); ?>
      </textarea>
      <br/>
      <br/>
      <div class="instructions">
<?php if ($ok) { ?>
        Wifi Setup Success!<br/>
        <br/>
        <span class="large">Step 1.</span>Disconnect the power and ethernet network cable from your 
        KegNet device, and then reconnect the power cable only.<br/>
        <br/>
        <span class="large">Step 2.</span >In 2-3 minutes, the green "CON" indicator 
        light should illuminate indicating a successfull connection to the 
        KegNet servers over Wifi.<br/>
        <br/>
        <div class="center">
          <img alt="diagram" src="case_front_1.png" width="250" style="margin-left:auto;">
        </div>
<?php } else { ?>
        Wifi Configuration Failed!<br/>
        <br/>
        Click BACK try again.  For addition help, please save and submit the 
        above output to KegNet support.
<?php } ?>
      </div>
      <br/>
    </div>
  </body>
</html>
      
      
<?php
function connect() 
{
  echo "Setting up wifi...\n\n";
  
  $address = htmlspecialchars($_POST["address"]);
  if (empty($address)) {
    echo "Error: missing 'address' field.";
    return false;
  }
  
  echo "Address: $address\n";
  
  $sid = htmlspecialchars($_POST[$address . "_sid"]);
  if (empty($sid)) {
    echo "Error: missing '$address_sid' field.";
    return false;
  }
  
  echo "SSID: $sid\n";
  
  $type = htmlspecialchars($_POST[$address . "_type"]);
  if (empty($type)) {
    echo "Error: missing '$address_type' field.";
    return false;
  }
  
  echo "Type: $type\n";
  
  $password = htmlspecialchars($_POST["password"]);
  if (empty($password) && $type != 'open') {
    echo "Error: missing 'password' field.";
    return false;
  }
  
  echo "Using Password: " . (empty($password) ? "No" : "Yes") . "\n\n";
  
  $cmd = "sudo /usr/share/kegnet-client/scripts/wificonfig '$type' '$sid'";
  if ($type != 'open') {
    $cmd = $cmd . " '$password'";
  }
  
  $lines = null;
  $ret = -1;
  
  exec($cmd, $lines, $ret);
  
  foreach($lines as $line) {
    echo "$line\n";
  }
  
  echo "\n";
  
  echo "Return Code: $ret\n\n";
  
  if ($ret == 0) {
    echo "Success!\n";
    return true;
  } else {
    echo "Failure!\n\n";
    echo "POST Data:\n\n";
    echo var_dump($_POST);
    return false;
  }

}
?>
