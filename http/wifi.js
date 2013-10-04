function showPassword() {
  var address = getSelectedAddress();
  var type = document.getElementById(address + '_type').value;
  
  var passwordBox = document.getElementById('passwordBox');
  var passwordInput = document.getElementById('password');
  
  if (type !== "open") {
    passwordBox.style.visibility = "visible"
  } else {
    passwordBox.style.visibility = "hidden"
    passwordInput.value = "";
  }
}

function checkPassword() {
  var address = getSelectedAddress();
  if (address == null) {
    alert("Error: Select the network");
    return false;
  }
  
  var password = document.getElementById('password').value;
  var type = document.getElementById(address + '_type').value;
  var sid = document.getElementById(address + '_sid').value;
  
  if (type !== "open" && (password == null || password == "")) {
    alert("Error: Password is required for " + sid);
    return false;
  }
  
  return true;
}

function getSelectedAddress() {
  var addresses = document.getElementsByName('address');
  for (i=0; i < addresses.length; i++) {
    if (addresses[i].checked) {
      return addresses[i].value;
    }
  }
  
  return null;
}
