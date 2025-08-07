import sys
import threading
import time
import os

# Detect if running on Raspberry Pi
try:
    import lgpio
    ON_PI = True
except ImportError:
    ON_PI = False

# Set Qt environment variables for Raspberry Pi
if ON_PI:
    os.environ['QT_QPA_PLATFORM'] = 'eglfs'  # Use EGLFS for Raspberry Pi
    os.environ['QT_QPA_EGLFS_PHYSICAL_WIDTH'] = '800'
    os.environ['QT_QPA_EGLFS_PHYSICAL_HEIGHT'] = '600'
    # Fallback to offscreen if eglfs fails
    try:
        os.environ['DISPLAY'] = ':0'
    except:
        pass

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QSpinBox, QDoubleSpinBox, QPushButton, QTextEdit,
    QGroupBox, QMessageBox, QComboBox
)
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QIcon

MOTORS = [
    {'step': 17, 'dir': 27},
    {'step': 22, 'dir': 23},
    {'step': 24, 'dir': 25}
]
STEPS_PER_REV = 4

class MotorThread(threading.Thread):
    def __init__(self, step_pin, dir_pin, speed_rpm, running_event, steps_moved, idx, status_callback, direction, start_position, gpio_handle):
        super().__init__()
        self.step_pin = step_pin
        self.dir_pin = dir_pin
        self.speed_rpm = speed_rpm
        self.running_event = running_event
        self.steps_moved = steps_moved
        self.idx = idx
        self.status_callback = status_callback
        self.direction = direction
        self.daemon = True
        self.start_position = start_position
        self.gpio_handle = gpio_handle

    def run(self):
        step_delay = 60.0 / (STEPS_PER_REV * self.speed_rpm) / 2
        if ON_PI:
            lgpio.gpio_write(self.gpio_handle, self.dir_pin, 1 if self.direction else 0)
        while self.running_event.is_set():
            if ON_PI:
                lgpio.gpio_write(self.gpio_handle, self.step_pin, 1)
                time.sleep(step_delay)
                lgpio.gpio_write(self.gpio_handle, self.step_pin, 0)
                time.sleep(step_delay)
            else:
                time.sleep(step_delay * 2)
            self.steps_moved[self.idx] += 1
            if self.steps_moved[self.idx] % 25 == 0:
                self.direction = False if self.direction == True else True
                if ON_PI:
                    lgpio.gpio_write(self.gpio_handle, self.dir_pin, 1 if self.direction else 0)
            if self.steps_moved[self.idx] % 50 == 0:
                self.status_callback(f"Motor {self.idx+1} moved: {self.start_position}")
                print(f"Motor {self.idx+1} moved: {self.start_position}")
            elif self.steps_moved[self.idx] % 25 == 0:
                self.status_callback(f"Motor {self.idx+1} moved: C")
                print(f"Motor {self.idx+1} moved: C")

class ReturnThread(threading.Thread):
    def __init__(self, step_pin, dir_pin, speed_rpm, steps_to_return, idx, status_callback, direction, start_position, gpio_handle):
        super().__init__()
        self.step_pin = step_pin
        self.dir_pin = dir_pin
        self.speed_rpm = speed_rpm
        self.steps_to_return = steps_to_return
        self.idx = idx
        self.status_callback = status_callback
        self.direction = direction
        self.daemon = True
        self.start_position = start_position
        self.gpio_handle = gpio_handle

    def run(self):
        step_delay = 60.0 / (STEPS_PER_REV * self.speed_rpm) / 2
        if ON_PI:
            lgpio.gpio_write(self.gpio_handle, self.dir_pin, 1 if self.direction else 0)
        s = self.steps_to_return
        while True:
            if ON_PI:
                lgpio.gpio_write(self.gpio_handle, self.step_pin, 1)
                time.sleep(step_delay)
                lgpio.gpio_write(self.gpio_handle, self.step_pin, 0)
                time.sleep(step_delay)
            else:
                time.sleep(step_delay * 2)
            s += 1
            if s % 25 == 0:
                self.direction = False if self.direction == True else True
                if ON_PI:
                    lgpio.gpio_write(self.gpio_handle, self.dir_pin, 1 if self.direction else 0)

            if s % 50 == 0:
                self.status_callback(f"Motor {self.idx+1} moved: {self.start_position}")
                print(f"Motor {self.idx+1} moved: {self.start_position}")
                break
            elif s % 25 == 0:
                self.status_callback(f"Motor {self.idx+1} moved: C")
                print(f"Motor {self.idx+1} moved: C")

        self.status_callback(f"Motor {self.idx+1} returned to start position.")
        print(f"Motor {self.idx+1} returned to start position.")

