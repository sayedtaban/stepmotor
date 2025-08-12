import sys
import threading
import time
import os
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QSpinBox, QDoubleSpinBox, QPushButton, QTextEdit, QGroupBox, QMessageBox, QComboBox
)
from PyQt5.QtCore import pyqtSignal, Qt

try:
    import lgpio
    ON_PI = True
except ImportError:
    ON_PI = False

# Prefer windowed Qt backend on Raspberry Pi (avoid fullscreen eglfs)
if ON_PI:
    os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')
    os.environ.setdefault('DISPLAY', ':0')

MOTORS = [
    {'step': 27, 'dir': 17, 'start_pos': 'A'},
    {'step': 23, 'dir': 22, 'start_pos': 'B'},
    {'step': 24, 'dir': 25, 'start_pos': 'B'}
]
STEPS_PER_REV = 400  # Adjust for your hardware if needed

GPIO_HANDLE = None

def init_gpio_pins():
    """Initialize lgpio chip and claim motor pins as outputs with LOW default."""
    if not ON_PI:
        return
    global GPIO_HANDLE
    if GPIO_HANDLE is not None:
        return
    GPIO_HANDLE = lgpio.gpiochip_open(0)
    # Claim outputs for all motor lines
    for motor_pin_config in MOTORS:
        lgpio.gpio_claim_output(GPIO_HANDLE, 0, motor_pin_config['step'], 0)
        lgpio.gpio_claim_output(GPIO_HANDLE, 0, motor_pin_config['dir'], 0)

def cleanup_gpio():
    """Free all claimed lines and close the lgpio chip handle."""
    if not ON_PI:
        return
    global GPIO_HANDLE
    if GPIO_HANDLE is None:
        return
    for motor_pin_config in MOTORS:
        try:
            lgpio.gpio_free(GPIO_HANDLE, motor_pin_config['step'])
        except Exception:
            pass
        try:
            lgpio.gpio_free(GPIO_HANDLE, motor_pin_config['dir'])
        except Exception:
            pass
    try:
        lgpio.gpiochip_close(GPIO_HANDLE)
    except Exception:
        pass
    GPIO_HANDLE = None

if ON_PI:
    init_gpio_pins()

class MotorThread(threading.Thread):
    def __init__(self, step_pin, dir_pin, speed_rpm, delay_seconds, angle_degrees, repetitions,
                 running_event, steps_moved, idx, status_callback, direction=True):
        super().__init__()
        self.step_pin = step_pin
        self.dir_pin = dir_pin
        self.speed_rpm = speed_rpm
        self.delay_seconds = delay_seconds
        self.angle_degrees = angle_degrees
        self.repetitions = repetitions
        self.running_event = running_event
        self.steps_moved = steps_moved
        self.idx = idx
        self.status_callback = status_callback
        self.direction = direction
        self.daemon = True

    def run(self):
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)
        step_delay = 60.0 / (STEPS_PER_REV * self.speed_rpm) / 2
        steps_to_move = max(1, int(STEPS_PER_REV * (self.angle_degrees / 360.0)))

        # Set direction once for all repetitions
        if ON_PI and GPIO_HANDLE is not None:
            lgpio.gpio_write(GPIO_HANDLE, self.dir_pin, 1 if self.direction else 0)

        repetitions_completed = 0
        while self.running_event.is_set() and repetitions_completed < self.repetitions:
            # Perform one move to final position (discrete rotation)
            if ON_PI and GPIO_HANDLE is not None:
                lgpio.gpio_write(GPIO_HANDLE, self.dir_pin, 1 if self.direction else 0)
            self.status_callback(f"Motor {self.idx + 1}: direction changed 1")
            for id in range(steps_to_move):
                if not self.running_event.is_set():
                    break
                if ON_PI:
                    lgpio.gpio_write(GPIO_HANDLE, self.step_pin, 1)
                    time.sleep(step_delay)
                    lgpio.gpio_write(GPIO_HANDLE, self.step_pin, 0)
                    time.sleep(step_delay)
                else:
                    time.sleep(step_delay * 2)
                if id == int(steps_to_move / 2):
                    if ON_PI:
                        lgpio.gpio_write(GPIO_HANDLE, self.dir_pin, 0 if self.direction else 1)
                    self.status_callback(f"Motor {self.idx + 1}: direction changed 0")
                self.steps_moved[self.idx] += 1
                
            repetitions_completed += 1
            self.status_callback(
                f"Motor {self.idx+1}: completed {repetitions_completed}/{self.repetitions} rotation(s) of {self.angle_degrees}°."
            )

            if not self.running_event.is_set() or repetitions_completed >= self.repetitions:
                break
            # Wait 5 seconds between repetitions
            for _ in range(50):
                if not self.running_event.is_set():
                    break
                time.sleep(0.1)

        self.status_callback(f"Motor {self.idx+1}: thread finished.")

