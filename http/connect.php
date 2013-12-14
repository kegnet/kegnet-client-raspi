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
      <textarea wrap="hard" disabled="disabled" style="width:90%; height:120px;">
<?php $ok = connect(); ?>
      </textarea>
      <br/>
      <br/>
      <div class="instructions">
<?php if ($ok) { ?>
        Wifi Configuration OK!<br/>
        <br/>
        <span class="large">Click Next below to continue</span>
<?php } else { ?>
        Wifi Configuration Failed!<br/>
        <br/>
        <span class="large">Click BACK try again.</span><br/>
        <br/>
        For addition help, please save and submit the 
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
