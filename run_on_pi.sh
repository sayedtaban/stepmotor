#!/bin/bash

# Script to run the stepper motor control application on Raspberry Pi

echo "Starting Stepper Motor Control Application..."

# Set Qt environment variables for Raspberry Pi
export QT_QPA_PLATFORM=eglfs
export QT_QPA_EGLFS_PHYSICAL_WIDTH=800
export QT_QPA_EGLFS_PHYSICAL_HEIGHT=600

# Try to run the application
echo "Attempting to run with eglfs platform..."
python3 main2.0.py

# If eglfs fails, try offscreen
if [ $? -ne 0 ]; then
    echo "eglfs failed, trying offscreen platform..."
    export QT_QPA_PLATFORM=offscreen
    python3 main2.0.py
fi

# If offscreen fails, try linuxfb
if [ $? -ne 0 ]; then
    echo "offscreen failed, trying linuxfb platform..."
    export QT_QPA_PLATFORM=linuxfb
    python3 main2.0.py
fi

# If all fail, provide instructions
if [ $? -ne 0 ]; then
    echo "All Qt platforms failed. Please try:"
    echo "1. Install Qt5: sudo apt-get install qt5-default"
    echo "2. Or run with X11 forwarding: ssh -X pi@your_pi_ip"
    echo "3. Or install a desktop environment: sudo apt-get install raspberrypi-ui-mods"
fi 