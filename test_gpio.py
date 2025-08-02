#!/usr/bin/env python3
"""
GPIO Test Script for Raspberry Pi
This script tests GPIO access and helps diagnose permission issues.
"""

import os
import sys

def check_gpio_permissions():
    """Check if we have permission to access GPIO"""
    print("🔍 Checking GPIO permissions...")
    
    # Check if running as root
    if os.geteuid() == 0:
        print("✅ Running as root (good for GPIO access)")
    else:
        print("⚠️  Not running as root (may cause GPIO issues)")
        print("💡 Try running with: sudo python3 test_gpio.py")
    
    # Check if GPIO module is loaded
    try:
        with open('/proc/modules', 'r') as f:
            modules = f.read()
            if 'bcm2835' in modules:
                print("✅ BCM2835 GPIO module is loaded")
            else:
                print("⚠️  BCM2835 GPIO module not found")
    except:
        print("❌ Cannot read /proc/modules")
    
    # Check GPIO sysfs
    gpio_path = '/sys/class/gpio'
    if os.path.exists(gpio_path):
        print("✅ GPIO sysfs exists")
        try:
            os.listdir(gpio_path)
            print("✅ Can read GPIO sysfs")
        except PermissionError:
            print("❌ Permission denied accessing GPIO sysfs")
    else:
        print("❌ GPIO sysfs not found")

def test_gpio_import():
    """Test if RPi.GPIO can be imported"""
    print("\n🔍 Testing RPi.GPIO import...")
    try:
        import RPi.GPIO as GPIO
        print("✅ RPi.GPIO imported successfully")
        return GPIO
    except ImportError as e:
        print(f"❌ Failed to import RPi.GPIO: {e}")
        print("💡 Install with: sudo apt-get install python3-rpi.gpio")
        return None
    except Exception as e:
        print(f"❌ Unexpected error importing RPi.GPIO: {e}")
        return None

def test_gpio_setup(gpio):
    """Test GPIO setup"""
    if not gpio:
        return False
    
    print("\n🔍 Testing GPIO setup...")
    try:
        # Clean up any existing setup
        gpio.cleanup()
        
        # Set mode
        gpio.setmode(gpio.BCM)
        print("✅ GPIO mode set to BCM")
        
        # Set warnings to False
        gpio.setwarnings(False)
        print("✅ GPIO warnings disabled")
        
        # Test pins
        test_pins = [17, 22, 24, 27, 23, 25]
        for pin in test_pins:
            try:
                gpio.setup(pin, gpio.OUT)
                gpio.output(pin, gpio.LOW)
                print(f"✅ GPIO pin {pin} setup successful")
            except Exception as e:
                print(f"❌ GPIO pin {pin} setup failed: {e}")
        
        # Clean up
        gpio.cleanup()
        print("✅ GPIO cleanup successful")
        return True
        
    except RuntimeError as e:
        print(f"❌ RuntimeError during GPIO setup: {e}")
        print("💡 This usually means insufficient permissions or hardware access issues")
        return False
    except Exception as e:
        print(f"❌ Unexpected error during GPIO setup: {e}")
        return False

def check_system_info():
    """Check system information"""
    print("\n🔍 System Information:")
    
    # Check if we're on Raspberry Pi
    try:
        with open('/proc/cpuinfo', 'r') as f:
            cpuinfo = f.read()
            if 'Raspberry Pi' in cpuinfo:
                print("✅ Running on Raspberry Pi")
            else:
                print("⚠️  Not running on Raspberry Pi")
    except:
        print("❌ Cannot read CPU info")
    
    # Check kernel version
    try:
        with open('/proc/version', 'r') as f:
            version = f.read().strip()
            print(f"📋 Kernel: {version}")
    except:
        print("❌ Cannot read kernel version")

def main():
    print("🚀 GPIO Test Script for Raspberry Pi")
    print("=" * 50)
    
    check_system_info()
    check_gpio_permissions()
    gpio = test_gpio_import()
    success = test_gpio_setup(gpio)
    
    print("\n" + "=" * 50)
    if success:
        print("✅ All GPIO tests passed!")
        print("💡 Your GPIO setup should work with the main application")
    else:
        print("❌ GPIO tests failed!")
        print("💡 Try the following solutions:")
        print("   1. Run with sudo: sudo python3 test_gpio.py")
        print("   2. Install GPIO library: sudo apt-get install python3-rpi.gpio")
        print("   3. Check if GPIO pins are in use: ls /sys/class/gpio/")
        print("   4. Unload conflicting modules: sudo modprobe -r spi_bcm2835")

if __name__ == "__main__":
    main() 