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
    # Use xcb for windowed mode instead of eglfs for fullscreen
    os.environ['QT_QPA_PLATFORM'] = 'xcb'
    # Remove fullscreen environment variables
    # os.environ['QT_QPA_EGLFS_PHYSICAL_WIDTH'] = '800'
    # os.environ['QT_QPA_EGLFS_PHYSICAL_HEIGHT'] = '600'
    # Fallback to offscreen if eglfs fails
    try:
        os.environ['DISPLAY'] = ':0'
    except:
        pass

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QSpinBox, QDoubleSpinBox, QPushButton, QTextEdit,
    QGroupBox, QMessageBox, QComboBox, QCheckBox
)
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QIcon

MOTORS = [
    {'step': 27, 'dir': 17},
    {'step': 23, 'dir': 22},
    {'step': 24, 'dir': 25}
]
STEPS_PER_REV = 400
ANGLE_TO_MOVE = 45  # 45 degrees movement

class MotorThread(threading.Thread):
    def __init__(self, step_pin, dir_pin, speed_rpm, running_event, steps_moved, idx, status_callback, direction, start_position, gpio_handle, target_angle=45):
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
        self.target_angle = target_angle
        self.steps_to_target = int(STEPS_PER_REV * target_angle / 360)

    def run(self):
        step_delay = 60.0 / (STEPS_PER_REV * self.speed_rpm) / 2
        if ON_PI:
            lgpio.gpio_write(self.gpio_handle, self.dir_pin, 1 if self.direction else 0)
        
        # Move to target position
        steps_moved_to_target = 0
        while steps_moved_to_target < self.steps_to_target and self.running_event.is_set():
            if ON_PI:
                lgpio.gpio_write(self.gpio_handle, self.step_pin, 1)
                time.sleep(step_delay)
                lgpio.gpio_write(self.gpio_handle, self.step_pin, 0)
                time.sleep(step_delay)
            else:
                time.sleep(step_delay * 2)
            steps_moved_to_target += 1
            self.steps_moved[self.idx] += 1
            
            if steps_moved_to_target % 25 == 0:
                self.status_callback(f"Motor {self.idx+1}: Moving to target position... ({steps_moved_to_target}/{self.steps_to_target})")
                print(f"Motor {self.idx+1}: Moving to target position... ({steps_moved_to_target}/{self.steps_to_target})")
        
        if steps_moved_to_target >= self.steps_to_target:
            self.status_callback(f"Motor {self.idx+1}: Reached target position! Waiting 3 seconds...")
            print(f"Motor {self.idx+1}: Reached target position! Waiting 3 seconds...")
            time.sleep(3)  # Wait 3 seconds at target position

class ReturnThread(threading.Thread):
    def __init__(self, step_pin, dir_pin, speed_rpm, steps_to_return, idx, status_callback, direction, start_position, gpio_handle, return_speed_factor=0.5):
        super().__init__()
        self.step_pin = step_pin
        self.dir_pin = dir_pin
        self.speed_rpm = speed_rpm * return_speed_factor  # Slower return speed
        self.steps_to_return = steps_to_return
        self.idx = idx
        self.status_callback = status_callback
        self.direction = not direction  # Reverse direction for return
        self.daemon = True
        self.start_position = start_position
        self.gpio_handle = gpio_handle

    def run(self):
        if self.steps_to_return == 0:
            self.status_callback(f"Motor {self.idx+1}: Already at start position.")
            print(f"Motor {self.idx+1}: Already at start position.")
            return
            
        step_delay = 60.0 / (STEPS_PER_REV * self.speed_rpm) / 2
        if ON_PI:
            lgpio.gpio_write(self.gpio_handle, self.dir_pin, 1 if self.direction else 0)
        
        self.status_callback(f"Motor {self.idx+1}: Returning {self.steps_to_return} steps to {self.start_position} position...")
        print(f"Motor {self.idx+1}: Returning {self.steps_to_return} steps to {self.start_position} position...")
        
        for step in range(self.steps_to_return):
            if ON_PI:
                lgpio.gpio_write(self.gpio_handle, self.step_pin, 1)
                time.sleep(step_delay)
                lgpio.gpio_write(self.gpio_handle, self.step_pin, 0)
                time.sleep(step_delay)
            else:
                time.sleep(step_delay * 2)
            
            if step % 25 == 0:
                self.status_callback(f"Motor {self.idx+1}: Returning... ({step}/{self.steps_to_return})")
                print(f"Motor {self.idx+1}: Returning... ({step}/{self.steps_to_return})")

        self.status_callback(f"Motor {self.idx+1}: Returned to start position.")
        print(f"Motor {self.idx+1}: Returned to start position.")

