import sys
import threading
import time
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QSpinBox, QDoubleSpinBox, QPushButton, QTextEdit, QGroupBox, QMessageBox, QComboBox, QCheckBox
)
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QIcon

try:
    import RPi.GPIO as GPIO
    ON_PI = True
except ImportError:
    ON_PI = False

MOTORS = [
    {'step': 17, 'dir': 27, 'start_pos': 'A'},
    {'step': 22, 'dir': 23, 'start_pos': 'B'},
    {'step': 24, 'dir': 25, 'start_pos': 'B'}
]
STEPS_PER_REV = 200
ANGLE_TO_MOVE = 45

def move_motor(step_pin, dir_pin, speed_rpm, angle, stop_event, motor_idx, status_callback, direction=True):
    steps_needed = int(STEPS_PER_REV * angle / 360)
    if speed_rpm <= 0:
        return
    step_delay = 60.0 / (STEPS_PER_REV * speed_rpm) / 2
    if ON_PI:
        GPIO.output(dir_pin, GPIO.HIGH if direction else GPIO.LOW)
    
    for step in range(steps_needed):
        if stop_event.is_set():  # Check if STOP button pressed
            status_callback(f"Motor {motor_idx+1}: Stopped after {step}/{steps_needed} steps.")
            break
        if ON_PI:
            GPIO.output(step_pin, GPIO.HIGH)
            time.sleep(step_delay)
            GPIO.output(step_pin, GPIO.LOW)
            time.sleep(step_delay)
        else:
            # Simulation: comment out for hardware
            if step % 25 == 0:
                status_callback(f"[SIM] Motor {motor_idx+1}: step {step}/{steps_needed}")
            time.sleep(step_delay*2)
    
    # Wait 3 seconds at target position
    if not stop_event.is_set():
        status_callback(f"Motor {motor_idx+1}: Reached target position! Waiting 3 seconds...")
        time.sleep(3)

def return_motor(step_pin, dir_pin, speed_rpm, steps_to_return, motor_idx, status_callback, direction=True, return_speed_factor=0.5):
    if steps_to_return <= 0:
        status_callback(f"Motor {motor_idx+1}: Already at start position.")
        return
    
    return_speed = speed_rpm * return_speed_factor
    step_delay = 60.0 / (STEPS_PER_REV * return_speed) / 2
    if ON_PI:
        GPIO.output(dir_pin, GPIO.LOW if direction else GPIO.HIGH)  # Reverse direction
    
    status_callback(f"Motor {motor_idx+1}: Returning {steps_to_return} steps to start position...")
    
    for step in range(steps_to_return):
        if ON_PI:
            GPIO.output(step_pin, GPIO.HIGH)
            time.sleep(step_delay)
            GPIO.output(step_pin, GPIO.LOW)
            time.sleep(step_delay)
        else:
            if step % 25 == 0:
                status_callback(f"[SIM] Motor {motor_idx+1}: returning step {step}/{steps_to_return}")
            time.sleep(step_delay*2)
    
    status_callback(f"Motor {motor_idx+1}: Returned to start position.")

