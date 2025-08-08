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
from PyQt5.QtCore import pyqtSignal, Qt, QTimer, QMetaObject, Q_ARG
from PyQt5.QtGui import QIcon, QTextCursor

# Note: qRegisterMetaType is not available in PyQt5, we'll handle QTextCursor issues differently

MOTORS = [
    {'step': 27, 'dir': 17},
    {'step': 23, 'dir': 22},
    {'step': 24, 'dir': 25}
]
STEPS_PER_REV = 400

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
        
        if steps_moved_to_target >= self.steps_to_target:
            self.status_callback(f"Motor {self.idx+1}: Reached target position! Waiting 3 seconds...")
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
            return
            
        step_delay = 60.0 / (STEPS_PER_REV * self.speed_rpm) / 2
        if ON_PI:
            lgpio.gpio_write(self.gpio_handle, self.dir_pin, 1 if self.direction else 0)
        
        self.status_callback(f"Motor {self.idx+1}: Returning {self.steps_to_return} steps to {self.start_position} position...")
        
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

        self.status_callback(f"Motor {self.idx+1}: Returned to start position.")

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
        self.gpio_initialized = False
        self.current_rep = 0
        self.total_reps = 1
        self.is_running_sequence = False
        
        # Ensure button states are properly initialized
        self.reset_button_states()

    def init_gpio_once(self) -> bool:
        """Initialize GPIO only once for the app session."""
        if not ON_PI:
            return True
        if self.gpio_initialized and self.gpio_handle is not None:
            return True
        try:
            self.append_status("🔧 Initializing GPIO (one-time)...")
            self.gpio_handle = lgpio.gpiochip_open(0)
            if self.gpio_handle < 0:
                raise RuntimeError(f"Failed to open GPIO chip. Error code: {self.gpio_handle}")

            # Claim all pins once
            for i, m in enumerate(MOTORS):
                result = lgpio.gpio_claim_output(self.gpio_handle, 0, m['step'], 0)
                if result < 0:
                    raise RuntimeError(f"Failed to claim step pin {m['step']} for motor {i+1}. Error: {result}")
                result = lgpio.gpio_claim_output(self.gpio_handle, 0, m['dir'], 0)
                if result < 0:
                    raise RuntimeError(f"Failed to claim dir pin {m['dir']} for motor {i+1}. Error: {result}")
            self.gpio_initialized = True
            self.append_status("✅ GPIO initialized and pins claimed (will persist until app exit)")
            return True
        except Exception as e:
            error_msg = str(e)
            self.append_status(f"❌ GPIO Error: {error_msg}")
            QMessageBox.critical(self, "GPIO Error", 
                                 f"Failed to initialize GPIO: {error_msg}\n\n"
                                 "Try closing other apps using GPIO or run with sudo.")
            self.reset_button_states()
            return False

    def emit_motor_status_safe(self, message):
        """Thread-safe method to emit motor_status signal"""
        try:
            QTimer.singleShot(0, lambda: self._emit_motor_status_safe(message))
        except Exception as e:
            # Fallback: try direct emission
            try:
                self.motor_status.emit(message)
            except:
                pass  # Ignore errors to prevent crashes

    def _emit_motor_status_safe(self, message):
        """Internal method to safely emit motor_status signal"""
        try:
            self.motor_status.emit(message)
        except Exception as e:
            # If signal emission fails, try to append directly
            try:
                self.append_status(message)
            except:
                pass

    def emit_sequence_complete_safe(self):
        """Thread-safe method to emit sequence_complete signal"""
        try:
            QTimer.singleShot(0, lambda: self.sequence_complete.emit())
        except Exception as e:
            try:
                self.sequence_complete.emit()
            except:
                pass

    def emit_finished_safe(self):
        """Thread-safe method to emit finished signal"""
        try:
            QTimer.singleShot(0, lambda: self.finished.emit())
        except Exception as e:
            try:
                self.finished.emit()
            except:
                pass

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
        
        # GPIO Diagnostics button (only show on Raspberry Pi)
        if ON_PI:
            self.gpio_diag_btn = QPushButton("🔧 GPIO Check")
            self.gpio_diag_btn.setStyleSheet("background-color:#ffd43b; color:black; font-weight:bold;")
            self.gpio_diag_btn.clicked.connect(self.show_gpio_diagnostics)
            btn_hbox.addWidget(self.gpio_diag_btn)
        
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
        
        # Add debug and control buttons to status tab
        btn_layout = QHBoxLayout()
        
        # Debug button to check button states
        debug_btn = QPushButton("🔍 Debug Button States")
        debug_btn.setStyleSheet("background-color:#17a2b8; color:white; font-weight:bold;")
        debug_btn.clicked.connect(self.debug_button_states)
        btn_layout.addWidget(debug_btn)
        
        # Reset button states
        reset_btn = QPushButton("🔄 Reset Buttons")
        reset_btn.setStyleSheet("background-color:#6f42c1; color:white; font-weight:bold;")
        reset_btn.clicked.connect(self.reset_button_states)
        btn_layout.addWidget(reset_btn)
        
        # Add close button to status tab as well
        close_status_btn = QPushButton("❌ Close Application")
        close_status_btn.setStyleSheet("background-color:#868e96; color:white; font-weight:bold;")
        close_status_btn.clicked.connect(self.close_application)
        btn_layout.addWidget(close_status_btn)
        
        vlayout.addLayout(btn_layout)
        self.status_tab.setLayout(vlayout)

    def debug_button_states(self):
        """Debug method to check current button states"""
        start_enabled = self.start_btn.isEnabled()
        stop_enabled = self.stop_btn.isEnabled()
        running = self.is_running_sequence
        
        debug_info = f"""
🔍 Button State Debug:
• Start Button Enabled: {start_enabled}
• Stop Button Enabled: {stop_enabled}
• Sequence Running: {running}
• Current Repetition: {self.current_rep + 1}
• Total Repetitions: {self.total_reps}
• ON_PI: {ON_PI}
• GPIO Handle: {hasattr(self, 'gpio_handle') and self.gpio_handle is not None}
• Threads Active: {sum(1 for t in self.threads if t and t.is_alive())}
• Return Threads Active: {sum(1 for rt in self.return_threads if rt and rt.is_alive())}
"""
        
        self.append_status(debug_info)
        QMessageBox.information(self, "Button States", debug_info)

    def append_status(self, message):
        """Thread-safe method to append status messages"""
        try:
            # Use QTimer to ensure this runs on the main thread
            QTimer.singleShot(0, lambda: self._append_status_safe(message))
        except Exception as e:
            # Fallback to direct append if timer fails
            try:
                self.status_text.append(message)
            except:
                pass  # Ignore any errors to prevent crashes

    def _append_status_safe(self, message):
        """Internal method to safely append status (called from main thread)"""
        try:
            self.status_text.append(message)
        except Exception as e:
            # If there's still an issue, try to clear and re-append
            try:
                self.status_text.clear()
                self.status_text.append(message)
            except:
                pass  # Final fallback - ignore errors

    def show_finished(self):
        self.append_status("✅ All sequences completed!")
        QMessageBox.information(self, "Done", "All sequences completed successfully!")
        self.reset_button_states()  # Use reset_button_states instead of manual setting

    def on_sequence_complete(self):
        """Called when one sequence is complete"""
        self.current_rep += 1
        if self.current_rep < self.total_reps:
            self.append_status(f"🔄 Sequence {self.current_rep} complete. Starting sequence {self.current_rep + 1}/{self.total_reps}...")
            # Wait 2-5 seconds before next sequence
            wait_time = 2 if self.return_together_cb.isChecked() else 5
            self.append_status(f"⏳ Waiting {wait_time} seconds before next sequence...")
            # Use QTimer to start next sequence
            QTimer.singleShot(wait_time * 1000, self.run_single_sequence)
        else:
            self.append_status("🎉 All sequences completed!")
            # Use QTimer to emit finished signal from main thread
            QTimer.singleShot(0, self.emit_finished_safe)

    def reset_button_states(self):
        """Reset button states to initial state"""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.is_running_sequence = False

    def start_sequence(self):
        """Start the complete sequence with repetitions"""
        self.total_reps = self.rep_spin.value()
        self.current_rep = 0
        self.is_running_sequence = True
        
        self.append_status(f"🚀 Starting sequence with {self.total_reps} repetition(s)...")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        
        # Initialize GPIO only once
        if not self.init_gpio_once():
            return
        if not ON_PI:
            # Not on Raspberry Pi - simulate mode
            self.append_status("🖥️ Running in simulation mode (not on Raspberry Pi)")
        
        # Start the first sequence
        self.run_single_sequence()

    def run_single_sequence(self):
        """Run a single sequence of motor movements"""
        if not self.is_running_sequence:
            self.append_status("⚠️ Sequence stopped or not running")
            return
            
        self.append_status(f"🔄 Running sequence {self.current_rep + 1}/{self.total_reps}")
        
        self.start_positions = [cb.currentText() for cb in self.pos_combos]
        self.steps_moved = [0, 0, 0]
        # Reset thread references for a clean run
        self.threads = [None, None, None]
        self.return_threads = []
        speeds = [spin.value() for spin in self.speed_spins]
        delays = [spin.value() for spin in self.delay_spins]
        angles = [spin.value()/2 for spin in self.angle_spins]
        
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
                    
                self.emit_motor_status_safe(
                    f"Motor {idx+1}: started at speed {speeds[idx]} RPM after {delays[idx]:.1f}s delay. [Start: {self.start_positions[idx]}, Angle: {angles[idx]}°]"
                )
                
                thread = MotorThread(
                    step_pin=m['step'],
                    dir_pin=m['dir'],
                    speed_rpm=speeds[idx],
                    running_event=self.running_events[idx],
                    steps_moved=self.steps_moved,
                    idx=idx,
                    status_callback=self.emit_motor_status_safe,
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
                self.append_status("⚠️ Sequence stopped during motor movement")
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
                    status_callback=self.emit_motor_status_safe,
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
                self.append_status(f"✅ Return sequence {self.current_rep + 1} complete")
                self.emit_sequence_complete_safe()
            else:
                self.append_status("⚠️ Sequence stopped during return")
        
        threading.Thread(target=finish_return, daemon=True).start()

    def return_motors_individually(self, speeds):
        """Return motors to start position one by one"""
        def return_individual(idx=0):
            if idx >= len(MOTORS) or not self.is_running_sequence:
                if self.is_running_sequence:
                    self.append_status(f"✅ Return sequence {self.current_rep + 1} complete")
                    self.emit_sequence_complete_safe()
                else:
                    self.append_status("⚠️ Sequence stopped during return")
                return
                
            if self.steps_moved[idx] > 0:
                rt = ReturnThread(
                    step_pin=MOTORS[idx]['step'],
                    dir_pin=MOTORS[idx]['dir'],
                    speed_rpm=speeds[idx],
                    steps_to_return=self.steps_moved[idx],
                    idx=idx,
                    status_callback=self.emit_motor_status_safe,
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
        if ON_PI and hasattr(self, 'gpio_handle') and self.gpio_handle is not None:
            try:
                # Free all GPIO pins
                for m in MOTORS:
                    try:
                        lgpio.gpio_free(self.gpio_handle, m['step'])
                    except:
                        pass
                    try:
                        lgpio.gpio_free(self.gpio_handle, m['dir'])
                    except:
                        pass
                
                # Close GPIO chip
                lgpio.gpiochip_close(self.gpio_handle)
                self.gpio_initialized = False
                self.gpio_handle = None
            except:
                pass
        
        # Close the application
        self.close()
        QApplication.quit()

    def closeEvent(self, event):
        """Handle window close event"""
        self.close_application()
        event.accept()

    def check_gpio_status(self):
        """Check GPIO status and provide diagnostics"""
        if not ON_PI:
            return "Not running on Raspberry Pi"
        
        try:
            # Non-intrusive check: only try to open the chip (do not claim/free pins)
            test_handle = lgpio.gpiochip_open(0)
            if test_handle < 0:
                return f"GPIO chip access failed. Error code: {test_handle}"
            lgpio.gpiochip_close(test_handle)
            return "GPIO chip accessible. Pins not probed to avoid interfering with operation."
            
        except Exception as e:
            return f"GPIO check failed: {e}"

    def show_gpio_diagnostics(self):
        """Show GPIO diagnostics dialog"""
        status = self.check_gpio_status()
        QMessageBox.information(self, "GPIO Diagnostics", 
                               f"GPIO Status:\n\n{status}\n\n"
                               "If pins are busy, try:\n"
                               "• sudo pkill -f python\n"
                               "• sudo gpio unexportall\n"
                               "• Restart Raspberry Pi")

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