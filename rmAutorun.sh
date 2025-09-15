#!/bin/bash
SERVICE_PATH="/etc/systemd/system/f007th.service"

echo "Stopping f007th service..."
sudo systemctl stop f007th.service

echo "Disabling f007th service..."
sudo systemctl disable f007th.service

echo "Removing f007th service file..."
sudo rm -f "$SERVICE_PATH"

echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

echo "Removing gpio_ts from /etc/modules..."
sudo sed -i '/^gpio_ts$/d' /etc/modules

echo "Removing gpio-ts modprobe options..."
sudo rm -f /etc/modprobe.d/gpio_ts.conf

echo "Unloading gpio_ts module (if loaded)..."
if lsmod | grep -q '^gpio_ts'; then
    sudo rmmod gpio_ts
    echo "gpio_ts module unloaded."
else
    echo "gpio_ts module not loaded."
fi

echo "Service removed."