class MotorControlApp(QMainWindow):
    finished = pyqtSignal()
    motor_status = pyqtSignal(str)
    sequence_complete = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Stepper Motor Control - Advanced Sequence")
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

        self.stop_event = threading.Event()
        self.running_threads = []
        self.current_rep = 0
        self.total_reps = 1
        self.is_running_sequence = False
        self.steps_moved = [0, 0, 0]

    def _init_config_tab(self):
        vbox = QVBoxLayout()
        
        # Motor Configuration Group
        group = QGroupBox("Configure Each Motor")
        form = QFormLayout()

        self.speed_spins = []
        self.delay_spins = []
        self.angle_spins = []

        for i in range(3):
            hbox = QHBoxLayout()
            
            speed_spin = QSpinBox()
            speed_spin.setRange(1, 300)
            speed_spin.setValue(60 + i * 20)
            hbox.addWidget(QLabel("Speed (RPM):"))
            hbox.addWidget(speed_spin)
            hbox.addSpacing(10)
            
            delay_spin = QDoubleSpinBox()
            delay_spin.setRange(0, 2)
            delay_spin.setSingleStep(0.1)
            delay_spin.setValue(i * 0.2)
            hbox.addWidget(QLabel("Delay (s):"))
            hbox.addWidget(delay_spin)
            hbox.addSpacing(10)
            
            angle_spin = QSpinBox()
            angle_spin.setRange(15, 180)
            angle_spin.setValue(45)
            angle_spin.setSingleStep(15)
            hbox.addWidget(QLabel("Angle (°):"))
            hbox.addWidget(angle_spin)
            
            form.addRow(f"Motor {i+1} ({MOTORS[i]['start_pos']}→Target):", hbox)
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
            GPIO.setmode(GPIO.BCM)
            for m in MOTORS:
                GPIO.setup(m['step'], GPIO.OUT)
                GPIO.setup(m['dir'], GPIO.OUT)
        
        # Start the first sequence
        self.run_single_sequence()

    def run_single_sequence(self):
        """Run a single sequence of motor movements"""
        if not self.is_running_sequence:
            return
            
        self.append_status(f"🔄 Running sequence {self.current_rep + 1}/{self.total_reps}")
        
        self.stop_event.clear()
        self.steps_moved = [0, 0, 0]
        speeds = [spin.value() for spin in self.speed_spins]
        delays = [spin.value() for spin in self.delay_spins]
        angles = [spin.value() for spin in self.angle_spins]
        
        self.status_text.clear()
        self.append_status("🚦 Starting movement sequence...")

        threads = []
        for idx, m in enumerate(MOTORS):
            def run_motor(idx=idx, m=m):
                self.motor_status.emit(f"Motor {idx+1}: Will start after {delays[idx]:.1f}s delay ({speeds[idx]} RPM, {angles[idx]}°).")
                time.sleep(delays[idx])
                if self.stop_event.is_set():
                    self.motor_status.emit(f"Motor {idx+1}: Not started (stopped).")
                    return
                self.motor_status.emit(f"Motor {idx+1}: Moving to target position...")
                move_motor(m['step'], m['dir'], speeds[idx], angles[idx], self.stop_event, idx, self.motor_status.emit)
                if not self.stop_event.is_set():
                    self.motor_status.emit(f"Motor {idx+1}: Reached target and waited 3 seconds.")
                    self.steps_moved[idx] = int(STEPS_PER_REV * angles[idx] / 360)
            t = threading.Thread(target=run_motor)
            threads.append(t)
            t.start()

        self.running_threads = threads

        # Wait for all motors to complete and then return
        def wait_and_return():
            for t in threads:
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
        return_threads = []
        
        for idx, m in enumerate(MOTORS):
            if self.steps_moved[idx] > 0:
                def return_motor(idx=idx, m=m):
                    return_motor(m['step'], m['dir'], speeds[idx], self.steps_moved[idx], idx, self.motor_status.emit)
                t = threading.Thread(target=return_motor)
                return_threads.append(t)
                t.start()
        
        # Wait for all return threads to complete
        def finish_return():
            for t in return_threads:
                t.join()
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
                return_motor(MOTORS[idx]['step'], MOTORS[idx]['dir'], speeds[idx], self.steps_moved[idx], idx, self.motor_status.emit)
            
            # Wait before next motor returns
            if idx < len(MOTORS) - 1:
                time.sleep(1)
            
            # Return next motor
            return_individual(idx + 1)
        
        threading.Thread(target=return_individual, daemon=True).start()

    def stop_motors(self):
        self.append_status("🛑 Stop requested. Halting all motors...")
        self.is_running_sequence = False
        self.stop_event.set()
        # Wait for all threads to finish
        for t in getattr(self, 'running_threads', []):
            t.join(timeout=1)
        if ON_PI:
            GPIO.cleanup()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def close_application(self):
        """Close the application with proper cleanup"""
        self.is_running_sequence = False
        
        # Stop any running motors first
        if hasattr(self, 'stop_event'):
            self.stop_event.set()
        
        # Wait for threads to finish
        if hasattr(self, 'running_threads'):
            for thread in self.running_threads:
                if thread and thread.is_alive():
                    thread.join(timeout=1)
        
        # Cleanup GPIO if on Raspberry Pi
        if ON_PI:
            try:
                GPIO.cleanup()
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
    app = QApplication(sys.argv)
    window = MotorControlApp()
    window.resize(540, 340)
    # Ensure window is not fullscreen
    window.setWindowState(window.windowState() & ~Qt.WindowFullScreen)
    window.show()
    sys.exit(app.exec_())
