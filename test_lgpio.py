#!/usr/bin/env python3
"""
lgpio Test Script for Raspberry Pi
This script tests lgpio access and helps diagnose permission issues.
"""

import os
import sys

def check_lgpio_permissions():
    """Check if we have permission to access GPIO"""
    print("🔍 Checking lgpio permissions...")
    
    # Check if running as root
    if os.geteuid() == 0:
        print("✅ Running as root (good for GPIO access)")
    else:
        print("⚠️  Not running as root (may cause GPIO issues)")
        print("💡 Try running with: sudo python3 test_lgpio.py")
    
    # Check if lgpio module is available
    try:
        with open('/proc/modules', 'r') as f:
            modules = f.read()
            if 'gpiochip' in modules or 'bcm2835' in modules:
                print("✅ GPIO modules are loaded")
            else:
                print("⚠️  GPIO modules not found")
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

def test_lgpio_import():
    """Test if lgpio can be imported"""
    print("\n🔍 Testing lgpio import...")
    try:
        import lgpio
        print("✅ lgpio imported successfully")
        return lgpio
    except ImportError as e:
        print(f"❌ Failed to import lgpio: {e}")
        print("💡 Install with: sudo apt-get install python3-lgpio")
        return None
    except Exception as e:
        print(f"❌ Unexpected error importing lgpio: {e}")
        return None

def test_lgpio_setup(lgpio_module):
    """Test lgpio setup"""
    if not lgpio_module:
        return False
    
    print("\n🔍 Testing lgpio setup...")
    try:
        # Open GPIO chip
        handle = lgpio_module.gpiochip_open(0)
        if handle < 0:
            print("❌ Failed to open GPIO chip")
            return False
        print("✅ GPIO chip opened successfully")
        
        # Test pins
        test_pins = [17, 22, 24, 27, 23, 25]
        failed_pins = []
        
        for pin in test_pins:
            try:
                # Claim pin as output
                result = lgpio_module.gpio_claim_output(handle, 0, pin, 0)
                if result == 0:
                    print(f"✅ GPIO pin {pin} setup successful")
                else:
                    print(f"❌ GPIO pin {pin} setup failed (error code: {result})")
                    failed_pins.append(pin)
            except Exception as e:
                print(f"❌ GPIO pin {pin} setup failed: {e}")
                failed_pins.append(pin)
        
        # Clean up
        lgpio_module.gpiochip_close(handle)
        print("✅ GPIO chip closed successfully")
        
        # Return success only if all pins worked
        if failed_pins:
            print(f"❌ Failed to setup pins: {failed_pins}")
            return False
        else:
            return True
        
    except Exception as e:
        print(f"❌ Unexpected error during lgpio setup: {e}")
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
    print("🚀 lgpio Test Script for Raspberry Pi")
    print("=" * 50)
    
    check_system_info()
    check_lgpio_permissions()
    lgpio_module = test_lgpio_import()
    success = test_lgpio_setup(lgpio_module)
    
    print("\n" + "=" * 50)
    if success:
        print("✅ All lgpio tests passed!")
        print("💡 Your lgpio setup should work with the main application")
    else:
        print("❌ lgpio tests failed!")
        print("💡 The lgpio library requires proper permissions and hardware access.")
        print("")
        print("🔧 Solutions to try:")
        print("   1. Run with sudo: sudo python3 test_lgpio.py")
        print("   2. Install lgpio: sudo apt-get install python3-lgpio")
        print("   3. Check if GPIO pins are in use: ls /sys/class/gpio/")
        print("   4. Unload conflicting modules: sudo modprobe -r spi_bcm2835")
        print("   5. Reboot the Raspberry Pi: sudo reboot")
        print("")
        print("💡 For the main application, run with:")
        print("   sudo python3 main2.3.py")
        print("   or")
        print("   sudo ./run_with_sudo.sh")

if __name__ == "__main__":
    main() 