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

echo "Service removed."