class MotorControlApp(QMainWindow):
    finished = pyqtSignal()
    motor_status = pyqtSignal(str)
    sequence_complete = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Stepper Motor Control - Advanced Sequence (lgpio)")
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
        self.sequence_complete.connect(self.on_sequence_complete)

        self.steps_moved = [0, 0, 0]
        self.running_events = [threading.Event() for _ in range(3)]
        self.threads = [None, None, None]
        self.return_threads = []
        self.start_positions = ['A', 'A', 'A']  # default
        self.gpio_handle = None
        self.current_rep = 0
        self.total_reps = 1
        self.is_running_sequence = False

    def _init_config_tab(self):
        vbox = QVBoxLayout()
        
        # Motor Configuration Group
        group = QGroupBox("Configure Each Motor")
        form = QFormLayout()
        self.speed_spins = []
        self.delay_spins = []
        self.pos_combos = []
        self.angle_spins = []
        
        for i in range(3):
            hbox = QHBoxLayout()
            
            # Start position
            pos_combo = QComboBox()
            pos_combo.addItems(['A', 'B'])
            self.pos_combos.append(pos_combo)
            pos_combo.setCurrentIndex(0)
            hbox.addWidget(QLabel("Start:"))
            hbox.addWidget(pos_combo)
            hbox.addSpacing(10)

            # Speed
            speed_spin = QSpinBox()
            speed_spin.setRange(1, 300)
            speed_spin.setValue(60 + i * 20)
            hbox.addWidget(QLabel("Speed (RPM):"))
            hbox.addWidget(speed_spin)
            hbox.addSpacing(10)

            # Delay
            delay_spin = QDoubleSpinBox()
            delay_spin.setRange(0, 2)
            delay_spin.setSingleStep(0.1)
            delay_spin.setValue(i * 0.2)
            hbox.addWidget(QLabel("Delay (s):"))
            hbox.addWidget(delay_spin)
            hbox.addSpacing(10)
            
            # Angle
            angle_spin = QSpinBox()
            angle_spin.setRange(15, 180)
            angle_spin.setValue(45)
            angle_spin.setSingleStep(15)
            hbox.addWidget(QLabel("Angle (°):"))
            hbox.addWidget(angle_spin)

            form.addRow(f"Motor {i+1} Setup:", hbox)
            self.speed_spins.append(speed_spin)
            self.delay_spins.append(delay_spin)
            self.angle_spins.append(angle_spin)
            
        group.setLayout(form)
        vbox.addWidget(group)

        # Sequence Configuration Group
        seq_group = QGroupBox("Sequence Configuration")
        seq_layout = QHBoxLayout()
        
        # Repetitions
        seq_layout.addWidget(QLabel("Number of Repetitions:"))
        self.rep_spin = QSpinBox()
        self.rep_spin.setRange(1, 50)
        self.rep_spin.setValue(1)
        seq_layout.addWidget(self.rep_spin)
        
        # Return together checkbox
        self.return_together_cb = QCheckBox("Return motors together")
        self.return_together_cb.setChecked(True)
        seq_layout.addWidget(self.return_together_cb)
        
        seq_layout.addStretch(1)
        seq_group.setLayout(seq_layout)
        vbox.addWidget(seq_group)

        # Control Buttons
        btn_hbox = QHBoxLayout()
        self.start_btn = QPushButton("▶ Start Sequence")
        self.start_btn.setStyleSheet("background-color:#37b24d; color:white; font-weight:bold;")
        self.start_btn.clicked.connect(self.start_sequence)
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
        
        # Add close button to status tab as well
        close_status_btn = QPushButton("❌ Close Application")
        close_status_btn.setStyleSheet("background-color:#868e96; color:white; font-weight:bold;")
        close_status_btn.clicked.connect(self.close_application)
        vlayout.addWidget(close_status_btn)
        
        self.status_tab.setLayout(vlayout)

    def append_status(self, message):
        self.status_text.append(message)
        self.tabs.setCurrentWidget(self.status_tab)

    def show_finished(self):
        self.append_status("✅ All sequences completed!")
        QMessageBox.information(self, "Done", "All sequences completed successfully!")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.is_running_sequence = False

    def on_sequence_complete(self):
        """Called when one sequence is complete"""
        self.current_rep += 1
        if self.current_rep < self.total_reps:
            self.append_status(f"🔄 Sequence {self.current_rep} complete. Starting sequence {self.current_rep + 1}/{self.total_reps}...")
            # Wait 2-5 seconds before next sequence
            wait_time = 2 if self.return_together_cb.isChecked() else 5
            self.append_status(f"⏳ Waiting {wait_time} seconds before next sequence...")
            threading.Timer(wait_time, self.run_single_sequence).start()
        else:
            self.append_status("🎉 All sequences completed!")
            self.finished.emit()

    def start_sequence(self):
        """Start the complete sequence with repetitions"""
        self.total_reps = self.rep_spin.value()
        self.current_rep = 0
        self.is_running_sequence = True
        
        self.append_status(f"🚀 Starting sequence with {self.total_reps} repetition(s)...")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        
        # Initialize GPIO if on Raspberry Pi
        if ON_PI:
            try:
                self.gpio_handle = lgpio.gpiochip_open(0)
                if self.gpio_handle < 0:
                    raise RuntimeError("Failed to open GPIO chip")
                
                for m in MOTORS:
                    lgpio.gpio_claim_output(self.gpio_handle, 0, m['step'], 0)
                    lgpio.gpio_claim_output(self.gpio_handle, 0, m['dir'], 0)
                
                self.append_status("✅ GPIO pins initialized successfully")
            except Exception as e:
                self.append_status(f"❌ GPIO Error: {e}")
                QMessageBox.critical(self, "GPIO Error", f"Failed to initialize GPIO: {e}")
                self.start_btn.setEnabled(True)
                self.stop_btn.setEnabled(False)
                return

        # Start the first sequence
        self.run_single_sequence()

    def run_single_sequence(self):
        """Run a single sequence of motor movements"""
        if not self.is_running_sequence:
            return
            
        self.append_status(f"🔄 Running sequence {self.current_rep + 1}/{self.total_reps}")
        
        self.start_positions = [cb.currentText() for cb in self.pos_combos]
        self.steps_moved = [0, 0, 0]
        speeds = [spin.value() for spin in self.speed_spins]
        delays = [spin.value() for spin in self.delay_spins]
        angles = [spin.value() for spin in self.angle_spins]
        
        # Clear any previous running events
        for evt in self.running_events:
            evt.clear()

        # Start motors with delays
        for idx, m in enumerate(MOTORS):
            self.running_events[idx].set()
            def run_motor(idx=idx, m=m):
                time.sleep(delays[idx])
                if not self.is_running_sequence:
                    return
                    
                self.motor_status.emit(
                    f"Motor {idx+1}: started at speed {speeds[idx]} RPM after {delays[idx]:.1f}s delay. [Start: {self.start_positions[idx]}, Angle: {angles[idx]}°]"
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
                    gpio_handle=self.gpio_handle,
                    target_angle=angles[idx]
                )
                self.threads[idx] = thread
                thread.start()
                
            threading.Thread(target=run_motor).start()

        # Wait for all motors to reach target and complete 3-second wait
        def wait_and_return():
            # Wait for all motors to complete their movement
            for t in self.threads:
                if t and t.is_alive():
                    t.join()
            
            if not self.is_running_sequence:
                return
                
            self.append_status("⏳ All motors reached target. Starting return sequence...")
            
            if self.return_together_cb.isChecked():
                # Return all motors together
                self.return_all_motors_together(speeds)
            else:
                # Return motors individually
                self.return_motors_individually(speeds)
        
        threading.Thread(target=wait_and_return, daemon=True).start()

    def return_all_motors_together(self, speeds):
        """Return all motors to start position together"""
        self.return_threads = []
        
        for idx, m in enumerate(MOTORS):
            if self.steps_moved[idx] > 0:
                rt = ReturnThread(
                    step_pin=m['step'],
                    dir_pin=m['dir'],
                    speed_rpm=speeds[idx],
                    steps_to_return=self.steps_moved[idx],
                    idx=idx,
                    status_callback=self.motor_status.emit,
                    direction=True if self.start_positions[idx] == 'A' else False,
                    start_position=self.start_positions[idx],
                    gpio_handle=self.gpio_handle,
                    return_speed_factor=0.5
                )
                self.return_threads.append(rt)
                rt.start()

        # Wait for all return threads to complete
        def finish_return():
            for rt in self.return_threads:
                if rt and rt.is_alive():
                    rt.join()
            if self.is_running_sequence:
                self.sequence_complete.emit()
        
        threading.Thread(target=finish_return, daemon=True).start()

    def return_motors_individually(self, speeds):
        """Return motors to start position one by one"""
        def return_individual(idx=0):
            if idx >= len(MOTORS) or not self.is_running_sequence:
                self.sequence_complete.emit()
                return
                
            if self.steps_moved[idx] > 0:
                rt = ReturnThread(
                    step_pin=MOTORS[idx]['step'],
                    dir_pin=MOTORS[idx]['dir'],
                    speed_rpm=speeds[idx],
                    steps_to_return=self.steps_moved[idx],
                    idx=idx,
                    status_callback=self.motor_status.emit,
                    direction=True if self.start_positions[idx] == 'A' else False,
                    start_position=self.start_positions[idx],
                    gpio_handle=self.gpio_handle,
                    return_speed_factor=0.5
                )
                rt.start()
                rt.join()
            
            # Wait before next motor returns
            if idx < len(MOTORS) - 1:
                time.sleep(1)
            
            # Return next motor
            return_individual(idx + 1)
        
        threading.Thread(target=return_individual, daemon=True).start()

    def stop_motors(self):
        """Stop all motors and reset sequence"""
        self.append_status("🛑 Stop requested. Halting all motors...")
        self.is_running_sequence = False
        
        # Stop all running events
        for evt in self.running_events:
            evt.clear()
        
        # Wait for threads to finish
        for t in self.threads:
            if t and t.is_alive():
                t.join(timeout=2)
        
        for rt in self.return_threads:
            if rt and rt.is_alive():
                rt.join(timeout=2)
        
        # Cleanup GPIO
        if ON_PI and self.gpio_handle:
            try:
                lgpio.gpiochip_close(self.gpio_handle)
            except:
                pass
        
        self.append_status("🛑 All motors stopped.")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def close_application(self):
        """Close the application with proper cleanup"""
        self.is_running_sequence = False
        
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
                lgpio.gpiochip_close(self.gpio_handle)
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
        # Use windowed mode platforms instead of fullscreen
        platforms_to_try = ['xcb', 'x11', 'offscreen']
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
        # Ensure window is not fullscreen
        window.setWindowState(window.windowState() & ~Qt.WindowFullScreen)
        window.show()
        sys.exit(app.exec_())
    except Exception as e:
        print(f"Error starting application: {e}")
        if ON_PI:
            print("If running on Raspberry Pi, try:")
            print("1. Install: sudo apt-get install qt5-default")
            print("2. Or run with: export QT_QPA_PLATFORM=xcb")
        sys.exit(1)
