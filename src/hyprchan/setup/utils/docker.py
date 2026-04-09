import subprocess
import shutil

def is_docker_available() -> bool:
    """Checks if docker is installed and the daemon is reachable."""
    if not shutil.which("docker"):
        return False
    try:
        # Check if we can talk to the daemon
        subprocess.run(["docker", "info"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