class MotorControlApp(QMainWindow):
    finished = pyqtSignal()
    motor_status = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Stepper Motor Control - Start A or B & Return (lgpio)")
        self.setStyleSheet("QLabel{font-size:13pt;} QPushButton{font-size:12pt; min-width:120px;}")

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.config_tab = QWidget()
        self.status_tab = QWidget()
        self.tabs.addTab(self.config_tab, "Motor Control")
        self.tabs.addTab(self.status_tab, "Status Log")

        self._init_config_tab()
        self._init_status_tab()
        self.finished.connect(self.show_finished)
        self.motor_status.connect(self.append_status)

        self.steps_moved = [0, 0, 0]
        self.running_events = [threading.Event() for _ in range(3)]
        self.threads = [None, None, None]
        self.return_threads = []
        self.start_positions = ['A', 'A', 'A']  # default
        self.gpio_handle = None

    def _init_config_tab(self):
        vbox = QVBoxLayout()
        group = QGroupBox("Configure Each Motor")
        form = QFormLayout()
        self.speed_spins = []
        self.delay_spins = []
        self.pos_combos = []
        for i in range(3):
            hbox = QHBoxLayout()
            pos_combo = QComboBox()
            pos_combo.addItems(['A', 'B'])
            self.pos_combos.append(pos_combo)
            pos_combo.setCurrentIndex(0)
            hbox.addWidget(QLabel("Start:"))
            hbox.addWidget(pos_combo)
            hbox.addSpacing(10)

            speed_spin = QSpinBox()
            speed_spin.setRange(1, 300)
            speed_spin.setValue(60 + i * 20)
            hbox.addWidget(QLabel("Speed (RPM):"))
            hbox.addWidget(speed_spin)

            delay_spin = QDoubleSpinBox()
            delay_spin.setRange(0, 1)
            delay_spin.setSingleStep(0.05)
            delay_spin.setValue(i * 0.2)
            hbox.addWidget(QLabel("Delay (s):"))
            hbox.addWidget(delay_spin)

            form.addRow(f"Motor {i+1} Setup:", hbox)
            self.speed_spins.append(speed_spin)
            self.delay_spins.append(delay_spin)
        group.setLayout(form)
        vbox.addWidget(group)

        btn_hbox = QHBoxLayout()
        self.start_btn = QPushButton("▶ Start Motors")
        self.start_btn.setStyleSheet("background-color:#37b24d; color:white; font-weight:bold;")
        self.start_btn.clicked.connect(self.start_motors)
        btn_hbox.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("🛑 Stop")
        self.stop_btn.setStyleSheet("background-color:#fa5252; color:white; font-weight:bold;")
        self.stop_btn.clicked.connect(self.stop_motors)
        self.stop_btn.setEnabled(False)
        btn_hbox.addWidget(self.stop_btn)
        
        self.close_btn = QPushButton("❌ Close")
        self.close_btn.setStyleSheet("background-color:#868e96; color:white; font-weight:bold;")
        self.close_btn.clicked.connect(self.close_application)
        btn_hbox.addWidget(self.close_btn)
        
        vbox.addLayout(btn_hbox)
        vbox.addStretch(1)
        self.config_tab.setLayout(vbox)

    def _init_status_tab(self):
        vlayout = QVBoxLayout()
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        vlayout.addWidget(QLabel("Live Status:"))
        vlayout.addWidget(self.status_text)
        self.stop_btn = QPushButton("🛑 Stop + Return")
        self.stop_btn.setStyleSheet("background-color:#fa5252; color:white; font-weight:bold;")
        self.stop_btn.clicked.connect(self.stop_motors)
        self.stop_btn.setEnabled(False)
        vlayout.addWidget(self.stop_btn)
        
        self.status_tab.setLayout(vlayout)

    def append_status(self, message):
        self.status_text.append(message)
        self.tabs.setCurrentWidget(self.status_tab)

    def show_finished(self):
        self.append_status("✅ All motors returned to their start positions.")
        QMessageBox.information(self, "Done", "All motors returned to their start positions.")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def start_motors(self):
        self.start_positions = [cb.currentText() for cb in self.pos_combos]
        self.append_status(
            "🚦 Starting motors... Start positions: " +
            ", ".join([f"Motor {i+1}: {pos}" for i, pos in enumerate(self.start_positions)])
        )
        self.steps_moved = [0, 0, 0]
        speeds = [spin.value() for spin in self.speed_spins]
        delays = [spin.value() for spin in self.delay_spins]
        
        if ON_PI:
            try:
                # Initialize lgpio
                self.gpio_handle = lgpio.gpiochip_open(0)
                if self.gpio_handle < 0:
                    raise RuntimeError("Failed to open GPIO chip")
                
                # Setup GPIO pins
                for m in MOTORS:
                    # Configure step pin as output
                    lgpio.gpio_claim_output(self.gpio_handle, 0, m['step'], 0)
                    # Configure dir pin as output
                    lgpio.gpio_claim_output(self.gpio_handle, 0, m['dir'], 0)
                
                self.append_status("✅ GPIO pins initialized successfully with lgpio")
            except Exception as e:
                self.append_status(f"❌ GPIO Error: {e}")
                self.append_status("💡 Try running with sudo or check if GPIO pins are in use")
                QMessageBox.critical(self, "GPIO Error", 
                                   f"Failed to initialize GPIO: {e}\n\n"
                                   "Try running with sudo or check if GPIO pins are already in use.")
                return

        for evt in self.running_events:
            evt.clear()
        self.return_threads = []

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        for idx, m in enumerate(MOTORS):
            self.running_events[idx].set()
            def run_motor(idx=idx, m=m):
                time.sleep(delays[idx])
                self.motor_status.emit(
                    f"Motor {idx+1}: started at speed {speeds[idx]} RPM after {delays[idx]:.2f}s delay. [Start: {self.start_positions[idx]}]"
                )
                thread = MotorThread(
                    step_pin=m['step'],
                    dir_pin=m['dir'],
                    speed_rpm=speeds[idx],
                    running_event=self.running_events[idx],
                    steps_moved=self.steps_moved,
                    idx=idx,
                    status_callback=self.motor_status.emit,
                    direction=True if self.start_positions[idx] == 'A' else False,
                    start_position=self.start_positions[idx],
                    gpio_handle=self.gpio_handle
                )
                self.threads[idx] = thread
                thread.start()
            threading.Thread(target=run_motor).start()

    def stop_motors(self):
        self.append_status("🛑 Stop pressed: halting and returning all motors to start position...")
        self.stop_btn.setEnabled(False)

        for evt in self.running_events:
            evt.clear()
        for t in self.threads:
            if t is not None:
                t.join(timeout=2)

        speeds = [spin.value() for spin in self.speed_spins]
        for idx, m in enumerate(MOTORS):
            steps_back = self.steps_moved[idx]
            if steps_back == 0:
                self.motor_status.emit(f"Motor {idx+1} already at {self.start_positions[idx]} position.")
                continue
            self.motor_status.emit(
                f"Motor {idx+1} returning {steps_back} steps to {self.start_positions[idx]} position."
            )
            rt = ReturnThread(
                step_pin=m['step'],
                dir_pin=m['dir'],
                speed_rpm=speeds[idx],
                steps_to_return=steps_back,
                idx=idx,
                status_callback=self.motor_status.emit,
                direction=True if self.start_positions[idx] == 'A' else False,
                start_position=self.start_positions[idx],
                gpio_handle=self.gpio_handle
            )
            self.return_threads.append(rt)
            rt.start()

        def finish_notice():
            for rt in self.return_threads:
                rt.join()
            if ON_PI and self.gpio_handle is not None:
                lgpio.gpiochip_close(self.gpio_handle)
            self.finished.emit()
        threading.Thread(target=finish_notice, daemon=True).start()

    def close_application(self):
        """Close the application with proper cleanup"""
        # Stop any running motors first
        if hasattr(self, 'running_events'):
            for event in self.running_events:
                event.clear()
        
        # Wait for threads to finish
        if hasattr(self, 'threads'):
            for thread in self.threads:
                if thread and thread.is_alive():
                    thread.join(timeout=1)
        
        if hasattr(self, 'return_threads'):
            for thread in self.return_threads:
                if thread and thread.is_alive():
                    thread.join(timeout=1)
        
        # Cleanup GPIO if on Raspberry Pi
        if ON_PI and self.gpio_handle:
            try:
                lgpio.gpio_close(self.gpio_handle)
            except:
                pass
        
        # Close the application
        self.close()
        QApplication.quit()

    def closeEvent(self, event):
        """Handle window close event"""
        self.close_application()
        event.accept()

if __name__ == "__main__":
    # Try different Qt platforms for Raspberry Pi
    if ON_PI:
        platforms_to_try = ['eglfs', 'offscreen', 'linuxfb']
        for platform in platforms_to_try:
            try:
                os.environ['QT_QPA_PLATFORM'] = platform
                app = QApplication(sys.argv)
                break
            except Exception as e:
                print(f"Failed to initialize with platform '{platform}': {e}")
                continue
        else:
            print("Failed to initialize Qt with any platform. Trying default...")
            app = QApplication(sys.argv)
    else:
        app = QApplication(sys.argv)
    
    try:
        window = MotorControlApp()
        window.resize(600, 380)
        window.show()
        sys.exit(app.exec_())
    except Exception as e:
        print(f"Error starting application: {e}")
        if ON_PI:
            print("If running on Raspberry Pi, try:")
            print("1. Install: sudo apt-get install qt5-default")
            print("2. Or run with: export QT_QPA_PLATFORM=offscreen")
        sys.exit(1)
