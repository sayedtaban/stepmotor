#!/bin/bash

# Script to run the stepper motor control application on Raspberry Pi

echo "Starting Stepper Motor Control Application..."

# Check if running as root (needed for GPIO access)
if [ "$EUID" -ne 0 ]; then
    echo "⚠️  Warning: Not running as root. GPIO access may fail."
    echo "💡 If you get GPIO errors, try running with: sudo ./run_on_pi.sh"
    echo ""
fi

# Check if GPIO pins are available
echo "🔍 Checking GPIO pin availability..."
for pin in 17 22 24 27 23 25; do
    if [ -d "/sys/class/gpio/gpio$pin" ]; then
        echo "⚠️  Warning: GPIO pin $pin is already exported"
    fi
done

# Set Qt environment variables for Raspberry Pi
export QT_QPA_PLATFORM=eglfs
export QT_QPA_EGLFS_PHYSICAL_WIDTH=800
export QT_QPA_EGLFS_PHYSICAL_HEIGHT=600

# Try to run the application
echo "Attempting to run with eglfs platform..."
python3 main2.1.py

# If eglfs fails, try offscreen
if [ $? -ne 0 ]; then
    echo "eglfs failed, trying offscreen platform..."
    export QT_QPA_PLATFORM=offscreen
    python3 main2.1.py
fi

# If offscreen fails, try linuxfb
if [ $? -ne 0 ]; then
    echo "offscreen failed, trying linuxfb platform..."
    export QT_QPA_PLATFORM=linuxfb
    python3 main2.1.py
fi

# If all fail, provide instructions
if [ $? -ne 0 ]; then
    echo "All Qt platforms failed. Please try:"
    echo "1. Install Qt5: sudo apt-get install qt5-default"
    echo "2. Or run with X11 forwarding: ssh -X pi@your_pi_ip"
    echo "3. Or install a desktop environment: sudo apt-get install raspberrypi-ui-mods"
    echo ""
    echo "For GPIO issues:"
    echo "1. Run with sudo: sudo ./run_on_pi.sh"
    echo "2. Check if GPIO pins are in use: ls /sys/class/gpio/"
    echo "3. Unload conflicting modules: sudo modprobe -r spi_bcm2835"
fi 