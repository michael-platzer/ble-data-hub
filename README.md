# ble-data-hub
Bluetooth LE Data Hub

## Configure Raspberry Pi:

Refer to: https://die-antwort.eu/techblog/2017-12-setup-raspberry-pi-for-kiosk-mode/

Change password:

    $ passwd

Configure keyboard layout and allow SSH access with:

    # raspi-config

The `raspi-config` utility also allows to disable overscan (under `Advanced Options`), which is required of the output image does not fill the entire screen.

Install required packages:

    # sudo apt-get update
    # sudo apt-get upgrade
    # sudo apt-get install --no-install-recommends xserver-xorg x11-xserver-utils xinit openbox
    # sudo apt-get install --no-install-recommends chromium-browser

Configure openbox by editing `/etc/xdg/openbox/autostart`:

    # Disable any form of screen saver / screen blanking / power management
    xset s off
    xset s noblank
    xset -dpms

    # Allow quitting the X server with CTRL-ATL-Backspace
    setxkbmap -option terminate:ctrl_alt_bksp

    # Start Chromium in kiosk mode
    sed -i 's/"exited_cleanly":false/"exited_cleanly":true/' ~/.config/chromium/'Local State'
    sed -i 's/"exited_cleanly":false/"exited_cleanly":true/; s/"exit_type":"[^"]\+"/"exit_type":"Normal"/' ~/.config/chromium/Default/Preferences
    chromium-browser --disable-infobars --kiosk 'http://your-url-here'

Note: we assure Chromium that it exited cleanly last time (see https://superuser.com/a/1206120).

Test the setup with following command:

    $ startx -- -nocursor

If everything works as expected, run `raspi-config` once more to configure autologin for the user `pi`.
To start the X server automatically on boot, append the following line to `~/.bash_profile`:

    [[ -z $DISPLAY && $XDG_VTNR -eq 1 ]] && startx -- -nocursor

To install bluetooth and GLIB:

    sudo apt-get install libbluetooth-dev libglib2.0-dev

Reference: https://people.csail.mit.edu/albert/bluez-intro/c404.html
