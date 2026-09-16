"""Launch with fresh interpreter initialization, preserving virtualenv isolation."""
import subprocess


class ParserProcess:
    def __init__(self, command):
        self.command = command
        self.process = None

    def start(self):
        # Raw parser output can contain document content; only structured,
        # sanitized spool records leave the child.
        self.process = subprocess.Popen(self.command, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def is_alive(self):
        return self.process.poll() is None

    def join(self, timeout=None):
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass

    def kill(self):
        self.process.kill()

    @property
    def exitcode(self):
        return self.process.poll()