class MotorControlApp(QMainWindow):
    finished = pyqtSignal()
    motor_status = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Stepper Motor Control - Angle & Repetitions")
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

    def _init_config_tab(self):
        vbox = QVBoxLayout()
        group = QGroupBox("Configure Each Motor")
        form = QFormLayout()
        self.speed_spins = []
        self.delay_spins = []
        self.angle_combos = []
        self.repeat_spins = []
        for i in range(3):
            hbox = QHBoxLayout()
            # Speed
            speed_spin = QSpinBox()
            speed_spin.setRange(1, 300)
            speed_spin.setValue(60 + i * 20)
            hbox.addWidget(QLabel("Speed (RPM):"))
            hbox.addWidget(speed_spin)
            hbox.addSpacing(10)
            # Start delay
            delay_spin = QDoubleSpinBox()
            delay_spin.setRange(0, 10)
            delay_spin.setSingleStep(0.1)
            delay_spin.setValue(i * 0.2)
            hbox.addWidget(QLabel("Delay (s):"))
            hbox.addWidget(delay_spin)
            hbox.addSpacing(10)
            # Angle (45 or 90)
            angle_combo = QComboBox()
            angle_combo.addItems(["45", "90"])  # degrees
            angle_combo.setCurrentIndex(0)
            hbox.addWidget(QLabel("Angle (°):"))
            hbox.addWidget(angle_combo)
            hbox.addSpacing(10)
            # Repetitions per motor
            repeat_spin = QSpinBox()
            repeat_spin.setRange(1, 100)
            repeat_spin.setValue(3)
            hbox.addWidget(QLabel("Repetitions:"))
            hbox.addWidget(repeat_spin)

            form.addRow(f"Motor {i+1} ({MOTORS[i]['start_pos']}):", hbox)
            self.speed_spins.append(speed_spin)
            self.delay_spins.append(delay_spin)
            self.angle_combos.append(angle_combo)
            self.repeat_spins.append(repeat_spin)
        group.setLayout(form)
        vbox.addWidget(group)

        btn_hbox = QHBoxLayout()
        self.start_btn = QPushButton("▶ Start Motors")
        self.start_btn.setStyleSheet("background-color:#37b24d; color:white; font-weight:bold;")
        self.start_btn.clicked.connect(self.start_motors)
        btn_hbox.addWidget(self.start_btn)

        vbox.addLayout(btn_hbox)
        vbox.addStretch(1)
        self.config_tab.setLayout(vbox)

    def _init_status_tab(self):
        vlayout = QVBoxLayout()
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        vlayout.addWidget(QLabel("Live Status:"))
        vlayout.addWidget(self.status_text)

        self.stop_btn = QPushButton("🛑 Stop")
        self.stop_btn.setStyleSheet("background-color:#fa5252; color:white; font-weight:bold;")
        self.stop_btn.clicked.connect(self.stop_motors)
        self.stop_btn.setEnabled(False)
        vlayout.addWidget(self.stop_btn)

        self.status_tab.setLayout(vlayout)

    def append_status(self, message):
        self.status_text.append(message)
        self.tabs.setCurrentWidget(self.status_tab)

    def show_finished(self):
        self.append_status("✅ All motors finished their configured repetitions.")
        QMessageBox.information(self, "Done", "All motors finished their configured repetitions.")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _watch_for_completion(self):
        # Wait for all motor threads to finish
        for t in self.threads:
            if t is not None:
                t.join()
        self.finished.emit()

    def start_motors(self):
        init_gpio_pins()
        self.append_status("🚦 Starting motors...")
        self.steps_moved = [0, 0, 0]
        speeds = [spin.value() for spin in self.speed_spins]
        delays = [spin.value() for spin in self.delay_spins]
        angles = [int(combo.currentText()) for combo in self.angle_combos]
        reps = [spin.value() for spin in self.repeat_spins]

        for evt in self.running_events:
            evt.clear()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        for idx, m in enumerate(MOTORS):
            self.running_events[idx].set()
            def run_motor(idx=idx, m=m):
                self.motor_status.emit(
                    f"Motor {idx+1}: speed {speeds[idx]} RPM, delay {delays[idx]:.2f}s, angle {angles[idx]}°, reps {reps[idx]}"
                )
                thread = MotorThread(
                    step_pin=m['step'],
                    dir_pin=m['dir'],
                    speed_rpm=speeds[idx],
                    delay_seconds=delays[idx],
                    angle_degrees=angles[idx],
                    repetitions=reps[idx],
                    running_event=self.running_events[idx],
                    steps_moved=self.steps_moved,
                    idx=idx,
                    status_callback=self.motor_status.emit,
                    direction=True
                )
                self.threads[idx] = thread
                thread.start()
            threading.Thread(target=run_motor, daemon=True).start()

        # Start watcher thread to emit finished when all done
        threading.Thread(target=self._watch_for_completion, daemon=True).start()

    def stop_motors(self):
        self.append_status("🛑 Stop pressed: halting all motors...")
        self.stop_btn.setEnabled(False)

        for evt in self.running_events:
            evt.clear()
        for t in self.threads:
            if t is not None:
                t.join(timeout=2)

        if ON_PI:
            cleanup_gpio()
        self.finished.emit()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MotorControlApp()
    window.resize(560, 360)
    # Ensure not fullscreen on Raspberry Pi
    window.setWindowState(window.windowState() & ~Qt.WindowFullScreen)
    window.show()
    sys.exit(app.exec_())
