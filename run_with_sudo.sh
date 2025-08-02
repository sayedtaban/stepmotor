#!/bin/bash

# Script to run the stepper motor control application with sudo
# This is needed for GPIO access on Raspberry Pi

echo "🚀 Starting Stepper Motor Control with lgpio..."
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "✅ Already running as root"
else
    echo "🔧 Elevating to root for GPIO access..."
fi

# Set Qt environment variables for Raspberry Pi
export QT_QPA_PLATFORM=eglfs
export QT_QPA_EGLFS_PHYSICAL_WIDTH=800
export QT_QPA_EGLFS_PHYSICAL_HEIGHT=600

# Run the application with sudo
echo "🎯 Starting application..."
sudo -E python3 main2.3.py

# Check exit code
if [ $? -eq 0 ]; then
    echo "✅ Application completed successfully"
else
    echo "❌ Application exited with errors"
    echo ""
    echo "💡 If you still have issues:"
    echo "   1. Test lgpio: sudo python3 test_lgpio.py"
    echo "   2. Check GPIO pins: ls /sys/class/gpio/"
    echo "   3. Install lgpio: sudo apt-get install python3-lgpio"
    echo "   4. Reboot: sudo reboot"
fi 